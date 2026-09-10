"""Source-independent Asterion-prime session over the common Pi transport."""

from __future__ import annotations

import weakref
from collections.abc import AsyncIterator, Callable, Mapping

from asterion.agents.prime.execution import (
    ASTERION_PRIME_CAPABILITIES,
    ASTERION_PRIME_LIMITS,
    AsterionPrimeLimits,
    PrimeExecutionKernel,
)
from asterion.runtime.host import CancellationSignal, RunEvent, RunRequest
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.pi_extensions import PiExtensionBinding, PiExtensionLease
from asterion.runtimes.pi_rpc import PiRpcSession


_CONTINUE_PROMPT = (
    "Continue solving the same interactive puzzle from the current Python "
    "state. Use only the ipython tool, check p7_client.status() and "
    "p7_client.observe(), then take an available primitive action when the "
    "level is not complete."
)


class AsterionPrimeSession:
    """Consume one pinned extension lease for one bounded Prime-style run."""

    __slots__ = (
        "_active",
        "_kernel",
        "_approved_command",
        "_consumed",
        "_extension_binding",
        "_extension_finalizer",
        "_extension_lease",
        "_limits",
        "_completion_predicate",
        "_continuation_prompt",
        "_rpc_session",
        "_used_run_ids",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        rpc_session: PiRpcSession,
        extension_binding: PiExtensionBinding,
        extension_lease: PiExtensionLease,
        approved_command: tuple[str, ...],
        approved_environment: Mapping[str, str] | None = None,
        limits: AsterionPrimeLimits = ASTERION_PRIME_LIMITS,
        completion_predicate: Callable[[], bool] | None = None,
        continuation_prompt: Callable[[int], str] | None = None,
    ) -> None:
        try:
            if limits != ASTERION_PRIME_LIMITS:
                raise ProtocolError("Asterion-prime launch material is invalid")
            PrimeExecutionKernel._validate_launch_material(
                rpc_session,
                extension_binding,
                extension_lease,
                approved_command,
                approved_environment,
                limits,
            )
        except Exception:
            if type(extension_lease) is PiExtensionLease:
                extension_lease.close()
            raise
        self._rpc_session = rpc_session
        self._approved_command = approved_command
        self._extension_binding = extension_binding
        self._extension_lease = extension_lease
        self._extension_finalizer = weakref.finalize(self, extension_lease.close)
        self._limits = limits
        if completion_predicate is not None and not callable(completion_predicate):
            raise ProtocolError("Asterion-prime continuation is invalid")
        if continuation_prompt is not None and not callable(continuation_prompt):
            raise ProtocolError("Asterion-prime continuation is invalid")
        self._completion_predicate = completion_predicate
        self._continuation_prompt = continuation_prompt
        self._used_run_ids: set[str] = set()
        self._active = False
        self._consumed = False
        self._kernel = PrimeExecutionKernel(
            rpc_session=rpc_session,
            extension_binding=extension_binding,
            extension_lease=extension_lease,
            approved_command=approved_command,
            approved_environment=approved_environment,
            limits=limits,
            completion_predicate=completion_predicate,
            continuation_prompt=continuation_prompt or (lambda _: _CONTINUE_PROMPT),
        )

    def __repr__(self) -> str:
        return "<AsterionPrimeSession redacted>"

    def close(self) -> None:
        """Release the owned single-run lease without invoking the transport."""

        if self._active:
            raise ProtocolError("Asterion-prime already has an active request")
        self._extension_lease.close()
        self._extension_finalizer.detach()

    async def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AsyncIterator[RunEvent]:
        if type(request) is not RunRequest:
            raise ProtocolError("Asterion-prime request is invalid")
        request.to_mapping()
        if self._active:
            raise ProtocolError("Asterion-prime already has an active request")
        if request.run_id in self._used_run_ids:
            raise ProtocolError("Asterion-prime run_id was already used")
        if self._consumed or self._extension_lease.closed:
            raise ProtocolError("Asterion-prime session lease is unavailable")
        self._active = True
        self._consumed = True
        self._used_run_ids.add(request.run_id)
        public: list[RunEvent] = []

        def emit(event_type: str, payload: Mapping[str, object]) -> None:
            public.append(
                RunEvent(
                    run_id=request.run_id,
                    sequence=len(public) + 1,
                    type=event_type,
                    payload=payload,
                )
            )

        emit("run.started", {"capabilities": list(ASTERION_PRIME_CAPABILITIES)})
        try:
            if any(
                capability not in ASTERION_PRIME_CAPABILITIES
                for capability in request.requested_capabilities
            ):
                raise ProtocolError("Asterion-prime capability is unavailable")
            if request.deadline_ms not in {None, self._limits.deadline_ms}:
                raise ProtocolError("Asterion-prime uses a fixed deadline")
            if signal is not None and signal.cancelled:
                emit("run.completed", {"status": "cancelled"})
            else:
                await self._invoke(request, signal, emit)
        finally:
            self._active = False
            self.close()
        for event in public:
            yield event

    async def _invoke(
        self,
        request: RunRequest,
        signal: CancellationSignal | None,
        emit: Callable[[str, Mapping[str, object]], None],
    ) -> None:
        await self._kernel.invoke(request, signal, emit)


__all__ = (
    "ASTERION_PRIME_CAPABILITIES",
    "ASTERION_PRIME_LIMITS",
    "AsterionPrimeLimits",
    "AsterionPrimeSession",
)
