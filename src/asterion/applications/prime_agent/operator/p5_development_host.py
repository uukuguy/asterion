"""Private trusted gate for the fixed P5 clamp repair workload."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Awaitable, Callable, Mapping
from hashlib import sha256
import json
import re
from typing import Protocol

from .p5_development_receipt import (
    P5DevelopmentReceipt,
    validate_p5_development_receipt,
)
from .p5_development_workload import (
    P5_DEVELOPMENT_MODEL_DIGEST,
    P5_DEVELOPMENT_ORACLE_DIGEST,
    P5_DEVELOPMENT_SCHEMA_DIGEST,
    P5_DEVELOPMENT_WORKLOAD_DIGEST,
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_DAEMON_ID = re.compile(r"[0-9a-f]{64}\Z")
_COUNTS = (2, 4, 2)
_GOAL_ID = "prime.bounded-autonomy/v1"
_INITIAL_SOURCE = b"def clamp(value, lower, upper):\n    return min(upper, value)\n"
_REPAIRED_SOURCE = (
    b"def clamp(value, lower, upper):\n"
    b"    return min(max(value, lower), upper)\n"
)


class PrimeP5DevelopmentHostError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P5 development host is unavailable")


class P5DevelopmentGateway(Protocol):
    def bind(
        self,
        *,
        model_hook: Callable[[object], Awaitable[dict[str, object]]],
        tool_hook: Callable[[object], Awaitable[dict[str, object]]],
    ) -> None: ...

    async def open(self, **kwargs: object) -> None: ...
    async def prompt(self, prompt: str) -> Mapping[str, object]: ...
    async def feedback(self, feedback: str) -> Mapping[str, object]: ...
    def terminal_witness(self) -> Mapping[str, object]: ...
    async def close(self) -> None: ...
    async def cancel(self) -> object: ...


class P5DevelopmentProvider(Protocol):
    async def __call__(self, body: bytes) -> bytes: ...
    def terminal_usage(self) -> object: ...
    async def close(self) -> None: ...


class P5DevelopmentWorker(Protocol):
    async def acquire(self) -> None: ...
    async def snapshot(self) -> object: ...
    async def execute_cell(self, cell: str) -> Mapping[str, object]: ...
    async def artifact(self) -> bytes: ...
    async def cleanup(self) -> None: ...


class PrimeP5DevelopmentTrace:
    __slots__ = ("_digest",)

    def __init__(self, digest: str) -> None:
        if not _is_digest(digest):
            raise PrimeP5DevelopmentHostError()
        self._digest = digest

    @property
    def trace_sha256(self) -> str:
        return self._digest

    def __repr__(self) -> str:
        return "PrimeP5DevelopmentTrace(redacted)"


async def run_p5_development_lifecycle(
    *,
    gateway: P5DevelopmentGateway,
    provider: P5DevelopmentProvider,
    worker: P5DevelopmentWorker,
    run_id: str,
    session_id: str,
    container_id: str,
    goal_id: str,
    prime_source_root: str = "/prime",
    workspace: str = "/workspace",
) -> PrimeP5DevelopmentTrace:
    if not _inputs(
        gateway,
        provider,
        worker,
        run_id,
        session_id,
        container_id,
        goal_id,
        prime_source_root,
        workspace,
    ):
        raise PrimeP5DevelopmentHostError()
    if goal_id != _GOAL_ID:
        raise PrimeP5DevelopmentHostError()
    opened = provider_closed = cleaned = False
    cancelled = False
    try:
        await worker.acquire()
        observed_daemon = getattr(worker, "daemon_id", None)
        if (
            type(observed_daemon) is not str
            or _DAEMON_ID.fullmatch(observed_daemon) is None
        ):
            raise ValueError
        container_id = observed_daemon
        image_digest = _worker_image(worker)
        initial = _source_from_snapshot(await worker.snapshot())
        if initial != _INITIAL_SOURCE:
            raise ValueError
        validate_p5_development_snapshot(initial, repaired=False)
        model_calls = tool_calls = 0

        async def model_hook(payload: object) -> dict[str, object]:
            nonlocal model_calls
            if type(payload) is not dict or model_calls >= 4:
                raise ValueError
            reply = _strict_json(await provider(_canonical(payload)))
            model_calls += 1
            return reply

        async def tool_hook(payload: object) -> dict[str, object]:
            nonlocal tool_calls
            if (
                type(payload) is not dict
                or set(payload) != {"tool_call_id", "code"}
                or type(payload["tool_call_id"]) is not str
                or not payload["tool_call_id"]
                or type(payload["code"]) is not str
                or not payload["code"]
                or tool_calls >= 2
            ):
                raise ValueError
            result = await worker.execute_cell(payload["code"])
            tool_calls += 1
            if type(result) is not dict or result.get("cell_count") != tool_calls:
                raise ValueError
            return {
                "content": [{"type": "text", "text": "IPython cell completed"}],
                "details": {},
                "isError": False,
            }

        gateway.bind(model_hook=model_hook, tool_hook=tool_hook)
        await gateway.open(
            run_id=run_id,
            session_id=session_id,
            generation=1,
            prime_source_root=prime_source_root,
            workspace=workspace,
        )
        opened = True
        first = await gateway.prompt(_prompt("diagnose", run_id, goal_id, 1))
        _completed(first, 2, 1)
        diagnosed = _source_from_snapshot(await worker.snapshot())
        validate_p5_development_snapshot(diagnosed, repaired=False)
        if diagnosed != initial:
            raise ValueError
        first_artifact = await worker.artifact()
        validate_p5_development_artifact(
            first_artifact, run_id=run_id, goal_id=goal_id, source=diagnosed, stage=1
        )
        seen_sources: set[str] = set()
        if _bytes_digest(diagnosed) in seen_sources:
            raise ValueError
        seen_sources.add(_bytes_digest(diagnosed))
        first_result, first_quality = _gates(
            diagnosed, first_artifact, run_id, goal_id, 1
        )
        if first_result["passed"] is not True or first_quality["passed"] is not False:
            raise ValueError
        feedback = _feedback(first_quality, run_id, goal_id)
        await gateway.feedback(feedback)
        second = await gateway.prompt(_prompt("repair", run_id, goal_id, 2))
        _completed(second, 4, 2)
        witness = _terminal_witness(gateway.terminal_witness(), run_id, session_id)
        if (model_calls, tool_calls) != (4, 2):
            raise ValueError
        repaired = _source_from_snapshot(await worker.snapshot())
        validate_p5_development_snapshot(repaired, repaired=True)
        if _bytes_digest(repaired) in seen_sources:
            raise ValueError
        seen_sources.add(_bytes_digest(repaired))
        artifact = await worker.artifact()
        validate_p5_development_artifact(
            artifact, run_id=run_id, goal_id=goal_id, source=repaired, stage=2
        )
        second_result, second_quality = _gates(repaired, artifact, run_id, goal_id, 2)
        if second_result["passed"] is not True or second_quality["passed"] is not True:
            raise ValueError
        await gateway.close()
        opened = False
        usage = _usage(provider.terminal_usage())
        await provider.close()
        provider_closed = True
        if getattr(worker, "daemon_id", None) != container_id:
            raise ValueError
        if _worker_image(worker) != image_digest:
            raise ValueError
        await worker.cleanup()
        cleaned = True
        receipt = P5DevelopmentReceipt(
            P5_DEVELOPMENT_WORKLOAD_DIGEST,
            P5_DEVELOPMENT_SCHEMA_DIGEST,
            P5_DEVELOPMENT_MODEL_DIGEST,
            P5_DEVELOPMENT_ORACLE_DIGEST,
            _digest({"goal": goal_id}),
            _digest(dict(witness["identity"])),
            _digest({"container": container_id}),
            _digest({"image": image_digest}),
            _bytes_digest(diagnosed),
            _bytes_digest(repaired),
            _digest(first_result),
            _digest(second_result),
            _digest(first_quality),
            _digest(second_quality),
            _digest(feedback),
            _bytes_digest(artifact),
            _digest(usage),
            *_COUNTS,
            2,
            2,
            1,
            1,
            0,
            0,
            0,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
        )
        validate_p5_development_receipt(receipt)
        return trace_p5_development_receipt(receipt)
    except asyncio.CancelledError:
        cancelled = True
    except BaseException:
        pass
    finally:
        if not cleaned:
            await _cleanup(gateway, provider, worker, opened, provider_closed)
    if cancelled:
        raise asyncio.CancelledError
    raise PrimeP5DevelopmentHostError()


def validate_p5_development_snapshot(source: object, *, repaired: bool) -> None:
    if type(source) is not bytes:
        raise ValueError
    if repaired and source != _REPAIRED_SOURCE:
        raise ValueError
    try:
        tree = ast.parse(source.decode("utf-8", "strict"), mode="exec")
    except (SyntaxError, UnicodeError):
        raise ValueError from None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError
    function = tree.body[0]
    if (
        function.name != "clamp"
        or function.decorator_list
        or function.returns is not None
        or getattr(function, "type_params", ())
        or function.args.posonlyargs
        or len(function.args.args) != 3
        or [arg.arg for arg in function.args.args] != ["value", "lower", "upper"]
        or any(arg.annotation is not None for arg in function.args.args)
        or function.args.defaults
        or function.args.kw_defaults
        or function.args.vararg is not None
        or function.args.kwarg is not None
        or len(function.body) != 1
        or not isinstance(function.body[0], ast.Return)
    ):
        raise ValueError
    allowed = (ast.Return, ast.Call, ast.Name, ast.Load)
    if any(not isinstance(node, allowed) for node in ast.walk(function.body[0])):
        raise ValueError
    names = {
        node.id for node in ast.walk(function.body[0]) if isinstance(node, ast.Name)
    }
    if not names <= {"value", "lower", "upper", "min", "max"}:
        raise ValueError
    expression = function.body[0].value
    exact = (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Name)
        and expression.func.id == "min"
        and len(expression.args) == 2
        and isinstance(expression.args[0], ast.Call)
        and isinstance(expression.args[0].func, ast.Name)
        and expression.args[0].func.id == "max"
        and isinstance(expression.args[1], ast.Name)
        and expression.args[1].id == "upper"
    )
    if repaired is not exact:
        raise ValueError


def validate_p5_development_artifact(
    value: object,
    *,
    run_id: str | None = None,
    goal_id: str | None = None,
    source: bytes | None = None,
    stage: int | None = None,
) -> None:
    if type(value) is not bytes:
        raise ValueError
    try:
        parsed = json.loads(value.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError from None
    if (
        type(parsed) is not dict
        or set(parsed)
        != {"goal_id", "goal_sha256", "marker", "run_id", "source_sha256", "stage"}
        or parsed.get("marker") != "clamp-result"
        or type(parsed.get("stage")) is not int
        or parsed["stage"] not in {1, 2}
        or not _is_digest(parsed.get("goal_sha256"))
        or not _is_digest(parsed.get("source_sha256"))
        or _canonical(parsed) != value
    ):
        raise ValueError
    if run_id is not None and (
        parsed["run_id"] != run_id
        or parsed["goal_id"] != goal_id
        or parsed["stage"] != stage
        or source is None
        or parsed["source_sha256"] != _bytes_digest(source)
        or parsed["goal_sha256"] != _goal_digest(goal_id)
    ):
        raise ValueError


def trace_p5_development_receipt(receipt: object) -> PrimeP5DevelopmentTrace:
    try:
        validate_p5_development_receipt(receipt)
        return PrimeP5DevelopmentTrace(
            _digest(
                {
                    "domain": "asterion.prime.p5-development.trace/v1",
                    "receipt": vars(receipt),
                }
            )
        )
    except BaseException:
        raise PrimeP5DevelopmentHostError() from None


def _source_from_snapshot(value: object) -> bytes:
    if type(value) is bytes:
        return value
    if (
        type(value) is not dict
        or set(value) != {"solution.py"}
        or type(value["solution.py"]) is not bytes
    ):
        raise ValueError
    return value["solution.py"]


def _worker_image(worker: object) -> str:
    value = getattr(worker, "image_digest", None)
    if type(value) is not str or not _is_digest(value):
        raise ValueError
    return value


def _completed(value: object, callbacks: int, tools: int) -> None:
    if type(value) is not dict or value != {
        "lifecycle": "completed",
        "model_callback_count": callbacks,
        "tool_callback_count": tools,
    }:
        raise ValueError


def _terminal_witness(
    value: object, run_id: str, session_id: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "identity",
        "result",
        "cumulative",
    }:
        raise ValueError
    identity, cumulative = value["identity"], value["cumulative"]
    if (
        not isinstance(identity, Mapping)
        or not isinstance(cumulative, Mapping)
        or set(identity) != {"run_id", "session_id", "runtime_id", "generation"}
        or identity["run_id"] != run_id
        or identity["session_id"] != session_id
        or type(identity["generation"]) is not int
        or identity["generation"] != 1
        or identity["runtime_id"] != "prime.agent"
        or set(cumulative) != {"model_callback_count", "tool_callback_count"}
        or any(type(cumulative[name]) is not int for name in cumulative)
        or dict(cumulative) != {"model_callback_count": 4, "tool_callback_count": 2}
    ):
        raise ValueError
    return value


def _gates(
    source: bytes, artifact: bytes, run_id: str, goal_id: str, stage: int
) -> tuple[dict[str, object], dict[str, object]]:
    outcomes = _clamp_cases(source)
    result = {
        "passed": True,
        "result_sha256": _digest(
            {
                "gate": "result",
                "run_id": run_id,
                "goal_id": goal_id,
                "stage": stage,
                "source_sha256": _bytes_digest(source),
                "artifact_sha256": _bytes_digest(artifact),
                "outcomes": outcomes,
            }
        ),
    }
    # A diagnosis is a valid result only if it is the exact fixed defect; quality
    # gates it until the repair replaces the observed workspace bytes.
    quality = {
        "passed": all(outcomes),
        "result_sha256": _digest(
            {
                "gate": "quality",
                "run_id": run_id,
                "goal_id": goal_id,
                "stage": stage,
                "source_sha256": _bytes_digest(source),
                "artifact_sha256": _bytes_digest(artifact),
                "outcomes": outcomes,
            }
        ),
    }
    return result, quality


def _feedback(value: Mapping[str, object], run_id: str, goal_id: str) -> str:
    if value["passed"] is not False:
        raise ValueError
    return (
        "quality gate failed for run="
        + run_id
        + " goal="
        + goal_id
        + " gate="
        + str(value["result_sha256"])
        + "; source="
        + _bytes_digest(_INITIAL_SOURCE)
        + "; repair /workspace/solution.py and replace /workspace/result.json"
    )


def _prompt(phase: str, run_id: str, goal_id: str, stage: int) -> str:
    source = _INITIAL_SOURCE if stage == 1 else _REPAIRED_SOURCE
    return (
        "P5 "
        + phase
        + " stage. You must make exactly one ipython call; that sole call must complete the required filesystem mutation before it returns. "
        "Do not inspect, read, print, execute, or subprocess /workspace/solution.py. Its exact bytes and defect are already known. "
        "Do not use the call for diagnosis, validation, or explanation. "
        "You must atomically write /workspace/result.json with a same-directory temporary file and os.replace, with no trailing newline. "
        "The result bytes must be canonical JSON from json.dumps(..., sort_keys=True, separators=(',', ':')).encode('utf-8') with keys goal_id,goal_sha256,marker,run_id,source_sha256,stage; marker=clamp-result; "
        "source_sha256="
        + _bytes_digest(source)
        + "; goal_sha256="
        + _goal_digest(goal_id)
        + "; run_id="
        + run_id
        + "; goal_id="
        + goal_id
        + "; stage="
        + str(stage)
        + ". "
        + (
            "This is the diagnosis artifact stage: atomically write result.json only. Do not edit /workspace/solution.py."
            if stage == 1
            else "This is the repair stage: repair /workspace/solution.py exactly to def clamp(value, lower, upper):\\n    return min(max(value, lower), upper)\\n, then atomically replace result.json."
        )
    )


def _goal_digest(goal_id: object) -> str:
    if type(goal_id) is not str or not goal_id:
        raise ValueError
    return _digest(
        {
            "format": "asterion.prime-p5-goal/v1",
            "goal_id": goal_id,
            "workload_sha256": P5_DEVELOPMENT_WORKLOAD_DIGEST,
            "oracle_sha256": P5_DEVELOPMENT_ORACLE_DIGEST,
        }
    )


def _clamp_cases(source: bytes) -> tuple[bool, ...]:
    # The AST is recognized first; host never evaluates model bytes.
    try:
        tree = ast.parse(source.decode("utf-8", "strict"), mode="exec")
    except (SyntaxError, UnicodeError):
        raise ValueError from None
    expr = tree.body[0].body[0].value  # validated by validate_p5_development_snapshot

    def eval_expr(node: ast.AST, env: dict[str, int]) -> int:
        if isinstance(node, ast.Name):
            try:
                return env[node.id]
            except KeyError:
                raise ValueError from None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"min", "max"}
            and len(node.args) == 2
        ):
            args = [eval_expr(arg, env) for arg in node.args]
            return min(args) if node.func.id == "min" else max(args)
        raise ValueError

    return tuple(
        eval_expr(expr, {"value": value, "lower": lower, "upper": upper})
        == min(max(value, lower), upper)
        for value, lower, upper in (
            (-4, -2, 3),
            (-1, -2, 3),
            (1, -2, 3),
            (4, -2, 3),
            (-9, -7, -3),
            (-5, -7, -3),
            (0, -7, -3),
        )
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _digest(value: object) -> str:
    return "sha256:" + sha256(_canonical(value)).hexdigest()


def _bytes_digest(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _is_digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _strict_json(value: object) -> dict[str, object]:
    if type(value) is not bytes:
        raise ValueError
    parsed = json.loads(value.decode("utf-8", "strict"))
    if type(parsed) is not dict or _canonical(parsed) != value:
        raise ValueError
    return parsed


def _usage(value: object) -> dict[str, int]:
    fields = ("input_tokens", "output_tokens", "cost_microunits")
    if any(
        type(getattr(value, field, None)) is not int or getattr(value, field) < 0
        for field in fields
    ):
        raise ValueError
    return {field: getattr(value, field) for field in fields}


def _inputs(g: object, p: object, w: object, *ids: object) -> bool:
    return (
        all(type(value) is str and value for value in ids)
        and all(
            callable(getattr(g, name, None))
            for name in (
                "bind",
                "open",
                "prompt",
                "feedback",
                "terminal_witness",
                "close",
                "cancel",
            )
        )
        and all(
            callable(getattr(p, name, None))
            for name in ("__call__", "terminal_usage", "close")
        )
        and all(
            callable(getattr(w, name, None))
            for name in (
                "acquire",
                "snapshot",
                "execute_cell",
                "artifact",
                "cleanup",
            )
        )
    )


async def _cleanup(
    g: object, p: object, w: object, opened: bool, provider_closed: bool
) -> None:
    if opened:
        try:
            await g.cancel()  # type: ignore[attr-defined]
        except BaseException:
            pass
        try:
            await g.close()  # type: ignore[attr-defined]
        except BaseException:
            pass
    if not provider_closed:
        try:
            await p.close()  # type: ignore[attr-defined]
        except BaseException:
            pass
    try:
        await w.cleanup()  # type: ignore[attr-defined]
    except BaseException:
        pass


__all__ = (
    "P5DevelopmentGateway",
    "P5DevelopmentProvider",
    "P5DevelopmentWorker",
    "PrimeP5DevelopmentHostError",
    "PrimeP5DevelopmentTrace",
    "run_p5_development_lifecycle",
    "trace_p5_development_receipt",
    "validate_p5_development_artifact",
    "validate_p5_development_snapshot",
)
