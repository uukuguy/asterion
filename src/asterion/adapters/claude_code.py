"""Translate Claude Code SDK stream-json messages to protocol v1 events."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy

from asterion.runtime.protocol import PROTOCOL_VERSION, ProtocolError


CLAUDE_CAPABILITY_MAP = {
    "Read": "filesystem.read",
    "Bash": "shell",
    "Write": "filesystem.write",
    "Edit": "filesystem.write",
}


def map_claude_capabilities(tools: object) -> list[str]:
    if not isinstance(tools, list):
        return []
    capabilities: list[str] = []
    for tool in tools:
        if not isinstance(tool, str) or not tool:
            continue
        capability = CLAUDE_CAPABILITY_MAP.get(tool, f"claude.tool.{tool.lower()}")
        if capability not in capabilities:
            capabilities.append(capability)
    return capabilities


class ClaudeCodeProtocolAdapter:
    """Stateful translator for one Claude Code stream-json invocation."""

    def __init__(
        self,
        *,
        run_id: str,
        emit: Callable[[dict[str, object]], None],
    ) -> None:
        if not run_id:
            raise ProtocolError("Claude Code protocol run_id must be non-empty")
        self.run_id = run_id
        self.emit = emit
        self.sequence = 0
        self.started = False
        self.terminal = False
        self.tool_calls: set[str] = set()
        self.tool_results: set[str] = set()

    def _emit(self, event_type: str, payload: dict[str, object]) -> None:
        if self.terminal:
            raise ProtocolError("Claude Code emitted after its terminal result")
        self.sequence += 1
        self.emit(
            {
                "protocol": PROTOCOL_VERSION,
                "run_id": self.run_id,
                "sequence": self.sequence,
                "type": event_type,
                "payload": payload,
            }
        )
        if event_type in {"run.completed", "run.failed"}:
            self.terminal = True

    def _require_started(self) -> None:
        if not self.started:
            raise ProtocolError("Claude Code stream must begin with system/init")

    def consume(self, raw_event: Mapping[str, object]) -> None:
        event_type = raw_event.get("type")
        if event_type == "system" and raw_event.get("subtype") == "init":
            if self.started:
                raise ProtocolError("Claude Code emitted duplicate system/init")
            self.started = True
            self._emit(
                "run.started",
                {"capabilities": map_claude_capabilities(raw_event.get("tools"))},
            )
            return

        self._require_started()
        if event_type == "assistant":
            if raw_event.get("error") is not None:
                return
            self._consume_assistant(raw_event.get("message"))
        elif event_type == "user":
            self._consume_user(raw_event.get("message"))
        elif event_type == "result":
            self._consume_result(raw_event)

    def _consume_assistant(self, message_value: object) -> None:
        if not isinstance(message_value, Mapping):
            return
        content = message_value.get("content")
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, Mapping):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    self._emit("text.delta", {"text": text})
            elif block_type == "tool_use":
                call_id = block.get("id")
                name = block.get("name")
                arguments = block.get("input")
                if not isinstance(call_id, str) or not call_id:
                    raise ProtocolError("Claude Code tool_use lacks id")
                if not isinstance(name, str) or not name:
                    raise ProtocolError("Claude Code tool_use lacks name")
                if call_id in self.tool_calls:
                    raise ProtocolError(f"Claude Code emitted duplicate tool id {call_id}")
                self.tool_calls.add(call_id)
                normalized_arguments = (
                    dict(deepcopy(arguments))
                    if isinstance(arguments, Mapping)
                    else {"value": deepcopy(arguments)}
                )
                self._emit(
                    "tool.call",
                    {
                        "call_id": call_id,
                        "name": name,
                        "arguments": normalized_arguments,
                    },
                )

    def _consume_user(self, message_value: object) -> None:
        if not isinstance(message_value, Mapping):
            return
        content = message_value.get("content")
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, Mapping) or block.get("type") != "tool_result":
                continue
            call_id = block.get("tool_use_id")
            if not isinstance(call_id, str) or call_id not in self.tool_calls:
                raise ProtocolError("Claude Code tool_result has no matching tool_use")
            if call_id in self.tool_results:
                raise ProtocolError(f"Claude Code emitted duplicate tool_result {call_id}")
            is_error = block.get("is_error", False)
            if not isinstance(is_error, bool):
                raise ProtocolError("Claude Code tool_result is_error must be boolean")
            self.tool_results.add(call_id)
            self._emit(
                "tool.result",
                {
                    "call_id": call_id,
                    "output": deepcopy(block.get("content")),
                    "is_error": is_error,
                },
            )

    def _consume_result(self, raw_event: Mapping[str, object]) -> None:
        usage = raw_event.get("usage")
        if isinstance(usage, Mapping):
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            if (
                isinstance(input_tokens, int)
                and not isinstance(input_tokens, bool)
                and input_tokens >= 0
                and isinstance(output_tokens, int)
                and not isinstance(output_tokens, bool)
                and output_tokens >= 0
            ):
                self._emit(
                    "usage.reported",
                    {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    },
                )
        if raw_event.get("is_error") is True:
            self._emit(
                "run.failed",
                {
                    "code": "claude_code_failed",
                    "message": "Claude Code runtime failed; see the raw stderr artifact.",
                },
            )
        else:
            result_text = raw_event.get("result")
            if isinstance(result_text, str) and result_text:
                self._emit(
                    "artifact.created",
                    {
                        "artifact": {
                            "artifact_id": "final-answer",
                            "kind": "answer",
                            "media_type": "text/plain",
                            "uri": "final.txt",
                        }
                    },
                )
            self._emit("run.completed", {"status": "completed"})

    def fail(self) -> None:
        self._require_started()
        self._emit(
            "run.failed",
            {
                "code": "claude_code_failed",
                "message": "Claude Code runtime failed; see the raw stderr artifact.",
            },
        )
