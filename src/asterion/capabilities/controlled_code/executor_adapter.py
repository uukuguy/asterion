"""Package-owned adapter for the injected controlled-executor service."""

from __future__ import annotations

from typing import Protocol, cast

from asterion.capability_sdk import (
    CancellationSignal,
    CapabilityExecutionError,
    CapabilityInvocation,
)
from asterion.services.controlled_executor import (
    ControlledExecutionRequest,
    ControlledExecutionResult,
)


class _ControlledExecutor(Protocol):
    async def execute(
        self,
        request: ControlledExecutionRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> ControlledExecutionResult: ...


async def execute_controlled(
    invocation: CapabilityInvocation,
) -> ControlledExecutionResult:
    """Execute one validated request through an injected host service."""

    service = invocation.host_services.get("executor.controlled")
    if not callable(getattr(service, "execute", None)):
        raise CapabilityExecutionError("controlled executor service is invalid")
    executor = cast(_ControlledExecutor, service)
    return await executor.execute(
        ControlledExecutionRequest(invocation.input_text),
        signal=invocation.signal,
    )
