"""Digest-only Pathlight observations derived from Pi native events.

This adapter is deliberately best-effort: malformed or incomplete native
events become explicit missing evidence and never expose their contents.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from asterion.pathlight.runtime_observation import (
    ContextFrameObservation,
    ContextSegmentSummary,
    ModelCallObservation,
    RuntimeObservationBatch,
    ToolCallObservation,
)


_Role = Literal["system", "user", "assistant", "tool-result", "unknown"]


@dataclass(frozen=True, slots=True)
class PiObservationCheckpoint:
    """A reversible boundary between Pi attempts."""

    frame_count: int
    model_call_count: int
    tool_count: int
    message_count: int


@dataclass(frozen=True, slots=True)
class _SegmentDraft:
    role: _Role
    content_sha256: str | None
    content_length: int | None
    source_call_id: str | None
    missing_evidence: bool


@dataclass(frozen=True, slots=True)
class _FrameDraft:
    request_index: int
    native_request_index: int
    segments: tuple[_SegmentDraft, ...]
    valid: bool


@dataclass(slots=True)
class _ModelCallDraft:
    frame_index: int
    model_sha256: str | None
    request_sha256: str | None
    response_sha256: str | None = None
    response_length: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    status: Literal["completed", "failed", "cancelled", "missing"] = "missing"
    boundary_observed: bool = True
    response_observed: bool = False


@dataclass(slots=True)
class _ToolDraft:
    call_id: str
    tool_sha256: str | None
    arguments_sha256: str | None
    result_sha256: str | None = None
    result_length: int | None = None
    status: Literal["completed", "failed", "cancelled", "missing"] = "missing"


class PiObservationBuilder:
    """Build a content-safe observation closure from one Pi process stream."""

    def __init__(self, clock: Callable[[], int] | object) -> None:
        # The caller owns timestamps.  Keeping the injected clock preserves a
        # stable construction seam without retaining timing data in Pathlight.
        self._clock = clock
        self._frames: list[_FrameDraft] = []
        self._model_calls: list[_ModelCallDraft] = []
        self._tools: list[_ToolDraft] = []
        self._messages: list[Mapping[str, object]] = []
        self._retry_native_starts: frozenset[int] | None = None
        self._inferred_call_open = False

    def consume(self, event: Mapping[str, object], timestamp_ns: int) -> None:
        """Consume one native event without allowing observation failures out."""

        del timestamp_ns
        try:
            event_type = event.get("type")
            if event_type == "provider_request_context":
                self._consume_provider_context(event)
            elif event_type == "message_start":
                self._consume_message_start(event)
            elif event_type == "tool_execution_start":
                self._consume_tool_start(event)
            elif event_type == "tool_execution_end":
                self._consume_tool_end(event)
            elif event_type == "message_end":
                self._consume_message_end(event)
        except Exception:
            # This is a non-authoritative side channel.  A hostile or future
            # Pi event can only reduce available observation evidence.
            self._mark_invalid()

    def checkpoint(self) -> PiObservationCheckpoint:
        return PiObservationCheckpoint(
            frame_count=len(self._frames),
            model_call_count=len(self._model_calls),
            tool_count=len(self._tools),
            message_count=len(self._messages),
        )

    def rollback(self, checkpoint: PiObservationCheckpoint) -> None:
        """Discard events belonging to a Pi attempt that will be retried."""

        if (
            type(checkpoint) is not PiObservationCheckpoint
            or checkpoint.frame_count < 0
            or checkpoint.model_call_count < 0
            or checkpoint.tool_count < 0
            or checkpoint.message_count < 0
            or checkpoint.frame_count > len(self._frames)
            or checkpoint.model_call_count > len(self._model_calls)
            or checkpoint.tool_count > len(self._tools)
            or checkpoint.message_count > len(self._messages)
        ):
            return
        removed_native_indexes = tuple(
            frame.native_request_index
            for frame in self._frames[checkpoint.frame_count :]
            if frame.valid
        )
        del self._frames[checkpoint.frame_count :]
        del self._model_calls[checkpoint.model_call_count :]
        del self._tools[checkpoint.tool_count :]
        del self._messages[checkpoint.message_count :]
        self._inferred_call_open = False
        if removed_native_indexes:
            reset_start = (
                self._frames[-1].native_request_index + 1
                if self._frames
                else 1
            )
            self._retry_native_starts = frozenset(
                (reset_start, max(removed_native_indexes) + 1)
            )

    def complete(self, run_id: str) -> RuntimeObservationBatch:
        """Return the validated safe closure, degrading to missing evidence."""

        if any(not frame.valid for frame in self._frames):
            return _empty_batch(run_id)
        try:
            tools = self._completed_tools()
            tools_by_call = {tool.call_sha256: tool for tool in tools}
            frames = self._completed_frames(tools_by_call)
            calls = self._completed_model_calls(frames)
            labels = _missing_labels(frames, calls, tools)
            return RuntimeObservationBatch.build(
                run_sha256=_digest_text(run_id),
                frames=frames,
                model_calls=calls,
                tools=tools,
                missing_evidence=tuple(sorted(labels)),
            )
        except Exception:
            return _empty_batch(run_id)

    def _consume_provider_context(self, event: Mapping[str, object]) -> None:
        if self._inferred_call_open:
            self._frames.pop()
            self._model_calls.pop()
            self._inferred_call_open = False
        index = event.get("requestIndex")
        expected_index = (
            self._frames[-1].native_request_index + 1
            if self._frames
            else None
        )
        index_is_expected = (
            index == expected_index
            if expected_index is not None
            else index in self._retry_native_starts
            if self._retry_native_starts is not None
            else index == 1
        )
        if (
            type(index) is not int
            or index < 1
            or len(self._model_calls) != len(self._frames)
            or not index_is_expected
        ):
            self._mark_invalid()
            return
        normalized_index = len(self._frames) + 1
        self._retry_native_starts = None
        messages = event.get("messages")
        if type(messages) is list:
            segments = tuple(_segment_from_message(message) for message in messages)
            request_sha256 = _digest_json(messages)
            if request_sha256 is None:
                segments = (_missing_segment(),)
        else:
            segments = (_missing_segment(),)
            request_sha256 = None
        model_sha256 = _model_digest(event)
        self._frames.append(
            _FrameDraft(normalized_index, index, segments, True)
        )
        self._model_calls.append(
            _ModelCallDraft(
                frame_index=normalized_index,
                model_sha256=model_sha256,
                request_sha256=request_sha256,
            )
        )

    def _consume_message_start(self, event: Mapping[str, object]) -> None:
        message = event.get("message")
        if (
            not isinstance(message, Mapping)
            or message.get("role") != "assistant"
            or len(self._model_calls) != len(self._frames)
            or any(not call.response_observed for call in self._model_calls)
        ):
            return
        index = len(self._frames) + 1
        segments = (
            _missing_segment(),
            *(_segment_from_message(value) for value in self._messages),
        )
        self._frames.append(_FrameDraft(index, index, segments, True))
        self._model_calls.append(
            _ModelCallDraft(
                frame_index=index,
                model_sha256=_model_digest(message),
                request_sha256=None,
            )
        )
        self._inferred_call_open = True

    def _consume_tool_start(self, event: Mapping[str, object]) -> None:
        call_id = event.get("toolCallId")
        if (
            type(call_id) is not str
            or not call_id
            or any(tool.call_id == call_id for tool in self._tools)
        ):
            self._mark_invalid()
            return
        name = event.get("toolName")
        self._tools.append(
            _ToolDraft(
                call_id=call_id,
                tool_sha256=_digest_text(name) if type(name) is str and name else None,
                arguments_sha256=_digest_json(event.get("args")),
            )
        )

    def _consume_tool_end(self, event: Mapping[str, object]) -> None:
        call_id = event.get("toolCallId")
        if type(call_id) is not str or not call_id:
            self._mark_invalid()
            return
        tool = next((item for item in self._tools if item.call_id == call_id), None)
        if tool is None:
            self._tools.append(_ToolDraft(call_id, None, None))
            return
        if tool.status != "missing" or type(event.get("isError")) is not bool:
            self._mark_invalid()
            return
        result = _content_summary(event.get("result"))
        tool.result_sha256, tool.result_length = result
        tool.status = "failed" if event["isError"] else "completed"

    def _consume_message_end(self, event: Mapping[str, object]) -> None:
        message = event.get("message")
        if not isinstance(message, Mapping):
            return
        if message.get("role") == "assistant":
            call = next(
                (
                    item
                    for item in reversed(self._model_calls)
                    if not item.response_observed
                ),
                None,
            )
            if call is not None:
                content = message.get("content", message.get("text"))
                call.response_sha256, call.response_length = _content_summary(content)
                usage = message.get("usage")
                if isinstance(usage, Mapping):
                    input_tokens = usage.get("input")
                    output_tokens = usage.get("output")
                    if _nonnegative_int(input_tokens) and _nonnegative_int(
                        output_tokens
                    ):
                        call.input_tokens = input_tokens
                        call.output_tokens = output_tokens
                call.status = (
                    "failed" if message.get("stopReason") == "error" else "completed"
                )
                call.response_observed = True
                self._inferred_call_open = False
        detached = _json_mapping_copy(message)
        if detached is not None:
            self._messages.append(detached)

    def _mark_invalid(self) -> None:
        # A sentinel is counted by checkpoints, making retry rollback restore
        # the prior trustworthy state without expanding their public shape.
        self._retry_native_starts = None
        self._frames.append(_FrameDraft(0, 0, (), False))

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
                candidate_call_sha256 = (
                    _digest_text(draft.source_call_id)
                    if draft.source_call_id is not None
                    else None
                )
                source = (
                    tools_by_call.get(candidate_call_sha256)
                    if candidate_call_sha256 is not None
                    else None
                )
                if draft.role == "tool-result":
                    content_sha256 = draft.content_sha256
                    content_length = draft.content_length
                    verified_lineage = (
                        source is not None
                        and content_sha256 is not None
                        and (content_sha256, content_length)
                        == (source.result_sha256, source.result_length)
                    )
                    source_call_sha256 = (
                        candidate_call_sha256 if verified_lineage else None
                    )
                    missing_evidence = not verified_lineage
                else:
                    content_sha256 = draft.content_sha256
                    content_length = draft.content_length
                    source_call_sha256 = None
                    missing_evidence = draft.missing_evidence
                segments.append(
                    ContextSegmentSummary(
                        segment_index=index,
                        role=draft.role,
                        structure_kind=(
                            "tool-result"
                            if draft.role == "tool-result"
                            else "missing" if missing_evidence else "message"
                        ),
                        content_sha256=content_sha256,
                        content_length=content_length,
                        source_call_sha256=source_call_sha256,
                        missing_evidence=missing_evidence,
                    )
                )
            frames.append(
                ContextFrameObservation(frame_index=frame.request_index, segments=tuple(segments))
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
                model_sha256=call.model_sha256,
                request_sha256=call.request_sha256,
                response_sha256=call.response_sha256,
                response_length=call.response_length,
                input_tokens=call.input_tokens,
                output_tokens=call.output_tokens,
                status=call.status,
                boundary_observed=call.boundary_observed,
            )
            for call in self._model_calls
        )


def _segment_from_message(value: object) -> _SegmentDraft:
    if not isinstance(value, Mapping):
        return _missing_segment()
    role = value.get("role")
    if role in {"tool", "tool-result", "tool_result", "toolResult"}:
        call_id = value.get("toolCallId", value.get("tool_call_id"))
        digest, length = _content_summary(
            value.get("content", value.get("text"))
        )
        return _SegmentDraft(
            "tool-result",
            digest,
            length,
            call_id if type(call_id) is str and call_id else None,
            digest is None or type(call_id) is not str or not call_id,
        )
    normalized_role: _Role = role if role in {"system", "user", "assistant"} else "unknown"
    digest, length = _content_summary(value.get("content", value.get("text")))
    return _SegmentDraft(
        normalized_role, digest, length, None, digest is None
    )


def _missing_segment() -> _SegmentDraft:
    return _SegmentDraft("unknown", None, None, None, True)


def _model_digest(event: Mapping[str, object]) -> str | None:
    provider = event.get("provider")
    model = event.get("model")
    if type(provider) is not str or type(model) is not str:
        return None
    return _digest_json({"provider": provider, "model": model})


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


def _json_mapping_copy(value: Mapping[str, object]) -> Mapping[str, object] | None:
    rendered = _canonical_json(value)
    if rendered is None:
        return None
    copied = json.loads(rendered)
    return copied if isinstance(copied, dict) else None


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
