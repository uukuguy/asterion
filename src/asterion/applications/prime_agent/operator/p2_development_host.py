"""Private P2 development lifecycle with a corpus-owning host oracle.

The worker only executes its one IPython cell.  This module, rather than the
worker or model, reads the result and decides whether an unpromoted trace may
exist.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Literal, Protocol

from .p2_development_workload import (
    P2_DEVELOPMENT_AGGREGATE,
    P2_DEVELOPMENT_CORPUS_DIGEST,
    P2_DEVELOPMENT_WORKLOAD_DIGEST,
    canonical_p2_development_corpus_bytes,
    p2_development_aggregate,
)
from .p2_development_docker import PrimeP2DevelopmentDockerTransport
from .p2_development_gateway import PrimeP2DevelopmentGateway
from .p2_development_sdk_provider import create_prime_p2_development_sdk_provider
from .docker_worker import _LifecycleCallControl
from asterion.runtime.host import CancellationSignal

_MAX_CELL_BYTES = 16 * 1024
_CALLBACKS = 2


class PrimeP2DevelopmentHostError(ValueError):
    """Body-free P2 development failure."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P2 development host is unavailable")


class P2DevelopmentGateway(Protocol):
    async def open(self, **kwargs: object) -> None: ...
    async def prompt(self, prompt: str) -> Mapping[str, object]: ...
    async def cancel(self) -> Mapping[str, object]: ...
    async def close(self) -> None: ...


@dataclass(frozen=True, repr=False)
class PrimeP2DevelopmentEvidence:
    """A digest-only development trace; never a production result."""

    trace: "PrimeP2DevelopmentTrace"
    scope: Literal["p2-development"] = "p2-development"
    promotion: Literal["unpromoted"] = "unpromoted"

    def __repr__(self) -> str:
        return "PrimeP2DevelopmentEvidence(redacted)"


class PrimeP2DevelopmentTrace:
    __slots__ = ("_digest",)

    def __init__(self, digest: str) -> None:
        if not isinstance(digest, str) or not digest.startswith("sha256:") or len(digest) != 71:
            raise PrimeP2DevelopmentHostError()
        self._digest = digest

    @property
    def evidence_digest(self) -> str:
        return self._digest

    @property
    def trace_sha256(self) -> str:
        return self._digest

    def __repr__(self) -> str:
        return "PrimeP2DevelopmentTrace(redacted)"


async def run_p2_development_lifecycle(
    *,
    gateway: P2DevelopmentGateway,
    open_arguments: Mapping[str, object],
    prompt: str,
    run_id: str,
    session_id: str,
    image_digest: str,
    callback_count: Callable[[], int],
    tool_count: Callable[[], int],
    cell_bytes: Callable[[], bytes],
    read_result: Callable[[], Awaitable[bytes]],
    cleanup: Callable[[], Awaitable[None]],
    usage_certain: Callable[[], bool],
    terminal_usage: Callable[[], object],
) -> PrimeP2DevelopmentEvidence:
    """Bind one SDK prompt, one cell, host oracle and verified cleanup.

    Adapters provide opaque callbacks.  Their private provider, corpus and
    process details never flow into an exception or the resulting trace.
    """
    opened = False
    cleaned = False
    try:
        if (
            type(run_id) is not str
            or not run_id
            or type(session_id) is not str
            or not session_id
            or type(image_digest) is not str
            or not image_digest.startswith("sha256:")
            or len(image_digest) != 71
        ):
            raise ValueError
        expected_open_identity = {
            "generation": 1,
            "prime_source_root": open_arguments.get("prime_source_root"),
            "run_id": run_id,
            "session_id": session_id,
            "workspace": open_arguments.get("workspace"),
        }
        if (
            dict(open_arguments) != expected_open_identity
            or type(expected_open_identity["prime_source_root"]) is not str
            or not os.path.isabs(expected_open_identity["prime_source_root"])
            or type(expected_open_identity["workspace"]) is not str
            or not os.path.isabs(expected_open_identity["workspace"])
        ):
            raise ValueError
        corpus = canonical_p2_development_corpus_bytes()
        if "sha256:" + sha256(corpus).hexdigest() != P2_DEVELOPMENT_CORPUS_DIGEST:
            raise ValueError
        if p2_development_aggregate(corpus) != P2_DEVELOPMENT_AGGREGATE:
            raise ValueError
        await gateway.open(**dict(open_arguments))
        opened = True
        result = await gateway.prompt(prompt)
        observed_usage, observations = _validate_gateway_result(
            result, terminal_usage()
        )
        cell = cell_bytes()
        if type(cell) is not bytes or not cell or len(cell) > _MAX_CELL_BYTES:
            raise ValueError
        if callback_count() != _CALLBACKS or tool_count() != 1 or not usage_certain():
            raise ValueError
        aggregate_bytes = await read_result()
        aggregate = _validate_p2_result(aggregate_bytes)
        await gateway.close()
        opened = False
        await cleanup()
        cleaned = True
        return PrimeP2DevelopmentEvidence(
            PrimeP2DevelopmentTrace(
                "sha256:"
                + sha256(
                    _canonical(
                        {
                            "aggregate": aggregate,
                            "aggregate_sha256": "sha256:"
                            + sha256(aggregate_bytes).hexdigest(),
                            "callbacks": _CALLBACKS,
                            "cell_sha256": "sha256:" + sha256(cell).hexdigest(),
                            "cleanup": "container-absent",
                            "corpus_sha256": P2_DEVELOPMENT_CORPUS_DIGEST,
                            "image_digest": image_digest,
                            "observations": observations,
                            "run_id": run_id,
                            "session_id": session_id,
                            "tool_calls": 1,
                            "usage": observed_usage,
                            "workload": P2_DEVELOPMENT_WORKLOAD_DIGEST,
                        }
                    )
                ).hexdigest()
            )
        )
    except BaseException as error:
        if opened:
            try:
                await gateway.cancel()
            except BaseException:
                pass
            try:
                await gateway.close()
            except BaseException:
                pass
        if not cleaned:
            try:
                await cleanup()
            except BaseException:
                pass
        if isinstance(error, asyncio.CancelledError):
            raise
        raise PrimeP2DevelopmentHostError() from None


async def run_prime_p2_development(
    *, image_digest: str, transport: PrimeP2DevelopmentDockerTransport,
    operator_config: Mapping[str, object], node_bin: str, entrypoint: str,
    prime_source_root: str, run_id: str, signal: CancellationSignal | None = None,
) -> PrimeP2DevelopmentTrace:
    """Concrete local P2 Docker + SDK execution entry point."""
    if not isinstance(transport, PrimeP2DevelopmentDockerTransport) or not isinstance(run_id, str) or not run_id:
        raise PrimeP2DevelopmentHostError()
    provider = create_prime_p2_development_sdk_provider(operator_config)
    control = _LifecycleCallControl(monotonic() + 300, signal)
    container = await transport.create(image_digest=image_digest, run_id=run_id, session_id="p2-" + run_id, control=control)
    callbacks = 0
    cells: list[bytes] = []
    try:
        await transport.start(container, control)

        async def model(payload: object) -> object:
            nonlocal callbacks
            callbacks += 1
            return json.loads(await provider(_canonical(payload)))

        async def tool(payload: object) -> object:
            if type(payload) is not dict or set(payload) != {"tool_call_id", "code"} or type(payload["code"]) is not str:
                raise PrimeP2DevelopmentHostError()
            cell = payload["code"].encode("utf-8", "strict")
            cells.append(cell)
            await transport.execute_cell(container, payload["code"], control)
            return {"content": [{"type": "text", "text": "cell completed"}], "details": {}, "isError": False}

        gateway = PrimeP2DevelopmentGateway(node_bin=node_bin, entrypoint=entrypoint, deadline_seconds=60, model_hook=model, tool_hook=tool)
        async def read() -> bytes:
            return await transport.read_result(container, control)
        async def cleanup() -> None:
            cleanup_control = _LifecycleCallControl(monotonic() + 5.0, None)
            await transport.remove(container, cleanup_control)
            await transport.assert_absent(container, cleanup_control)
        def certain() -> bool:
            try:
                provider.terminal_usage()
                return True
            except BaseException:
                return False
        session_id = "p2-" + run_id
        with TemporaryDirectory(prefix="asterion-prime-p2-") as workspace:
            evidence = await run_p2_development_lifecycle(gateway=gateway, open_arguments={"run_id": run_id, "session_id": session_id, "generation": 1, "prime_source_root": prime_source_root, "workspace": workspace}, prompt=_P2_PROMPT, run_id=run_id, session_id=session_id, image_digest=image_digest, callback_count=lambda: callbacks, tool_count=lambda: len(cells), cell_bytes=lambda: cells[0] if len(cells) == 1 else b"", read_result=read, cleanup=cleanup, usage_certain=certain, terminal_usage=provider.terminal_usage)
        return evidence.trace
    except BaseException as error:
        try:
            cleanup_control = _LifecycleCallControl(monotonic() + 5.0, None)
            await transport.remove(container, cleanup_control)
            await transport.assert_absent(container, cleanup_control)
        except BaseException:
            pass
        if isinstance(error, asyncio.CancelledError):
            raise
        raise PrimeP2DevelopmentHostError() from None


def _validate_p2_result(value: object) -> dict[str, int]:
    """Accept only the exact aggregate serialization written by the cell."""
    expected = b'{"count":3,"sum":23}\n'
    if type(value) is not bytes or value != expected:
        raise PrimeP2DevelopmentHostError()
    try:
        decoded = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PrimeP2DevelopmentHostError() from None
    if type(decoded) is not dict or decoded != P2_DEVELOPMENT_AGGREGATE:
        raise PrimeP2DevelopmentHostError()
    return {"count": 3, "sum": 23}


def _validate_gateway_result(
    value: object, terminal: object
) -> tuple[dict[str, int], dict[str, object]]:
    if type(value) is not dict or set(value) != {
        "assistant",
        "lifecycle",
        "observations",
        "usage",
    }:
        raise PrimeP2DevelopmentHostError()
    usage, assistant, observations = (
        value["usage"],
        value["assistant"],
        value["observations"],
    )
    if value["lifecycle"] != "completed" or type(usage) is not dict or set(usage) != {"input_tokens", "output_tokens", "total_tokens"} or assistant != {"completed": True, "stop_reason": "stop"}:
        raise PrimeP2DevelopmentHostError()
    if any(type(usage[key]) is not int or usage[key] < 0 for key in usage) or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]:
        raise PrimeP2DevelopmentHostError()
    if (usage["input_tokens"], usage["output_tokens"]) != (getattr(terminal, "input_tokens", None), getattr(terminal, "output_tokens", None)):
        raise PrimeP2DevelopmentHostError()
    cost = getattr(terminal, "cost_microunits", None)
    if type(cost) is not int or cost < 0:
        raise PrimeP2DevelopmentHostError()
    expected_observations = {
        "active_tool_names": ["ipython"],
        "compact_count": 0,
        "model_callback_count": 2,
        "rlm_child_count": 0,
        "tool_call_count": 1,
    }
    if observations != expected_observations:
        raise PrimeP2DevelopmentHostError()
    return (
        {
            "cost_microunits": cost,
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["total_tokens"],
        },
        expected_observations,
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


__all__ = (
    "P2DevelopmentGateway",
    "PrimeP2DevelopmentEvidence",
    "PrimeP2DevelopmentHostError",
    "PrimeP2DevelopmentTrace",
    "run_p2_development_lifecycle",
    "run_prime_p2_development",
)

_P2_PROMPT = (
    "Use the ipython tool exactly once. Read /opt/prime-p2/records.jsonl using only "
    "its include:boolean and value:integer schema. Write the aggregate object with "
    "count and sum keys to /workspace/result.json as UTF-8 JSON with lexicographically "
    "sorted keys, no spaces, and exactly one trailing newline. Do not reveal corpus "
    "contents. Then make a text-only completion."
)
