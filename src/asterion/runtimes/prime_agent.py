"""Prime's inert P1 runtime protocol adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator

from asterion.runtime.host import (
    AgentRuntimeClient,
    CancellationSignal,
    RunEvent,
    RunRequest,
    RuntimeManifest,
)
from asterion.runtime.protocol import ProtocolError


PRIME_RUNTIME_ID = "prime.agent"
PRIME_IPYTHON_CAPABILITY = "prime.tool.ipython"


class PrimeAgentRuntimeError(ValueError):
    """Raised before a Prime frame could enter execution."""


class PrimeAgentRuntimeClient(AgentRuntimeClient):
    """Validate P1 frames without selecting a model or starting a worker."""

    @property
    def manifest(self) -> RuntimeManifest:
        return RuntimeManifest(PRIME_RUNTIME_ID, (PRIME_IPYTHON_CAPABILITY,))

    async def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AsyncIterator[RunEvent]:
        del signal
        try:
            request.to_mapping()
        except ProtocolError as error:
            raise PrimeAgentRuntimeError("Prime runtime request is invalid") from error
        if request.requested_capabilities != (PRIME_IPYTHON_CAPABILITY,):
            raise PrimeAgentRuntimeError("Prime runtime tool is not declared")
        yield RunEvent(
            run_id=request.run_id,
            sequence=1,
            type="run.started",
            payload={"capabilities": [PRIME_IPYTHON_CAPABILITY]},
        )
        yield RunEvent(
            run_id=request.run_id,
            sequence=2,
            type="run.failed",
            payload={"code": "runtime-unavailable", "message": "Prime worker is unavailable"},
        )


__all__ = ("PRIME_IPYTHON_CAPABILITY", "PRIME_RUNTIME_ID", "PrimeAgentRuntimeClient")
