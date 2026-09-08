"""Source-independent Asterion-prime session over the common Pi transport."""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from asterion.agents.prime.tools import (
    PrimeToolCall,
    PrimeToolLedger,
    PrimeToolResult,
)
from asterion.runtime.host import CancellationSignal, RunEvent, RunRequest
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.pi_extensions import (
    PiExtensionBinding,
    PiExtensionLease,
    pi_extension_loader_path,
)
from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcEvent, PiRpcResult, PiRpcSession


ASTERION_PRIME_CAPABILITIES = (
    "prime.arc-agi-3-solving",
    "prime.tool.ipython",
)
_MODEL_CALLBACKS = 128
_TOOL_CALLBACKS = 500
_DEADLINE_MS = 60 * 60 * 1000
_SOURCE_NAME = "ASTERION_PI_EXTENSION_SOURCE_NAME"
_SOURCE_SHA256 = "ASTERION_PI_EXTENSION_SOURCE_SHA256"


@dataclass(frozen=True, slots=True)
class AsterionPrimeLimits:
    model_callbacks: int
    tool_callbacks: int
    deadline_ms: int

    def __post_init__(self) -> None:
        values = (self.model_callbacks, self.tool_callbacks, self.deadline_ms)
        if any(isinstance(value, bool) or type(value) is not int for value in values):
            raise ValueError("Asterion-prime limits are invalid")
        if (
            not 1 <= self.model_callbacks <= _MODEL_CALLBACKS
            or not 1 <= self.tool_callbacks <= _TOOL_CALLBACKS
            or not 1 <= self.deadline_ms <= _DEADLINE_MS
        ):
            raise ValueError("Asterion-prime limits are invalid")


ASTERION_PRIME_LIMITS = AsterionPrimeLimits(
    model_callbacks=_MODEL_CALLBACKS,
    tool_callbacks=_TOOL_CALLBACKS,
    deadline_ms=_DEADLINE_MS,
)


class _NeverCancelled:
    @property
    def cancelled(self) -> bool:
        return False


class AsterionPrimeSession:
    """Consume one pinned extension lease for one bounded Prime-style run."""

    __slots__ = (
        "_active",
        "_consumed",
        "_extension_binding",
        "_extension_finalizer",
        "_extension_lease",
        "_limits",
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
        limits: AsterionPrimeLimits = ASTERION_PRIME_LIMITS,
    ) -> None:
        try:
            self._validate_launch_material(
                rpc_session, extension_binding, extension_lease, limits
            )
        except Exception:
            if type(extension_lease) is PiExtensionLease:
                extension_lease.close()
            raise
        self._rpc_session = rpc_session
        self._extension_binding = extension_binding
        self._extension_lease = extension_lease
        self._extension_finalizer = weakref.finalize(self, extension_lease.close)
        self._limits = limits
        self._used_run_ids: set[str] = set()
        self._active = False
        self._consumed = False

    def __repr__(self) -> str:
        return "<AsterionPrimeSession redacted>"

    @staticmethod
    def _validate_launch_material(
        rpc_session: PiRpcSession,
        binding: PiExtensionBinding,
        lease: PiExtensionLease,
        limits: AsterionPrimeLimits,
    ) -> None:
        if (
            type(binding) is not PiExtensionBinding
            or type(lease) is not PiExtensionLease
            or type(limits) is not AsterionPrimeLimits
            or limits != ASTERION_PRIME_LIMITS
        ):
            raise ProtocolError("Asterion-prime launch material is invalid")
        if (
            binding.extension_id != "prime.ipython"
            or binding.capabilities != ("prime.tool.ipython",)
            or lease.closed
            or lease.loader_path != pi_extension_loader_path()
        ):
            raise ProtocolError("Asterion-prime launch material is invalid")
        try:
            lease.validate_launch()
            config = rpc_session.config
        except Exception:
            raise ProtocolError("Asterion-prime launch material is invalid") from None
        if type(config) is not PiRpcConfig:
            raise ProtocolError("Asterion-prime launch material is invalid")
        environment = dict(lease.environment)
        if (
            environment.get(_SOURCE_NAME) != binding.path.name
            or type(environment.get(_SOURCE_SHA256)) is not str
            or str(binding.path) not in lease.sensitive_values
            or dict(config.environment) != environment
            or config.inherited_fds != lease.inherited_fds
            or config.command[-2:] != lease.command_args()
            or config.command.count(lease.command_args()[0]) != 1
            or config.deadline_seconds * 1000 != limits.deadline_ms
        ):
            raise ProtocolError("Asterion-prime launch material is invalid")
        for name, value in binding.environment.items():
            leased = environment.get(name)
            if name.endswith("_FD"):
                if (
                    type(leased) is not str
                    or not leased.isdecimal()
                    or int(leased) not in lease.inherited_fds
                ):
                    raise ProtocolError("Asterion-prime launch material is invalid")
            elif leased != value:
                raise ProtocolError("Asterion-prime launch material is invalid")
        if any(
            descriptor not in lease.sensitive_values
            for descriptor in binding.inherited_fds
        ):
            raise ProtocolError("Asterion-prime launch material is invalid")

    def close(self) -> None:
        """Release the owned single-run lease without invoking the transport."""

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
        ledger = PrimeToolLedger(max_callbacks=self._limits.tool_callbacks)
        native: list[PiRpcEvent] = []
        model_callbacks = 0
        settled = False

        def consume(event: PiRpcEvent) -> None:
            nonlocal model_callbacks, settled
            if type(event) is not PiRpcEvent or event.sequence != len(native) + 1:
                raise ProtocolError("Asterion-prime native event is malformed")
            native.append(event)
            event_type = event.type
            payload = event.payload
            if event_type in {"response", "agent_start", "turn_end"}:
                return
            if event_type == "turn_start":
                model_callbacks += 1
                if model_callbacks > self._limits.model_callbacks:
                    raise ProtocolError("Asterion-prime model callback limit exceeded")
                return
            if event_type == "message_update":
                self._validate_message_update(payload)
                return
            if event_type == "message_end":
                usage = self._assistant_usage(payload)
                if usage is not None:
                    emit("usage.reported", usage)
                return
            if event_type == "tool_execution_start":
                call = self._tool_call(payload)
                ledger.record_call(call)
                emit(
                    "tool.call",
                    {"call_id": call.call_id, "name": call.name, "arguments": {}},
                )
                return
            if event_type == "tool_execution_end":
                result = self._tool_result(payload)
                ledger.record_result(result)
                emit(
                    "tool.result",
                    {
                        "call_id": result.call_id,
                        "output": None,
                        "is_error": result.status != "ok",
                    },
                )
                return
            if event_type == "agent_settled":
                if settled:
                    raise ProtocolError(
                        "Asterion-prime emitted duplicate terminal event"
                    )
                settled = True
                return
            raise ProtocolError("Asterion-prime native event type is invalid")

        try:
            result = await self._rpc_session.run(
                request.input_text,
                signal=signal or _NeverCancelled(),
                on_event=consume,
            )
        except ProtocolError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            if signal is not None and signal.cancelled:
                emit("run.completed", {"status": "cancelled"})
            else:
                emit(
                    "run.failed",
                    {
                        "code": "asterion_prime_failed",
                        "message": "Asterion-prime execution failed.",
                    },
                )
            return
        if type(result) is not PiRpcResult or result.events != tuple(native):
            raise ProtocolError("Asterion-prime native result is malformed")
        if not settled or not native or native[-1].type != "agent_settled":
            raise ProtocolError("Asterion-prime native terminal is invalid")
        if signal is not None and signal.cancelled:
            emit("run.completed", {"status": "cancelled"})
            return
        ledger.seal()
        emit("run.completed", {"status": "completed"})

    @staticmethod
    def _validate_message_update(payload: Mapping[str, object]) -> None:
        assistant = payload.get("assistantMessageEvent")
        if not isinstance(assistant, Mapping):
            raise ProtocolError("Asterion-prime message update is malformed")
        if assistant.get("type") != "text_delta":
            return
        if type(assistant.get("delta")) is not str:
            raise ProtocolError("Asterion-prime message update is malformed")

    @staticmethod
    def _assistant_usage(payload: Mapping[str, object]) -> Mapping[str, object] | None:
        message = payload.get("message")
        if not isinstance(message, Mapping) or message.get("role") != "assistant":
            return None
        usage = message.get("usage")
        if usage is None:
            return None
        if not isinstance(usage, Mapping):
            raise ProtocolError("Asterion-prime usage event is malformed")
        input_tokens = usage.get("input")
        output_tokens = usage.get("output")
        if (
            isinstance(input_tokens, bool)
            or type(input_tokens) is not int
            or input_tokens < 0
            or isinstance(output_tokens, bool)
            or type(output_tokens) is not int
            or output_tokens < 0
        ):
            raise ProtocolError("Asterion-prime usage event is malformed")
        return {"input_tokens": input_tokens, "output_tokens": output_tokens}

    @staticmethod
    def _tool_call(payload: Mapping[str, object]) -> PrimeToolCall:
        call_id = payload.get("toolCallId")
        name = payload.get("toolName")
        arguments = payload.get("args")
        if (
            type(call_id) is not str
            or not call_id
            or type(name) is not str
            or name != "ipython"
            or not isinstance(arguments, Mapping)
        ):
            raise ProtocolError("Asterion-prime tool call is malformed")
        assert isinstance(call_id, str)
        assert isinstance(name, str)
        assert isinstance(arguments, Mapping)
        return PrimeToolCall(call_id, name, arguments)

    @staticmethod
    def _tool_result(payload: Mapping[str, object]) -> PrimeToolResult:
        call_id = payload.get("toolCallId")
        is_error = payload.get("isError")
        effect = payload.get("effect", "certain")
        if (
            type(call_id) is not str
            or not call_id
            or type(is_error) is not bool
            or effect not in {"certain", "uncertain"}
        ):
            raise ProtocolError("Asterion-prime tool result is malformed")
        status: Literal["ok", "error", "uncertain"] = (
            "uncertain" if effect == "uncertain" else ("error" if is_error else "ok")
        )
        return PrimeToolResult(call_id, status, ())


__all__ = (
    "ASTERION_PRIME_CAPABILITIES",
    "ASTERION_PRIME_LIMITS",
    "AsterionPrimeLimits",
    "AsterionPrimeSession",
)
