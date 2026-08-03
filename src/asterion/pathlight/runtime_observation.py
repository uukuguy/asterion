"""Immutable, content-safe runtime observations for Pathlight.

This optional side channel records only digests and fixed public metadata.  It
never accepts runtime payloads, prompts, answers, tool arguments, or paths.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, NoReturn, Protocol, cast, runtime_checkable

from asterion.pathlight.protocol import MISSING_EVIDENCE_LABELS, PathlightError


RUNTIME_OBSERVATION_SCHEMA = "asterion.pathlight-runtime-observation/v2"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEGMENT_ROLES = frozenset({"system", "user", "assistant", "tool-result", "unknown"})
_STRUCTURE_KINDS = frozenset({"message", "tool-result", "contract", "missing"})
_STATUSES = frozenset({"completed", "failed", "cancelled", "missing"})
_MISSING_EVIDENCE = MISSING_EVIDENCE_LABELS

_SEGMENT_FIELDS = frozenset(
    {
        "segment_index",
        "role",
        "structure_kind",
        "content_sha256",
        "content_length",
        "source_call_sha256",
        "missing_evidence",
        "segment_sha256",
    }
)
_FRAME_FIELDS = frozenset({"frame_index", "segments", "frame_sha256"})
_PROVIDER_REQUEST_FIELDS = frozenset(
    {
        "request_index",
        "payload_sha256",
        "payload_bytes",
        "shape_sha256",
        "field_count",
        "leaf_count",
        "text_characters",
        "private_reference_sha256",
        "segments",
        "provider_request_sha256",
    }
)
_MODEL_CALL_FIELDS = frozenset(
    {
        "request_index",
        "frame_sha256",
        "model_sha256",
        "request_sha256",
        "response_sha256",
        "response_length",
        "input_tokens",
        "output_tokens",
        "status",
        "boundary_observed",
        "model_call_sha256",
    }
)
_TOOL_CALL_FIELDS = frozenset(
    {
        "call_sha256",
        "tool_sha256",
        "arguments_sha256",
        "result_sha256",
        "result_length",
        "status",
        "tool_call_sha256",
    }
)
_BATCH_FIELDS = frozenset(
    {
        "schema",
        "run_sha256",
        "frames",
        "model_calls",
        "provider_requests",
        "tools",
        "missing_evidence",
        "batch_sha256",
    }
)


def _invalid() -> NoReturn:
    raise PathlightError("Pathlight runtime observation is invalid") from None


def _canonical_digest(domain: str, value: Mapping[str, object]) -> str:
    """Hash a public mapping with a type-specific domain separator."""

    rendered = json.dumps(
        {"domain": domain, "value": value}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _require_digest(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _invalid()
    return cast(str, value)


def _require_optional_digest(value: object) -> str | None:
    if value is None:
        return None
    return _require_digest(value)


def _require_nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        _invalid()
    return cast(int, value)


def _require_index(value: object, *, minimum: int) -> int:
    value = _require_nonnegative_int(value)
    if value < minimum:
        _invalid()
    return value


def _require_enum(value: object, values: frozenset[str]) -> str:
    if type(value) is not str or value not in values:
        _invalid()
    return cast(str, value)


def _require_bool(value: object) -> bool:
    if type(value) is not bool:
        _invalid()
    return cast(bool, value)


def _require_optional_nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    return _require_nonnegative_int(value)


def _require_optional_content(
    content_sha256: object, content_length: object
) -> tuple[str | None, int | None]:
    digest = _require_optional_digest(content_sha256)
    length = _require_optional_nonnegative_int(content_length)
    if (digest is None) != (length is None):
        _invalid()
    return digest, length


def _copy_exact_dict(value: object, fields: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict:
        _invalid()
    exact = cast(dict[object, object], value)
    keys = tuple(exact.keys())
    if any(type(name) is not str for name in keys):
        _invalid()
    exact_keys = cast(tuple[str, ...], keys)
    if len(exact_keys) != len(fields) or any(name not in fields for name in exact_keys):
        _invalid()
    return {name: exact[name] for name in exact_keys}


def _copy_exact_list(value: object) -> list[object]:
    if type(value) is not list:
        _invalid()
    return list(cast(list[object], value))


def _require_exact_tuple(value: object) -> tuple[object, ...]:
    if type(value) is not tuple:
        _invalid()
    return tuple(cast(tuple[object, ...], value))


@dataclass(frozen=True, slots=True)
class ContextSegmentSummary:
    """A digest-only summary of one ordered context segment."""

    segment_index: int
    role: Literal["system", "user", "assistant", "tool-result", "unknown"]
    structure_kind: Literal["message", "tool-result", "contract", "missing"]
    content_sha256: str | None
    content_length: int | None
    source_call_sha256: str | None
    missing_evidence: bool
    segment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.segment_index)
        _require_enum(self.role, _SEGMENT_ROLES)
        _require_enum(self.structure_kind, _STRUCTURE_KINDS)
        _require_optional_content(self.content_sha256, self.content_length)
        _require_optional_digest(self.source_call_sha256)
        _require_bool(self.missing_evidence)
        if (
            self.content_sha256 is None or self.structure_kind == "missing"
        ) and not self.missing_evidence:
            _invalid()
        if self.source_call_sha256 is not None and (
            self.role != "tool-result" or self.structure_kind != "tool-result"
        ):
            _invalid()
        object.__setattr__(
            self,
            "segment_sha256",
            _canonical_digest(
                "asterion.pathlight/context-segment-summary/v1",
                self._unsigned_mapping(),
            ),
        )

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "segment_index": self.segment_index,
            "role": self.role,
            "structure_kind": self.structure_kind,
            "content_sha256": self.content_sha256,
            "content_length": self.content_length,
            "source_call_sha256": self.source_call_sha256,
            "missing_evidence": self.missing_evidence,
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "segment_sha256": self.segment_sha256}


@dataclass(frozen=True, slots=True)
class ContextFrameObservation:
    """One ordered provider context frame, represented without its contents."""

    frame_index: int
    segments: tuple[ContextSegmentSummary, ...]
    frame_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _require_index(self.frame_index, minimum=1)
        values = _require_exact_tuple(self.segments)
        if any(type(segment) is not ContextSegmentSummary for segment in values):
            _invalid()
        segments = cast(tuple[ContextSegmentSummary, ...], values)
        segment_indexes = tuple(segment.segment_index for segment in segments)
        if segment_indexes != tuple(range(len(segments))):
            _invalid()
        object.__setattr__(self, "segments", segments)
        object.__setattr__(
            self,
            "frame_sha256",
            _canonical_digest(
                "asterion.pathlight/context-frame-observation/v1",
                self._unsigned_mapping(),
            ),
        )

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "frame_index": self.frame_index,
            "segments": [segment.to_mapping() for segment in self.segments],
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "frame_sha256": self.frame_sha256}


@dataclass(frozen=True, slots=True)
class ProviderRequestObservation:
    """Verified provider request metadata without request content or paths."""

    request_index: int
    payload_sha256: str
    payload_bytes: int
    shape_sha256: str
    field_count: int
    leaf_count: int
    text_characters: int
    private_reference_sha256: str
    segments: tuple[ContextSegmentSummary, ...]
    provider_request_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _require_index(self.request_index, minimum=1)
        _require_digest(self.payload_sha256)
        _require_nonnegative_int(self.payload_bytes)
        _require_digest(self.shape_sha256)
        _require_nonnegative_int(self.field_count)
        _require_nonnegative_int(self.leaf_count)
        _require_nonnegative_int(self.text_characters)
        _require_digest(self.private_reference_sha256)
        values = _require_exact_tuple(self.segments)
        if any(type(segment) is not ContextSegmentSummary for segment in values):
            _invalid()
        segments = cast(tuple[ContextSegmentSummary, ...], values)
        if tuple(segment.segment_index for segment in segments) != tuple(
            range(len(segments))
        ):
            _invalid()
        object.__setattr__(self, "segments", segments)
        object.__setattr__(
            self,
            "provider_request_sha256",
            _canonical_digest(
                "asterion.pathlight/provider-request-observation/v1",
                self._unsigned_mapping(),
            ),
        )

    @classmethod
    def build(cls, **values: object) -> ProviderRequestObservation:
        return cls(**values)  # type: ignore[arg-type]

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "request_index": self.request_index,
            "payload_sha256": self.payload_sha256,
            "payload_bytes": self.payload_bytes,
            "shape_sha256": self.shape_sha256,
            "field_count": self.field_count,
            "leaf_count": self.leaf_count,
            "text_characters": self.text_characters,
            "private_reference_sha256": self.private_reference_sha256,
            "segments": [segment.to_mapping() for segment in self.segments],
        }

    def to_mapping(self) -> dict[str, object]:
        return {
            **self._unsigned_mapping(),
            "provider_request_sha256": self.provider_request_sha256,
        }


@dataclass(frozen=True, slots=True)
class ModelCallObservation:
    """Digest-only facts about one model request and response boundary."""

    request_index: int
    frame_sha256: str
    model_sha256: str | None
    request_sha256: str | None
    response_sha256: str | None
    response_length: int | None
    input_tokens: int | None
    output_tokens: int | None
    status: Literal["completed", "failed", "cancelled", "missing"]
    boundary_observed: bool
    model_call_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _require_index(self.request_index, minimum=1)
        _require_digest(self.frame_sha256)
        _require_optional_digest(self.model_sha256)
        _require_optional_digest(self.request_sha256)
        _require_optional_content(self.response_sha256, self.response_length)
        _require_optional_nonnegative_int(self.input_tokens)
        _require_optional_nonnegative_int(self.output_tokens)
        _require_enum(self.status, _STATUSES)
        _require_bool(self.boundary_observed)
        object.__setattr__(
            self,
            "model_call_sha256",
            _canonical_digest(
                "asterion.pathlight/model-call-observation/v1", self._unsigned_mapping()
            ),
        )

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "request_index": self.request_index,
            "frame_sha256": self.frame_sha256,
            "model_sha256": self.model_sha256,
            "request_sha256": self.request_sha256,
            "response_sha256": self.response_sha256,
            "response_length": self.response_length,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "status": self.status,
            "boundary_observed": self.boundary_observed,
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "model_call_sha256": self.model_call_sha256}


@dataclass(frozen=True, slots=True)
class ToolCallObservation:
    """Digest-only facts about one tool call and its result."""

    call_sha256: str
    tool_sha256: str | None
    arguments_sha256: str | None
    result_sha256: str | None
    result_length: int | None
    status: Literal["completed", "failed", "cancelled", "missing"]
    tool_call_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _require_digest(self.call_sha256)
        _require_optional_digest(self.tool_sha256)
        _require_optional_digest(self.arguments_sha256)
        _require_optional_content(self.result_sha256, self.result_length)
        _require_enum(self.status, _STATUSES)
        object.__setattr__(
            self,
            "tool_call_sha256",
            _canonical_digest(
                "asterion.pathlight/tool-call-observation/v1", self._unsigned_mapping()
            ),
        )

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "call_sha256": self.call_sha256,
            "tool_sha256": self.tool_sha256,
            "arguments_sha256": self.arguments_sha256,
            "result_sha256": self.result_sha256,
            "result_length": self.result_length,
            "status": self.status,
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "tool_call_sha256": self.tool_call_sha256}


@dataclass(frozen=True, slots=True)
class RuntimeObservationBatch:
    """The complete safe observation closure for one already-completed run."""

    run_sha256: str
    frames: tuple[ContextFrameObservation, ...]
    model_calls: tuple[ModelCallObservation, ...]
    provider_requests: tuple[ProviderRequestObservation, ...]
    tools: tuple[ToolCallObservation, ...]
    missing_evidence: tuple[str, ...]
    batch_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _require_digest(self.run_sha256)
        frames = _require_exact_tuple(self.frames)
        model_calls = _require_exact_tuple(self.model_calls)
        provider_requests = _require_exact_tuple(self.provider_requests)
        tools = _require_exact_tuple(self.tools)
        missing_evidence = _require_exact_tuple(self.missing_evidence)
        if any(type(frame) is not ContextFrameObservation for frame in frames):
            _invalid()
        if any(type(call) is not ModelCallObservation for call in model_calls):
            _invalid()
        if any(
            type(request) is not ProviderRequestObservation
            for request in provider_requests
        ):
            _invalid()
        if any(type(tool) is not ToolCallObservation for tool in tools):
            _invalid()
        if any(
            type(item) is not str or item not in _MISSING_EVIDENCE
            for item in missing_evidence
        ):
            _invalid()
        typed_frames = cast(tuple[ContextFrameObservation, ...], frames)
        typed_model_calls = cast(tuple[ModelCallObservation, ...], model_calls)
        typed_provider_requests = cast(
            tuple[ProviderRequestObservation, ...], provider_requests
        )
        typed_tools = cast(tuple[ToolCallObservation, ...], tools)
        typed_missing_evidence = cast(tuple[str, ...], missing_evidence)
        _validate_batch_components(
            typed_frames,
            typed_model_calls,
            typed_provider_requests,
            typed_tools,
            typed_missing_evidence,
        )
        object.__setattr__(self, "frames", typed_frames)
        object.__setattr__(self, "model_calls", typed_model_calls)
        object.__setattr__(self, "provider_requests", typed_provider_requests)
        object.__setattr__(self, "tools", typed_tools)
        object.__setattr__(self, "missing_evidence", typed_missing_evidence)
        object.__setattr__(
            self,
            "batch_sha256",
            _canonical_digest(
                "asterion.pathlight/runtime-observation-batch/v2",
                self._unsigned_mapping(),
            ),
        )

    @classmethod
    def build(
        cls,
        *,
        run_sha256: str,
        frames: tuple[ContextFrameObservation, ...],
        model_calls: tuple[ModelCallObservation, ...],
        tools: tuple[ToolCallObservation, ...],
        provider_requests: tuple[ProviderRequestObservation, ...] = (),
        missing_evidence: tuple[str, ...] = (),
    ) -> RuntimeObservationBatch:
        return cls(
            run_sha256,
            frames,
            model_calls,
            provider_requests,
            tools,
            missing_evidence,
        )

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "schema": RUNTIME_OBSERVATION_SCHEMA,
            "run_sha256": self.run_sha256,
            "frames": [frame.to_mapping() for frame in self.frames],
            "model_calls": [call.to_mapping() for call in self.model_calls],
            "provider_requests": [
                request.to_mapping() for request in self.provider_requests
            ],
            "tools": [tool.to_mapping() for tool in self.tools],
            "missing_evidence": list(self.missing_evidence),
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "batch_sha256": self.batch_sha256}


def _validate_batch_components(
    frames: tuple[ContextFrameObservation, ...],
    model_calls: tuple[ModelCallObservation, ...],
    provider_requests: tuple[ProviderRequestObservation, ...],
    tools: tuple[ToolCallObservation, ...],
    missing_evidence: tuple[str, ...],
) -> None:
    if tuple(frame.frame_index for frame in frames) != tuple(range(1, len(frames) + 1)):
        _invalid()
    if tuple(call.request_index for call in model_calls) != tuple(
        range(1, len(model_calls) + 1)
    ):
        _invalid()
    if provider_requests:
        if len(provider_requests) != len(model_calls) or tuple(
            request.request_index for request in provider_requests
        ) != tuple(range(1, len(provider_requests) + 1)):
            _invalid()
    tool_calls = tuple(tool.call_sha256 for tool in tools)
    if tool_calls != tuple(sorted(tool_calls)) or len(tool_calls) != len(
        set(tool_calls)
    ):
        _invalid()
    if missing_evidence != tuple(sorted(missing_evidence)) or len(
        missing_evidence
    ) != len(set(missing_evidence)):
        _invalid()
    frame_ids = tuple(frame.frame_sha256 for frame in frames)
    if len(frame_ids) != len(set(frame_ids)):
        _invalid()
    if any(call.frame_sha256 not in frame_ids for call in model_calls):
        _invalid()
    if provider_requests:
        frames_by_sha256 = {frame.frame_sha256: frame for frame in frames}
        for request, call in zip(provider_requests, model_calls, strict=True):
            if (
                request.request_index != call.request_index
                or call.request_sha256 is None
                or call.boundary_observed
                or not hmac.compare_digest(request.payload_sha256, call.request_sha256)
                or request.segments != frames_by_sha256[call.frame_sha256].segments
            ):
                _invalid()
    tools_by_call = {tool.call_sha256: tool for tool in tools}
    for frame in frames:
        for segment in frame.segments:
            if segment.source_call_sha256 is None:
                continue
            tool = tools_by_call.get(segment.source_call_sha256)
            if tool is None or (
                segment.content_sha256,
                segment.content_length,
            ) != (tool.result_sha256, tool.result_length):
                _invalid()
            if tool.result_sha256 is None and not segment.missing_evidence:
                _invalid()
    required_evidence = _required_missing_evidence(frames, model_calls, tools)
    if not required_evidence.issubset(missing_evidence):
        _invalid()


def _required_missing_evidence(
    frames: tuple[ContextFrameObservation, ...],
    model_calls: tuple[ModelCallObservation, ...],
    tools: tuple[ToolCallObservation, ...],
) -> frozenset[str]:
    required: set[str] = set()
    if not frames:
        required.add("context-frame")
    if not model_calls:
        required.update(("model-request", "model-request-boundary"))
    if any(segment.missing_evidence for frame in frames for segment in frame.segments):
        required.add("context-segment")
    for call in model_calls:
        if call.model_sha256 is None:
            required.add("model-identity")
        if call.request_sha256 is None:
            required.add("model-request")
        if not call.boundary_observed:
            required.add("model-request-boundary")
        if call.response_sha256 is None:
            required.add("model-response")
        if call.input_tokens is None or call.output_tokens is None:
            required.add("token-usage")
    for tool in tools:
        if tool.status == "missing":
            required.add("tool-boundary")
        if tool.tool_sha256 is None:
            required.add("tool-identity")
        if tool.arguments_sha256 is None:
            required.add("tool-arguments")
        if tool.result_sha256 is None:
            required.add("tool-result")
    return frozenset(required)


def _segment_from_mapping(value: object) -> ContextSegmentSummary:
    raw = _copy_exact_dict(value, _SEGMENT_FIELDS)
    segment = ContextSegmentSummary(
        segment_index=raw["segment_index"],  # type: ignore[arg-type]
        role=raw["role"],  # type: ignore[arg-type]
        structure_kind=raw["structure_kind"],  # type: ignore[arg-type]
        content_sha256=raw["content_sha256"],  # type: ignore[arg-type]
        content_length=raw["content_length"],  # type: ignore[arg-type]
        source_call_sha256=raw["source_call_sha256"],  # type: ignore[arg-type]
        missing_evidence=raw["missing_evidence"],  # type: ignore[arg-type]
    )
    supplied = _require_digest(raw["segment_sha256"])
    if not hmac.compare_digest(supplied, segment.segment_sha256):
        _invalid()
    return segment


def _frame_from_mapping(value: object) -> ContextFrameObservation:
    raw = _copy_exact_dict(value, _FRAME_FIELDS)
    segments = tuple(
        _segment_from_mapping(item) for item in _copy_exact_list(raw["segments"])
    )
    frame = ContextFrameObservation(
        frame_index=raw["frame_index"],  # type: ignore[arg-type]
        segments=segments,
    )
    supplied = _require_digest(raw["frame_sha256"])
    if not hmac.compare_digest(supplied, frame.frame_sha256):
        _invalid()
    return frame


def _provider_request_from_mapping(value: object) -> ProviderRequestObservation:
    raw = _copy_exact_dict(value, _PROVIDER_REQUEST_FIELDS)
    request = ProviderRequestObservation.build(
        request_index=raw["request_index"],
        payload_sha256=raw["payload_sha256"],
        payload_bytes=raw["payload_bytes"],
        shape_sha256=raw["shape_sha256"],
        field_count=raw["field_count"],
        leaf_count=raw["leaf_count"],
        text_characters=raw["text_characters"],
        private_reference_sha256=raw["private_reference_sha256"],
        segments=tuple(
            _segment_from_mapping(item) for item in _copy_exact_list(raw["segments"])
        ),
    )
    supplied = _require_digest(raw["provider_request_sha256"])
    if not hmac.compare_digest(supplied, request.provider_request_sha256):
        _invalid()
    return request


def _model_call_from_mapping(value: object) -> ModelCallObservation:
    raw = _copy_exact_dict(value, _MODEL_CALL_FIELDS)
    call = ModelCallObservation(
        request_index=raw["request_index"],  # type: ignore[arg-type]
        frame_sha256=raw["frame_sha256"],  # type: ignore[arg-type]
        model_sha256=raw["model_sha256"],  # type: ignore[arg-type]
        request_sha256=raw["request_sha256"],  # type: ignore[arg-type]
        response_sha256=raw["response_sha256"],  # type: ignore[arg-type]
        response_length=raw["response_length"],  # type: ignore[arg-type]
        input_tokens=raw["input_tokens"],  # type: ignore[arg-type]
        output_tokens=raw["output_tokens"],  # type: ignore[arg-type]
        status=raw["status"],  # type: ignore[arg-type]
        boundary_observed=raw["boundary_observed"],  # type: ignore[arg-type]
    )
    supplied = _require_digest(raw["model_call_sha256"])
    if not hmac.compare_digest(supplied, call.model_call_sha256):
        _invalid()
    return call


def _tool_call_from_mapping(value: object) -> ToolCallObservation:
    raw = _copy_exact_dict(value, _TOOL_CALL_FIELDS)
    tool = ToolCallObservation(
        call_sha256=raw["call_sha256"],  # type: ignore[arg-type]
        tool_sha256=raw["tool_sha256"],  # type: ignore[arg-type]
        arguments_sha256=raw["arguments_sha256"],  # type: ignore[arg-type]
        result_sha256=raw["result_sha256"],  # type: ignore[arg-type]
        result_length=raw["result_length"],  # type: ignore[arg-type]
        status=raw["status"],  # type: ignore[arg-type]
    )
    supplied = _require_digest(raw["tool_call_sha256"])
    if not hmac.compare_digest(supplied, tool.tool_call_sha256):
        _invalid()
    return tool


def validate_runtime_observation_batch(
    mapping: Mapping[str, object],
) -> RuntimeObservationBatch:
    """Return a verified, immutable runtime observation batch.

    Only exact built-in JSON containers are accepted.  Each is copied before a
    nested constructor sees it, preventing mutable or hostile mappings from
    changing the validated closure during parsing.
    """

    try:
        raw = _copy_exact_dict(mapping, _BATCH_FIELDS)
        if (
            type(raw["schema"]) is not str
            or raw["schema"] != RUNTIME_OBSERVATION_SCHEMA
        ):
            _invalid()
        frames = tuple(
            _frame_from_mapping(item) for item in _copy_exact_list(raw["frames"])
        )
        model_calls = tuple(
            _model_call_from_mapping(item)
            for item in _copy_exact_list(raw["model_calls"])
        )
        provider_requests = tuple(
            _provider_request_from_mapping(item)
            for item in _copy_exact_list(raw["provider_requests"])
        )
        tools = tuple(
            _tool_call_from_mapping(item) for item in _copy_exact_list(raw["tools"])
        )
        missing_evidence = tuple(_copy_exact_list(raw["missing_evidence"]))
        batch = RuntimeObservationBatch.build(
            run_sha256=raw["run_sha256"],  # type: ignore[arg-type]
            frames=frames,
            model_calls=model_calls,
            provider_requests=provider_requests,
            tools=tools,
            missing_evidence=missing_evidence,  # type: ignore[arg-type]
        )
        supplied = _require_digest(raw["batch_sha256"])
        if not hmac.compare_digest(supplied, batch.batch_sha256):
            _invalid()
        return batch
    except Exception:
        _invalid()


@runtime_checkable
class RuntimeObservationSource(Protocol):
    """An optional post-run source for one safe runtime observation batch."""

    def pathlight_runtime_observation(self, run_id: str) -> Mapping[str, object] | None:
        """Return a safe observation mapping for a completed run, if available."""
