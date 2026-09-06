"""Private P4 orchestration over injected gateway, provider, and worker ports.

The host owns sequencing and evidence validation.  The ports keep native
session details private and make the lifecycle fake-closable for tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from hashlib import sha256
import json
from typing import Protocol

from .ipython_host_supervisor import inspect_answer_source
from .p1b_development_docker import (
    P1BDockerCompletion,
    P1BDockerPersistentWorkerService,
)
from .p1b_development_sdk_provider import PrimeP1BDevelopmentSdkProvider
from .p4_development_receipt import (
    P4DevelopmentReceipt,
    validate_p4_development_receipt,
)
from .p4_development_workload import (
    P4_DEVELOPMENT_MODEL_DIGEST,
    P4_DEVELOPMENT_ORACLE_DIGEST,
    P4_DEVELOPMENT_SCHEMA_DIGEST,
    P4_DEVELOPMENT_WORKLOAD_DIGEST,
)


# The P4 host deliberately retains P1-B's bounded provider and persistent
# worker implementations; only the native session gateway is a new port.
P4PersistentWorkerService = P1BDockerPersistentWorkerService
P4SdkProvider = PrimeP1BDevelopmentSdkProvider


_MODEL_COUNT = 5
_TOOL_COUNT = 2
_PROBE_COUNT = 12
_STARTER_SHA256 = "4f8e0bca0f70582bad96caa292823ac29577633bebd9f76257617dc92ab6832f"
_PROMPT_ONE = """Use the ipython tool exactly once. Submit exactly this Python cell:
from pathlib import Path as P1BPath
p1b_value = 41
def p1b_answer():
    return 42
import os
P1BPath("p1b-state").mkdir()
os.chdir(P1BPath.cwd() / "p1b-state")
P1BPath("continuity.txt").write_bytes(b"p1b continuity fixture\\n")
assert P1BPath("continuity.txt").read_bytes() == b"p1b continuity fixture\\n"
"""
_PROMPT_TWO = """Use the ipython tool exactly once. Use the preserved p1b_value, P1BPath, p1b_answer, current directory, and continuity.txt. Submit exactly this Python cell:
assert p1b_value == 41
assert p1b_answer() == 42
assert P1BPath("continuity.txt").read_bytes() == b"p1b continuity fixture\\n"
P1BPath("/workspace/solution.py").write_text("def answer() -> int:\\n    return 42\\n", encoding="utf-8")
"""


class PrimeP4DevelopmentHostError(ValueError):
    """Public-safe P4 lifecycle failure."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P4 development host is unavailable")


class P4DevelopmentGateway(Protocol):
    def bind(
        self,
        *,
        model_hook: Callable[[object], Awaitable[dict[str, object]]],
        tool_hook: Callable[[object], Awaitable[dict[str, object]]],
    ) -> None: ...
    async def open(self, **kwargs: object) -> None: ...
    async def prompt(self, prompt: str) -> Mapping[str, object]: ...
    async def recover(self) -> Mapping[str, object]: ...
    async def compact(self) -> Mapping[str, object]: ...
    async def cancel(self) -> object: ...
    async def close(self) -> None: ...


class P4DevelopmentWorker(Protocol):
    async def acquire(self) -> None: ...
    async def initial_snapshot(self) -> bytes: ...
    async def execute_cell(self, cell: str) -> Mapping[str, object]: ...
    async def finish(self) -> P1BDockerCompletion: ...
    async def snapshot(self) -> bytes: ...
    async def cleanup(self) -> None: ...


class P4DevelopmentProvider(Protocol):
    async def __call__(self, body: bytes) -> bytes: ...
    def terminal_usage(self) -> object: ...
    async def close(self) -> None: ...


class PrimeP4DevelopmentTrace:
    """The sole public P4 projection; receipt bodies never leave this module."""

    __slots__ = ("_digest",)

    def __init__(self, digest: str) -> None:
        if not _is_digest(digest):
            raise PrimeP4DevelopmentHostError()
        self._digest = digest

    @property
    def trace_sha256(self) -> str:
        return self._digest

    def __repr__(self) -> str:
        return "PrimeP4DevelopmentTrace(redacted)"


async def run_p4_development_lifecycle(
    *,
    gateway: P4DevelopmentGateway,
    provider: P4DevelopmentProvider,
    worker: P4DevelopmentWorker,
    run_id: str,
    session_id: str,
    prime_source_root: str,
    workspace: str,
) -> PrimeP4DevelopmentTrace:
    """Run P4 exactly once; no failed or uncertain action is replayed."""
    if not _inputs_are_valid(
        gateway, provider, worker, run_id, session_id, prime_source_root, workspace
    ):
        raise PrimeP4DevelopmentHostError()
    opened = provider_closed = cleaned = False
    cancelled = False
    try:
        await worker.acquire()
        initial = await worker.initial_snapshot()
        if (
            type(initial) is not bytes
            or "sha256:" + sha256(initial).hexdigest() != "sha256:" + _STARTER_SHA256
            or inspect_answer_source(initial)
        ):
            raise ValueError

        model_calls = tool_calls = 0
        tool_ids: set[str] = set()

        async def model_hook(payload: object) -> dict[str, object]:
            nonlocal model_calls
            if model_calls >= _MODEL_COUNT or type(payload) is not dict:
                raise ValueError
            reply = _strict_json_object(await provider(_canonical(payload)))
            model_calls += 1
            return reply

        async def tool_hook(payload: object) -> dict[str, object]:
            nonlocal tool_calls
            if (
                tool_calls >= _TOOL_COUNT
                or type(payload) is not dict
                or set(payload) != {"tool_call_id", "code"}
                or type(payload["tool_call_id"]) is not str
                or not payload["tool_call_id"]
                or payload["tool_call_id"] in tool_ids
                or type(payload["code"]) is not str
                or not payload["code"]
            ):
                raise ValueError
            tool_ids.add(payload["tool_call_id"])
            observed = await worker.execute_cell(payload["code"])
            tool_calls += 1
            if (
                type(observed) is not dict
                or observed.get("cell_count") != tool_calls
                or observed.get("kernel_generation") != 1
                or observed.get("probe_count") != tool_calls * 6
            ):
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
        first = await gateway.prompt(_PROMPT_ONE)
        candidate = _checkpoint_candidate(first)
        recovered = await gateway.recover()
        _validate_recovery(candidate, recovered)
        compact = await gateway.compact()
        if type(compact) is not dict or compact.get("succeeded") is not True:
            raise ValueError
        second = await gateway.prompt(_PROMPT_TWO)
        if (
            type(second) is not dict
            or second.get("lifecycle") != "completed"
            or model_calls != _MODEL_COUNT
            or tool_calls != _TOOL_COUNT
            or len(tool_ids) != _TOOL_COUNT
            or second.get("model_callback_count") != _MODEL_COUNT
            or second.get("tool_callback_count") != _TOOL_COUNT
        ):
            raise ValueError
        await gateway.close()
        opened = False
        usage = _usage(provider.terminal_usage())
        completion = await worker.finish()
        post = await worker.snapshot()
        if (
            type(post) is not bytes
            or not inspect_answer_source(post)
            or getattr(completion, "kernel_generation", None) != 1
            or getattr(completion, "cell_count", None) != _TOOL_COUNT
            or getattr(completion, "probe_count", None) != _PROBE_COUNT
        ):
            raise ValueError
        await provider.close()
        provider_closed = True
        await worker.cleanup()
        cleaned = True
        receipt = _receipt(
            candidate=candidate,
            compact=compact,
            usage=usage,
            initial=initial,
            post=post,
        )
        validate_p4_development_receipt(receipt)
        return trace_p4_development_receipt(receipt)
    except asyncio.CancelledError:
        cancelled = True
    except BaseException:
        pass
    finally:
        if not cleaned:
            await _cleanup(
                gateway=gateway,
                provider=provider,
                worker=worker,
                opened=opened,
                provider_closed=provider_closed,
            )
    if cancelled:
        raise asyncio.CancelledError
    raise PrimeP4DevelopmentHostError()


def trace_p4_development_receipt(receipt: object) -> PrimeP4DevelopmentTrace:
    """Project a previously validated receipt to its body-free trace."""
    try:
        validate_p4_development_receipt(receipt)
        return PrimeP4DevelopmentTrace(
            _digest(
                {
                    "receipt": vars(receipt),
                    "domain": "asterion.prime.p4-development.trace/v1",
                }
            )
        )
    except BaseException:
        raise PrimeP4DevelopmentHostError() from None


async def _cleanup(
    *,
    gateway: P4DevelopmentGateway,
    provider: P4DevelopmentProvider,
    worker: P4DevelopmentWorker,
    opened: bool,
    provider_closed: bool,
) -> None:
    async def action() -> None:
        if opened:
            try:
                await gateway.cancel()
            except BaseException:
                pass
            try:
                await gateway.close()
            except BaseException:
                pass
        if not provider_closed:
            try:
                await provider.close()
            except BaseException:
                pass
        try:
            await worker.cleanup()
        except BaseException:
            pass

    task = asyncio.create_task(action())
    interrupted = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            interrupted = True
    task.result()
    if interrupted:
        raise asyncio.CancelledError


def _checkpoint_candidate(first: object) -> dict[str, object]:
    if type(first) is not dict or first.get("lifecycle") != "completed":
        raise ValueError
    candidate = first.get("checkpoint_candidate")
    if type(candidate) is not dict or set(candidate) != {
        "active_session_id",
        "session_id",
        "cursor",
        "transcript_sha256",
        "tree_sha256",
        "artifact_sha256",
    }:
        raise ValueError
    if not all(
        _is_digest(candidate[key])
        for key in ("transcript_sha256", "tree_sha256", "artifact_sha256")
    ):
        raise ValueError
    _cursor(candidate["cursor"])
    if not all(
        type(candidate[key]) is str and candidate[key]
        for key in ("active_session_id", "session_id")
    ):
        raise ValueError
    return candidate


def _validate_recovery(candidate: Mapping[str, object], recovered: object) -> None:
    if type(recovered) is not dict or set(recovered) != {
        "active_session_id",
        "session_id",
        "from_cursor",
        "to_cursor",
        "snapshot_cursor",
    }:
        raise ValueError
    if (
        recovered["active_session_id"] != candidate["active_session_id"]
        or recovered["session_id"] != candidate["session_id"]
        or recovered["from_cursor"] != candidate["cursor"]
        or recovered["to_cursor"] != candidate["cursor"]
        or recovered["snapshot_cursor"] != candidate["cursor"]
    ):
        raise ValueError
    _cursor(recovered["to_cursor"])


def _receipt(
    *,
    candidate: Mapping[str, object],
    compact: Mapping[str, object],
    usage: Mapping[str, int],
    initial: bytes,
    post: bytes,
) -> P4DevelopmentReceipt:
    cursor = candidate["cursor"]
    cursor_digest = _digest(cursor)
    return P4DevelopmentReceipt(
        P4_DEVELOPMENT_WORKLOAD_DIGEST,
        P4_DEVELOPMENT_SCHEMA_DIGEST,
        P4_DEVELOPMENT_MODEL_DIGEST,
        P4_DEVELOPMENT_ORACLE_DIGEST,
        P4_DEVELOPMENT_ORACLE_DIGEST,
        _digest({"runtime": candidate["tree_sha256"]}),
        _digest({"session": candidate["session_id"]}),
        candidate["transcript_sha256"],
        _digest({"kernel": candidate["artifact_sha256"]}),
        cursor_digest,
        cursor_digest,
        cursor_digest,
        cursor_digest,
        _digest(
            {"initial": sha256(initial).hexdigest(), "post": sha256(post).hexdigest()}
        ),
        _digest(compact),
        _digest(usage),
        _digest({"post": sha256(post).hexdigest()}),
        0,
        cursor["sequence"],
        cursor["sequence"],
        cursor["sequence"],
        cursor["sequence"],
        0,
        0,
        1,
        1,
        1,
        2,
        5,
        2,
        1,
        1,
        1,
        1,
        1,
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
        True,
        True,
        True,
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(value: object) -> str:
    return "sha256:" + sha256(_canonical(value)).hexdigest()


def _is_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 71
        and value.startswith("sha256:")
        and all(c in "0123456789abcdef" for c in value[7:])
    )


def _cursor(value: object) -> None:
    if (
        type(value) is not dict
        or set(value) != {"generation", "sequence"}
        or type(value["generation"]) is not str
        or not value["generation"]
        or type(value["sequence"]) is not int
        or isinstance(value["sequence"], bool)
        or value["sequence"] < 0
    ):
        raise ValueError


def _strict_json_object(value: object) -> dict[str, object]:
    if type(value) is not bytes:
        raise ValueError
    decoded = json.loads(value.decode("utf-8", "strict"))
    if type(decoded) is not dict or _canonical(decoded) != value:
        raise ValueError
    return decoded


def _usage(value: object) -> dict[str, int]:
    fields = ("input_tokens", "output_tokens", "cost_microunits")
    if not all(
        type(getattr(value, field, None)) is int and getattr(value, field) >= 0
        for field in fields
    ):
        raise ValueError
    return {field: getattr(value, field) for field in fields}


def _inputs_are_valid(
    gateway: object,
    provider: object,
    worker: object,
    run_id: object,
    session_id: object,
    prime_source_root: object,
    workspace: object,
) -> bool:
    return (
        all(
            type(value) is str and value
            for value in (run_id, session_id, prime_source_root, workspace)
        )
        and all(
            callable(getattr(gateway, field, None))
            for field in (
                "bind",
                "open",
                "prompt",
                "recover",
                "compact",
                "cancel",
                "close",
            )
        )
        and all(
            callable(getattr(provider, field, None))
            for field in ("__call__", "terminal_usage", "close")
        )
        and all(
            callable(getattr(worker, field, None))
            for field in (
                "acquire",
                "initial_snapshot",
                "execute_cell",
                "finish",
                "snapshot",
                "cleanup",
            )
        )
    )


__all__ = (
    "P4DevelopmentGateway",
    "P4DevelopmentProvider",
    "P4DevelopmentWorker",
    "P4PersistentWorkerService",
    "P4SdkProvider",
    "PrimeP4DevelopmentHostError",
    "PrimeP4DevelopmentTrace",
    "run_p4_development_lifecycle",
    "trace_p4_development_receipt",
)
