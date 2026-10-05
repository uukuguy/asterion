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
from .console_export import export_console
from .solver_control import read_control_ack, write_control_request
from .console_preferences import read_selection, valid_selection, write_selection
from .game import _read_catalog, public_game_catalog
from .console_overview import ConsoleOverview, MODEL_ID
from .live import load_operator_environment, safe_run_id
from .model_selection import declared_model_selection


_RUN_ID = re.compile(r"p7-live-[0-9]{14}-[0-9a-f]{24}\Z")
_COMMAND_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_SECONDS = 900
_ACTIVE = {"starting", "running", "pause_requested", "paused", "resume_requested", "stopping"}
_MANUAL_ERRORS = {"session-busy", "command-invalid", "command-conflict", "command-limit",
                  "game-unavailable", "level-unavailable", "session-mismatch", "observation-stale", "action-invalid",
                  "action-unavailable", "manual-unavailable", "manual-uncertain",
                  "manual-cleanup-unconfirmed", "manual-expired", "manual-save-failed",
                  "manual-save-invalid", "manual-restore-failed", "manual-save-limit"}
_MANUAL_IDLE = {"session_id": None, "game_id": None, "state": "idle", "observation_version": 0,
                "episode_id": 0, "action_count": 0, "snapshot": None, "last_action": None}
_CLEARED_ENV = {
    "ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND", "ASTERION_PRIME_P7_RUN_MODE",
    "ASTERION_PRIME_P7_ATTEMPT_UNIT", "ASTERION_PRIME_P7_ATTEMPT_SECONDS",
    "ASTERION_PRIME_P7_CONSOLE_RUN_ID", "OPERATION_MODE", "MAKEFLAGS", "MFLAGS",
    "MAKEOVERRIDES", "GNUMAKEFLAGS", "MAKEFILES",
    "ASTERION_PRIME_P7_HISTORY_VARIANT", "ASTERION_PRIME_P7_RESUME_RUN_ID",
    "ASTERION_PRIME_P7_TARGET_LEVEL", "ASTERION_PRIME_P7_SEED",
    "ASTERION_PRIME_P7_GAME_ID", "LEVEL", "GAME", "ASTERION_PRIME_MODEL",
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
        guest_activity_reader: Callable[[], bool] | None = None,
        operator_environment_reader: Callable[[Path], Mapping[str, str]] = load_operator_environment,
        snapshot_reader: Callable = build_console_snapshot,
        manual_controller: object | None = None,
        manual_save_root: Path | None = None,
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
        source_catalog = tuple(deepcopy(catalog if catalog is not None else public_game_catalog(self._arc_root)))
        self._supplied_metadata = {entry["game_id"]: entry for entry in source_catalog
                                   if "baseline_actions" in entry}
        self._catalog = tuple({key: entry[key] for key in ("game_id", "alias", "win_levels")}
                              for entry in source_catalog)
        self._games = {entry["game_id"] for entry in self._catalog}
        self._game_levels = {entry["game_id"]: entry["win_levels"] for entry in self._catalog}
        self._selection = read_selection(self._root, self._game_levels)
        self._runs = self._root / ".asterion-private" / "prime-p7-live"
        self._overview_reader = None
        self._process_factory = process_factory
        self._process_stopper = process_stopper
        self._guest_cleanup = guest_cleanup or self._cleanup_guest
        self._guest_activity_reader = guest_activity_reader or self._query_guest_activity
        self._operator_environment_reader = operator_environment_reader
        self._activity_cache: tuple[float, bool | None] | None = None
        self._activity_lock = threading.Lock()
        self._snapshot_reader = snapshot_reader
        self._manual = manual_controller
        self._manual_save_root = (Path(manual_save_root) if manual_save_root is not None
                                  else self._root / '.asterion-private' / 'p7-console-manual')
        self._manual_inflight = False
        self._manual_done = threading.Event()
        self._manual_done.set()
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
        self._control_sequence = 0
        self._control_pending = None
        self._view = {"session_id": None, "state": "idle", "game_id": None,
                      "run_id": None, "cleanup_confirmed": True, "snapshot": None,
                      "revision": 0}

    def games(self) -> list[dict]:
        return deepcopy(list(self._catalog))

    def overview(self) -> dict:
        with self._lock:
            if self._overview_reader is None:
                try:
                    catalog = _read_catalog(self._arc_root)
                except (OSError, ValueError):
                    catalog = ()
                metadata = {entry["game_id"]: entry for entry in catalog}
                metadata.update(self._supplied_metadata)
                selected = []
                for game in self._catalog:
                    entry = metadata.get(game["game_id"])
                    if (entry is None or entry.get("alias") != game["alias"]
                            or entry.get("win_levels") != game["win_levels"]):
                        raise ConsoleSessionError("overview-unavailable")
                    selected.append(entry)
                self._overview_reader = ConsoleOverview(self._runs, tuple(selected))
            reader = self._overview_reader
            active = self._view["run_id"] if self._view["state"] in _ACTIVE else None
        value = reader.build(active_run_id=active)
        busy = self._read_guest_activity()
        block = "guest-unavailable" if busy is None else "session-busy" if busy else None
        try:
            self._validate_model()
        except ConsoleSessionError as error:
            block = str(error)
        with self._lock:
            if self._closed or self._manual_inflight or self._view["state"] in _ACTIVE or not self._view["cleanup_confirmed"]:
                block = "session-busy"
        value.update(guest_busy=busy, start_ready=block is None, start_block_reason=block)
        return value

    def _query_guest_activity(self) -> bool:
        result = subprocess.run(
            ["orb", "-m", self._guest, "-u", "root", "-w", "/tmp", "systemctl", "list-units",
             "--all", "--no-legend", "--plain", "--state=active,activating,deactivating",
             "asterion-p7-*.service"], capture_output=True, text=True, timeout=8, check=False,
        )
        if result.returncode != 0 or len(result.stdout) > 4096:
            raise ConsoleSessionError("guest-unavailable")
        units = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if not fields:
                continue
            if (len(fields) < 4 or re.fullmatch(r"asterion-p7-[0-9a-f]{32}\.service", fields[0]) is None
                    or fields[2] not in {"active", "activating", "deactivating"}):
                raise ConsoleSessionError("guest-unavailable")
            units.append(fields[0])
        return bool(units)

    def _read_guest_activity(self, *, force: bool = False) -> bool | None:
        with self._activity_lock:
            now = self._clock()
            if not force and self._activity_cache is not None and now - self._activity_cache[0] < 5:
                return self._activity_cache[1]
            try:
                busy = self._guest_activity_reader()
                if type(busy) is not bool:
                    busy = None
            except Exception:
                busy = None
            self._activity_cache = (now, busy)
            return busy

    def _validate_model(self) -> None:
        try:
            selected = declared_model_selection(self._operator_environment_reader(self._root))
        except Exception:
            raise ConsoleSessionError("model-unavailable") from None
        if selected.model != MODEL_ID:
            raise ConsoleSessionError("model-mismatch")

    def view(self) -> dict[str, object]:
        with self._lock:
            value = deepcopy(self._view)
            value["selection"] = deepcopy(self._selection)
            manual = self._manual
        value["manual"] = deepcopy(manual.view() if manual is not None else _MANUAL_IDLE)
        return value

    @staticmethod
    def _manual_error(error: Exception) -> ConsoleSessionError:
        code = str(error) if isinstance(error, ValueError) else "manual-unavailable"
        return ConsoleSessionError(code if code in _MANUAL_ERRORS else "manual-unavailable")

    def _ready(self) -> None:
        if (self._closed or self._manual_inflight or self._view["state"] in _ACTIVE
                or not self._view["cleanup_confirmed"]):
            raise ConsoleSessionError("session-busy")

    def _manual_call(self, method: str, args: tuple, *, game_id: str | None = None) -> dict:
        with self._lock:
            if method == "open" and (type(game_id) is not str or game_id not in self._games):
                raise ConsoleSessionError("game-unavailable")
            self._ready()
            if self._manual is None and method != "open":
                raise ConsoleSessionError("session-mismatch")
            self._manual_inflight = True
            self._manual_done.clear()
        try:
            if self._manual is None:
                from .console_manual import ManualConsole
                controller = ManualConsole(self._arc_root, save_root=self._manual_save_root)
                with self._lock:
                    self._manual = controller
            result = getattr(self._manual, method)(*args)
            with self._lock:
                if self._closed:
                    raise ConsoleSessionError("session-busy")
                if method in {"open", "act", "restart"}:
                    # A retry can return an old acknowledgement. Remember the
                    # current controller position, never that cached response.
                    current = self._manual.view()
                    choice = {"game_id": current["game_id"], "level": current.get("level", 1)}
                    if current["state"] == "ready" and valid_selection(choice, self._game_levels):
                        self._selection = choice
                        write_selection(self._root, choice, self._game_levels)
            return deepcopy(result)
        except Exception as error:
            raise self._manual_error(error) from None
        finally:
            with self._lock:
                self._manual_inflight = False
                self._manual_done.set()

    def manual_open(self, game_id: str, command_id: str, level: int = 1) -> dict:
        if type(game_id) is not str or game_id not in self._games:
            raise ConsoleSessionError("game-unavailable")
        wins = next(entry["win_levels"] for entry in self._catalog if entry["game_id"] == game_id)
        if type(level) is not int or not 1 <= level <= wins:
            raise ConsoleSessionError("level-unavailable")
        return self._manual_call("open", (game_id, wins, command_id, level), game_id=game_id)

    def manual_action(self, session_id: str, command_id: str, observation_version: int,
                      action: str, data: dict) -> dict:
        return self._manual_call("act", (session_id, command_id, observation_version, action, data))

    def manual_close(self, session_id: str, command_id: str) -> dict:
        return self._manual_call("close", (session_id, command_id))

    def manual_restart(self, session_id: str, command_id: str, observation_version: int) -> dict:
        return self._manual_call("restart", (session_id, command_id, observation_version))

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

    def start(self, game_id: str, command_id: str, *, target_level: int | None = None,
              resume_run_id: str | None = None) -> dict[str, object]:
        with self._lock:
            signature = ("start", game_id, str(target_level), str(resume_run_id))
            prior = self._prior(command_id, signature)
            if prior is not None:
                return prior
            self._ready()
            if type(game_id) is not str or game_id not in self._games:
                raise ConsoleSessionError("game-unavailable")
            target = 1 if target_level is None else target_level
            if type(target) is not int or not 1 <= target <= self._game_levels[game_id]:
                raise ConsoleSessionError("level-unavailable")
            try:
                overview = self.overview()
            except ConsoleSessionError as error:
                if str(error) != "overview-unavailable":
                    raise
                # Legacy injected catalogs have no score metadata. The actual
                # operator still validates resources before any execution.
                overview = {"games": []}
            self._validate_model()
            start_level = 1
            if resume_run_id is not None:
                if type(resume_run_id) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,159}", resume_run_id) is None:
                    raise ConsoleSessionError("resume-unavailable")
                source = next((run for game in overview["games"]
                               if game["game_id"] == game_id for run in game["runs"]
                               if run["run_id"] == resume_run_id), None)
                if (source is None or source.get("verified") is not True
                        or source.get("resume_eligible") is not True
                        or not 0 < source["completed_levels"] < target):
                    raise ConsoleSessionError("resume-unavailable")
                start_level = source["completed_levels"] + 1
            if self._manual is None:
                return self._launch_locked(game_id, command_id, signature, target, resume_run_id, start_level)
            self._manual_inflight = True
            self._manual_done.clear()
        try:
            self._manual.close()
            with self._lock:
                if self._closed:
                    raise ConsoleSessionError("session-busy")
                return self._launch_locked(game_id, command_id, signature, target, resume_run_id, start_level)
        except ConsoleSessionError:
            raise
        except Exception as error:
            raise self._manual_error(error) from None
        finally:
            with self._lock:
                self._manual_inflight = False
                self._manual_done.set()

    def _launch_locked(self, game_id: str, command_id: str, signature: tuple[str, ...],
                       target_level: int, resume_run_id: str | None, start_level: int) -> dict:
        run_id = self._run_id_factory()
        if self._run_path(run_id).exists():
            raise ConsoleSessionError("run-unavailable")
        busy = self._read_guest_activity(force=True)
        if busy is None:
            raise ConsoleSessionError("guest-unavailable")
        if busy:
            raise ConsoleSessionError("session-busy")
        self._validate_model()
        unit = "asterion-p7-" + secrets.token_hex(16) + ".service"
        self._stop = threading.Event()
        self._snapshot_key = None
        self._control_sequence = 0
        self._control_pending = None
        self._change(session_id="p7-console-" + secrets.token_hex(16), state="starting",
                     game_id=game_id, run_id=run_id, cleanup_confirmed=False, snapshot=None,
                     target_level=target_level, start_level=start_level, source_run_id=resume_run_id,
                     replay_saved=False)
        self._thread = threading.Thread(target=self._run, args=(game_id, run_id, unit, target_level, resume_run_id),
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

    def _control(self, operation: str, session_id: str, command_id: str) -> dict:
        with self._lock:
            signature = (operation, session_id)
            prior = self._prior(command_id, signature)
            if prior is not None:
                return prior
            if type(session_id) is not str or session_id != self._view['session_id']:
                raise ConsoleSessionError('session-mismatch')
            expected = 'running' if operation == 'pause' else 'paused'
            if self._view['state'] != expected or self._control_pending is not None:
                raise ConsoleSessionError('session-busy')
            sequence = self._control_sequence + 1
            try:
                request = write_control_request(self._run_path(self._view['run_id']),
                    run_id=self._view['run_id'], command_id=command_id,
                    request_sequence=sequence, operation=operation)
            except (OSError, ValueError, TypeError):
                raise ConsoleSessionError('control-unavailable') from None
            self._control_sequence = sequence
            self._control_pending = request
            self._change(state='pause_requested' if operation == 'pause' else 'resume_requested')
            return self._remember(command_id, signature)

    def pause(self, session_id: str, command_id: str) -> dict:
        return self._control('pause', session_id, command_id)

    def resume(self, session_id: str, command_id: str) -> dict:
        return self._control('resume', session_id, command_id)

    def _refresh_control(self, run_id: str) -> None:
        with self._lock:
            pending = self._control_pending
            if pending is None or self._view['run_id'] != run_id or self._view['state'] == 'stopping':
                return
        try:
            ack = read_control_ack(self._run_path(run_id), run_id=run_id)
        except (OSError, ValueError, TypeError):
            return
        if ack is None or any(ack[key] != pending[key] for key in ('run_id', 'command_id', 'request_sequence')):
            return
        with self._lock:
            if self._control_pending != pending or self._view['state'] == 'stopping':
                return
            target = 'paused' if pending['operation'] == 'pause' else 'running'
            if ack['state'] == target:
                self._control_pending = None
                self._change(state=target)
            elif ack['state'] == 'stop_requested':
                self._stop.set()
                self._change(state='stopping')

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

    def _run(self, game_id: str, run_id: str, unit: str, target_level: int = 1,
             resume_run_id: str | None = None) -> None:
        process = None
        outcome = "failed"
        reaped = True
        environment = {key: value for key, value in self._environment.items() if key not in _CLEARED_ENV}
        environment["ASTERION_PRIME_P7_CONSOLE_RUN_ID"] = run_id
        environment["ASTERION_PRIME_P7_HISTORY_VARIANT"] = "verified"
        environment["ASTERION_PRIME_P7_SEED"] = "0"
        environment["ASTERION_PRIME_MODEL"] = MODEL_ID
        if resume_run_id is not None:
            environment["ASTERION_PRIME_P7_RESUME_RUN_ID"] = resume_run_id
        argv = ["make", "asterion-prime-p7-level-witness", f"GAME={game_id}", f"LEVEL={target_level}",
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
                self._refresh_control(run_id)
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
            replay_saved = False
            if cleaned:
                try:
                    path = self._run_path(run_id)
                    summary = path / "summary.json"
                    if not summary.is_symlink() and summary.is_file():
                        export_console(path)
                        replay_saved = True
                except Exception:
                    # Viewing output cannot change solver or cleanup outcomes.
                    pass
            with self._lock:
                run = (self._view["snapshot"] or {}).get("run", {})
                if (outcome == "incomplete" and run.get("status") == "successful"
                        and run.get("replay_verified") is True and run.get("sealed_trace") is True):
                    outcome = "completed"
                self._change(state=outcome if cleaned else "cleanup-unconfirmed", cleanup_confirmed=cleaned,
                             replay_saved=replay_saved)

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
        manual_finished = self._manual_done.wait(timeout=30)
        try:
            if self._manual is not None:
                self._manual.shutdown()
        except Exception:
            manual_finished = False
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=60)
            if thread.is_alive():
                with self._lock:
                    self._change(state="cleanup-unconfirmed", cleanup_confirmed=False)
        if not manual_finished:
            with self._lock:
                self._change(state="cleanup-unconfirmed", cleanup_confirmed=False)


__all__ = ("ConsoleSession", "ConsoleSessionError")
