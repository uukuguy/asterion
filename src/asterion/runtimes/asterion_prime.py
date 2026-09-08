"""Agent Runtime Protocol adapter for the Asterion-prime implementation."""

from __future__ import annotations

from collections.abc import AsyncIterator

from asterion.agents.prime.session import (
    ASTERION_PRIME_CAPABILITIES,
    AsterionPrimeSession,
)
from asterion.runtime.host import (
    CancellationSignal,
    RunEvent,
    RunRequest,
    RuntimeManifest,
)
from asterion.runtime.protocol import ProtocolError


class AsterionPrimeRuntimeClient:
    """Expose one injected Asterion-prime session as an AgentRuntime client."""

    __slots__ = ("_session",)

    def __init__(self, session: AsterionPrimeSession) -> None:
        if type(session) is not AsterionPrimeSession:
            raise ProtocolError("Asterion-prime session is invalid")
        self._session = session

    @property
    def manifest(self) -> RuntimeManifest:
        return RuntimeManifest(
            runtime_id="asterion.prime",
            capabilities=ASTERION_PRIME_CAPABILITIES,
        )

    def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AsyncIterator[RunEvent]:
        return self._session.run(request, signal=signal)


__all__ = ("AsterionPrimeRuntimeClient",)
