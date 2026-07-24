"""Translate stable Pi RPC events to Agent Runtime Protocol v1 events."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy

from asterion.runtime.protocol import PROTOCOL_VERSION, ProtocolError


PI_CAPABILITY_MAP = {
    "read": "filesystem.read",
    "bash": "shell",
    "write": "filesystem.write",
    "edit": "filesystem.write",
}


def map_pi_capabilities(tools: str | None) -> list[str]:
    """Map configured Pi tool names to conservative protocol capabilities."""

    capabilities: list[str] = []
    for tool_name in (part.strip() for part in (tools or "").split(",")):
        if not tool_name:
            continue
        capability = PI_CAPABILITY_MAP.get(tool_name, f"pi.tool.{tool_name}")
        if capability not in capabilities:
            capabilities.append(capability)
    return capabilities


class PiProtocolAdapter:
    """Stateful one-attempt translator from Pi events to protocol events."""

    def __init__(
        self,
        *,
        run_id: str,
        capabilities: list[str],
        emit: Callable[[dict[str, object]], None],
    ) -> None:
        if not run_id:
            raise ProtocolError("Pi protocol run_id must be non-empty")
        self.run_id = run_id
        self.capabilities = list(capabilities)
        self.emit = emit
        self.sequence = 0
        self.started = False
        self.terminal = False
        self.tool_calls: set[str] = set()
        self.tool_results: set[str] = set()

    def _emit(self, event_type: str, payload: dict[str, object]) -> None:
        if self.terminal:
            raise ProtocolError("Pi adapter cannot emit after a terminal event")
        self.sequence += 1
        event: dict[str, object] = {
            "protocol": PROTOCOL_VERSION,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "type": event_type,
            "payload": payload,
        }
        self.emit(event)
        if event_type in {"run.completed", "run.failed"}:
            self.terminal = True

    def start(self) -> None:
        if self.started:
            raise ProtocolError("Pi adapter run already started")
        self.started = True
        self._emit("run.started", {"capabilities": list(self.capabilities)})

    def _require_active(self) -> None:
        if not self.started:
            raise ProtocolError("Pi adapter run has not started")
        if self.terminal:
            raise ProtocolError("Pi adapter run is already terminal")

    def consume(self, raw_event: Mapping[str, object]) -> None:
        """Consume one raw Pi event, emitting a normalized event when applicable."""

        self._require_active()
        event_type = raw_event.get("type")
        if event_type == "message_update":
            assistant_event = raw_event.get("assistantMessageEvent")
            if not isinstance(assistant_event, Mapping):
                return
            if assistant_event.get("type") != "text_delta":
                return
            delta = assistant_event.get("delta")
            if isinstance(delta, str) and delta:
                self._emit("text.delta", {"text": delta})
            return

        if event_type == "tool_execution_start":
            call_id = raw_event.get("toolCallId")
            tool_name = raw_event.get("toolName")
            if not isinstance(call_id, str) or not call_id:
                raise ProtocolError("Pi tool_execution_start lacks toolCallId")
            if not isinstance(tool_name, str) or not tool_name:
                raise ProtocolError("Pi tool_execution_start lacks toolName")
            if call_id in self.tool_calls:
                raise ProtocolError(f"Pi emitted duplicate toolCallId {call_id}")
            self.tool_calls.add(call_id)
            raw_args = raw_event.get("args")
            arguments = (
                dict(deepcopy(raw_args))
                if isinstance(raw_args, Mapping)
                else {"value": deepcopy(raw_args)}
            )
            self._emit(
                "tool.call",
                {"call_id": call_id, "name": tool_name, "arguments": arguments},
            )
            return

        if event_type == "tool_execution_end":
            call_id = raw_event.get("toolCallId")
            if not isinstance(call_id, str) or not call_id:
                raise ProtocolError("Pi tool_execution_end lacks toolCallId")
            is_error = raw_event.get("isError")
            if not isinstance(is_error, bool):
                raise ProtocolError("Pi tool_execution_end lacks boolean isError")
            if call_id not in self.tool_calls:
                raise ProtocolError(f"Pi tool result has no matching call {call_id}")
            if call_id in self.tool_results:
                raise ProtocolError(f"Pi emitted duplicate tool result {call_id}")
            self.tool_results.add(call_id)
            self._emit(
                "tool.result",
                {
                    "call_id": call_id,
                    "output": deepcopy(raw_event.get("result")),
                    "is_error": is_error,
                },
            )
            return

        if event_type == "message_end":
            message = raw_event.get("message")
            if not isinstance(message, Mapping) or message.get("role") != "assistant":
                return
            usage = message.get("usage")
            if not isinstance(usage, Mapping):
                return
            input_tokens = usage.get("input")
            output_tokens = usage.get("output")
            if (
                isinstance(input_tokens, bool)
                or not isinstance(input_tokens, int)
                or input_tokens < 0
                or isinstance(output_tokens, bool)
                or not isinstance(output_tokens, int)
                or output_tokens < 0
            ):
                raise ProtocolError("Pi assistant usage fields must be non-negative integers")
            self._emit(
                "usage.reported",
                {"input_tokens": input_tokens, "output_tokens": output_tokens},
            )

    def complete(self, *, artifact: Mapping[str, object] | None = None) -> None:
        self._require_active()
        if artifact is not None:
            self._emit("artifact.created", {"artifact": dict(deepcopy(artifact))})
        self._emit("run.completed", {"status": "completed"})

    def fail(self) -> None:
        self._require_active()
        self._emit(
            "run.failed",
            {
                "code": "pi_runtime_failed",
                "message": "Pi runtime failed; see the run stderr artifact.",
            },
        )
