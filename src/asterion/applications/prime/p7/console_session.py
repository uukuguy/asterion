"""One finite, operator-owned P7 witness behind the local console."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import threading
import time

from .console_snapshot import build_console_snapshot
from .game import public_game_catalog
from .live import safe_run_id


_RUN_ID = re.compile(r"p7-live-[0-9]{14}-[0-9a-f]{24}\Z")
_COMMAND_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_SECONDS = 900
_ACTIVE = {"starting", "running", "stopping"}
_CLEARED_ENV = {
    "ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND", "ASTERION_PRIME_P7_RUN_MODE",
    "ASTERION_PRIME_P7_ATTEMPT_UNIT", "ASTERION_PRIME_P7_ATTEMPT_SECONDS",
    "ASTERION_PRIME_P7_CONSOLE_RUN_ID", "OPERATION_MODE", "MAKEFLAGS", "MFLAGS",
    "MAKEOVERRIDES", "GNUMAKEFLAGS", "MAKEFILES",
}


class ConsoleSessionError(ValueError):
    """A fixed, public-safe console request error."""


def _stop_process(process: subprocess.Popen) -> None:
    # Kill the launcher before checking unit absence: it must never submit a
    # service after the guest cleanup has declared it missing.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # Reaping Make/the parent says nothing about its descendants. Kill any
    # remaining members even when the parent already exited naturally or
    # promptly accepted SIGTERM, then establish that the owned group is gone.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)
    deadline = time.monotonic() + 5
    while True:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        if time.monotonic() >= deadline:
            raise ConsoleSessionError("launcher-cleanup-unconfirmed")
        time.sleep(0.02)


class ConsoleSession:
    """Launch only the existing packaged witness; never own solver execution."""

    def __init__(
        self, operator_root: Path, arc_root: Path, *, guest_machine: str = "ubuntu",
        catalog: tuple[dict, ...] | None = None,
        process_factory: Callable = subprocess.Popen,
        process_stopper: Callable = _stop_process,
        guest_cleanup: Callable[[str], bool] | None = None,
        snapshot_reader: Callable = build_console_snapshot,
        run_id_factory: Callable[[], str] = safe_run_id,
        environment: Mapping[str, str] | None = None, poll_interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._root = Path(operator_root).resolve(strict=True)
        self._arc_root = Path(arc_root).resolve(strict=True)
        if not self._root.is_dir() or not self._arc_root.is_dir():
            raise ConsoleSessionError("console-unavailable")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", guest_machine):
            raise ConsoleSessionError("console-unavailable")
        self._guest = guest_machine
        self._catalog = tuple(deepcopy(catalog if catalog is not None else public_game_catalog(self._arc_root)))
        self._games = {entry["game_id"] for entry in self._catalog}
        self._runs = self._root / ".asterion-private" / "prime-p7-live"
        self._process_factory = process_factory
        self._process_stopper = process_stopper
        self._guest_cleanup = guest_cleanup or self._cleanup_guest
        self._snapshot_reader = snapshot_reader
        self._run_id_factory = run_id_factory
        self._environment = dict(os.environ if environment is None else environment)
        self._poll_interval = poll_interval
        self._clock = clock
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._closed = False
        self._commands: dict[str, tuple[tuple[str, ...], dict]] = {}
        self._snapshot_key = None
        self._view = {"session_id": None, "state": "idle", "game_id": None,
                      "run_id": None, "cleanup_confirmed": True, "snapshot": None,
                      "revision": 0}

    def games(self) -> list[dict]:
        return deepcopy(list(self._catalog))

    def view(self) -> dict[str, object]:
        with self._lock:
            return deepcopy(self._view)

    def _change(self, **values) -> None:
        if any(self._view.get(key) != value for key, value in values.items()):
            self._view.update(values)
            self._view["revision"] += 1

    def _prior(self, command_id: str, signature: tuple[str, ...]) -> dict | None:
        if type(command_id) is not str or not _COMMAND_ID.fullmatch(command_id):
            raise ConsoleSessionError("command-invalid")
        prior = self._commands.get(command_id)
        if prior is not None:
            if prior[0] != signature:
                raise ConsoleSessionError("command-conflict")
            return deepcopy(prior[1])
        if len(self._commands) >= 256:
            raise ConsoleSessionError("command-limit")
        return None

    def _remember(self, command_id: str, signature: tuple[str, ...]) -> dict:
        value = deepcopy(self._view)
        self._commands[command_id] = (signature, value)
        return deepcopy(value)

    def _run_path(self, run_id: str) -> Path:
        if type(run_id) is not str or not _RUN_ID.fullmatch(run_id):
            raise ConsoleSessionError("run-unavailable")
        path = self._runs / run_id
        if any(part.is_symlink() for part in (self._runs.parent, self._runs, path)):
            raise ConsoleSessionError("run-unavailable")
        return path

    def start(self, game_id: str, command_id: str) -> dict[str, object]:
        with self._lock:
            signature = ("start", game_id)
            prior = self._prior(command_id, signature)
            if prior is not None:
                return prior
            if self._closed or self._view["state"] in _ACTIVE or not self._view["cleanup_confirmed"]:
                raise ConsoleSessionError("session-busy")
            if type(game_id) is not str or game_id not in self._games:
                raise ConsoleSessionError("game-unavailable")
            run_id = self._run_id_factory()
            if self._run_path(run_id).exists():
                raise ConsoleSessionError("run-unavailable")
            unit = "asterion-p7-" + secrets.token_hex(16) + ".service"
            self._stop = threading.Event()
            self._snapshot_key = None
            self._change(session_id="p7-console-" + secrets.token_hex(16), state="starting",
                         game_id=game_id, run_id=run_id, cleanup_confirmed=False, snapshot=None)
            self._thread = threading.Thread(target=self._run, args=(game_id, run_id, unit),
                                            name="p7-console-witness", daemon=True)
            response = self._remember(command_id, signature)
            self._thread.start()
            return response

    def stop(self, session_id: str, command_id: str) -> dict[str, object]:
        with self._lock:
            signature = ("stop", session_id)
            prior = self._prior(command_id, signature)
            if prior is not None:
                return prior
            if type(session_id) is not str or session_id != self._view["session_id"]:
                raise ConsoleSessionError("session-mismatch")
            if self._view["state"] in _ACTIVE:
                self._stop.set()
                self._change(state="stopping")
            return self._remember(command_id, signature)

    def _cleanup_guest(self, unit: str) -> bool:
        result = subprocess.run(
            ["orb", "-m", self._guest, "-u", "root", "-w", "/tmp", "python3",
             str(self._root / "tools" / "run_prime_p7_guest.py"), "cleanup", "--unit", unit],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=40, check=False,
        )
        return result.returncode == 0

    def _refresh(self, run_id: str, game_id: str) -> None:
        try:
            path = self._run_path(run_id)
            if not path.is_dir():
                return
            snapshot = self._snapshot_reader(path)
            identity = snapshot.get("run", {})
            if identity.get("run_id") != run_id or identity.get("game_id") != game_id:
                return
            key = json.dumps({k: v for k, v in snapshot.items() if k != "generated_at"},
                             sort_keys=True, allow_nan=False)
            with self._lock:
                if key != self._snapshot_key:
                    self._snapshot_key = key
                    self._change(snapshot=deepcopy(snapshot))
        except (OSError, ValueError, TypeError):
            # A partial writer row or not-yet-created recording is not a
            # new observation. Keep the previous confirmed projection.
            return

    def _run(self, game_id: str, run_id: str, unit: str) -> None:
        process = None
        outcome = "failed"
        reaped = True
        environment = {key: value for key, value in self._environment.items() if key not in _CLEARED_ENV}
        environment["ASTERION_PRIME_P7_CONSOLE_RUN_ID"] = run_id
        argv = ["make", "asterion-prime-p7-level-witness", f"GAME={game_id}", "LEVEL=1",
                f"ASTERION_PRIME_P7_ATTEMPT_UNIT={unit}", f"ASTERION_PRIME_P7_ATTEMPT_SECONDS={_SECONDS}",
                f"PRIME_ORB_MACHINE={self._guest}", f"ASTERION_PRIME_OPERATOR_ROOT={self._root}",
                f"ASTERION_PRIME_ARC_ROOT={self._arc_root}"]
        deadline = self._clock() + _SECONDS
        try:
            process = self._process_factory(argv, cwd=self._root, env=environment,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            start_new_session=True)
            with self._lock:
                if not self._stop.is_set():
                    self._change(state="running")
            while True:
                self._refresh(run_id, game_id)
                if self._stop.is_set():
                    outcome = "cancelled"
                    break
                if self._clock() >= deadline:
                    outcome = "timed-out"
                    break
                code = process.poll()
                if code is not None:
                    outcome = "incomplete" if code == 0 else "failed"
                    break
                self._stop.wait(self._poll_interval)
        except Exception:
            outcome = "failed"
        finally:
            if process is not None:
                try:
                    # Also reap a naturally completed parent; the exact guest
                    # unit is always independently checked below.
                    self._process_stopper(process)
                    reaped = process.poll() is not None
                except Exception:
                    reaped = False
            with self._lock:
                self._change(state="stopping")
            try:
                cleaned = self._guest_cleanup(unit) is True and reaped
            except Exception:
                cleaned = False
            self._refresh(run_id, game_id)
            with self._lock:
                run = (self._view["snapshot"] or {}).get("run", {})
                if (outcome == "incomplete" and run.get("status") == "successful"
                        and run.get("replay_verified") is True and run.get("sealed_trace") is True):
                    outcome = "completed"
                self._change(state=outcome if cleaned else "cleanup-unconfirmed", cleanup_confirmed=cleaned)

    def recorded_runs(self) -> list[dict]:
        if self._runs.is_symlink() or self._runs.parent.is_symlink() or not self._runs.is_dir():
            return []
        result = []
        for path in sorted(self._runs.iterdir(), key=lambda p: p.name, reverse=True)[:256]:
            if not _RUN_ID.fullmatch(path.name) or path.is_symlink() or not path.is_dir():
                continue
            try:
                snapshot = self.replay(path.name)
                run = snapshot["run"]
                result.append({key: run[key] for key in ("run_id", "game_id", "status")})
            except ConsoleSessionError:
                continue
        return result

    def replay(self, run_id: str) -> dict:
        try:
            path = self._run_path(run_id)
            if not path.is_dir():
                raise ValueError
            snapshot = self._snapshot_reader(path)
            run = snapshot["run"]
            if run["run_id"] != run_id or run["game_id"] not in self._games:
                raise ValueError
            return snapshot
        except (OSError, ValueError, KeyError, TypeError):
            raise ConsoleSessionError("run-unavailable") from None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._stop.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=60)
            if thread.is_alive():
                with self._lock:
                    self._change(state="cleanup-unconfirmed", cleanup_confirmed=False)


__all__ = ("ConsoleSession", "ConsoleSessionError")
