"""Operator-side plumbing for the fixed native P7 solve preset.

Recovered from the removed ``tools/run_asterion_prime_p7.py`` driver. The
process boundary, the ARC engine adapter and the private-evidence readers keep
that driver's behaviour. What moving them into the installed application
package changed is where each value comes from:

* the IPython worker runs on this environment's own interpreter, so nothing
  resolves an interpreter outside the distribution;
* the Pi command is assembled from operator-owned values, so nothing here
  reaches into a Pi checkout; and
* the comparison report comes from the application-owned
  :func:`asterion.applications.prime.p7.comparison.compare_runs`, not from a
  repository tool an installed wheel cannot import.

Nothing in this module decides how the run is orchestrated; that stays in
:mod:`asterion.applications.prime.p7.operator`. This module is the leaf, so the
operator module may import it and never the other way round.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from importlib import resources as importlib_resources
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading

from asterion.agents.prime.trace import PrimeTraceEntry, validate_trace
from asterion.applications.prime.p7.game import DEFAULT_GAME, P7GameSelection
from asterion.applications.prime.p7.ipython_host import (
    IpythonWorkerResult,
    P7ClientFacade,
)
from asterion.applications.prime.p7.tool_registry import P7_APPLICATION_TOOL_NAMES


GAME_ID = DEFAULT_GAME.game_id
SEED = DEFAULT_GAME.seed
WORKER_PROTOCOL = "asterion.prime-p7-worker/v1"
_PRIVATE_ROOT = ".asterion-private/prime-p7-live"
_CELL_LOG = "worker-cells.jsonl"
_TRACE_NAME = "prime-trace.jsonl"
OPERATOR_ROOT_ENV = "ASTERION_PRIME_OPERATOR_ROOT"
ARC_ROOT_ENV = "ASTERION_PRIME_ARC_ROOT"
NODE_ENV = "ASTERION_PRIME_NODE"
PI_ENTRY_ENV = "ASTERION_PRIME_PI_ENTRY"
PI_AGENT_DIR_ENV = "ASTERION_PRIME_PI_AGENT_DIR"
_EXTENSION_RESOURCE = "resources/ipython-extension.mjs"
# The fixed Pi RPC contract this application launches. It is the same mode
# surface the intact run-story narrator uses; only the tool exposure differs,
# because the solve reaches the game through the packaged IPython extension.
_PI_RPC_FLAGS = (
    "--mode",
    "rpc",
    "--print",
    "--no-builtin-tools",
    "--tools",
    ",".join(P7_APPLICATION_TOOL_NAMES),
    "--approve",
    "--no-session",
    "--no-extensions",
    "--no-skills",
    "--no-prompt-templates",
    "--no-themes",
    "--no-context-files",
    "--thinking",
    "high",
)


class P7LiveSolveError(RuntimeError):
    """Body-free live-solve failure carrying a fixed public reason.

    Every message raised with this type is a fixed public-safe string, so the
    operator entrypoint may project it into a receipt ``reason``. Failures of
    any other type are reported as a single generic reason instead.
    """


@dataclass(frozen=True, slots=True)
class P7LiveExecution:
    """One live solve attempt, successful or not."""

    run_id: str
    completed_level_count: int
    primitive_action_count: int
    replay_verified: bool
    sealed_trace: bool
    cleanup_complete: bool
    trace_root: Path
    receipt: Mapping[str, object]
    comparison_report: Path | None
    game: P7GameSelection
    broker_replay_sha256: str
    terminal_reason: str


class NeverCancelled:
    """The preset runs to its own deadline; it exposes no cancellation input."""

    @property
    def cancelled(self) -> bool:
        return False


class ProcessCancellation:
    """Mutable cancellation state used to let supervisor signals seal evidence."""

    __slots__ = ("_cancelled",)

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


class ArcadeEngine:
    """The ARC-AGI-3 adapter the broker and the replay share.

    The engine is a black box behind the broker's ``_ArcEngine`` protocol, so
    the ARC packages are imported only when a live solve actually constructs
    one. An operator-supplied ARC root is the only thing that names them.
    """

    def __init__(
        self,
        *,
        arc_root: Path,
        recordings_dir: Path,
        game: P7GameSelection = DEFAULT_GAME,
    ) -> None:
        from arc_agi import Arcade, OperationMode
        from arcengine import GameAction

        if type(game) is not P7GameSelection:
            raise P7LiveSolveError("P7 game selection is unavailable")
        # The SDK gives COMPETITION in the process environment precedence over
        # the OFFLINE constructor argument and may contact the API in __init__.
        if os.environ.get("OPERATION_MODE", "").strip().lower() == "competition":
            raise P7LiveSolveError("offline ARC mode is unavailable")
        self.game_id = game.game_id
        self.seed = game.seed
        recordings_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(f"asterion.prime.p7.{id(self)}")
        self._logger.handlers = []
        self._logger.addHandler(logging.NullHandler())
        self._logger.propagate = False
        self._actions = {
            f"ACTION{number}": getattr(GameAction, f"ACTION{number}")
            for number in range(1, 8)
        }
        self._actions["RESET"] = GameAction.RESET
        self._arcade = Arcade(
            operation_mode=OperationMode.OFFLINE,
            environments_dir=str(arc_root / "environment_files"),
            recordings_dir=str(recordings_dir),
            logger=self._logger,
        )
        if self._arcade.operation_mode != OperationMode.OFFLINE:
            raise P7LiveSolveError("offline ARC mode is unavailable")
        self._environment = self._arcade.make(
            game.game_id,
            seed=game.seed,
            include_frame_data=True,
            save_recording=True,
        )
        if self._environment is None:
            raise P7LiveSolveError("ARC environment is unavailable")
        self._current = self._environment.reset()

    def __repr__(self) -> str:
        return "<ArcadeEngine redacted>"

    def observe(self) -> Mapping[str, object]:
        return self._snapshot(self._current)

    def step(self, action: str, data: Mapping[str, int] | None = None) -> Mapping[str, object]:
        if action not in self._actions:
            raise P7LiveSolveError("ARC action is unavailable")
        self._current = self._environment.step(self._actions[action], {} if data is None else dict(data))
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
            return [ArcadeEngine._frame(item) for item in value]
        if type(value) is tuple:
            return [ArcadeEngine._frame(item) for item in value]
        return value  # type: ignore[return-value]

    @classmethod
    def _snapshot(cls, value: object) -> Mapping[str, object]:
        if value is None:
            raise P7LiveSolveError("ARC observation is unavailable")
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


class P7ClientServer:
    """Operator-side endpoint the restricted worker process calls over a socket.

    The worker never receives the live client object; it receives only the
    six game operations through this single-threaded server, which is the
    only holder of the sealed facade.
    """

    __slots__ = ("_client", "_stop", "_directory", "_socket", "_thread", "path")

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

    def __repr__(self) -> str:
        return "<P7ClientServer redacted>"

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
                or request.get("protocol") != WORKER_PROTOCOL
                or type(request.get("id")) is not int
                or request.get("method") not in {"observe", "status", "mechanics_prior", "act", "history", "frame_at", "act_checked", "tried_actions", "last_outcome_summary", "world_model", "observation_state", "game_mechanics", "counterfactual_search", "cognition", "cognition_update", "action_effects", "mechanism_candidates", "probe_plan", "simulator_status", "playbook", "retrodiction_status", "model_search", "record_hypothesis", "promote_hypothesis"}
                or type(request.get("args")) is not list
            ):
                raise ValueError
            method = str(request["method"])
            args = request["args"]
            if len(args) != {"observe": 0, "status": 0, "mechanics_prior": 0, "act": 1, "history": 2, "frame_at": 1, "act_checked": 1, "tried_actions": 1, "last_outcome_summary": 1, "world_model": 0, "observation_state": 0, "game_mechanics": 0, "counterfactual_search": 0, "cognition": 0, "cognition_update": 1, "action_effects": 0, "mechanism_candidates": 0, "probe_plan": 0, "simulator_status": 0, "playbook": 1, "retrodiction_status": 0, "model_search": 0, "record_hypothesis": 3, "promote_hypothesis": 2}[method]:
                raise ValueError
            value = getattr(self._client, method)(*args)
            response = {
                "id": request["id"],
                "ok": True,
                "protocol": WORKER_PROTOCOL,
                "value": value,
            }
            encoded = json.dumps(response, allow_nan=False, separators=(",", ":")).encode()
            if method == "history" and len(json.dumps(value, allow_nan=False, separators=(",", ":")).encode()) > 16384:
                raise ValueError
            return encoded
        except Exception:
            return json.dumps({"id": None, "ok": False, "protocol": WORKER_PROTOCOL}, separators=(",", ":")).encode()


class SubprocessPythonWorker:
    """The restricted persistent worker, on this environment's interpreter.

    ``python`` defaults to ``sys.executable``, i.e. the isolated interpreter the
    preset installed the wheel into. The worker therefore needs nothing outside
    the distribution, and the cell namespace survives across cells because the
    process is the state.
    """

    __slots__ = ("_root", "_python", "_server", "_process", "closed")

    def __init__(self, *, root: Path, python: Path | None = None) -> None:
        self._root = root
        self._python = Path(sys.executable) if python is None else python
        self._server: P7ClientServer | None = None
        self._process: subprocess.Popen[str] | None = None
        self.closed = False

    def __repr__(self) -> str:
        return "<SubprocessPythonWorker redacted>"

    async def start(self, p7_client: P7ClientFacade, *, signal: object) -> None:
        if getattr(signal, "cancelled", False):
            raise P7LiveSolveError("P7 worker was cancelled")
        workspace = self._root / "worker"
        workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._server = P7ClientServer(p7_client)
        (workspace / "p7_client.py").write_text(
            client_module_source(str(self._server.path)), encoding="utf-8"
        )
        controller = worker_controller_source()
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

    async def execute_cell(self, code: str, *, signal: object) -> IpythonWorkerResult:
        if getattr(signal, "cancelled", False):
            raise P7LiveSolveError("P7 worker was cancelled")
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise P7LiveSolveError("P7 worker is unavailable")
        request = json.dumps({"code": code}, separators=(",", ":")) + "\n"
        process.stdin.write(request)
        process.stdin.flush()
        raw = await asyncio.to_thread(process.stdout.readline)
        if not raw:
            raise P7LiveSolveError("P7 worker exited")
        value = json.loads(raw)
        if (
            type(value) is not dict
            or set(value) != {"cell_count", "is_error", "output"}
            or type(value["cell_count"]) is not int
            or type(value["is_error"]) is not bool
            or type(value["output"]) is not str
        ):
            raise P7LiveSolveError("P7 worker returned invalid output")
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
            with (self._root / _CELL_LOG).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        except Exception:
            return


def worker_controller_source() -> str:
    """The cell loop that runs inside the restricted worker process."""

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


def client_module_source(socket_path: str) -> str:
    """The exact module the restricted worker imports to reach the game.

    ``p7_client_module_facade`` validates this source against a fixed shape, so
    it stays a plain module with six public functions and no other public
    statements.
    """

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
    if (
        isinstance(frame, list)
        and frame
        and isinstance(frame[0], list)
        and frame[0]
        and isinstance(frame[0][0], list)
    ):
        return frame[-1]
    return frame

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
    rows = len(before_grid)
    cols = len(before_grid[0]) if rows else 0
    border_changed = sum(
        1 for x, y, _old, _new in changes
        if x == 0 or y == 0 or x == cols - 1 or y == rows - 1
    )
    interior_changed = len(changes) - border_changed
    if not changes:
        return {{
            "changed": 0,
            "interior_changed_cells": 0,
            "border_changed_cells": 0,
            "border_only": False,
            "bbox": None,
            "sample": [],
        }}
    xs = [item[0] for item in changes]
    ys = [item[1] for item in changes]
    return {{
        "changed": len(changes),
        "interior_changed_cells": interior_changed,
        "border_changed_cells": border_changed,
        "border_only": bool(border_changed and not interior_changed),
        "bbox": [min(xs), min(ys), max(xs), max(ys)],
        "sample": changes[:80],
    }}

def summary(obs=None):
    value = observe() if obs is None else obs
    grid = _grid(value)
    current_status = value.get("status")
    if current_status is None:
        current_status = status()
    return {{
        "available_actions": value["available_actions"],
        "counts": _counts(grid),
        "components": _components(grid)[:40],
        "levels_completed": value["levels_completed"],
        "positions_0_1": positions([0, 1], value),
        "shape": _shape(value["frame"]),
        "state": value["state"],
        "status": current_status,
        "win_levels": value["win_levels"],
    }}

def render(obs=None, *, x0=0, y0=0, x1=64, y1=64):
    grid = _grid(obs)
    symbols = dict(enumerate("0123456789ABCDEF"))
    rows = []
    for y in range(max(0, y0), min(len(grid), y1)):
        row = grid[y]
        rows.append(f"{{y:02d}} " + "".join(symbols.get(row[x], "?") for x in range(max(0, x0), min(len(row), x1))))
    return "\\n".join(rows)

def act_and_observe(actions):
    before = p7_observe()
    after = p7_act(actions)
    return {{"act": after["batch"], "diff": diff(before, after), "summary": summary(after)}}

def p7_observe():
    """Read the current game state.

    Returns the full observation dictionary: available_actions, last
    settled frame, levels_completed, state, win_levels. Use this *first*
    on a new level to see what actions are available and where you are.
    """
    return _call("observe")

def p7_mechanics_prior():
    """Read bounded mechanics evidence inferred from prior actions."""
    return _call("mechanics_prior")

def p7_history(start, limit):
    """Read a page of session history records starting at index `start` with up to `limit` records."""
    return _call("history", start, limit)

def p7_frame_at(sequence):
    """Read the settled frame at history sequence `sequence`."""
    return _call("frame_at", sequence)

def p7_act_checked(plan):
    """Dispatch a checked batch of actions with prediction.

    ``plan`` is a list of ``{{action, expect}}`` dicts. Each ``expect`` keys
    on a cell value, frame hash, levels_completed, or state. The broker
    stops at the first mismatch / no-effect / unavailable action. Use this
    instead of bare :func:`p7_act` when you have a specific hypothesis to
    test; a wrong prediction costs only one tool_use call instead of an
    action slot.
    """
    return _call("act_checked", plan)

def p7_tried_actions(level=None):
    """Enumerate every ``(level, action, position)`` tuple the model has
    dispatched this run, with counts.

    ``level=None`` returns all levels. ``position`` is
    ``{{"x": int, "y": int}}`` for ``ACTION6`` clicks and ``None`` for
    direction / interact actions. The broker records every dispatched
    action unconditionally — including the prefix replay from any prior
    verified level — so this view spans cross-level history. Call this
    before dispatching a probe you are unsure about: if the same
    ``(action, position)`` tuple already has a non-zero count at this
    level, the broker has already observed its outcome.
    """
    return _call("tried_actions", level)

def p7_last_outcome_summary(level=None):
    """Aggregate per-action counts for the current run, split into
    ``{{"attempts": {{action: count}}, "no_effect": {{action: count}}}}``.

    Useful for spotting an action that has been attempted many times
    at this level with no observed frame change. ``level=None`` sums
    across all levels.
    """
    return _call("last_outcome_summary", level)

def p7_world_model():
    """Read the bounded same-game confirmed model projection."""
    return _call("world_model")

def p7_observation_state():
    """Read the unified immutable observation with optional game metadata."""
    return _call("observation_state")

def p7_game_mechanics():
    """Read persistent game-wide mechanisms; this is advisory memory only."""
    return _call("game_mechanics")

def p7_counterfactual_search():
    """Compare candidate mechanics and subgoal progress without dispatching actions."""
    return _call("counterfactual_search")

def p7_cognition():
    """Read advisory type cognition and exact-game experience."""
    return _call("cognition")

def p7_cognition_update(payload):
    """Propose or analyze semantic cognition; never dispatches an action."""
    return _call("cognition_update", payload)

def p7_action_effects():
    """Read bounded per-action effect summaries learned in this run."""
    return _call("action_effects")

def p7_mechanism_candidates():
    """Read mechanism candidates and their evidence lifecycle."""
    return _call("mechanism_candidates")

def p7_probe_plan():
    """Read one safe probe suggestion without dispatching it."""
    return _call("probe_plan")

def p7_simulator_status():
    """Read simulator coverage and certificate status."""
    return _call("simulator_status")

def p7_playbook(level=None):
    """Read the bounded same-game Playbook projection."""
    return _call("playbook", level)

def p7_retrodiction_status():
    """Read scalar transition-model verification status."""
    return _call("retrodiction_status")

def p7_model_search():
    """Search a verified same-game mechanism without dispatching actions."""
    return _call("model_search")

def p7_record_hypothesis(layer, key, value):
    """Submit one bounded hypothesis with an application-owned probe."""
    return _call("record_hypothesis", layer, key, value)

def p7_promote_hypothesis(key, evidence_kind):
    """Promote a visual candidate only after broker-verified action evidence."""
    return _call("promote_hypothesis", key, evidence_kind)

def p7_components(level=None):
    """Return connected-component analysis of the current settled grid.

    Each component is a 4-connected region of non-background cells, with
    its color value, axis-aligned bounding box, and cell count. Background
    is treated as value 4 by convention; pass a different value if the
    game uses a different background color.

    This is what the worker should call *first* on a new level: it gives
    the structural layout (cart, markers, walls, etc.) without forcing the
    model to recompute connected components in Python.
    """
    value = p7_observe()
    grid = _grid(value)
    return _components(grid)


def _p7_untried_clicks(level=None):
    """Return the components at ``level`` that the model has NOT yet clicked.

    Combines :func:`p7_components` with :func:`p7_tried_actions` so the
    model can see, at a glance, which component positions are still
    unexplored. ``tried_actions`` only returns a flat list of counts;
    this function returns structured component positions that are NOT
    in the tried set.

    Call this before dispatching a probe on a component that has not
    been visited yet; the broker will still apply ``no_effect_guard`` on
    repeated clicks inside that component.
    """
    components = p7_components(level)
    tried = p7_tried_actions(level)
    tried_keys = {{
        (
            item["action"],
            tuple(sorted(item["position"].items()))
            if item.get("position") is not None
            else None,
        )
        for item in tried
    }}
    untried: list[dict[str, object]] = []
    for comp in components:
        position = {{"x": (comp["bbox"][0] + comp["bbox"][2]) // 2,
                     "y": (comp["bbox"][1] + comp["bbox"][3]) // 2}}
        action_name = "ACTION6"
        key = (
            action_name,
            tuple(sorted(position.items())),
        )
        if key not in tried_keys:
            entry = dict(comp, position=position, suggested_action=action_name)
            untried.append(entry)
    return untried


def _p7_hypothesis(level, key, value=None):
    """DEPRECATED: model rarely uses this; framework injects components
    and untried-clicks directly via level_hint / no_effect_hint.

    Kept for backward-compatibility but new model runs should prefer
    calling p7_observe and inspecting the auto-injected hints.
    """
    from .hypothesis_store import hypothesis_store
    return hypothesis_store(level).getset(key, value)


def p7_act(actions):
    if isinstance(actions, str):
        actions = [{{"name": actions, "data": {{}}}}]
    elif isinstance(actions, dict):
        actions = [{{"name": actions["name"], "data": actions.get("data", {{}})}}]
    elif isinstance(actions, list) and all(isinstance(action, str) for action in actions):
        actions = [{{"name": action, "data": {{}}}} for action in actions]
    batch = _call("act", actions)
    view = batch["observation"]
    current = batch["terminal"]
    levels = current["levels_completed"]
    target = current["target_level"]
    remaining = current["actions_remaining"]
    reason = current["terminal_reason"]
    terminal = (
        "GAME_SOLVED" if view["state"] == "WIN" and levels >= target
        else "LEVEL_SOLVED" if reason == "level-completed" and levels >= target
        else "ACTION_CAP" if remaining <= 0
        else "RESET_REQUIRED" if reason == "reset-required"
        else "GAME_OVER" if reason == "game-incomplete"
        else "GAME_OVER" if reason == "game-over"
        else "LEVEL_ADVANCED" if batch["level_advanced"]
        else "ACTIVE"
    )
    return {{
        **view,
        "actions_taken": current["primitive_actions"],
        "actions_remaining": remaining,
        "status": current,
        "terminal": terminal,
        "batch": batch,
    }}

# Stable worker-facing names used by the P7 prompt. The p7_* names above are
# retained for the native tool documentation and share the same socket calls.
def observe():
    return p7_observe()

def status():
    return _call("status")

def mechanics_prior():
    return p7_mechanics_prior()

def history(start, limit):
    return p7_history(start, limit)

def frame_at(sequence):
    return p7_frame_at(sequence)

def act_checked(plan):
    return p7_act_checked(plan)

def tried_actions(level=None):
    return p7_tried_actions(level)

def last_outcome_summary(level=None):
    return p7_last_outcome_summary(level)

def world_model():
    return p7_world_model()

def observation_state():
    return p7_observation_state()

def game_mechanics():
    return p7_game_mechanics()

def counterfactual_search():
    return p7_counterfactual_search()

def cognition():
    return p7_cognition()

def cognition_update(payload):
    return p7_cognition_update(payload)

def action_effects():
    return p7_action_effects()

def mechanism_candidates():
    return p7_mechanism_candidates()

def probe_plan():
    return p7_probe_plan()

def simulator_status():
    return p7_simulator_status()

def playbook(level=None):
    return p7_playbook(level)

def retrodiction_status():
    return p7_retrodiction_status()

def model_search():
    return p7_model_search()

def record_hypothesis(layer, key, value):
    return p7_record_hypothesis(layer, key, value)

def promote_hypothesis(key, evidence_kind):
    return p7_promote_hypothesis(key, evidence_kind)

def components(level=None):
    return p7_components(level)

def act(actions):
    return p7_act(actions)
'''


def _dotenv_values(path: Path) -> Mapping[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip().strip("'").strip('"')
    return values


def load_operator_environment(operator_root: Path) -> Mapping[str, str]:
    """Merge operator-owned configuration with the process environment.

    The process environment supplies runtime paths and credentials. Model
    selection is configuration-owned: when the operator file declares a
    provider or model, it wins over stale exported values from the terminal.
    ``ASTERION_PRIME_PI_AGENT_DIR`` is required here so the operator rejects
    an invocation without an authenticated Pi profile before it starts any
    process.
    """

    dotenv = _dotenv_values(operator_root / ".env")
    values = {**dotenv, **os.environ}
    for key in ("ASTERION_PRIME_PROVIDER", "ASTERION_PRIME_MODEL"):
        if key in dotenv:
            values[key] = dotenv[key]
    if not values.get(PI_AGENT_DIR_ENV, "").strip():
        raise P7LiveSolveError("Pi agent profile is unavailable")
    return values


def _resolved_file(environment: Mapping[str, str], name: str) -> Path:
    raw = environment.get(name, "").strip()
    if not raw:
        raise P7LiveSolveError(f"{name} is unavailable")
    try:
        path = Path(raw).resolve(strict=True)
    except OSError:
        raise P7LiveSolveError(f"{name} is unavailable") from None
    if not path.is_file() or not os.access(path, os.X_OK):
        raise P7LiveSolveError(f"{name} is unavailable")
    return path


def resolve_node(environment: Mapping[str, str]) -> Path:
    """Resolve the operator-owned node executable that runs the Pi RPC host."""

    return _resolved_file(environment, NODE_ENV)


def resolve_pi_entry(environment: Mapping[str, str]) -> Path:
    """Resolve the operator-owned Pi RPC entry script.

    Which Pi the operator supplies is the operator's decision; Asterion owns
    only the RPC mode contract it launches that entry with.
    """

    return _resolved_file(environment, PI_ENTRY_ENV)


def resolve_pi_agent_dir(environment: Mapping[str, str]) -> Path:
    """Resolve the operator-owned Pi profile used for Codex OAuth."""

    raw = environment.get(PI_AGENT_DIR_ENV, "").strip()
    if not raw:
        raise P7LiveSolveError(f"{PI_AGENT_DIR_ENV} is unavailable")
    raw_path = Path(raw)
    if raw_path.is_symlink():
        raise P7LiveSolveError(f"{PI_AGENT_DIR_ENV} is unavailable")
    try:
        path = raw_path.resolve(strict=True)
    except OSError:
        raise P7LiveSolveError(f"{PI_AGENT_DIR_ENV} is unavailable") from None
    if (
        not path.is_dir()
        or not (path / "auth.json").is_file()
        or not (path / "models-store.json").is_file()
        or (path / "auth.json").is_symlink()
    ):
        raise P7LiveSolveError(f"{PI_AGENT_DIR_ENV} is unavailable")
    return path


def resolve_arc_root(environment: Mapping[str, str]) -> Path:
    """Resolve the operator-owned ARC-AGI-3 root holding the game data."""

    raw = environment.get(ARC_ROOT_ENV, "").strip()
    if not raw:
        raise P7LiveSolveError(f"{ARC_ROOT_ENV} is unavailable")
    try:
        root = Path(raw).resolve(strict=True)
    except OSError:
        raise P7LiveSolveError(f"{ARC_ROOT_ENV} is unavailable") from None
    if not root.is_dir() or not (root / "environment_files").is_dir():
        raise P7LiveSolveError(f"{ARC_ROOT_ENV} is unavailable")
    return root


def pi_base_command(*, node: Path, pi_entry: Path) -> tuple[str, ...]:
    """Return the exact Pi base argv the application launches.

    ``build_p7_operator_resources`` appends the fixed provider, model and
    extension lease arguments, and rejects a base that already carries any of
    them, so this function must not add them either.
    """

    return (str(node), str(pi_entry), *_PI_RPC_FLAGS)


def extension_path() -> Path:
    """Resolve the packaged Pi extension the runtime pins.

    The installed resource is the only source. The removed driver fell back to
    a path inside the repository's TypeScript tree, which an installed wheel
    cannot reach and a released application must not depend on.
    """

    installed = Path(
        str(
            importlib_resources.files("asterion.applications.prime").joinpath(
                _EXTENSION_RESOURCE
            )
        )
    )
    if installed.is_file():
        return installed.resolve(strict=True)
    raise P7LiveSolveError("P7 extension is unavailable")


def private_root(operator_root: Path, run_id: str) -> Path:
    """Create the one private directory this run owns."""

    path = (operator_root / _PRIVATE_ROOT / run_id).resolve()
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    return path


def safe_run_id() -> str:
    """Return a UTC-stamped, collision-resistant run identity."""

    timestamp = subprocess.run(
        ("date", "-u", "+%Y%m%d%H%M%S"),
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip().lower()
    return "p7-live-" + timestamp + "-" + secrets.token_hex(12)


def receipt_value(result_artifacts: tuple[Mapping[str, object], ...]) -> Mapping[str, object]:
    """Return the single public receipt artifact, or fail closed."""

    if len(result_artifacts) != 1:
        raise P7LiveSolveError("P7 receipt artifact is unavailable")
    value = result_artifacts[0].get("value")
    if not isinstance(value, Mapping):
        raise P7LiveSolveError("P7 receipt artifact is invalid")
    return value


def read_trace_entries(trace_root: Path) -> tuple[PrimeTraceEntry, ...]:
    """Read and verify one sealed private trace."""

    path = trace_root / _TRACE_NAME
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


def worker_cell_count(root: Path) -> int:
    """Count the cells the worker actually executed, for private diagnostics."""

    try:
        path = root / _CELL_LOG
        if not path.is_file():
            return 0
        return sum(1 for _ in path.open(encoding="utf-8"))
    except Exception:
        return 0


def safe_stderr_summary(value: bytes) -> Mapping[str, object]:
    """Summarize host stderr without publishing an unbounded body."""

    text = value[:4096].decode("utf-8", "replace")
    return {
        "bytes": len(value),
        "sha256": hashlib.sha256(value).hexdigest(),
        "prefix": text,
        "truncated": len(value) > 4096,
    }


def find_baseline_trace(operator_root: Path) -> Path | None:
    """Find a sealed operator-stopped trace to compare against, if one exists."""

    configured = os.environ.get("ASTERION_PRIME_P7_BASELINE_TRACE")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend((operator_root / ".asterion-private").glob(f"**/{_TRACE_NAME}"))
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


def compare_if_available(
    operator_root: Path, trace_root: Path, private: Path
) -> Path | None:
    """Write the differential report when a baseline trace is present.

    The comparison runs in-process through the application-owned
    ``compare_runs``; the removed driver shelled out to a repository tool that
    is not part of the distribution.
    """

    from asterion.applications.prime.p7.comparison import compare_runs

    baseline = find_baseline_trace(operator_root)
    if baseline is None:
        return None
    try:
        report = compare_runs(
            read_trace_entries(trace_root), read_trace_entries(baseline.parent)
        )
    except Exception:
        return None
    output = private / "comparison-operator-stopped.json"
    output.write_text(
        json.dumps(
            {
                "baseline": baseline.parent.name,
                "deltas": dict(report.deltas),
                "left": dict(report.left),
                "right": dict(report.right),
                "schema": report.schema,
            },
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return output


def write_summary(
    operator_root: Path,
    private: Path,
    *,
    run_id: str,
    receipt: Mapping[str, object],
    broker_receipt: object,
    game: P7GameSelection,
    replay_verified: bool,
    sealed_trace: bool,
    cleanup_complete: bool,
    comparison_report: Path | None,
    reason: str | None,
    failure: BaseException | None,
    diagnostics: Mapping[str, object],
    completed_prefix: Mapping[str, object] | None = None,
    experiment: Mapping[str, object] | None = None,
    prediction_accounting: Mapping[str, int] | None = None,
) -> None:
    """Write the private per-run summary; never a public surface."""

    levels = getattr(broker_receipt, "levels_completed", None)
    summary = {
        "schema": "asterion.prime.p7-live-private-summary/v1",
        "run_id": run_id,
        "receipt": dict(receipt),
        "broker": None
        if broker_receipt is None
        else {
            "game_id": game.game_id,
            "seed": game.seed,
            "win_levels": game.win_levels,
            "levels_completed": levels,
            "primitive_actions": getattr(broker_receipt, "primitive_actions", None),
            "terminal_reason": getattr(broker_receipt, "terminal_reason", None),
            "replay_sha256": getattr(broker_receipt, "replay_sha256", None),
        },
        "replay_verified": replay_verified,
        "sealed_trace": sealed_trace,
        "completed_prefix": None if completed_prefix is None else dict(completed_prefix),
        "cleanup_complete": cleanup_complete,
        "comparison_report": None
        if comparison_report is None
        else str(comparison_report.relative_to(operator_root)),
        "reason": reason,
        "failure": None
        if failure is None
        else {
            "type": type(failure).__name__,
            "message": str(failure)[:1000],
        },
        "diagnostics": dict(diagnostics),
        "experiment": None if experiment is None else dict(experiment),
        "prediction_accounting": None if prediction_accounting is None else dict(prediction_accounting),
    }
    (private / "summary.json").write_text(
        json.dumps(summary, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


__all__ = (
    "ARC_ROOT_ENV",
    "GAME_ID",
    "PI_AGENT_DIR_ENV",
    "P7_APPLICATION_TOOL_NAMES",
    "NODE_ENV",
    "OPERATOR_ROOT_ENV",
    "PI_ENTRY_ENV",
    "SEED",
    "WORKER_PROTOCOL",
    "ArcadeEngine",
    "NeverCancelled",
    "ProcessCancellation",
    "P7ClientServer",
    "P7LiveExecution",
    "P7LiveSolveError",
    "SubprocessPythonWorker",
    "client_module_source",
    "compare_if_available",
    "extension_path",
    "find_baseline_trace",
    "load_operator_environment",
    "pi_base_command",
    "private_root",
    "read_trace_entries",
    "receipt_value",
    "resolve_arc_root",
    "resolve_node",
    "resolve_pi_entry",
    "resolve_pi_agent_dir",
    "safe_run_id",
    "safe_stderr_summary",
    "worker_cell_count",
    "worker_controller_source",
    "write_summary",
)
