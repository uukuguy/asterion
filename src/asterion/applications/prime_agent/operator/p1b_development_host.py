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
from .p1b_development_sdk_provider import create_prime_p1b_development_sdk_provider
from .p1b_workload import PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST


_SCOPE = "p1-b-development"
_PROMOTION = "unpromoted"
_MODEL_COUNT = 5
_TOOL_COUNT = 2
_PROBE_COUNT = 12
_HOST_TRACE_DOMAIN = "asterion.prime.p1-b-development.host-trace/v1"
_INITIAL_SNAPSHOT_SHA256 = (
    "sha256:4f8e0bca0f70582bad96caa292823ac29577633bebd9f76257617dc92ab6832f"
)
_PROMPT_ONE = "Complete the first fixed P1-B development cell using ipython."
_PROMPT_TWO = "Complete the second fixed P1-B development cell using ipython."


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
) -> PrimeP1BDevelopmentTrace:
    """Run the one fixed P1-B development flow and emit only its safe trace."""
    if not isinstance(operator_config, Mapping):
        raise PrimeP1BDevelopmentHostError()
    suffix = uuid4().hex
    run_id = "prime-p1b-development-" + suffix
    session_id = "prime-p1b-development-session-" + suffix
    service: P1BDockerPersistentWorkerService | None = None
    gateway: PrimeP1BDevelopmentGateway | None = None
    provider: object | None = None
    gateway_open = False
    gateway_closed = False
    try:
        provider = create_prime_p1b_development_sdk_provider(operator_config)
        service = P1BDockerPersistentWorkerService(
            image_digest=image_digest,
            transport=transport,
            run_id=run_id,
            session_id=session_id,
        )
        await service.acquire()
        model_calls = 0
        tool_calls = 0
        tool_ids: set[str] = set()

        async def model_hook(payload: object) -> dict[str, object]:
            nonlocal model_calls
            if (
                model_calls >= _MODEL_COUNT
                or type(payload) is not dict
                or not callable(provider)
            ):
                raise ValueError
            body = _canonical_json(payload).encode("utf-8")
            reply = await provider(body)
            value = _strict_json_object(reply)
            model_calls += 1
            return value

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
            observed = await service.execute_cell(payload["code"])
            tool_calls += 1
            if (
                type(observed) is not dict
                or observed.get("cell_count") != tool_calls
                or observed.get("kernel_generation") != 1
                or observed.get("probe_count") != tool_calls * 6
            ):
                raise ValueError
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
            await gateway.open(
                run_id=run_id,
                session_id=session_id,
                generation=1,
                prime_source_root=prime_source_root,
                workspace=workspace,
            )
            gateway_open = True
            if (await gateway.prompt(_PROMPT_ONE)).get("lifecycle") != "completed":
                raise ValueError
            compact = _safe_witness(await gateway.compact())
            if (await gateway.prompt(_PROMPT_TWO)).get("lifecycle") != "completed":
                raise ValueError
            await gateway.close()
            gateway_closed = True
        if (
            model_calls != _MODEL_COUNT
            or tool_calls != _TOOL_COUNT
            or len(tool_ids) != _TOOL_COUNT
        ):
            raise ValueError
        _terminal_provider_usage(provider)
        completion = await service.finish()
        post = await service.snapshot()
        if (
            not inspect_answer_source(post)
            or completion.kernel_generation != 1
            or completion.cell_count != _TOOL_COUNT
            or completion.probe_count != _PROBE_COUNT
        ):
            raise ValueError
        return PrimeP1BDevelopmentTrace(
            trace_sha256=_trace_digest(
                run_id=run_id,
                session_id=session_id,
                compact=compact,
                post=post,
            )
        )
    except asyncio.CancelledError:
        raise
    except BaseException:
        raise PrimeP1BDevelopmentHostError() from None
    finally:
        if gateway is not None and gateway_open and not gateway_closed:
            await _stop_gateway(gateway)
        await _stop_provider(provider)
        if service is not None:
            try:
                await service.cleanup()
            except BaseException:
                pass


async def _stop_gateway(gateway: PrimeP1BDevelopmentGateway) -> None:
    try:
        await gateway.cancel()
    except BaseException:
        pass
    try:
        await gateway.close()
    except BaseException:
        pass


async def _stop_provider(provider: object | None) -> None:
    """Support a future explicit provider closer without widening its public API."""
    closer = getattr(provider, "close", None)
    if callable(closer):
        try:
            result = closer()
            if hasattr(result, "__await__"):
                await result
        except BaseException:
            pass


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
    *, run_id: str, session_id: str, compact: dict[str, object], post: bytes
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
        "initial_snapshot_sha256": _INITIAL_SNAPSHOT_SHA256,
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
