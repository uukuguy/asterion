"""Prime's inert P1 runtime protocol adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from asterion.runtime.host import (
    AgentRuntimeClient,
    CancellationSignal,
    RunEvent,
    RunRequest,
    RuntimeManifest,
)
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.prime_agent_host import (
    PrimeSmallVerificationCancelled,
    PrimeSmallVerificationRequest,
    PrimeSmallVerificationResult,
    PrimeSmallVerificationService,
)


PRIME_RUNTIME_ID = "prime.agent"
PRIME_IPYTHON_CAPABILITY = "prime.tool.ipython"


class PrimeAgentRuntimeError(ValueError):
    """Raised before a Prime frame could enter execution."""


@dataclass(frozen=True)
class PrimeVerificationProfile:
    scope: str
    artifact_id: str
    kind: str
    media_type: str

    def __post_init__(self) -> None:
        if (
            self.scope,
            self.artifact_id,
            self.kind,
            self.media_type,
        ) not in {
            (
                "p1-b-development",
                "prime.p1-b-development.trace",
                "p1-b-development",
                "application/vnd.asterion.prime.p1-development-trace+json",
            ),
            (
                "p2-development",
                "prime.p2-development.trace",
                "p2-development",
                "application/vnd.asterion.prime.p2-development-trace+json",
            ),
            (
                "p3-development",
                "prime.p3-development.trace",
                "p3-development",
                "application/vnd.asterion.prime.p3-development-trace+json",
            ),
            (
                "p4-development",
                "prime.p4-development.trace",
                "p4-development",
                "application/vnd.asterion.prime.p4-development-trace+json",
            ),
            (
                "p5-development",
                "prime.p5-development.trace",
                "p5-development",
                "application/vnd.asterion.prime.p5-development-trace+json",
            ),
            (
                "p6-development",
                "prime.p6-development.trace",
                "p6-development",
                "application/vnd.asterion.prime.p6-development-trace+json",
            ),
            (
                "p7-development",
                "prime.p7-development.trace",
                "p7-development",
                "application/vnd.asterion.prime.p7-development-trace+json",
            ),
        }:
            raise PrimeAgentRuntimeError("Prime runtime profile is invalid")


PRIME_P1_PROFILE = PrimeVerificationProfile(
    scope="p1-b-development",
    artifact_id="prime.p1-b-development.trace",
    kind="p1-b-development",
    media_type="application/vnd.asterion.prime.p1-development-trace+json",
)
PRIME_P2_PROFILE = PrimeVerificationProfile(
    scope="p2-development",
    artifact_id="prime.p2-development.trace",
    kind="p2-development",
    media_type="application/vnd.asterion.prime.p2-development-trace+json",
)
PRIME_P3_PROFILE = PrimeVerificationProfile(
    scope="p3-development",
    artifact_id="prime.p3-development.trace",
    kind="p3-development",
    media_type="application/vnd.asterion.prime.p3-development-trace+json",
)
PRIME_P4_PROFILE = PrimeVerificationProfile(
    scope="p4-development",
    artifact_id="prime.p4-development.trace",
    kind="p4-development",
    media_type="application/vnd.asterion.prime.p4-development-trace+json",
)
PRIME_P5_PROFILE = PrimeVerificationProfile(
    scope="p5-development",
    artifact_id="prime.p5-development.trace",
    kind="p5-development",
    media_type="application/vnd.asterion.prime.p5-development-trace+json",
)
PRIME_P6_PROFILE = PrimeVerificationProfile(
    scope="p6-development",
    artifact_id="prime.p6-development.trace",
    kind="p6-development",
    media_type="application/vnd.asterion.prime.p6-development-trace+json",
)
PRIME_P7_PROFILE = PrimeVerificationProfile(
    scope="p7-development",
    artifact_id="prime.p7-development.trace",
    kind="p7-development",
    media_type="application/vnd.asterion.prime.p7-development-trace+json",
)

class PrimeAgentRuntimeClient(AgentRuntimeClient):
    """Project one host-owned fixed verification into runtime protocol frames."""

    def __init__(
        self,
        service: PrimeSmallVerificationService,
        *,
        profile: PrimeVerificationProfile = PRIME_P1_PROFILE,
    ) -> None:
        self._service = service
        if profile not in (
            PRIME_P1_PROFILE,
            PRIME_P2_PROFILE,
            PRIME_P3_PROFILE,
            PRIME_P4_PROFILE,
            PRIME_P5_PROFILE,
            PRIME_P6_PROFILE,
            PRIME_P7_PROFILE,
        ):
            raise PrimeAgentRuntimeError("Prime runtime profile is invalid")
        self._profile = profile

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
            for event in _cancelled_events(request.run_id):
                yield event
            return
        verification = PrimeSmallVerificationRequest(request.run_id)
        try:
            result = await self._service.verify(verification, signal=signal)
        except PrimeSmallVerificationCancelled:
            for event in _cancelled_events(request.run_id):
                yield event
            return
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
        if (
            type(result) is not PrimeSmallVerificationResult
            or result.run_id != request.run_id
            or result.scope != self._profile.scope
        ):
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
                    "artifact_id": self._profile.artifact_id,
                    "kind": self._profile.kind,
                    "media_type": self._profile.media_type,
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


def _cancelled_events(run_id: str) -> tuple[RunEvent, RunEvent]:
    return (
        RunEvent(
            run_id=run_id,
            sequence=1,
            type="run.started",
            payload={"capabilities": [PRIME_IPYTHON_CAPABILITY]},
        ),
        RunEvent(
            run_id=run_id,
            sequence=2,
            type="run.completed",
            payload={"status": "cancelled"},
        ),
    )


__all__ = (
    "PRIME_IPYTHON_CAPABILITY",
    "PRIME_P1_PROFILE",
    "PRIME_P2_PROFILE",
    "PRIME_P3_PROFILE",
    "PRIME_P4_PROFILE",
    "PRIME_P5_PROFILE",
    "PRIME_P6_PROFILE",
    "PRIME_P7_PROFILE",
    "PRIME_RUNTIME_ID",
    "PrimeAgentRuntimeClient",
    "PrimeVerificationProfile",
)
