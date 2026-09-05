"""Private fake-closable P1-B development host orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
from tempfile import TemporaryDirectory
from typing import Literal
from uuid import uuid4

from .ipython_host_supervisor import inspect_answer_source
from .p1_development_sdk_provider import _canonical_json
from .p1b_development_docker import P1BDockerPersistentWorkerService, P1BDockerTransport
from .p1b_development_gateway import PrimeP1BDevelopmentGateway, _safe_witness
from .p1b_development_observation import _P1BObservation
from .p1b_development_sdk_provider import (
    PrimeP1BDevelopmentSdkProvider,
    create_prime_p1b_development_sdk_provider,
)
from .p1b_workload import PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST


_SCOPE = "p1-b-development"
_PROMOTION = "unpromoted"
_MODEL_COUNT = 5
_TOOL_COUNT = 2
_PROBE_COUNT = 12
_HOST_TRACE_DOMAIN = "asterion.prime.p1-b-development.host-trace/v1"
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


class PrimeP1BDevelopmentHostError(ValueError):
    """Public-safe P1-B development host failure."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1-B development host is unavailable")


@dataclass(frozen=True, repr=False)
class PrimeP1BDevelopmentTrace:
    """The sole public, immutable, body-free P1-B development result."""

    scope: Literal["p1-b-development"] = _SCOPE
    promotion: Literal["unpromoted"] = _PROMOTION
    trace_sha256: str = ""

    def __post_init__(self) -> None:
        if type(self.trace_sha256) is not str or not _digest(self.trace_sha256):
            raise PrimeP1BDevelopmentHostError()

    def __repr__(self) -> str:
        return "PrimeP1BDevelopmentTrace(redacted)"


async def run_prime_p1b_development(
    *,
    image_digest: str,
    transport: P1BDockerTransport,
    operator_config: Mapping[str, object],
    node_bin: str,
    entrypoint: str,
    prime_source_root: str,
    run_id: str | None = None,
    _observation: _P1BObservation | None = None,
) -> PrimeP1BDevelopmentTrace:
    """Run the one fixed P1-B development flow and emit only its safe trace."""
    if not isinstance(operator_config, Mapping):
        raise PrimeP1BDevelopmentHostError()
    suffix = uuid4().hex
    if run_id is None:
        run_id = "prime-p1b-development-" + suffix
    elif type(run_id) is not str or not run_id:
        raise PrimeP1BDevelopmentHostError()
    session_id = "prime-p1b-development-session-" + suffix
    service: P1BDockerPersistentWorkerService | None = None
    gateway: PrimeP1BDevelopmentGateway | None = None
    provider: object | None = None
    gateway_open = False
    gateway_closed = False
    provider_closed = False
    cleanup_complete = False
    active_work: tuple[str, int | None] | None = None
    try:
        provider = create_prime_p1b_development_sdk_provider(operator_config)
        service = P1BDockerPersistentWorkerService(
            image_digest=image_digest,
            transport=transport,
            run_id=run_id,
            session_id=session_id,
        )
        active_work = ("worker.acquire", None)
        _record(_observation, "worker.acquire")
        await service.acquire()
        _record(_observation, "worker.acquire", state="succeeded")
        active_work = ("worker.snapshot0", None)
        _record(_observation, "worker.snapshot0")
        initial = await service.initial_snapshot()
        _record(_observation, "worker.snapshot0", state="succeeded")
        active_work = ("oracle", 0)
        _record(_observation, "oracle", index=0)
        if "sha256:" + sha256(
            initial
        ).hexdigest() != "sha256:" + _STARTER_SHA256 or inspect_answer_source(initial):
            raise ValueError
        _record(_observation, "oracle", index=0, state="succeeded")
        active_work = None
        model_calls = 0
        tool_calls = 0
        tool_ids: set[str] = set()

        async def model_hook(payload: object) -> dict[str, object]:
            nonlocal active_work, model_calls
            if (
                model_calls >= _MODEL_COUNT
                or type(payload) is not dict
                or not callable(provider)
            ):
                raise ValueError
            index = model_calls
            previous_work = active_work
            active_work = ("provider.callback", index)
            _record(_observation, "provider.callback", index=index)
            try:
                body = _canonical_json(payload).encode("utf-8")
                reply = await provider(body)
                value = _strict_json_object(reply)
            except BaseException:
                _record(
                    _observation, "provider.callback", index=index,
                    state=_provider_failure_state(provider),
                )
                active_work = previous_work
                raise
            model_calls += 1
            _record(_observation, "provider.callback", index=index, state="succeeded")
            active_work = previous_work
            return value

        async def tool_hook(payload: object) -> dict[str, object]:
            nonlocal active_work, tool_calls
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
            index = tool_calls
            previous_work = active_work
            active_work = ("worker.cell", index)
            tool_ids.add(payload["tool_call_id"])
            _record(_observation, "worker.cell", index=index)
            try:
                observed = await service.execute_cell(payload["code"])
            except BaseException:
                _record(_observation, "worker.cell", index=index, state="failed")
                active_work = previous_work
                raise
            tool_calls += 1
            if (
                type(observed) is not dict
                or observed.get("cell_count") != tool_calls
                or observed.get("kernel_generation") != 1
                or observed.get("probe_count") != tool_calls * 6
            ):
                _record(_observation, "worker.cell", index=index, state="failed")
                active_work = previous_work
                raise ValueError
            _record(_observation, "worker.cell", index=index, state="succeeded")
            active_work = previous_work
            return {
                "content": [{"text": "IPython cell completed", "type": "text"}],
                "details": {},
                "isError": False,
            }

        with TemporaryDirectory(prefix="asterion-prime-p1b-") as workspace:
            gateway = PrimeP1BDevelopmentGateway(
                node_bin=node_bin,
                entrypoint=entrypoint,
                model_hook=model_hook,
                tool_hook=tool_hook,
                deadline_seconds=180,
            )
            active_work = ("gateway.open", None)
            _record(_observation, "gateway.open")
            await gateway.open(
                run_id=run_id,
                session_id=session_id,
                generation=1,
                prime_source_root=prime_source_root,
                workspace=workspace,
            )
            gateway_open = True
            _record(_observation, "gateway.open", state="succeeded")
            active_work = ("gateway.prompt0", None)
            _record(_observation, "gateway.prompt0")
            prompt_zero = await gateway.prompt(_PROMPT_ONE)
            if prompt_zero.get("lifecycle") != "completed":
                raise ValueError
            _record(_observation, "gateway.prompt0", state="succeeded")
            active_work = ("gateway.compact", None)
            _record(_observation, "gateway.compact")
            compact = _safe_witness(await gateway.compact())
            _record(_observation, "gateway.compact", state="succeeded")
            active_work = ("gateway.prompt1", None)
            _record(_observation, "gateway.prompt1")
            prompt_one = await gateway.prompt(_PROMPT_TWO)
            if prompt_one.get("lifecycle") != "completed":
                raise ValueError
            _record(_observation, "gateway.prompt1", state="succeeded")
            active_work = ("gateway.close", None)
            _record(_observation, "gateway.close")
            await gateway.close()
            gateway_closed = True
            _record(_observation, "gateway.close", state="succeeded")
            active_work = None
        if (
            model_calls != _MODEL_COUNT
            or tool_calls != _TOOL_COUNT
            or len(tool_ids) != _TOOL_COUNT
        ):
            raise ValueError
        active_work = ("provider.usage", None)
        _record(_observation, "provider.usage")
        _terminal_provider_usage(provider)
        _record(_observation, "provider.usage", state="succeeded")
        active_work = ("worker.finish", None)
        _record(_observation, "worker.finish")
        completion = await service.finish()
        _record(_observation, "worker.finish", state="succeeded")
        active_work = ("worker.snapshot1", None)
        _record(_observation, "worker.snapshot1")
        post = await service.snapshot()
        _record(_observation, "worker.snapshot1", state="succeeded")
        active_work = ("oracle", 1)
        _record(_observation, "oracle", index=1)
        if (
            not inspect_answer_source(post)
            or completion.kernel_generation != 1
            or completion.cell_count != _TOOL_COUNT
            or completion.probe_count != _PROBE_COUNT
        ):
            raise ValueError
        _record(_observation, "oracle", index=1, state="succeeded")
        active_work = ("trace", None)
        _record(_observation, "trace")
        trace_sha256 = _trace_digest(
            run_id=run_id,
            session_id=session_id,
            compact=compact,
            initial=initial,
            post=post,
        )
        _record(_observation, "trace", state="succeeded")
        active_work = ("provider.close", None)
        _record(_observation, "provider.close")
        await _close_provider(provider)
        provider_closed = True
        _record(_observation, "provider.close", state="succeeded")
        active_work = None
        _record(_observation, "worker.cleanup", lane="cleanup")
        await service.cleanup()
        cleanup_complete = True
        _record(_observation, "worker.cleanup", lane="cleanup", state="succeeded")
        return PrimeP1BDevelopmentTrace(trace_sha256=trace_sha256)
    except asyncio.CancelledError:
        raise
    except BaseException:
        if active_work is not None:
            _record(_observation, active_work[0], index=active_work[1], state="failed")
        raise PrimeP1BDevelopmentHostError() from None
    finally:
        if not cleanup_complete:
            await _shielded_best_effort_cleanup(
                gateway=gateway,
                gateway_open=gateway_open,
                gateway_closed=gateway_closed,
                provider=provider,
                provider_closed=provider_closed,
                service=service,
                observation=_observation,
            )


def _record(
    observation: _P1BObservation | None,
    stage: str,
    *,
    lane: str = "work",
    state: str = "started",
    index: int | None = None,
) -> None:
    if observation is not None:
        observation.record(stage, lane=lane, state=state, index=index)


def _provider_failure_state(provider: object) -> str:
    if type(provider) is not PrimeP1BDevelopmentSdkProvider:
        return "failed"
    failure = getattr(provider, "_failure", None)
    kind = getattr(failure, "kind", None)
    if kind in {
        "dns", "connect", "tls", "timeout", "http-4xx", "http-5xx", "response",
    }:
        return "failed-" + kind
    return "failed"


async def _stop_gateway(
    gateway: PrimeP1BDevelopmentGateway,
    observation: _P1BObservation | None,
) -> None:
    failed = False
    _record(observation, "gateway.close", lane="cleanup")
    try:
        await gateway.cancel()
    except BaseException:
        failed = True
    try:
        await gateway.close()
    except BaseException:
        failed = True
    _record(
        observation, "gateway.close", lane="cleanup",
        state="failed" if failed else "succeeded",
    )


async def _close_provider(provider: object | None) -> None:
    """Close the bounded provider before Docker cleanup can authorize a trace."""
    closer = getattr(provider, "close", None)
    if not callable(closer):
        raise ValueError
    result = closer()
    if not hasattr(result, "__await__"):
        raise ValueError
    await result


async def _shielded_best_effort_cleanup(
    *,
    gateway: PrimeP1BDevelopmentGateway | None,
    gateway_open: bool,
    gateway_closed: bool,
    provider: object | None,
    provider_closed: bool,
    service: P1BDockerPersistentWorkerService | None,
    observation: _P1BObservation | None,
) -> None:
    async def cleanup() -> None:
        if gateway is not None and gateway_open and not gateway_closed:
            await _stop_gateway(gateway, observation)
        if provider is not None and not provider_closed:
            _record(observation, "provider.close", lane="cleanup")
            try:
                await _close_provider(provider)
            except BaseException:
                _record(observation, "provider.close", lane="cleanup", state="failed")
            else:
                _record(observation, "provider.close", lane="cleanup", state="succeeded")
        if service is not None:
            _record(observation, "worker.cleanup", lane="cleanup")
            try:
                await service.cleanup()
            except BaseException:
                _record(observation, "worker.cleanup", lane="cleanup", state="failed")
            else:
                _record(observation, "worker.cleanup", lane="cleanup", state="succeeded")

    task = asyncio.create_task(cleanup())
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError


def _terminal_provider_usage(provider: object | None) -> None:
    terminal_usage = getattr(provider, "terminal_usage", None)
    if not callable(terminal_usage):
        raise ValueError
    usage = terminal_usage()
    if not all(
        type(getattr(usage, field, None)) is int and getattr(usage, field) >= 0
        for field in ("input_tokens", "output_tokens", "cost_microunits")
    ):
        raise ValueError


def _trace_digest(
    *,
    run_id: str,
    session_id: str,
    compact: dict[str, object],
    initial: bytes,
    post: bytes,
) -> str:
    value = {
        "domain": _HOST_TRACE_DOMAIN,
        "workload_digest": PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST,
        "run_id": run_id,
        "session_id": session_id,
        "provider_request_count": _MODEL_COUNT,
        "tool_call_count": _TOOL_COUNT,
        "prompt_count": 2,
        "manual_compact_count": 1,
        "compact": compact,
        "kernel_generation_count": 1,
        "kernel_restart_count": 0,
        "continuity_probe_count": _PROBE_COUNT,
        "initial_snapshot_sha256": "sha256:" + sha256(initial).hexdigest(),
        "post_snapshot_sha256": "sha256:" + sha256(post).hexdigest(),
        "initial_ast_oracle_passed": False,
        "final_ast_oracle_passed": True,
        "cleanup": True,
    }
    return (
        "sha256:"
        + sha256(
            json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
    )


def _strict_json_object(value: object) -> dict[str, object]:
    if type(value) is not bytes:
        raise ValueError
    try:
        decoded = json.loads(value.decode("utf-8", "strict"))
        if (
            type(decoded) is not dict
            or _canonical_json(decoded).encode("utf-8") != value
        ):
            raise ValueError
        return decoded
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        raise ValueError from None


def _digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 71
        and value.startswith("sha256:")
        and all(char in "0123456789abcdef" for char in value[7:])
    )


__all__ = (
    "PrimeP1BDevelopmentHostError",
    "PrimeP1BDevelopmentTrace",
    "run_prime_p1b_development",
)
