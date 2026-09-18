"""Runtime-owned native P5 bounded-autonomy session.

P5 owns one bounded propose/verify/repair round per invocation. The runtime
drives the call against the injected host; the host owns the in-process
state. There is no continuity store, no checkpoint seal, and no recovery
semantics on this path — those belong to P4 and are not part of P5's
contract. The session adapter carries the five host-service references
through to the ``P5RuntimeHost`` Protocol surface that the operator
exercises against a built runtime.

The bounded-autonomy host service ``prime.bounded-autonomy`` is opened by
the operator (Task 8) and wired with ``prime.ipython`` and
``prime.p5-oracle`` via :meth:`BoundedAutonomyLoop.set_step_callables`
before this runtime binding is constructed; the binding does not reopen
the loop. ``prime.session-backend`` is the ``P5RuntimeHost`` surface
that wraps the loop — the binding adapts the session-backend through
its four Protocol methods (``validate_runtime_services`` / ``run_loop``
/ ``report_loop_stopped`` / ``wait_finalization``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from types import MappingProxyType

from asterion.applications.prime.p5.host import (
    P5Finalization,
    P5LoopResult,
    P5RuntimeHost,
    P5TerminalReason,
)
from asterion.applications.prime.p5.oracle import P5Oracle
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError
from asterion.runtime.host import CancellationSignal, RunEvent, RunRequest
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient


# P5's host capabilities: per the application assembly JSON
# (``src/asterion/applications/prime/assemblies/prime-bounded-autonomy.json``)
# P5 depends on these five injected host services. The spec lists
# ``prime.ipython`` and ``prime.p5-oracle`` as the bounded-autonomy
# substrate (new for Phase 8), and the other three as the same
# Asterion-owned substrate P1 / P2 / P4 already consume. P5 has no
# continuity store, no child runner, and no checkpoint — those surfaces
# belong to P3 / P4 only.
P5_HOST_CAPABILITIES: tuple[str, ...] = (
    "prime.ipython",
    "prime.p5-oracle",
    "prime.pi-extension",
    "prime.private-trace",
    "prime.session-backend",
)
P5_RUNTIME_OPTIONS: Mapping[str, str] = MappingProxyType(
    {
        "aggregate_tokens": "32000",
        "cost_micros": "300000",
        "deadline_ms": "120000",
        "max_callbacks": "4",
        "max_tool_callbacks": "2",
    }
)
_ERROR = "Asterion-prime runtime configuration is invalid"


class _P5RuntimeSession:
    """Own one bounded propose/verify/repair round and adapt to P5RuntimeHost.

    Implements the four-method ``P5RuntimeHost`` Protocol
    (``validate_runtime_services`` / ``run_loop`` /
    ``report_loop_stopped`` / ``wait_finalization``) over the
    five injected host services, and exposes the runtime-client
    ``run`` iterator that drives one round per ``RunRequest``.
    """

    __slots__ = (
        "_active",
        "_consumed",
        "_oracle",
        "_private_trace",
        "_session_backend",
    )

    def __init__(
        self,
        *,
        session_backend: P5RuntimeHost,
        oracle: P5Oracle,
        private_trace: object | None,
    ) -> None:
        self._session_backend = session_backend
        self._oracle = oracle
        self._private_trace = private_trace
        self._active = False
        self._consumed = False

    # ------------------------------------------------------------------
    # P5RuntimeHost Protocol surface
    # ------------------------------------------------------------------

    def validate_runtime_services(
        self, services: Mapping[str, object]
    ) -> None:
        """Reject unknown or missing host services — fail closed.

        ``services`` must equal ``P5_HOST_CAPABILITIES`` exactly (set
        equality; ordering is the spec's contract).
        """

        if set(services) != set(P5_HOST_CAPABILITIES):
            raise RuntimeFactoryError(_ERROR)

    async def run_loop(
        self,
        *,
        root_run_id: str,
        signal: CancellationSignal,
    ) -> P5LoopResult:
        """Drive the bounded-autonomy loop and return the sealed result."""

        return await self._session_backend.run_loop(
            root_run_id=root_run_id,
            signal=signal,
        )

    def report_loop_stopped(
        self,
        *,
        terminal_reason: P5TerminalReason,
        root_run_id: str,
    ) -> None:
        """Forward a closed-enum stop reason to the host's observability surface."""

        self._session_backend.report_loop_stopped(
            terminal_reason=terminal_reason,
            root_run_id=root_run_id,
        )

    async def wait_finalization(
        self, *, signal: CancellationSignal
    ) -> P5Finalization:
        """Block until the host transfers terminal status."""

        return await self._session_backend.wait_finalization(signal=signal)

    # ------------------------------------------------------------------
    # Runtime-client session interface
    # ------------------------------------------------------------------

    async def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AsyncIterator[RunEvent]:
        if type(request) is not RunRequest:
            raise ProtocolError("P5 runtime request is invalid")
        request.to_mapping()
        if self._active or self._consumed:
            raise ProtocolError("P5 runtime session is unavailable")
        self._active = self._consumed = True
        # The P5 witness is operator-driven through Make; this surface
        # exists so the runtime client is constructable end-to-end and
        # yields a single terminal event so callers see a closed shape.
        try:
            yield RunEvent(
                request.run_id,
                1,
                "run.completed",
                {"status": "completed"},
            )
        finally:
            self._active = False


__all__ = (
    "P5_HOST_CAPABILITIES",
    "P5_RUNTIME_OPTIONS",
)


def build_p5_runtime(context: RuntimeFactoryContext) -> AsterionPrimeRuntimeClient:
    """Bind exact preflighted P5 services without constructing the coordinator.

    Composes the five host services from the context (already injected by
    the operator) into a single client that exposes the ``P5RuntimeHost``
    Protocol surface (``validate_runtime_services`` / ``run_loop`` /
    ``report_loop_stopped`` / ``wait_finalization``).

    The bounded-autonomy loop controller is opened and wired with
    ``prime.ipython`` (propose + repair) and ``prime.p5-oracle`` (verify)
    by the operator (Task 8) before this binding runs; ``set_step_callables``
    is the operator's responsibility, not the binding's. The binding only
    validates the 5-tuple and adapts the session-backend through the
    ``P5RuntimeHost`` surface.

    Returns a frozen :class:`AsterionPrimeRuntimeClient` carrying the
    bound host services and an internal :class:`_P5RuntimeSession`
    adapter. Fails closed on any host-service mismatch.
    """

    try:
        if type(context) is not RuntimeFactoryContext:
            raise ValueError
        host_services = context.host_services
        service = host_services.get("prime.session-backend")
        oracle_value = host_services.get("prime.p5-oracle")
        # prime.private-trace has no consumer in P5 (no persistent
        # session to trace), so it is allowed to be None. Every other
        # host service must be a real instance.
        required_host_services = tuple(
            name
            for name in P5_HOST_CAPABILITIES
            if name != "prime.private-trace"
        )
        if (
            context.provider_id != "prime-applications"
            or context.application_id != "prime.bounded-autonomy"
            or context.application_version != "1.0.0"
            or context.runtime_id != "asterion.prime"
            or set(host_services) != set(P5_HOST_CAPABILITIES)
            or any(
                host_services.get(name) is None
                for name in required_host_services
            )
            or dict(context.options) != dict(P5_RUNTIME_OPTIONS)
            or not isinstance(service, P5RuntimeHost)
            or not isinstance(oracle_value, P5Oracle)
        ):
            raise ValueError
        session = _P5RuntimeSession(
            session_backend=service,
            oracle=oracle_value,
            private_trace=host_services.get("prime.private-trace"),
        )
        # Eagerly validate the 5-tuple so a malformed host-services
        # shape is rejected before the runtime is handed to callers.
        session.validate_runtime_services(host_services)
        return AsterionPrimeRuntimeClient(session)
    except Exception:
        raise RuntimeFactoryError(_ERROR) from None
