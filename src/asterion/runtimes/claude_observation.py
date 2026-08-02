"""Digest-only Pathlight observations derived from Claude stream-json events.

Claude Code's stream reports responses and tool results, but not the complete
provider request submitted for any turn.  This adapter therefore records only
the visible conversation mainline and always marks request boundaries missing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from asterion.pathlight.runtime_observation import (
    ContextFrameObservation,
    ContextSegmentSummary,
    ModelCallObservation,
    RuntimeObservationBatch,
    ToolCallObservation,
)


_Role = Literal["assistant", "tool-result", "unknown", "user"]
_Status = Literal["completed", "failed", "missing"]


@dataclass(frozen=True, slots=True)
class _SegmentDraft:
    role: _Role
    content_sha256: str | None
    content_length: int | None
    source_call_id: str | None
    missing_evidence: bool


@dataclass(frozen=True, slots=True)
class _FrameDraft:
    frame_index: int
    segments: tuple[_SegmentDraft, ...]


@dataclass(slots=True)
class _ModelCallDraft:
    frame_index: int
    response_sha256: str | None = None
    response_length: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    status: _Status = "missing"


@dataclass(slots=True)
class _ToolDraft:
    call_id: str
    tool_sha256: str | None
    arguments_sha256: str | None
    result_sha256: str | None = None
    result_length: int | None = None
    status: _Status = "missing"


class ClaudeObservationBuilder:
    """Build a content-safe, explicitly incomplete Claude stream closure."""

    def __init__(self) -> None:
        self._frames: list[_FrameDraft] = []
        self._model_calls: list[_ModelCallDraft] = []
        self._tools: list[_ToolDraft] = []
        self._pending_segments: list[_SegmentDraft] = [_missing_segment()]
        self._host_input_recorded = False

    def record_host_input(self, input_text: str) -> None:
        """Record only the host input digest, never a claimed provider request."""

        if (
            type(input_text) is not str
            or self._host_input_recorded
            or self._model_calls
        ):
            return
        digest, length = _content_summary(input_text)
        self._pending_segments = [
            _SegmentDraft("user", digest, length, None, True)
        ]
        self._host_input_recorded = True

    def consume(self, event: Mapping[str, object], timestamp_ns: int) -> None:
        """Consume one native stream event without retaining its contents."""

        del timestamp_ns
        try:
            event_type = event.get("type")
            if event_type == "assistant":
                self._consume_assistant(event)
            elif event_type == "user":
                self._consume_user(event)
            elif event_type == "result":
                self._consume_result(event)
        except Exception:
            # Observation is optional.  A malformed or future stream event can
            # reduce evidence only; it must never influence the runtime path.
            self._pending_segments.append(_missing_segment())

    def complete(self, run_id: str) -> RuntimeObservationBatch:
        """Return the validated digest-only closure for this stream."""

        try:
            tools = self._completed_tools()
            tools_by_call = {tool.call_sha256: tool for tool in tools}
            frames = self._completed_frames(tools_by_call)
            calls = self._completed_model_calls(frames)
            return RuntimeObservationBatch.build(
                run_sha256=_digest_text(run_id),
                frames=frames,
                model_calls=calls,
                tools=tools,
                missing_evidence=tuple(sorted(_missing_labels(frames, calls, tools))),
            )
        except Exception:
            return _empty_batch(run_id)

    def _consume_assistant(self, event: Mapping[str, object]) -> None:
        message = event.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        call = self._start_model_call()
        call.response_sha256, call.response_length = _content_summary(content)
        call.status = "failed" if event.get("error") is not None else "completed"
        self._pending_segments.append(
            _SegmentDraft(
                "assistant",
                call.response_sha256,
                call.response_length,
                None,
                call.response_sha256 is None,
            )
        )
        if isinstance(content, list):
            for block in content:
                self._consume_tool_use(block)

    def _consume_tool_use(self, block: object) -> None:
        if not isinstance(block, Mapping) or block.get("type") != "tool_use":
            return
        call_id = block.get("id")
        if (
            type(call_id) is not str
            or not call_id
            or any(tool.call_id == call_id for tool in self._tools)
        ):
            self._pending_segments.append(_missing_segment())
            return
        name = block.get("name")
        self._tools.append(
            _ToolDraft(
                call_id=call_id,
                tool_sha256=_digest_text(name) if type(name) is str and name else None,
                arguments_sha256=_digest_json(block.get("input")),
            )
        )

    def _consume_user(self, event: Mapping[str, object]) -> None:
        message = event.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, list):
            return
        for block in content:
            self._consume_tool_result(block)

    def _consume_tool_result(self, block: object) -> None:
        if not isinstance(block, Mapping) or block.get("type") != "tool_result":
            return
        call_id = block.get("tool_use_id")
        if type(call_id) is not str or not call_id:
            self._pending_segments.append(_missing_segment())
            return
        result_sha256, result_length = _content_summary(block.get("content"))
        tool = next((item for item in self._tools if item.call_id == call_id), None)
        boundary_missing = tool is None
        is_error = block.get("is_error", False)
        if type(is_error) is not bool:
            is_error = None
        if tool is None:
            tool = _ToolDraft(call_id, None, None)
            self._tools.append(tool)
        if tool.status != "missing":
            self._pending_segments.append(_missing_segment())
            return
        tool.result_sha256 = result_sha256
        tool.result_length = result_length
        tool.status = (
            "missing"
            if boundary_missing or is_error is None
            else "failed" if is_error else "completed"
        )
        self._pending_segments.append(
            _SegmentDraft(
                "tool-result",
                result_sha256,
                result_length,
                call_id,
                result_sha256 is None or boundary_missing or is_error is None,
            )
        )

    def _consume_result(self, event: Mapping[str, object]) -> None:
        call = self._model_calls[-1] if self._model_calls else self._start_model_call()
        if call.response_sha256 is None:
            call.response_sha256, call.response_length = _content_summary(
                event.get("result")
            )
        is_error = event.get("is_error")
        if is_error is True:
            call.status = "failed"
        elif is_error is False:
            call.status = "completed"
        usage = event.get("usage")
        if isinstance(usage, Mapping):
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            if _nonnegative_int(input_tokens) and _nonnegative_int(output_tokens):
                call.input_tokens = input_tokens
                call.output_tokens = output_tokens

    def _start_model_call(self) -> _ModelCallDraft:
        frame_index = len(self._frames) + 1
        self._frames.append(
            _FrameDraft(frame_index, tuple(self._pending_segments))
        )
        call = _ModelCallDraft(frame_index)
        self._model_calls.append(call)
        return call

    def _completed_tools(self) -> tuple[ToolCallObservation, ...]:
        return tuple(
            sorted(
                (
                    ToolCallObservation(
                        call_sha256=_digest_text(tool.call_id),
                        tool_sha256=tool.tool_sha256,
                        arguments_sha256=tool.arguments_sha256,
                        result_sha256=tool.result_sha256,
                        result_length=tool.result_length,
                        status=tool.status,
                    )
                    for tool in self._tools
                ),
                key=lambda tool: tool.call_sha256,
            )
        )

    def _completed_frames(
        self, tools_by_call: Mapping[str, ToolCallObservation]
    ) -> tuple[ContextFrameObservation, ...]:
        frames: list[ContextFrameObservation] = []
        for frame in self._frames:
            segments: list[ContextSegmentSummary] = []
            for index, draft in enumerate(frame.segments):
                call_sha256 = (
                    _digest_text(draft.source_call_id)
                    if draft.source_call_id is not None
                    else None
                )
                tool = tools_by_call.get(call_sha256) if call_sha256 else None
                linked = (
                    tool is not None
                    and draft.content_sha256 is not None
                    and (draft.content_sha256, draft.content_length)
                    == (tool.result_sha256, tool.result_length)
                )
                missing = draft.missing_evidence or (
                    draft.role == "tool-result" and not linked
                )
                segments.append(
                    ContextSegmentSummary(
                        segment_index=index,
                        role=draft.role,
                        structure_kind=(
                            "tool-result"
                            if draft.role == "tool-result"
                            else "missing" if missing else "message"
                        ),
                        content_sha256=draft.content_sha256,
                        content_length=draft.content_length,
                        source_call_sha256=call_sha256 if linked else None,
                        missing_evidence=missing,
                    )
                )
            frames.append(
                ContextFrameObservation(frame_index=frame.frame_index, segments=tuple(segments))
            )
        return tuple(frames)

    def _completed_model_calls(
        self, frames: tuple[ContextFrameObservation, ...]
    ) -> tuple[ModelCallObservation, ...]:
        frame_hashes = {frame.frame_index: frame.frame_sha256 for frame in frames}
        return tuple(
            ModelCallObservation(
                request_index=call.frame_index,
                frame_sha256=frame_hashes[call.frame_index],
                model_sha256=None,
                request_sha256=None,
                response_sha256=call.response_sha256,
                response_length=call.response_length,
                input_tokens=call.input_tokens,
                output_tokens=call.output_tokens,
                status=call.status,
                boundary_observed=False,
            )
            for call in self._model_calls
        )


def _missing_segment() -> _SegmentDraft:
    return _SegmentDraft("unknown", None, None, None, True)


def _content_summary(value: object) -> tuple[str | None, int | None]:
    if value is None:
        return None, None
    if type(value) is str:
        return _digest_text(value), len(value)
    rendered = _canonical_json(value)
    if rendered is None:
        return None, None
    return _digest_text(rendered), len(rendered)


def _digest_json(value: object) -> str | None:
    rendered = _canonical_json(value)
    return _digest_text(rendered) if rendered is not None else None


def _canonical_json(value: object) -> str | None:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


def _digest_text(value: object) -> str:
    text = value if type(value) is str else ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _missing_labels(
    frames: tuple[ContextFrameObservation, ...],
    calls: tuple[ModelCallObservation, ...],
    tools: tuple[ToolCallObservation, ...],
) -> set[str]:
    labels: set[str] = set()
    if not frames:
        labels.add("context-frame")
    if not calls:
        labels.update(("model-request", "model-request-boundary"))
    if any(segment.missing_evidence for frame in frames for segment in frame.segments):
        labels.add("context-segment")
    for call in calls:
        if call.model_sha256 is None:
            labels.add("model-identity")
        if call.request_sha256 is None:
            labels.add("model-request")
        if not call.boundary_observed:
            labels.add("model-request-boundary")
        if call.response_sha256 is None:
            labels.add("model-response")
        if call.input_tokens is None or call.output_tokens is None:
            labels.add("token-usage")
    for tool in tools:
        if tool.status == "missing":
            labels.add("tool-boundary")
        if tool.tool_sha256 is None:
            labels.add("tool-identity")
        if tool.arguments_sha256 is None:
            labels.add("tool-arguments")
        if tool.result_sha256 is None:
            labels.add("tool-result")
    return labels


def _empty_batch(run_id: str) -> RuntimeObservationBatch:
    return RuntimeObservationBatch.build(
        run_sha256=_digest_text(run_id),
        frames=(),
        model_calls=(),
        tools=(),
        missing_evidence=(
            "context-frame",
            "model-request",
            "model-request-boundary",
        ),
    )
