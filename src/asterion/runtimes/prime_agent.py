"""Prime's inert P1 runtime protocol adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from asterion.runtime.host import (
    AgentRuntimeClient,
    CancellationSignal,
    RunEvent,
    RunRequest,
    RuntimeManifest,
)
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.prime_agent_host import (
    PrimeSmallVerificationRequest,
    PrimeSmallVerificationResult,
    PrimeSmallVerificationService,
)


PRIME_RUNTIME_ID = "prime.agent"
PRIME_IPYTHON_CAPABILITY = "prime.tool.ipython"


class PrimeAgentRuntimeError(ValueError):
    """Raised before a Prime frame could enter execution."""


class PrimeAgentRuntimeClient(AgentRuntimeClient):
    """Project one host-owned fixed verification into runtime protocol frames."""

    def __init__(self, service: PrimeSmallVerificationService) -> None:
        self._service = service

    @property
    def manifest(self) -> RuntimeManifest:
        return RuntimeManifest(PRIME_RUNTIME_ID, (PRIME_IPYTHON_CAPABILITY,))

    async def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AsyncIterator[RunEvent]:
        try:
            request.to_mapping()
        except ProtocolError as error:
            raise PrimeAgentRuntimeError("Prime runtime request is invalid") from error
        if (
            request.input_text != "fixed-small-verification"
            or request.requested_capabilities != (PRIME_IPYTHON_CAPABILITY,)
            or request.deadline_ms is not None
        ):
            raise PrimeAgentRuntimeError("Prime runtime tool is not declared")
        if signal is not None and signal.cancelled:
            raise asyncio.CancelledError
        verification = PrimeSmallVerificationRequest(request.run_id)
        try:
            result = await self._service.verify(verification, signal=signal)
        except asyncio.CancelledError:
            raise
        except BaseException:
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
                payload={"code": "verification-failed", "message": "Prime verification failed"},
            )
            return
        if type(result) is not PrimeSmallVerificationResult or result.run_id != request.run_id:
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
                payload={"code": "verification-failed", "message": "Prime verification failed"},
            )
            return
        yield RunEvent(
            run_id=request.run_id,
            sequence=1,
            type="run.started",
            payload={"capabilities": [PRIME_IPYTHON_CAPABILITY]},
        )
        yield RunEvent(
            run_id=request.run_id,
            sequence=2,
            type="artifact.created",
            payload={
                "artifact": {
                    "artifact_id": "prime.p1-b-development.trace",
                    "kind": "p1-b-development",
                    "media_type": "application/vnd.asterion.prime.p1-development-trace+json",
                    "sha256": result.trace_sha256.removeprefix("sha256:"),
                }
            },
        )
        yield RunEvent(
            run_id=request.run_id,
            sequence=3,
            type="run.completed",
            payload={"status": "completed"},
        )


__all__ = ("PRIME_IPYTHON_CAPABILITY", "PRIME_RUNTIME_ID", "PrimeAgentRuntimeClient")
