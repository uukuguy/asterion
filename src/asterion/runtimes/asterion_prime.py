"""Agent Runtime Protocol adapter for the Asterion-prime implementation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Protocol, runtime_checkable

from asterion.agents.prime.session import (
    ASTERION_PRIME_CAPABILITIES,
)
from asterion.runtime.host import (
    CancellationSignal,
    RunEvent,
    RunRequest,
    RuntimeManifest,
)
from asterion.runtime.protocol import ProtocolError
from asterion.services.diagnostics import FailureDiagnostic


@runtime_checkable
class _PrimeRuntimeSession(Protocol):
    def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AsyncIterator[RunEvent]: ...


class AsterionPrimeRuntimeClient:
    """Expose one injected Asterion-prime session as an AgentRuntime client."""

    __slots__ = ("_event_projector", "_session")

    def __init__(
        self,
        session: _PrimeRuntimeSession,
        *,
        event_projector: Callable[
            [RunRequest, AsyncIterator[RunEvent]], AsyncIterator[RunEvent]
        ]
        | None = None,
    ) -> None:
        if not isinstance(session, _PrimeRuntimeSession) or not callable(session.run):
            raise ProtocolError("Asterion-prime session is invalid")
        if event_projector is not None and not callable(event_projector):
            raise ProtocolError("Asterion-prime event projector is invalid")
        self._session = session
        self._event_projector = event_projector

    @property
    def manifest(self) -> RuntimeManifest:
        return RuntimeManifest(
            runtime_id="asterion.prime",
            capabilities=ASTERION_PRIME_CAPABILITIES,
        )

    @property
    def last_diagnostic_id(self) -> str | None:
        value = getattr(self._session, "last_diagnostic_id", None)
        return value if type(value) is str else None

    @property
    def last_diagnostic(self) -> FailureDiagnostic | None:
        value = getattr(self._session, "last_diagnostic", None)
        return value if type(value) is FailureDiagnostic else None

    def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AsyncIterator[RunEvent]:
        events = self._session.run(request, signal=signal)
        if self._event_projector is None:
            return events
        return self._event_projector(request, events)


__all__ = ("AsterionPrimeRuntimeClient",)
