"""Source-independent Asterion-prime session over the common Pi transport."""

from __future__ import annotations

import asyncio
import math
import weakref
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
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
_TRANSPORT_PROTOCOL_ERROR = "Asterion-prime transport protocol failed"
_NATIVE_EVENT_ERROR = "Asterion-prime native event is invalid"


class _CallbackRejected(Exception):
    pass


class _NativeDiagnostic(Enum):
    EVENT_MALFORMED = "event_malformed"
    MODEL_CALLBACK_LIMIT = "model_callback_limit"
    TOOL_CALLBACK_LIMIT = "tool_callback_limit"
    TOOL_CALL_INVALID = "tool_call_invalid"
    TOOL_RESULT_INVALID = "tool_result_invalid"
    DUPLICATE_TERMINAL = "duplicate_terminal"
    EVENT_TYPE_INVALID = "event_type_invalid"
    MESSAGE_UPDATE_MALFORMED = "message_update_malformed"
    USAGE_MALFORMED = "usage_malformed"
    TOOL_CALL_MALFORMED = "tool_call_malformed"
    TOOL_RESULT_MALFORMED = "tool_result_malformed"


_NATIVE_DIAGNOSTIC_MESSAGES = MappingProxyType(
    {
        _NativeDiagnostic.EVENT_MALFORMED: "Asterion-prime native event is malformed",
        _NativeDiagnostic.MODEL_CALLBACK_LIMIT: (
            "Asterion-prime model callback limit exceeded"
        ),
        _NativeDiagnostic.TOOL_CALLBACK_LIMIT: (
            "Asterion-prime tool callback limit exceeded"
        ),
        _NativeDiagnostic.TOOL_CALL_INVALID: "Asterion-prime tool call is invalid",
        _NativeDiagnostic.TOOL_RESULT_INVALID: "Asterion-prime tool result is invalid",
        _NativeDiagnostic.DUPLICATE_TERMINAL: (
            "Asterion-prime emitted duplicate terminal event"
        ),
        _NativeDiagnostic.EVENT_TYPE_INVALID: (
            "Asterion-prime native event type is invalid"
        ),
        _NativeDiagnostic.MESSAGE_UPDATE_MALFORMED: (
            "Asterion-prime message update is malformed"
        ),
        _NativeDiagnostic.USAGE_MALFORMED: (
            "Asterion-prime usage event is malformed"
        ),
        _NativeDiagnostic.TOOL_CALL_MALFORMED: (
            "Asterion-prime tool call is malformed"
        ),
        _NativeDiagnostic.TOOL_RESULT_MALFORMED: (
            "Asterion-prime tool result is malformed"
        ),
    }
)


class _NativeEventRejected(Exception):
    def __init__(self, code: _NativeDiagnostic) -> None:
        if type(code) is not _NativeDiagnostic:
            raise TypeError("Asterion-prime native diagnostic is invalid")
        super().__init__()
        self.code = code


def _snapshot_native_value(value: object, active: set[int] | None = None) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError
        return value
    if active is None:
        active = set()
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise ValueError
        active.add(identity)
        try:
            snapshot: dict[str, object] = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise ValueError
                snapshot[key] = _snapshot_native_value(item, active)
            return MappingProxyType(snapshot)
        finally:
            active.remove(identity)
    if isinstance(value, (list, tuple)):
        if type(value) not in {list, tuple}:
            raise ValueError
        identity = id(value)
        if identity in active:
            raise ValueError
        active.add(identity)
        try:
            return tuple(_snapshot_native_value(item, active) for item in value)
        finally:
            active.remove(identity)
    raise ValueError


def _snapshot_native_event(event: object) -> PiRpcEvent:
    if type(event) is not PiRpcEvent:
        raise ValueError
    payload = _snapshot_native_value(event.payload)
    if not isinstance(payload, Mapping):
        raise ValueError
    return PiRpcEvent(sequence=event.sequence, type=event.type, payload=payload)


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
        "_approved_command",
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
        approved_command: tuple[str, ...],
        limits: AsterionPrimeLimits = ASTERION_PRIME_LIMITS,
    ) -> None:
        try:
            self._validate_launch_material(
                rpc_session,
                extension_binding,
                extension_lease,
                approved_command,
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
        approved_command: tuple[str, ...],
        limits: AsterionPrimeLimits,
    ) -> None:
        if (
            type(binding) is not PiExtensionBinding
            or type(lease) is not PiExtensionLease
            or type(approved_command) is not tuple
            or not approved_command
            or any(type(part) is not str or not part for part in approved_command)
            or type(limits) is not AsterionPrimeLimits
            or limits != ASTERION_PRIME_LIMITS
        ):
            raise ProtocolError("Asterion-prime launch material is invalid")
        if (
            binding.extension_id != "prime.ipython"
            or binding.capabilities != ("prime.tool.ipython",)
            or binding.binding_fingerprint != lease.binding_fingerprint
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
            or dict(config.environment) != environment
            or config.inherited_fds != lease.inherited_fds
            or config.command != approved_command
            or approved_command[-2:] != lease.command_args()
            or approved_command.count(lease.command_args()[0]) != 1
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
        ledger = PrimeToolLedger(max_callbacks=self._limits.tool_callbacks)
        native: list[PiRpcEvent] = []
        pending_calls: dict[str, PrimeToolCall] = {}
        model_callbacks = 0
        settled = False
        callback_failure: ProtocolError | None = None

        def consume_checked(event: PiRpcEvent) -> None:
            nonlocal model_callbacks, settled
            if type(event) is not PiRpcEvent or event.sequence != len(native) + 1:
                raise _NativeEventRejected(_NativeDiagnostic.EVENT_MALFORMED)
            native.append(event)
            event_type = event.type
            payload = event.payload
            if event_type in {"response", "agent_start", "turn_end"}:
                return
            if event_type == "turn_start":
                model_callbacks += 1
                if model_callbacks > self._limits.model_callbacks:
                    raise _NativeEventRejected(_NativeDiagnostic.MODEL_CALLBACK_LIMIT)
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
                if ledger.callback_count >= self._limits.tool_callbacks:
                    raise _NativeEventRejected(_NativeDiagnostic.TOOL_CALLBACK_LIMIT)
                try:
                    ledger.record_call(call)
                except ProtocolError:
                    raise _NativeEventRejected(
                        _NativeDiagnostic.TOOL_CALL_INVALID
                    ) from None
                pending_calls[call.call_id] = call
                return
            if event_type == "tool_execution_end":
                result = self._tool_result(payload)
                try:
                    ledger.record_result(result)
                except ProtocolError:
                    raise _NativeEventRejected(
                        _NativeDiagnostic.TOOL_RESULT_INVALID
                    ) from None
                call = pending_calls.pop(result.call_id)
                if result.status == "uncertain":
                    return
                emit(
                    "tool.call",
                    {"call_id": call.call_id, "name": call.name, "arguments": {}},
                )
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
                    raise _NativeEventRejected(_NativeDiagnostic.DUPLICATE_TERMINAL)
                settled = True
                return
            raise _NativeEventRejected(_NativeDiagnostic.EVENT_TYPE_INVALID)

        def consume(event: PiRpcEvent) -> None:
            nonlocal callback_failure
            try:
                trusted_event = _snapshot_native_event(event)
            except BaseException:
                callback_failure = ProtocolError(_NATIVE_EVENT_ERROR)
                raise _CallbackRejected from None
            safe_failure: ProtocolError | None = None
            try:
                consume_checked(trusted_event)
            except _NativeEventRejected as error:
                safe_failure = ProtocolError(_NATIVE_DIAGNOSTIC_MESSAGES[error.code])
            except Exception:
                safe_failure = ProtocolError(_NATIVE_EVENT_ERROR)
            if safe_failure is not None:
                callback_failure = safe_failure
                raise _CallbackRejected from None

        protocol_failure: ProtocolError | None = None
        result: PiRpcResult | None = None
        try:
            result = await self._rpc_session.run(
                request.input_text,
                signal=signal or _NeverCancelled(),
                on_event=consume,
            )
        except _CallbackRejected:
            protocol_failure = callback_failure or ProtocolError(_NATIVE_EVENT_ERROR)
        except ProtocolError:
            protocol_failure = ProtocolError(_TRANSPORT_PROTOCOL_ERROR)
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
        if protocol_failure is not None:
            raise protocol_failure from None
        if result is None or type(result) is not PiRpcResult:
            raise ProtocolError(_TRANSPORT_PROTOCOL_ERROR)
        if result.events != tuple(native):
            raise ProtocolError("Asterion-prime native result is malformed")
        if signal is not None and signal.cancelled:
            emit("run.completed", {"status": "cancelled"})
            return
        if not settled or not native or native[-1].type != "agent_settled":
            raise ProtocolError("Asterion-prime native terminal is invalid")
        ledger.seal()
        emit("run.completed", {"status": "completed"})

    @staticmethod
    def _validate_message_update(payload: Mapping[str, object]) -> None:
        assistant = payload.get("assistantMessageEvent")
        if not isinstance(assistant, Mapping):
            raise _NativeEventRejected(
                _NativeDiagnostic.MESSAGE_UPDATE_MALFORMED
            )
        if assistant.get("type") != "text_delta":
            return
        if type(assistant.get("delta")) is not str:
            raise _NativeEventRejected(
                _NativeDiagnostic.MESSAGE_UPDATE_MALFORMED
            )

    @staticmethod
    def _assistant_usage(payload: Mapping[str, object]) -> Mapping[str, object] | None:
        message = payload.get("message")
        if not isinstance(message, Mapping) or message.get("role") != "assistant":
            return None
        usage = message.get("usage")
        if usage is None:
            return None
        if not isinstance(usage, Mapping):
            raise _NativeEventRejected(_NativeDiagnostic.USAGE_MALFORMED)
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
            raise _NativeEventRejected(_NativeDiagnostic.USAGE_MALFORMED)
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
            raise _NativeEventRejected(_NativeDiagnostic.TOOL_CALL_MALFORMED)
        assert isinstance(call_id, str)
        assert isinstance(name, str)
        assert isinstance(arguments, Mapping)
        try:
            return PrimeToolCall(call_id, name, arguments)
        except ProtocolError:
            raise _NativeEventRejected(_NativeDiagnostic.TOOL_CALL_MALFORMED) from None

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
            raise _NativeEventRejected(_NativeDiagnostic.TOOL_RESULT_MALFORMED)
        status: Literal["ok", "error", "uncertain"] = (
            "uncertain" if effect == "uncertain" else ("error" if is_error else "ok")
        )
        try:
            return PrimeToolResult(call_id, status, ())
        except ProtocolError:
            raise _NativeEventRejected(
                _NativeDiagnostic.TOOL_RESULT_MALFORMED
            ) from None


__all__ = (
    "ASTERION_PRIME_CAPABILITIES",
    "ASTERION_PRIME_LIMITS",
    "AsterionPrimeLimits",
    "AsterionPrimeSession",
)
