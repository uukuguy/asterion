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
_COUNTS = (2, 4, 2)


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
    async def result_gate(self) -> object: ...
    async def quality_gate(self) -> object: ...
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
    opened = provider_closed = cleaned = False
    cancelled = False
    try:
        await worker.acquire()
        initial = _source_from_snapshot(await worker.snapshot())
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
        first = await gateway.prompt("diagnose clamp defect")
        _completed(first, 2, 1)
        first_result = _gate(await worker.result_gate(), True)
        first_quality = _gate(await worker.quality_gate(), False)
        feedback = _feedback(first_quality)
        await gateway.feedback(feedback)
        second = await gateway.prompt("repair clamp defect")
        _completed(second, 4, 2)
        if (model_calls, tool_calls) != (4, 2):
            raise ValueError
        second_result = _gate(await worker.result_gate(), True)
        second_quality = _gate(await worker.quality_gate(), True)
        repaired = _source_from_snapshot(await worker.snapshot())
        validate_p5_development_snapshot(repaired, repaired=True)
        if sha256(initial).digest() == sha256(repaired).digest():
            raise ValueError
        artifact = await worker.artifact()
        validate_p5_development_artifact(artifact)
        await gateway.close()
        opened = False
        usage = _usage(provider.terminal_usage())
        await provider.close()
        provider_closed = True
        await worker.cleanup()
        cleaned = True
        receipt = P5DevelopmentReceipt(
            P5_DEVELOPMENT_WORKLOAD_DIGEST,
            P5_DEVELOPMENT_SCHEMA_DIGEST,
            P5_DEVELOPMENT_MODEL_DIGEST,
            P5_DEVELOPMENT_ORACLE_DIGEST,
            _digest({"goal": goal_id}),
            _digest({"session": session_id}),
            _digest({"container": container_id}),
            _bytes_digest(initial),
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
    try:
        tree = ast.parse(source.decode("utf-8", "strict"), mode="exec")
    except (SyntaxError, UnicodeError):
        raise ValueError from None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError
    function = tree.body[0]
    if (
        function.name != "clamp"
        or len(function.args.args) != 3
        or [arg.arg for arg in function.args.args] != ["value", "lower", "upper"]
        or len(function.body) != 1
        or not isinstance(function.body[0], ast.Return)
    ):
        raise ValueError
    allowed = (ast.Expression, ast.Return, ast.Call, ast.Name, ast.Load)
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


def validate_p5_development_artifact(value: object) -> None:
    if type(value) is not bytes:
        raise ValueError
    try:
        parsed = json.loads(value.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError from None
    if (
        type(parsed) is not dict
        or parsed != {"passed": True, "result": "clamp"}
        or _canonical(parsed) != value
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


def _completed(value: object, callbacks: int, tools: int) -> None:
    if type(value) is not dict or value != {
        "lifecycle": "completed",
        "model_callback_count": callbacks,
        "tool_callback_count": tools,
    }:
        raise ValueError


def _gate(value: object, passed: bool) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value) != {"passed", "result_sha256"}
        or value["passed"] is not passed
        or not _is_digest(value["result_sha256"])
    ):
        raise ValueError
    return value


def _feedback(value: Mapping[str, object]) -> str:
    if value["passed"] is not False:
        raise ValueError
    return "quality gate failed; repair clamp defect"


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
            for name in ("bind", "open", "prompt", "feedback", "close", "cancel")
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
                "result_gate",
                "quality_gate",
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
