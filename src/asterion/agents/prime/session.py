"""Source-independent Asterion-prime session over the common Pi transport."""

from __future__ import annotations

import asyncio
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


_DEFAULT_TOOL_NAMES = ("ipython",)


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
        allowed_tool_names: tuple[str, ...] = _DEFAULT_TOOL_NAMES,
    ) -> None:
        try:
            if limits not in (ASTERION_PRIME_LIMITS, AsterionPrimeLimits(None, None, None)):
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
            allowed_tool_names=allowed_tool_names,
        )

    def __repr__(self) -> str:
        return "<AsterionPrimeSession redacted>"

    @property
    def native_event_summary(self) -> tuple[dict[str, object], ...]:
        """Return private, payload-free native event diagnostics."""

        events = getattr(self._kernel, "_native_events", ())
        summary: list[dict[str, object]] = []
        for event in events[-64:]:
            item: dict[str, object] = {
                "sequence": event.sequence,
                "type": event.type,
            }
            if event.type == "tool_execution_start":
                name = event.payload.get("toolName")
                if type(name) is str:
                    item["tool_name"] = name
            elif event.type == "message_end":
                message = event.payload.get("message")
                if isinstance(message, Mapping):
                    role = message.get("role")
                    stop_reason = message.get("stopReason")
                    if type(role) is str:
                        item["role"] = role
                    if type(stop_reason) is str:
                        item["stop_reason"] = stop_reason
                    content = message.get("content")
                    if isinstance(content, (list, tuple)):
                        item["content_items"] = len(content)
                        item["tool_call_names"] = tuple(
                            block.get("name")
                            for block in content
                            if isinstance(block, Mapping)
                            and block.get("type") == "toolCall"
                            and type(block.get("name")) is str
                        )
            summary.append(item)
        return tuple(summary)

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
        pending: asyncio.Queue[RunEvent] = asyncio.Queue()

        def emit(event_type: str, payload: Mapping[str, object]) -> None:
            event = RunEvent(
                run_id=request.run_id,
                sequence=len(public) + 1,
                type=event_type,
                payload=payload,
            )
            public.append(event)
            pending.put_nowait(event)

        task: asyncio.Task[None] | None = None
        try:
            emit("run.started", {"capabilities": list(ASTERION_PRIME_CAPABILITIES)})
            yield await pending.get()
            task = asyncio.create_task(self._execute(request, signal, emit))
            while True:
                if not pending.empty():
                    yield pending.get_nowait()
                    continue
                if task.done():
                    await task
                    break
                event_task = asyncio.create_task(pending.get())
                done, _ = await asyncio.wait(
                    (task, event_task), return_when=asyncio.FIRST_COMPLETED
                )
                if event_task in done:
                    yield event_task.result()
                    continue
                event_task.cancel()
                try:
                    await event_task
                except asyncio.CancelledError:
                    pass
                if not pending.empty():
                    yield pending.get_nowait()
                    continue
                await task
                break
        finally:
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self._active = False
            self.close()

    async def _execute(
        self,
        request: RunRequest,
        signal: CancellationSignal | None,
        emit: Callable[[str, Mapping[str, object]], None],
    ) -> None:
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
            try:
                await self._invoke(request, signal, emit)
            except asyncio.CancelledError:
                raise
            except ProtocolError:
                raise
            except BaseException:
                raise ProtocolError(
                    "Asterion-prime execution failed"
                ) from None

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
