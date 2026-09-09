from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from importlib import resources as importlib_resources
from asterion.agents.prime.trace import PrimeTraceEntry, validate_trace
from asterion.applications.prime import create_provider
from asterion.applications.prime.p7.broker import ArcBroker, ArcRunReceipt
from asterion.applications.prime.p7.diagnostics import analyze_trace
from asterion.applications.prime.p7.ipython_host import (
    IpythonWorkerResult,
    P7ClientFacade,
)
from asterion.applications.prime.p7.operator import build_p7_operator_resources
from asterion.applications.prime.p7.prompt import P7_SOLVE_PROMPT
from asterion.applications.provider import resolve_installed_provider
from asterion.capabilities.prime_arc_agi_3_solver.provider import (
    CAPABILITY_REF,
    PACKAGE_REF,
    create_prime_arc_agi_3_solver_package,
)
from asterion.runner.composed import run_composed_application
from asterion.runtime.defaults import default_runtime_factory_registry
from asterion.runtime.factory import RuntimeFactoryContext


_GAME_ID = "ls20-9607627b"
_SEED = 0
_MODEL = "deepseek-v4-flash"
_PROVIDER = "deepseek"
_MAX_ACTIONS = 500
_MAX_CALLBACKS = 128
_DEADLINE_SECONDS = 60 * 60
_PRIVATE_ROOT = ".asterion-private/prime-p7-live"
_WORKER_PROTOCOL = "asterion.prime-p7-worker/v1"


class LiveSolveError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class P7LiveExecution:
    run_id: str
    completed_level_count: int
    primitive_action_count: int
    replay_verified: bool
    sealed_trace: bool
    cleanup_complete: bool
    trace_root: Path
    receipt: Mapping[str, object]
    comparison_report: Path | None


class _NeverCancelled:
    @property
    def cancelled(self) -> bool:
        return False


class _ArcadeEngine:
    game_id = _GAME_ID
    seed = _SEED

    def __init__(self, *, external_root: Path, recordings_dir: Path) -> None:
        from arc_agi import Arcade, OperationMode
        from arcengine import GameAction

        recordings_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(f"asterion.prime.p7.{id(self)}")
        self._logger.handlers = []
        self._logger.addHandler(logging.NullHandler())
        self._logger.propagate = False
        self._actions = {
            f"ACTION{number}": getattr(GameAction, f"ACTION{number}")
            for number in range(1, 8)
        }
        self._arcade = Arcade(
            operation_mode=OperationMode.OFFLINE,
            environments_dir=str(external_root / "environment_files"),
            recordings_dir=str(recordings_dir),
            logger=self._logger,
        )
        self._environment = self._arcade.make(
            _GAME_ID,
            seed=_SEED,
            include_frame_data=True,
            save_recording=True,
        )
        if self._environment is None:
            raise LiveSolveError("ARC environment is unavailable")
        self._current = self._environment.reset()

    def observe(self) -> Mapping[str, object]:
        return self._snapshot(self._current)

    def step(self, action: str) -> Mapping[str, object]:
        if action not in self._actions:
            raise LiveSolveError("ARC action is unavailable")
        self._current = self._environment.step(self._actions[action], {})
        return self._snapshot(self._current)

    def close(self) -> None:
        close = getattr(self._environment, "close", None)
        if callable(close):
            close()

    @staticmethod
    def _frame(value: object) -> list[object]:
        if hasattr(value, "tolist"):
            return value.tolist()
        if type(value) is list:
            return [_ArcadeEngine._frame(item) for item in value]
        if type(value) is tuple:
            return [_ArcadeEngine._frame(item) for item in value]
        return value  # type: ignore[return-value]

    @classmethod
    def _snapshot(cls, value: object) -> Mapping[str, object]:
        if value is None:
            raise LiveSolveError("ARC observation is unavailable")
        available = getattr(value, "available_actions")
        state = getattr(value, "state")
        state_value = getattr(state, "value", None)
        if type(state_value) is not str:
            state_value = getattr(state, "name", None)
        if type(state_value) is not str:
            state_value = str(state)
        return {
            "available_actions": sorted(
                int(getattr(item, "value", item)) for item in available
            ),
            "frame": cls._frame(getattr(value, "frame")),
            "levels_completed": int(getattr(value, "levels_completed")),
            "state": state_value,
            "win_levels": int(getattr(value, "win_levels")),
        }


class _P7ClientServer:
    def __init__(self, client: P7ClientFacade) -> None:
        self._client = client
        self._stop = threading.Event()
        self._directory = tempfile.TemporaryDirectory(
            prefix="asterion-p7-client-", dir="/tmp"
        )
        self.path = Path(self._directory.name) / "client.sock"
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.bind(str(self.path))
        self._socket.listen(1)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        try:
            self._socket.close()
        except OSError:
            pass
        self._thread.join(timeout=1.0)
        self._directory.cleanup()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                channel, _ = self._socket.accept()
            except OSError:
                return
            with channel:
                pending = bytearray()
                while not self._stop.is_set():
                    try:
                        chunk = channel.recv(65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    pending.extend(chunk)
                    while b"\n" in pending:
                        raw, _, trailing = pending.partition(b"\n")
                        pending = bytearray(trailing)
                        response = self._dispatch(raw)
                        try:
                            channel.sendall(response + b"\n")
                        except OSError:
                            break

    def _dispatch(self, raw: bytes) -> bytes:
        try:
            request = json.loads(raw.decode("utf-8", "strict"))
            if (
                type(request) is not dict
                or request.get("protocol") != _WORKER_PROTOCOL
                or type(request.get("id")) is not int
                or request.get("method") not in {"observe", "status", "act"}
                or type(request.get("args")) is not list
            ):
                raise ValueError
            method = str(request["method"])
            args = request["args"]
            value = getattr(self._client, method)(*args)
            response = {
                "id": request["id"],
                "ok": True,
                "protocol": _WORKER_PROTOCOL,
                "value": value,
            }
        except Exception:
            response = {"id": None, "ok": False, "protocol": _WORKER_PROTOCOL}
        return json.dumps(response, allow_nan=False, separators=(",", ":")).encode()


class _SubprocessPythonWorker:
    def __init__(self, *, root: Path, python: Path) -> None:
        self._root = root
        self._python = python
        self._server: _P7ClientServer | None = None
        self._process: subprocess.Popen[str] | None = None
        self.closed = False

    async def start(self, p7_client: P7ClientFacade, *, signal: object) -> None:
        if getattr(signal, "cancelled", False):
            raise LiveSolveError("P7 worker was cancelled")
        workspace = self._root / "worker"
        workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._server = _P7ClientServer(p7_client)
        (workspace / "p7_client.py").write_text(
            _client_module_source(str(self._server.path)), encoding="utf-8"
        )
        controller = _worker_controller_source()
        environment = {
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PYTHONPATH": str(workspace),
        }
        self._process = subprocess.Popen(
            (str(self._python), "-I", "-u", "-c", controller, str(workspace)),
            cwd=workspace,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    async def execute_cell(
        self, code: str, *, signal: object
    ) -> IpythonWorkerResult:
        if getattr(signal, "cancelled", False):
            raise LiveSolveError("P7 worker was cancelled")
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise LiveSolveError("P7 worker is unavailable")
        request = json.dumps({"code": code}, separators=(",", ":")) + "\n"
        process.stdin.write(request)
        process.stdin.flush()
        raw = await asyncio.to_thread(process.stdout.readline)
        if not raw:
            raise LiveSolveError("P7 worker exited")
        value = json.loads(raw)
        if (
            type(value) is not dict
            or set(value) != {"cell_count", "is_error", "output"}
            or type(value["cell_count"]) is not int
            or type(value["is_error"]) is not bool
            or type(value["output"]) is not str
        ):
            raise LiveSolveError("P7 worker returned invalid output")
        self._append_cell_log(code, value)
        return IpythonWorkerResult("ok", value["output"])

    async def close(self) -> None:
        process = self._process
        if process is not None:
            try:
                if process.stdin is not None:
                    process.stdin.close()
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1.0)
        if self._server is not None:
            self._server.close()
        self.closed = True

    def _append_cell_log(self, code: str, value: Mapping[str, object]) -> None:
        try:
            output = str(value["output"])
            record = {
                "cell_count": value["cell_count"],
                "code": code,
                "code_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
                "is_error": value["is_error"],
                "output": output,
                "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
            }
            with (self._root / "worker-cells.jsonl").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        except Exception:
            return


def _worker_controller_source() -> str:
    return r'''
import ast
import contextlib
import io
import json
import sys
import traceback

_OUTPUT_LIMIT = 12000
if len(sys.argv) == 2:
    sys.path.insert(0, sys.argv[1])
namespace = {}
cell_count = 0
for raw in sys.stdin:
    cell_count += 1
    output = io.StringIO()
    is_error = False
    try:
        request = json.loads(raw)
        code = request["code"]
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            tree = ast.parse(code, "<asterion-p7-cell>", "exec")
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                prefix = ast.Module(body=tree.body[:-1], type_ignores=[])
                ast.fix_missing_locations(prefix)
                if prefix.body:
                    exec(compile(prefix, "<asterion-p7-cell>", "exec"), namespace, namespace)
                expression = ast.Expression(tree.body[-1].value)
                ast.fix_missing_locations(expression)
                value = eval(compile(expression, "<asterion-p7-cell>", "eval"), namespace, namespace)
                if value is not None:
                    print(repr(value))
            else:
                exec(compile(tree, "<asterion-p7-cell>", "exec"), namespace, namespace)
    except BaseException:
        is_error = True
        output.write(traceback.format_exc(limit=1))
    text = output.getvalue()
    encoded = text.encode("utf-8", "replace")
    if len(encoded) > _OUTPUT_LIMIT:
        text = encoded[:_OUTPUT_LIMIT].decode("utf-8", "replace") + "\n[asterion: output truncated; keep full frame in variables and print summaries]\n"
    print(json.dumps({"cell_count": cell_count, "is_error": is_error, "output": text}, separators=(",", ":")), flush=True)
'''


def _client_module_source(socket_path: str) -> str:
    encoded = json.dumps(socket_path)
    return f'''
import json
import socket

_PROTOCOL = "asterion.prime-p7-worker/v1"
_PATH = {encoded}
_NEXT_ID = 0

def _call(method, *args):
    global _NEXT_ID
    _NEXT_ID += 1
    request = json.dumps({{"args": list(args), "id": _NEXT_ID, "method": method, "protocol": _PROTOCOL}}, separators=(",", ":")) + "\\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(_PATH)
        client.sendall(request.encode("utf-8"))
        pending = b""
        while b"\\n" not in pending:
            chunk = client.recv(65536)
            if not chunk:
                raise RuntimeError("P7 client unavailable")
            pending += chunk
    response = json.loads(pending.split(b"\\n", 1)[0].decode("utf-8"))
    if response.get("protocol") != _PROTOCOL or response.get("ok") is not True or response.get("id") != _NEXT_ID:
        raise RuntimeError("P7 client unavailable")
    return response["value"]

def _grid(obs=None):
    value = observe() if obs is None else obs
    frame = value["frame"]
    return frame[0] if isinstance(frame, list) and frame and isinstance(frame[0], list) else frame

def _shape(value):
    result = []
    while isinstance(value, list):
        result.append(len(value))
        value = value[0] if value else None
    return result

def _counts(grid):
    counts = {{}}
    for row in grid:
        for value in row:
            counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))

def _components(grid, *, background=4):
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    seen = set()
    result = []
    for y in range(rows):
        for x in range(cols):
            if (x, y) in seen or grid[y][x] == background:
                continue
            value = grid[y][x]
            stack = [(x, y)]
            seen.add((x, y))
            cells = []
            while stack:
                cx, cy = stack.pop()
                cells.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < cols and 0 <= ny < rows and (nx, ny) not in seen and grid[ny][nx] == value:
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            xs = [cell[0] for cell in cells]
            ys = [cell[1] for cell in cells]
            result.append({{"value": value, "bbox": [min(xs), min(ys), max(xs), max(ys)], "size": len(cells)}})
    return sorted(result, key=lambda item: (item["bbox"][1], item["bbox"][0], item["value"], item["size"]))

def positions(values, obs=None):
    wanted = set(values if isinstance(values, (list, tuple, set)) else [values])
    grid = _grid(obs)
    return {{value: [(x, y) for y, row in enumerate(grid) for x, item in enumerate(row) if item == value] for value in sorted(wanted)}}

def diff(before, after):
    before_grid = _grid(before)
    after_grid = _grid(after)
    changes = []
    for y, row in enumerate(before_grid):
        for x, value in enumerate(row):
            new_value = after_grid[y][x]
            if value != new_value:
                changes.append((x, y, value, new_value))
    if not changes:
        return {{"changed": 0, "bbox": None, "sample": []}}
    xs = [item[0] for item in changes]
    ys = [item[1] for item in changes]
    return {{"changed": len(changes), "bbox": [min(xs), min(ys), max(xs), max(ys)], "sample": changes[:80]}}

def summary(obs=None):
    value = observe() if obs is None else obs
    grid = _grid(value)
    return {{
        "available_actions": value["available_actions"],
        "counts": _counts(grid),
        "components": _components(grid)[:40],
        "levels_completed": value["levels_completed"],
        "positions_0_1": positions([0, 1], value),
        "shape": _shape(value["frame"]),
        "state": value["state"],
        "status": status(),
        "win_levels": value["win_levels"],
    }}

def render(obs=None, *, x0=0, y0=0, x1=64, y1=64):
    grid = _grid(obs)
    symbols = {{0:"0", 1:"1", 3:".", 4:" ", 5:"#", 8:"8", 9:"9", 11:"A", 12:"B"}}
    rows = []
    for y in range(max(0, y0), min(len(grid), y1)):
        row = grid[y]
        rows.append(f"{{y:02d}} " + "".join(symbols.get(row[x], "?") for x in range(max(0, x0), min(len(row), x1))))
    return "\\n".join(rows)

def act_and_observe(actions):
    before = observe()
    after = act(actions)
    return {{"act": after["batch"], "diff": diff(before, after), "summary": summary(after)}}

def observe():
    return _call("observe")

def status():
    return _call("status")

def act(actions):
    if isinstance(actions, str):
        actions = [{{"name": actions, "data": {{}}}}]
    elif isinstance(actions, dict):
        actions = [{{"name": actions["name"], "data": actions.get("data", {{}})}}]
    elif isinstance(actions, list) and all(isinstance(action, str) for action in actions):
        actions = [{{"name": action, "data": {{}}}} for action in actions]
    batch = _call("act", actions)
    view = observe()
    current = status()
    levels = current["levels_completed"]
    remaining = current["actions_remaining"]
    terminal = "LEVEL_SOLVED" if levels > 0 else ("ACTION_CAP" if remaining <= 0 else "ACTIVE")
    return {{
        **view,
        "actions_taken": current["primitive_actions"],
        "actions_remaining": remaining,
        "terminal": terminal,
        "batch": batch,
    }}
'''


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Run the fixed native Asterion-prime P7 solve preset."
    )


def classify_live_result(result: P7LiveExecution) -> Mapping[str, object]:
    if result.completed_level_count != 1:
        raise LiveSolveError("authoritative level transition was not observed")
    if not 1 <= result.primitive_action_count <= _MAX_ACTIONS:
        raise LiveSolveError("primitive action count is invalid")
    if not result.replay_verified:
        raise LiveSolveError("replay verification did not pass")
    if not result.sealed_trace:
        raise LiveSolveError("sealed trace was not verified")
    if not result.cleanup_complete:
        raise LiveSolveError("cleanup did not complete")
    return _public_receipt("PASS", result, reason=None)


def _public_receipt(
    status: str, result: P7LiveExecution, *, reason: str | None
) -> Mapping[str, object]:
    receipt = dict(result.receipt)
    safe: dict[str, object] = {
        "schema": "asterion.prime.p7-live-receipt/v1",
        "application_id": "prime.arc-agi-3-solving",
        "runtime_id": "asterion.prime",
        "provider": _PROVIDER,
        "model": _MODEL,
        "game_id": _GAME_ID,
        "seed": _SEED,
        "status": status,
        "run_id": result.run_id,
        "completed_level_count": result.completed_level_count,
        "primitive_action_count": result.primitive_action_count,
        "replay_verified": result.replay_verified,
        "sealed_trace": result.sealed_trace,
        "cleanup_complete": result.cleanup_complete,
    }
    for name in ("partial_game_score", "receipt_sha256", "promotion", "scope"):
        if name in receipt:
            safe[name] = receipt[name]
    if result.comparison_report is not None:
        safe["comparison_report"] = "available"
    if reason is not None:
        safe["reason"] = reason
    return safe


def _load_env(root: Path) -> Mapping[str, str]:
    values = dict(os.environ)
    path = root / ".env"
    if not path.is_file():
        raise LiveSolveError("operator environment is unavailable")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in values:
            values[key] = value
    if not values.get("DEEPSEEK_API_KEY", "").strip():
        raise LiveSolveError("fixed model host is unavailable")
    return values


def _node22(root: Path) -> Path:
    candidates: list[str] = []
    env_node = os.environ.get("ASTERION_PRIME_NODE")
    if env_node:
        candidates.append(env_node)
    node = shutil.which("node")
    if node:
        candidates.append(node)
    for candidate in candidates:
        path = Path(candidate)
        if _node_major(path) >= 22:
            return path.resolve()
    for offline in (True, False):
        command = ["npm", "exec"]
        if offline:
            command.append("--offline")
        command.extend(
            [
                "--yes",
                "--package=node@22",
                "--",
                "node",
                "-p",
                "process.execPath",
            ]
        )
        completed = subprocess.run(
            tuple(command),
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if completed.returncode == 0:
            path = Path(completed.stdout.strip())
            if path.is_file() and _node_major(path) >= 22:
                return path.resolve()
    raise LiveSolveError("Node 22 runtime is unavailable")


def _node_major(path: Path) -> int:
    try:
        expected_platform = "darwin" if sys.platform == "darwin" else "linux"
        completed = subprocess.run(
            (str(path), "-p", "process.versions.node.split('.')[0]"),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        platform = subprocess.run(
            (str(path), "-p", "process.platform"),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if platform.stdout.strip() != expected_platform:
            return 0
        return int(completed.stdout.strip()) if completed.returncode == 0 else 0
    except Exception:
        return 0


def _private_root(root: Path, run_id: str) -> Path:
    path = (root / _PRIVATE_ROOT / run_id).resolve()
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    return path


def _safe_run_id() -> str:
    return "p7-live-" + subprocess.run(
        ("date", "-u", "+%Y%m%d%H%M%S"),
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip().lower()


def _receipt_value(result_artifacts: tuple[Mapping[str, object], ...]) -> Mapping[str, object]:
    if len(result_artifacts) != 1:
        raise LiveSolveError("P7 receipt artifact is unavailable")
    value = result_artifacts[0].get("value")
    if not isinstance(value, Mapping):
        raise LiveSolveError("P7 receipt artifact is invalid")
    return value


def _trace_entries(trace_root: Path) -> tuple[PrimeTraceEntry, ...]:
    path = trace_root / "prime-trace.jsonl"
    entries: list[PrimeTraceEntry] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(raw)
        entries.append(
            PrimeTraceEntry(
                sequence=value["sequence"],
                kind=value["kind"],
                identities=value["identities"],
                payload=value["payload"],
                previous_sha256=value["previous_sha256"],
                sha256=value["sha256"],
            )
        )
    return validate_trace(tuple(entries))


def _write_summary(
    root: Path,
    private_root: Path,
    *,
    run_id: str,
    receipt: Mapping[str, object],
    broker_receipt: ArcRunReceipt | None,
    replay_verified: bool,
    sealed_trace: bool,
    cleanup_complete: bool,
    comparison_report: Path | None,
    reason: str | None,
    failure: BaseException | None,
    diagnostics: Mapping[str, object],
) -> None:
    summary = {
        "schema": "asterion.prime.p7-live-private-summary/v1",
        "run_id": run_id,
        "receipt": dict(receipt),
        "broker": None
        if broker_receipt is None
        else {
            "levels_completed": broker_receipt.levels_completed,
            "primitive_actions": broker_receipt.primitive_actions,
            "terminal_reason": broker_receipt.terminal_reason,
            "replay_sha256": broker_receipt.replay_sha256,
        },
        "replay_verified": replay_verified,
        "sealed_trace": sealed_trace,
        "cleanup_complete": cleanup_complete,
        "comparison_report": None
        if comparison_report is None
        else str(comparison_report.relative_to(root)),
        "reason": reason,
        "failure": None
        if failure is None
        else {
            "type": type(failure).__name__,
            "message": str(failure)[:1000],
        },
        "diagnostics": dict(diagnostics),
    }
    (private_root / "summary.json").write_text(
        json.dumps(summary, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _find_baseline(root: Path) -> Path | None:
    configured = os.environ.get("ASTERION_PRIME_P7_BASELINE_TRACE")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend((root / ".asterion-private").glob("**/prime-trace.jsonl"))
    for path in candidates:
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "operator-stopped" in text:
                return path.resolve()
        except OSError:
            continue
    return None


def _compare_if_available(root: Path, trace_root: Path, private_root: Path) -> Path | None:
    baseline = _find_baseline(root)
    if baseline is None:
        return None
    from tools.compare_prime_p7_runs import main as compare_main

    output = private_root / "comparison-operator-stopped.json"
    status = compare_main(
        [
            "--asterion",
            str(trace_root / "prime-trace.jsonl"),
            "--baseline",
            str(baseline),
            "--output",
            str(output),
        ]
    )
    return output if status == 0 and output.is_file() else None


def _worker_cell_count(private_root: Path) -> int:
    try:
        path = private_root / "worker-cells.jsonl"
        if not path.is_file():
            return 0
        return sum(1 for _ in path.open(encoding="utf-8"))
    except Exception:
        return 0


def _safe_stderr_summary(value: bytes) -> Mapping[str, object]:
    text = value[:4096].decode("utf-8", "replace")
    return {
        "bytes": len(value),
        "sha256": hashlib.sha256(value).hexdigest(),
        "prefix": text,
        "truncated": len(value) > 4096,
    }


def _extension_path(root: Path) -> Path:
    installed = Path(
        str(
            importlib_resources.files("asterion.applications.prime").joinpath(
                "resources/ipython-extension.mjs"
            )
        )
    )
    if installed.is_file():
        return installed.resolve(strict=True)
    source_dist = (
        root
        / "packages/typescript/asterion-prime-extension/dist/ipython-extension.mjs"
    )
    if source_dist.is_file():
        return source_dist.resolve(strict=True)
    raise LiveSolveError("P7 Pi extension is unavailable")


async def _run_live(root: Path, run_id: str) -> P7LiveExecution:
    print("[asterion-prime-p7] preflight", file=sys.stderr, flush=True)
    env = _load_env(root)
    node = _node22(root)
    external_root = (root.parent / "external-prime" / "arc-agi-3").resolve()
    python = (external_root / "venv/bin/python").resolve(strict=True)
    private_root = _private_root(root, run_id)
    trace_root = private_root / "trace"
    trace_root.mkdir(mode=0o700)
    extension = _extension_path(root)
    worker = _SubprocessPythonWorker(root=private_root, python=python)
    engine = _ArcadeEngine(
        external_root=external_root, recordings_dir=private_root / "recordings"
    )
    resources_ = build_p7_operator_resources(
        environment=env,
        pi_base_command=(
            str(node),
            str((root / "pi/packages/coding-agent/dist/rpc-entry.js").resolve(strict=True)),
            "--mode",
            "rpc",
            "--print",
            "--no-builtin-tools",
            "--tools",
            "ipython",
            "--approve",
            "--no-session",
        ),
        extension_path=extension,
        working_directory=root,
        worker=worker,
        engine=engine,
        private_trace_root=trace_root,
    )
    receipt: Mapping[str, object] = {}
    broker_receipt: ArcRunReceipt | None = None
    replay_verified = False
    sealed_trace = False
    cleanup_complete = False
    comparison_report: Path | None = None
    reason: str | None = None
    failure: BaseException | None = None
    diagnostics: dict[str, object] = {}
    try:
        print("[asterion-prime-p7] live-run", file=sys.stderr, flush=True)
        provider = resolve_installed_provider(
            create_provider(),
            runtime_factories=default_runtime_factory_registry(),
            installed_packages=(create_prime_arc_agi_3_solver_package(),),
        )
        application = provider.applications[0]
        assembly = application.assemblies[0]
        runtime = assembly.runtime_binding.factory(
            RuntimeFactoryContext(
                provider_id="prime-applications",
                application_id="prime.arc-agi-3-solving",
                application_version="1.0.0",
                runtime_id="asterion.prime",
                assembly_path=assembly.path,
                options=resources_.runtime_options,
                host_services=resources_.host_services,
            )
        )
        result = await run_composed_application(
            assembly.plan,
            implementations=application.implementations,
            runtime=runtime,
            run_id=run_id,
            input_text=P7_SOLVE_PROMPT,
            host_services=resources_.host_services,
            implementation_packages={CAPABILITY_REF: PACKAGE_REF},
            signal=_NeverCancelled(),
        )
        receipt = _receipt_value(result.artifacts)
        broker = resources_.host_services["prime.arc-broker"]
        if not isinstance(broker, ArcBroker):
            raise LiveSolveError("P7 broker is unavailable")
        broker_receipt = broker.seal()
        broker.replay(
            lambda: _ArcadeEngine(
                external_root=external_root,
                recordings_dir=private_root / "replay-recordings",
            )
        )
        replay_verified = True
        entries = _trace_entries(trace_root)
        analyze_trace(entries)
        sealed_trace = True
        comparison_report = _compare_if_available(root, trace_root, private_root)
    except Exception as error:
        failure = error
        reason = "P7 live solve unsuccessful"
        if isinstance(error, LiveSolveError):
            reason = str(error)
        raise
    finally:
        try:
            broker_value = resources_.host_services.get("prime.arc-broker")
            if isinstance(broker_value, ArcBroker):
                try:
                    status = broker_value.status()
                    diagnostics["broker_status"] = {
                        "actions_remaining": status.actions_remaining,
                        "levels_completed": status.levels_completed,
                        "primitive_actions": status.primitive_actions,
                        "terminal_reason": status.terminal_reason,
                    }
                except Exception:
                    pass
            launch_value = resources_.host_services.get("prime.pi-extension")
            rpc_session = getattr(launch_value, "rpc_session", None)
            last_failure = getattr(rpc_session, "last_failure", None)
            if type(last_failure) is str and last_failure:
                diagnostics["pi_failure"] = last_failure[:1000]
            stderr = getattr(rpc_session, "stderr", b"")
            if type(stderr) is bytes and stderr:
                diagnostics["pi_stderr"] = _safe_stderr_summary(stderr)
            diagnostics["worker_cell_count"] = _worker_cell_count(private_root)
            await resources_.close()
            engine.close()
            cleanup_complete = worker.closed
        finally:
            _write_summary(
                root,
                private_root,
                run_id=run_id,
                receipt=receipt,
                broker_receipt=broker_receipt,
                replay_verified=replay_verified,
                sealed_trace=sealed_trace,
                cleanup_complete=cleanup_complete,
                comparison_report=comparison_report,
                reason=reason,
                failure=failure,
                diagnostics=diagnostics,
            )
    return P7LiveExecution(
        run_id=run_id,
        completed_level_count=int(receipt.get("completed_level_count", 0)),
        primitive_action_count=int(receipt.get("primitive_action_count", 0)),
        replay_verified=replay_verified,
        sealed_trace=sealed_trace,
        cleanup_complete=cleanup_complete,
        trace_root=trace_root,
        receipt=receipt,
        comparison_report=comparison_report,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    root = Path.cwd().resolve()
    run_id = _safe_run_id()
    try:
        result = asyncio.run(_run_live(root, run_id))
        receipt = classify_live_result(result)
        print(json.dumps(receipt, allow_nan=False, separators=(",", ":"), sort_keys=True))
        print("[asterion-prime-p7] PASS", file=sys.stderr, flush=True)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        reason = str(error) if isinstance(error, LiveSolveError) else "unsuccessful"
        result = P7LiveExecution(
            run_id=run_id,
            completed_level_count=0,
            primitive_action_count=0,
            replay_verified=False,
            sealed_trace=False,
            cleanup_complete=False,
            trace_root=root,
            receipt={},
            comparison_report=None,
        )
        print(
            json.dumps(
                _public_receipt("unsuccessful", result, reason=reason),
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        print("[asterion-prime-p7] unsuccessful", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
