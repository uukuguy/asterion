"""Package-owned adapter from capability invocations to runtime protocol values."""

from __future__ import annotations

from collections.abc import Mapping

from asterion.capability_sdk import CapabilityInvocation
from asterion.runtime.host import RunRequest
from asterion.runtime.protocol import ProtocolError, validate_event_stream


class DciRuntimeAdapterError(RuntimeError):
    """Body-free failure at the package-owned runtime adapter boundary."""


async def run_declared_runtime(
    invocation: CapabilityInvocation,
    *,
    input_text: str,
    requested_capabilities: tuple[str, ...],
) -> tuple[Mapping[str, object], ...]:
    """Run and validate one request without exposing runtime internals."""

    request = RunRequest(
        run_id=invocation.run_id,
        input_text=input_text,
        requested_capabilities=requested_capabilities,
    )
    try:
        events = tuple(
            [
                event.to_mapping()
                async for event in invocation.runtime.run(
                    request,
                    signal=invocation.signal,
                )
            ]
        )
        validate_event_stream(events)
        return events
    except (ProtocolError, RuntimeError, TypeError, ValueError):
        raise DciRuntimeAdapterError("DCI runtime adapter failed") from None
