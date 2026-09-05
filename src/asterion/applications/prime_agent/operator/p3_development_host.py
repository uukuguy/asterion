"""P3 host lifecycle over an injected three-worker execution service."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Literal, Protocol

from .p3_development_workload import (
    P3_AGGREGATE_BYTES,
    P3_DEVELOPMENT_WORKLOAD_DIGEST,
    validate_p3_aggregate_bytes,
    validate_p3_source_bytes,
    validate_p3_test_bytes,
)


class PrimeP3DevelopmentHostError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P3 development host is unavailable")


class P3Gateway(Protocol):
    async def open(self, **kwargs: object) -> None: ...
    async def prompt(self, prompt: str) -> Mapping[str, object]: ...
    async def cancel(self) -> Mapping[str, object]: ...
    async def close(self) -> None: ...
    async def request_nested(
        self, kind: str, payload: Mapping[str, object]
    ) -> Mapping[str, object]: ...


class P3ExecutionService(Protocol):
    async def start(self) -> None: ...
    async def execute(self, role: str, cell: str) -> None: ...
    async def read(self, name: str) -> bytes: ...
    async def cleanup(self) -> None: ...


@dataclass(frozen=True, repr=False)
class PrimeP3DevelopmentTrace:
    trace_sha256: str
    scope: Literal["p3-development"] = "p3-development"
    promotion: Literal["unpromoted"] = "unpromoted"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.trace_sha256, str)
            or len(self.trace_sha256) != 71
            or not self.trace_sha256.startswith("sha256:")
        ):
            raise PrimeP3DevelopmentHostError()


async def run_prime_p3_development(
    *,
    gateway: P3Gateway,
    service: P3ExecutionService,
    run_id: str,
    session_id: str,
    prompt: str,
) -> PrimeP3DevelopmentTrace:
    """Run one fixed P3 graph and issue a digest only after absence cleanup."""
    opened = started = cleaned = False
    try:
        if not all(
            isinstance(value, str) and value for value in (run_id, session_id, prompt)
        ):
            raise ValueError
        await service.start()
        started = True
        await gateway.open(
            run_id=run_id,
            session_id=session_id,
            generation=1,
            prime_source_root="/operator/prime",
            workspace="/workspace",
        )
        opened = True
        result = await gateway.prompt(prompt)
        observations = _observations(result)
        source, tests, aggregate = (
            await service.read("solution.py"),
            await service.read("test_solution.py"),
            await service.read("aggregate.json"),
        )
        validate_p3_source_bytes(source)
        validate_p3_test_bytes(tests)
        validate_p3_aggregate_bytes(aggregate)
        await gateway.close()
        opened = False
        await service.cleanup()
        cleaned = True
        return PrimeP3DevelopmentTrace(
            "sha256:"
            + sha256(
                _canonical(
                    {
                        "aggregate_sha256": sha256(P3_AGGREGATE_BYTES).hexdigest(),
                        "observations": observations,
                        "run_id": run_id,
                        "session_id": session_id,
                        "workload": P3_DEVELOPMENT_WORKLOAD_DIGEST,
                    }
                )
            ).hexdigest()
        )
    except asyncio.CancelledError:
        raise
    except BaseException:
        raise PrimeP3DevelopmentHostError() from None
    finally:
        if opened:
            try:
                await gateway.cancel()
                await gateway.close()
            except BaseException:
                pass
        if started and not cleaned:
            try:
                await service.cleanup()
            except BaseException:
                pass


def _observations(result: object) -> dict[str, int]:
    if (
        type(result) is not dict
        or set(result) != {"lifecycle", "usage", "assistant", "observations"}
        or result["lifecycle"] != "completed"
    ):
        raise PrimeP3DevelopmentHostError()
    observed = result["observations"]
    expected = {
        "child_count": 2,
        "max_depth": 1,
        "model_callback_count": 10,
        "remaining_child_count": 0,
        "retained_follow_up_count": 1,
        "tool_call_count": 4,
    }
    if (
        type(observed) is not dict
        or observed != expected
        or result["assistant"] != {"completed": True, "stop_reason": "stop"}
    ):
        raise PrimeP3DevelopmentHostError()
    return expected


def _canonical(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


__all__ = (
    "P3ExecutionService",
    "P3Gateway",
    "PrimeP3DevelopmentHostError",
    "PrimeP3DevelopmentTrace",
    "run_prime_p3_development",
)
