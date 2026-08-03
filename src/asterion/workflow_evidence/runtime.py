"""Observe validated runtime calls without retaining their private content."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable

from asterion.pathlight import (
    MemoryPathlightRecorder,
    ModelCallObservation,
    PathlightRecorder,
    RuntimeObservationBatch,
    TraceEvent,
    validate_runtime_observation_batch,
)

from asterion.runtime.host import (
    AgentRuntimeClient,
    CancellationSignal,
    RunEvent,
    RunRequest,
    RuntimeManifest,
)

from asterion.workflow_evidence.collector import (
    WorkflowEvidenceError,
    collect_workflow_evidence,
)


@dataclass(frozen=True, slots=True)
class CompletedRuntimeEvidence:
    """One safe workflow record and trace projected after runtime completion."""

    record: Mapping[str, object]
    trace: Mapping[str, object]


def project_completed_runtime_evidence(
    *,
    request: RunRequest,
    event_observations: Sequence[
        tuple[Mapping[str, object], int | None, int | None]
    ],
    native_observation: RuntimeObservationBatch | None,
    runtime_id: str,
    trace_id: str,
    invocation_started_ns: int | None,
    invocation_ended_ns: int | None,
) -> CompletedRuntimeEvidence:
    """Project an already completed runtime stream without retaining content."""

    try:
        request.to_mapping()
        if type(runtime_id) is not str or not runtime_id:
            raise ValueError
        observations = _completed_event_observations(
            event_observations,
            invocation_started_ns=invocation_started_ns,
            invocation_ended_ns=invocation_ended_ns,
        )
        events = [mapping for mapping, _started, _ended in observations]
        evidence = collect_workflow_evidence(
            events,
            input_digest=hashlib.sha256(request.input_text.encode("utf-8")).hexdigest(),
        )
        checked_native = _validated_supplied_runtime_observation(
            native_observation,
            request,
            events,
            evidence=evidence,
        )
        recorder = MemoryPathlightRecorder(trace_id)
        _RuntimePathlightProjection(recorder).project(
            request,
            observations,
            evidence=evidence,
            native_observation=checked_native,
            runtime_id=runtime_id,
            invocation_started_ns=invocation_started_ns,
            invocation_ended_ns=invocation_ended_ns,
        )
        trace = recorder.snapshot()
        if trace is None:
            raise ValueError
        return CompletedRuntimeEvidence(
            record=_freeze_completed_mapping(evidence),
            trace=_freeze_completed_mapping(trace),
        )
    except WorkflowEvidenceError:
        raise
    except Exception:
        raise WorkflowEvidenceError("completed runtime evidence is invalid") from None


def _freeze_completed_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(
        {key: _freeze_completed_value(item) for key, item in value.items()}
    )


def _freeze_completed_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_completed_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_completed_value(item) for item in value)
    return value


def _completed_event_observations(
    values: Sequence[tuple[Mapping[str, object], int | None, int | None]],
    *,
    invocation_started_ns: int | None,
    invocation_ended_ns: int | None,
) -> list[tuple[Mapping[str, object], int | None, int | None]]:
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError
    if type(invocation_started_ns) is not int or type(invocation_ended_ns) is not int:
        raise ValueError
    cursor = invocation_started_ns
    observations: list[tuple[Mapping[str, object], int | None, int | None]] = []
    for value in values:
        if not isinstance(value, tuple) or len(value) != 3:
            raise ValueError
        mapping, started_ns, ended_ns = value
        if (
            not isinstance(mapping, Mapping)
            or type(started_ns) is not int
            or type(ended_ns) is not int
            or started_ns <= cursor
            or ended_ns <= started_ns
        ):
            raise ValueError
        observations.append((dict(mapping), started_ns, ended_ns))
        cursor = ended_ns
    if invocation_ended_ns <= cursor:
        raise ValueError
    return observations


def _validated_supplied_runtime_observation(
    value: RuntimeObservationBatch | None,
    request: RunRequest,
    events: list[Mapping[str, object]],
    *,
    evidence: Mapping[str, object],
) -> RuntimeObservationBatch | None:
    if value is None:
        return None
    try:
        observation = validate_runtime_observation_batch(value.to_mapping())
        if evidence.get("run_id") != request.run_id:
            return None
        if any(event.get("run_id") != request.run_id for event in events):
            return None
        if not hmac.compare_digest(
            observation.run_sha256, _text_digest(request.run_id)
        ):
            return None
        if not _native_tools_match_stream(observation, events):
            return None
        if not observation.frames or not observation.model_calls:
            return None
        return observation
    except Exception:
        return None


class ObservedRuntimeClient:
    """Transparent runtime proxy that retains only safe observation records."""

    def __init__(
        self,
        runtime: AgentRuntimeClient,
        *,
        pathlight: PathlightRecorder | None = None,
        monotonic_ns: Callable[[], int] | None = None,
    ) -> None:
        self._runtime = runtime
        self._pathlight = pathlight
        self._monotonic_ns = (
            monotonic_ns if monotonic_ns is not None else time.monotonic_ns
        )
        self._last_timestamp_ns: int | None = None
        self._timestamps_monotonic = True
        self._records: list[Mapping[str, object]] = []
        self._failed_attempts: list[Mapping[str, object]] = []

    @property
    def manifest(self) -> RuntimeManifest:
        """Expose the wrapped runtime's exact manifest unchanged."""

        return self._runtime.manifest

    @property
    def records(self) -> tuple[Mapping[str, object], ...]:
        """Return immutable successful workflow evidence in call order."""

        return tuple(self._records)

    @property
    def failed_attempts(self) -> tuple[Mapping[str, object], ...]:
        """Return fixed-class observations for calls without a trusted graph."""

        return tuple(self._failed_attempts)

    async def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AsyncIterator[RunEvent]:
        """Yield the wrapped stream unchanged, then record its safe projection."""

        events: list[Mapping[str, object]] = []
        observations: list[tuple[Mapping[str, object], int | None, int | None]] = []
        input_digest = hashlib.sha256(request.input_text.encode("utf-8")).hexdigest()
        invocation_started_ns = self._capture_timestamp()
        try:
            async for event in self._runtime.run(request, signal=signal):
                observed_started_ns = self._capture_timestamp()
                event_mapping = event.to_mapping()
                observed_ended_ns = self._capture_timestamp()
                events.append(event_mapping)
                observations.append(
                    (event_mapping, observed_started_ns, observed_ended_ns)
                )
                yield event
            invocation_ended_ns = self._capture_timestamp()
            evidence = collect_workflow_evidence(events, input_digest=input_digest)
            native_observation = (
                _validated_runtime_observation(
                    self._runtime,
                    request,
                    events,
                    evidence=evidence,
                )
                if self._timestamps_monotonic
                else None
            )
            try:
                _RuntimePathlightProjection(self._pathlight).project(
                    request,
                    observations,
                    evidence=evidence,
                    native_observation=native_observation,
                    runtime_id=self.manifest.runtime_id,
                    invocation_started_ns=invocation_started_ns,
                    invocation_ended_ns=invocation_ended_ns,
                )
            except BaseException as error:
                _reraise_process_control(error)
                if native_observation is not None:
                    try:
                        _RuntimePathlightProjection(self._pathlight).project(
                            request,
                            observations,
                            evidence=evidence,
                            native_observation=None,
                            runtime_id=self.manifest.runtime_id,
                            invocation_started_ns=invocation_started_ns,
                            invocation_ended_ns=invocation_ended_ns,
                        )
                    except BaseException as fallback_error:
                        _reraise_process_control(fallback_error)
                        pass
        except BaseException:
            self._failed_attempts.append(
                MappingProxyType(
                    {
                        "schema": "asterion.workflow-observation/v1",
                        "run_id": request.run_id,
                        "input_digest": input_digest,
                        "status": "cancelled"
                        if signal is not None and signal.cancelled
                        else "failed",
                        "failure_class": "runtime-cancelled"
                        if signal is not None and signal.cancelled
                        else "runtime-invocation-failed",
                    }
                )
            )
            raise
        self._records.append(MappingProxyType(evidence))

    def _capture_timestamp(self) -> int | None:
        if self._pathlight is None:
            return None
        try:
            value = self._monotonic_ns()
        except Exception:
            self._pathlight = None
            return None
        if type(value) is not int or value <= 0:
            self._pathlight = None
            return None
        if self._last_timestamp_ns is not None and value <= self._last_timestamp_ns:
            if value < self._last_timestamp_ns:
                self._timestamps_monotonic = False
            value = self._last_timestamp_ns + 1
        self._last_timestamp_ns = value
        return value


class _RuntimePathlightProjection:
    """Project one validated stream into a standalone, content-safe trace."""

    def __init__(self, recorder: PathlightRecorder | None) -> None:
        self._recorder = recorder
        self._trace_id: str | None = None
        self._sequence = 0
        self._parent_span_id: str | None = None
        if recorder is not None:
            try:
                self._trace_id = recorder.trace_id
                if self._trace_id is not None:
                    self._sequence = _recorder_sequence(recorder) - 1
                    self._parent_span_id = _recorder_active_span(recorder)
            except Exception:
                self._disable()
        self._root_span_id: str | None = None
        self._context_span_id: str | None = None
        self._tool_spans: dict[str, tuple[str, str | None]] = {}
        self._tool_component_context_span_id: str | None = None
        self._completed_tool_span_ids: list[str] = []
        self._native_tool_span_ids: dict[str, str] = {}
        self._native_model_span_ids: dict[int, str] = {}
        self._started_ns: dict[str, int] = {}
        self._events: list[TraceEvent] = []
        self._input_tokens = 0
        self._output_tokens = 0
        self._batch_missing_evidence = False

    def start(
        self,
        request: RunRequest,
        *,
        runtime_id: str,
        native_observation: RuntimeObservationBatch | None,
        timestamp_ns: int | None,
    ) -> None:
        """Start with the request's digest and length, never the request itself."""

        self._root_span_id = self._start(
            "runtime",
            self._parent_span_id,
            attributes={
                "run_sha256": _text_digest(request.run_id),
                "runtime_sha256": _text_digest(runtime_id),
                **(
                    {"missing_evidence": True}
                    if native_observation is not None
                    and native_observation.missing_evidence
                    else {}
                ),
            },
            timestamp_ns=timestamp_ns,
        )
        if native_observation is None:
            self._context_span_id = self._start_context(
                {
                    "content_sha256": _text_digest(request.input_text),
                    "content_length": len(request.input_text.encode("utf-8")),
                    # Runtime v1 has no model-request/model-response boundary.
                    "missing_evidence": True,
                },
                timestamp_ns=timestamp_ns,
            )

    def project(
        self,
        request: RunRequest,
        observations: list[tuple[Mapping[str, object], int | None, int | None]],
        *,
        evidence: Mapping[str, object],
        native_observation: RuntimeObservationBatch | None,
        runtime_id: str,
        invocation_started_ns: int | None,
        invocation_ended_ns: int | None,
    ) -> None:
        """Record spans only after the complete stream has been validated."""

        usage = evidence.get("usage")
        if isinstance(usage, Mapping):
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            if type(input_tokens) is int and input_tokens >= 0:
                self._input_tokens = input_tokens
            if type(output_tokens) is int and output_tokens >= 0:
                self._output_tokens = output_tokens
        self.start(
            request,
            runtime_id=runtime_id,
            native_observation=native_observation,
            timestamp_ns=invocation_started_ns,
        )
        if native_observation is not None:
            self._batch_missing_evidence = bool(native_observation.missing_evidence)
            self._project_native(native_observation, observations)
        for event, observed_started_ns, observed_ended_ns in observations:
            payload = event["payload"]
            assert isinstance(payload, Mapping)
            event_type = event["type"]
            if event_type == "tool.call":
                if native_observation is not None:
                    continue
                self._project_tool_call(
                    payload,
                    native_observation=native_observation,
                    timestamp_ns=observed_started_ns,
                )
            elif event_type == "tool.result":
                if native_observation is not None:
                    continue
                self._project_tool_result(payload, timestamp_ns=observed_ended_ns)
            elif event_type == "artifact.created":
                self._project_artifact(
                    payload,
                    started_ns=observed_started_ns,
                    ended_ns=observed_ended_ns,
                )
            elif event_type == "run.completed":
                self.complete(
                    str(payload["status"]),
                    context_ended_ns=observed_started_ns,
                    runtime_ended_ns=invocation_ended_ns,
                )
            elif event_type == "run.failed":
                self._close_context(timestamp_ns=observed_started_ns)
                self._terminal(
                    self._root_span_id,
                    "failed",
                    "runtime",
                    attributes={
                        "failure_class": "unknown",
                        "input_tokens": self._input_tokens,
                        "output_tokens": self._output_tokens,
                    },
                    timestamp_ns=invocation_ended_ns,
                )
        self._publish()

    def _project_native(
        self,
        observation: RuntimeObservationBatch,
        observations: list[tuple[Mapping[str, object], int | None, int | None]],
    ) -> None:
        self._context_span_id = None
        self._native_tool_span_ids = {
            tool.call_sha256: _reserved_span_id(
                self._require_trace_id(),
                kind="tool-call",
                observation_sha256=tool.tool_call_sha256,
                ordinal=index,
            )
            for index, tool in enumerate(observation.tools, start=1)
        }
        self._native_model_span_ids = {
            call.request_index: _reserved_span_id(
                self._require_trace_id(),
                kind="model-call",
                observation_sha256=call.model_call_sha256,
                ordinal=call.request_index,
            )
            for call in observation.model_calls
        }
        tool_components = _tool_projection_components(observations)
        component_by_call = {
            call_sha256: component_index
            for component_index, component in enumerate(tool_components)
            for call_sha256 in component
        }
        component_cursor = 0
        frame_span_ids: dict[str, str] = {}
        for frame in observation.frames:
            source_calls = tuple(
                dict.fromkeys(
                    segment.source_call_sha256
                    for segment in frame.segments
                    if segment.source_call_sha256 is not None
                )
            )
            required_component_indexes = tuple(
                component_by_call[call_sha256]
                for call_sha256 in source_calls
                if component_by_call[call_sha256] >= component_cursor
            )
            if required_component_indexes:
                required_cursor = max(required_component_indexes) + 1
                while component_cursor < required_cursor:
                    self._project_native_tools(
                        observation,
                        tool_components[component_cursor],
                        observations,
                    )
                    component_cursor += 1
            frame_calls = tuple(
                call
                for call in observation.model_calls
                if call.frame_sha256 == frame.frame_sha256
            )
            frame_span_id = self._start_context(
                {
                    "frame_index": frame.frame_index,
                    "segment_count": len(frame.segments),
                    "observation_sha256": frame.frame_sha256,
                    "missing_evidence": (
                        "context-frame" in observation.missing_evidence
                        or "context-segment" in observation.missing_evidence
                        or any(segment.missing_evidence for segment in frame.segments)
                    ),
                },
                links=self._links_to(
                    (
                        self._native_model_span_ids[call.request_index]
                        for call in frame_calls
                    ),
                    "consumed-by",
                ),
                timestamp_ns=0,
            )
            if frame_span_id is None:
                raise ValueError("Pathlight native frame projection failed")
            frame_span_ids[frame.frame_sha256] = frame_span_id
            for segment in frame.segments:
                attributes: dict[str, str | int | bool] = {
                    "segment_index": segment.segment_index,
                    "segment_role": segment.role,
                    "structure_kind": segment.structure_kind,
                    "observation_sha256": segment.segment_sha256,
                    "missing_evidence": segment.missing_evidence,
                }
                if segment.content_sha256 is not None:
                    attributes["content_sha256"] = segment.content_sha256
                    assert segment.content_length is not None
                    attributes["content_length"] = segment.content_length
                links: tuple[Mapping[str, str], ...] = ()
                if segment.source_call_sha256 is not None:
                    attributes["source_call_sha256"] = segment.source_call_sha256
                    links = self._link_to(
                        self._native_tool_span_ids[segment.source_call_sha256],
                        "produced-by",
                    )
                segment_span_id = self._start(
                    "context-frame",
                    frame_span_id,
                    attributes=attributes,
                    links=links,
                    timestamp_ns=0,
                )
                self._terminal(
                    segment_span_id,
                    "completed",
                    "context-frame",
                    timestamp_ns=0,
                )
            self._terminal(
                frame_span_id,
                "completed",
                "context-frame",
                timestamp_ns=0,
            )
            for call in frame_calls:
                self._project_native_model_call(
                    call,
                    frame_span_ids[call.frame_sha256],
                    observation,
                )

        while component_cursor < len(tool_components):
            self._project_native_tools(
                observation,
                tool_components[component_cursor],
                observations,
            )
            component_cursor += 1

    def _project_native_model_call(
        self,
        call: ModelCallObservation,
        frame_span_id: str,
        observation: RuntimeObservationBatch,
    ) -> None:
        provider_request = next(
            (
                request
                for request in observation.provider_requests
                if request.request_index == call.request_index
            ),
            None,
        )
        attributes: dict[str, str | int | bool] = {
            "request_index": call.request_index,
            "boundary_observed": call.boundary_observed,
            "observation_sha256": call.model_call_sha256,
            "missing_evidence": (
                not call.boundary_observed
                or call.status == "missing"
                or call.model_sha256 is None
                or call.request_sha256 is None
                or call.response_sha256 is None
                or call.input_tokens is None
                or call.output_tokens is None
                or any(
                    label
                    in {
                        "model-identity",
                        "model-request",
                        "model-request-boundary",
                        "model-response",
                        "token-usage",
                    }
                    for label in observation.missing_evidence
                )
            ),
        }
        if call.model_sha256 is not None:
            attributes["model_id"] = call.model_sha256
        if call.request_sha256 is not None:
            attributes["request_sha256"] = call.request_sha256
        if provider_request is not None:
            attributes.update(
                {
                    "request_shape_sha256": provider_request.shape_sha256,
                    "payload_bytes": provider_request.payload_bytes,
                    "field_count": provider_request.field_count,
                    "leaf_count": provider_request.leaf_count,
                    "text_characters": provider_request.text_characters,
                    "private_reference_sha256": (
                        provider_request.private_reference_sha256
                    ),
                }
            )
        if call.response_sha256 is not None:
            attributes["response_sha256"] = call.response_sha256
            assert call.response_length is not None
            attributes["response_length"] = call.response_length
        if call.input_tokens is not None:
            attributes["input_tokens"] = call.input_tokens
        if call.output_tokens is not None:
            attributes["output_tokens"] = call.output_tokens
        span_id = self._start(
            "model-call",
            self._root_span_id,
            attributes=attributes,
            links=self._link_to(frame_span_id, "derived-from"),
            timestamp_ns=0,
            span_id=self._native_model_span_ids[call.request_index],
        )
        self._terminal(
            span_id,
            _trace_status(call.status),
            "model-call",
            attributes={"missing_evidence": attributes["missing_evidence"]},
            timestamp_ns=0,
        )

    def _project_native_tools(
        self,
        observation: RuntimeObservationBatch,
        call_sha256s: tuple[str, ...],
        observations: list[tuple[Mapping[str, object], int | None, int | None]],
    ) -> None:
        selected = set(call_sha256s)
        if not selected:
            return
        started: set[str] = set()
        completed: set[str] = set()
        for event, observed_started_ns, observed_ended_ns in observations:
            event_type = event["type"]
            if event_type not in {"tool.call", "tool.result"}:
                continue
            payload = event["payload"]
            if not isinstance(payload, Mapping):
                raise ValueError("Pathlight tool projection payload is invalid")
            call_id = payload["call_id"]
            if type(call_id) is not str:
                raise ValueError("Pathlight tool projection identity is invalid")
            call_sha256 = _text_digest(call_id)
            if call_sha256 not in selected:
                continue
            if event_type == "tool.call":
                self._project_tool_call(
                    payload,
                    native_observation=observation,
                    timestamp_ns=observed_started_ns,
                )
                started.add(call_sha256)
            else:
                self._project_tool_result(
                    payload,
                    timestamp_ns=observed_ended_ns,
                )
                completed.add(call_sha256)
        if started != selected or completed != selected:
            raise ValueError("Pathlight tool projection is incomplete")

    def complete(
        self,
        status: str,
        *,
        context_ended_ns: int | None,
        runtime_ended_ns: int | None,
    ) -> None:
        self._close_context(timestamp_ns=context_ended_ns)
        self._terminal(
            self._root_span_id,
            "cancelled" if status == "cancelled" else "completed",
            "runtime",
            attributes={
                **({"failure_class": "cancelled"} if status == "cancelled" else {}),
                "input_tokens": self._input_tokens,
                "output_tokens": self._output_tokens,
                **({"missing_evidence": True} if self._batch_missing_evidence else {}),
            },
            timestamp_ns=runtime_ended_ns,
        )

    def _project_tool_call(
        self,
        payload: Mapping[str, object],
        *,
        native_observation: RuntimeObservationBatch | None,
        timestamp_ns: int | None,
    ) -> None:
        if native_observation is None:
            if not self._tool_spans:
                self._tool_component_context_span_id = self._context_span_id
                self._close_context(timestamp_ns=timestamp_ns)
            context_span_id = self._tool_component_context_span_id
        else:
            context_span_id = self._context_span_id
        call_id = str(payload["call_id"])
        native_tool = (
            next(
                tool
                for tool in native_observation.tools
                if tool.call_sha256 == _text_digest(call_id)
            )
            if native_observation is not None
            else None
        )
        arguments = (
            {"content_sha256": native_tool.arguments_sha256}
            if native_tool is not None and native_tool.arguments_sha256 is not None
            else _content_summary(payload["arguments"])
        )
        attributes: dict[str, str | int | bool] = {
            "call_id": _text_digest(call_id),
            "tool_id": (
                native_tool.tool_sha256
                if native_tool is not None and native_tool.tool_sha256 is not None
                else _text_digest(str(payload["name"]))
            ),
        }
        if native_tool is not None:
            attributes["observation_sha256"] = native_tool.tool_call_sha256
        attributes.update(arguments)
        span_id = self._start(
            "tool-call",
            self._root_span_id,
            attributes=attributes,
            timestamp_ns=timestamp_ns,
            span_id=(
                self._native_tool_span_ids[native_tool.call_sha256]
                if native_tool is not None
                else None
            ),
        )
        if span_id is not None:
            self._tool_spans[call_id] = (span_id, context_span_id)

    def _project_tool_result(
        self, payload: Mapping[str, object], *, timestamp_ns: int | None
    ) -> None:
        call_id = str(payload["call_id"])
        span = self._tool_spans.pop(call_id, None)
        span_id, context_span_id = span if span is not None else (None, None)
        summary = _content_summary(payload["output"])
        native_call_sha256 = _text_digest(call_id)
        native_span_id = self._native_tool_span_ids.get(native_call_sha256)
        if native_span_id is not None:
            native_summary = _native_content_summary(payload["output"])
            if native_summary[0] is not None:
                summary = {
                    "content_sha256": native_summary[0],
                    "content_length": native_summary[1],
                }
        summary["is_error"] = bool(payload["is_error"])
        self._terminal(
            span_id,
            "failed" if payload["is_error"] else "completed",
            "tool-call",
            attributes=summary,
            links=self._link_to(context_span_id, "derived-from"),
            timestamp_ns=timestamp_ns,
        )
        if span_id is not None and native_span_id is None:
            self._completed_tool_span_ids.append(span_id)
            if not self._tool_spans:
                self._context_span_id = self._start_context(
                    {"missing_evidence": True},
                    links=self._links_to(
                        self._completed_tool_span_ids,
                        "derived-from",
                    ),
                    timestamp_ns=timestamp_ns,
                )
                self._completed_tool_span_ids.clear()
                self._tool_component_context_span_id = None

    def _project_artifact(
        self,
        payload: Mapping[str, object],
        *,
        started_ns: int | None,
        ended_ns: int | None,
    ) -> None:
        artifact = payload.get("artifact")
        if not isinstance(artifact, Mapping):
            return
        artifact_id = artifact.get("artifact_id")
        media_type = artifact.get("media_type")
        if type(artifact_id) is not str or type(media_type) is not str:
            return
        attributes: dict[str, str | int | bool] = {
            "artifact_sha256": _canonical_digest(
                {"artifact_id": artifact_id, "media_type": media_type}
            )
        }
        content_sha256 = artifact.get("sha256")
        if type(content_sha256) is str:
            attributes["content_sha256"] = content_sha256
        span_id = self._start(
            "artifact",
            self._root_span_id,
            attributes=attributes,
            timestamp_ns=started_ns,
        )
        self._terminal(
            span_id,
            "completed",
            "artifact",
            timestamp_ns=ended_ns,
        )

    def _start_context(
        self,
        attributes: Mapping[str, str | int | bool],
        *,
        links: tuple[Mapping[str, str], ...] = (),
        timestamp_ns: int | None,
    ) -> str | None:
        return self._start(
            "context-frame",
            self._root_span_id,
            attributes=attributes,
            links=links,
            timestamp_ns=timestamp_ns,
        )

    def _close_context(self, *, timestamp_ns: int | None) -> None:
        self._terminal(
            self._context_span_id,
            "completed",
            "context-frame",
            timestamp_ns=timestamp_ns,
        )
        self._context_span_id = None

    def _start(
        self,
        kind: str,
        parent_span_id: str | None,
        *,
        attributes: Mapping[str, str | int | bool] | None = None,
        links: tuple[Mapping[str, str], ...] = (),
        timestamp_ns: int | None,
        span_id: str | None = None,
    ) -> str | None:
        if self._trace_id is None or timestamp_ns is None:
            return None
        sequence = self._sequence + 1
        effective_attributes: dict[str, str | int | bool] = dict(attributes or {})
        if timestamp_ns == 0:
            effective_attributes["missing_evidence"] = True
        span_id = (
            _event_span_id(
                self._trace_id,
                sequence=sequence,
                kind=kind,
                parent_span_id=parent_span_id,
                attributes=effective_attributes,
            )
            if span_id is None
            else span_id
        )
        event = TraceEvent.start(
            self._trace_id,
            span_id,
            parent_span_id,
            sequence,
            kind,
            attributes=effective_attributes,
            links=links,
            timestamp_ns=timestamp_ns,
        )
        self._sequence = sequence
        self._events.append(event)
        if self._trace_id is not None:
            self._started_ns[span_id] = timestamp_ns
        return span_id

    def _terminal(
        self,
        span_id: str | None,
        status: str,
        kind: str,
        *,
        attributes: Mapping[str, str | int | bool] | None = None,
        links: tuple[Mapping[str, str], ...] = (),
        timestamp_ns: int | None,
    ) -> None:
        if self._trace_id is None or span_id is None or timestamp_ns is None:
            return
        started_ns = self._started_ns.get(span_id)
        if started_ns is None or timestamp_ns < started_ns:
            raise ValueError("Pathlight span timestamps are invalid")
        terminal_attributes: dict[str, str | int | bool] = dict(attributes or {})
        if started_ns == 0 or timestamp_ns == 0:
            terminal_attributes["missing_evidence"] = True
        else:
            terminal_attributes["duration_ns"] = timestamp_ns - started_ns
        sequence = self._sequence + 1
        event = TraceEvent.terminal(
            self._trace_id,
            span_id,
            sequence,
            status,
            kind=kind,
            attributes=terminal_attributes,
            links=links,
            timestamp_ns=timestamp_ns,
        )
        self._sequence = sequence
        self._events.append(event)
        self._started_ns.pop(span_id, None)

    def _publish(self) -> None:
        if self._recorder is None or self._trace_id is None:
            return
        self._recorder.record_many(tuple(self._events))

    def _disable(self) -> None:
        self._recorder = None
        self._trace_id = None
        self._events.clear()

    def _link_to(
        self, span_id: str | None, relation: str
    ) -> tuple[Mapping[str, str], ...]:
        if self._trace_id is None or span_id is None:
            return ()
        return (
            {
                "relation": relation,
                "trace_id": self._trace_id,
                "span_id": span_id,
            },
        )

    def _links_to(
        self,
        span_ids: Iterable[str],
        relation: str,
    ) -> tuple[Mapping[str, str], ...]:
        if self._trace_id is None:
            return ()
        return tuple(
            {
                "relation": relation,
                "trace_id": self._trace_id,
                "span_id": span_id,
            }
            for span_id in sorted(span_ids)
        )

    def _require_trace_id(self) -> str:
        if self._trace_id is None:
            raise ValueError("Pathlight trace identity is unavailable")
        return self._trace_id


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_digest(value: object) -> str:
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _opaque_digest_id(digest: str) -> str:
    return (
        f"{digest[:8]}-{digest[8:12]}-4{digest[13:16]}-8{digest[17:20]}-{digest[20:32]}"
    )


def _event_span_id(
    trace_id: str,
    *,
    sequence: int,
    kind: str,
    parent_span_id: str | None,
    attributes: Mapping[str, str | int | bool],
) -> str:
    return _opaque_digest_id(
        _canonical_digest(
            {
                "domain": "asterion.pathlight/event-span-id/v1",
                "trace_id": trace_id,
                "sequence": sequence,
                "kind": kind,
                "parent_span_id": parent_span_id,
                "attributes": dict(attributes),
            }
        )
    )


def _reserved_span_id(
    trace_id: str,
    *,
    kind: str,
    observation_sha256: str,
    ordinal: int,
) -> str:
    return _opaque_digest_id(
        _canonical_digest(
            {
                "domain": "asterion.pathlight/reserved-span-id/v1",
                "trace_id": trace_id,
                "kind": kind,
                "observation_sha256": observation_sha256,
                "ordinal": ordinal,
            }
        )
    )


def _tool_projection_components(
    observations: list[tuple[Mapping[str, object], int | None, int | None]],
) -> tuple[tuple[str, ...], ...]:
    components: list[tuple[str, ...]] = []
    active: set[str] = set()
    component: list[str] = []
    for event, _observed_started_ns, _observed_ended_ns in observations:
        event_type = event["type"]
        if event_type not in {"tool.call", "tool.result"}:
            continue
        payload = event["payload"]
        if not isinstance(payload, Mapping):
            raise ValueError("Pathlight tool projection payload is invalid")
        call_id = payload["call_id"]
        if type(call_id) is not str:
            raise ValueError("Pathlight tool projection identity is invalid")
        call_sha256 = _text_digest(call_id)
        if event_type == "tool.call":
            if call_sha256 in active:
                raise ValueError("Pathlight tool projection identity is duplicated")
            active.add(call_sha256)
            component.append(call_sha256)
        else:
            if call_sha256 not in active:
                raise ValueError("Pathlight tool projection result is unmatched")
            active.remove(call_sha256)
            if not active:
                components.append(tuple(component))
                component = []
    if active:
        raise ValueError("Pathlight tool projection is incomplete")
    return tuple(components)


def _reraise_process_control(error: BaseException) -> None:
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        raise error


def _recorder_sequence(recorder: PathlightRecorder) -> int:
    sequence = recorder.next_sequence
    if type(sequence) is not int or sequence < 1:
        raise ValueError("Pathlight recorder sequence is invalid")
    return sequence


def _recorder_active_span(recorder: PathlightRecorder) -> str | None:
    span_id = recorder.active_span_id
    if span_id is not None and type(span_id) is not str:
        raise ValueError("Pathlight recorder active span is invalid")
    return span_id


def _content_summary(value: object) -> dict[str, str | int | bool]:
    """Return a canonical digest/length pair, or explicitly missing evidence."""

    try:
        content = json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    except (TypeError, ValueError):
        return {"missing_evidence": True}
    return {
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "content_length": len(content),
    }


def _validated_runtime_observation(
    runtime: AgentRuntimeClient,
    request: RunRequest,
    events: list[Mapping[str, object]],
    *,
    evidence: Mapping[str, object],
) -> RuntimeObservationBatch | None:
    """Read and cross-check the optional post-run native observation."""

    try:
        source = getattr(runtime, "pathlight_runtime_observation", None)
        if not callable(source):
            return None
        mapping = source(request.run_id)
        if mapping is None:
            return None
        if not isinstance(mapping, Mapping):
            return None
        observation = validate_runtime_observation_batch(mapping)
        evidence_run_id = evidence.get("run_id")
        if type(evidence_run_id) is not str or evidence_run_id != request.run_id:
            return None
        if any(event.get("run_id") != request.run_id for event in events):
            return None
        if not hmac.compare_digest(
            observation.run_sha256, _text_digest(request.run_id)
        ):
            return None
        if not _native_tools_match_stream(observation, events):
            return None
        if not observation.frames or not observation.model_calls:
            return None
        return observation
    except BaseException as error:
        _reraise_process_control(error)
        return None


def _native_tools_match_stream(
    observation: RuntimeObservationBatch,
    events: list[Mapping[str, object]],
) -> bool:
    stream_tools: dict[str, dict[str, object]] = {}
    try:
        for event in events:
            payload = event["payload"]
            if not isinstance(payload, Mapping):
                return False
            if event["type"] == "tool.call":
                call_id = payload["call_id"]
                name = payload["name"]
                if type(call_id) is not str or type(name) is not str:
                    return False
                call_sha256 = _text_digest(call_id)
                if call_sha256 in stream_tools:
                    return False
                stream_tools[call_sha256] = {
                    "tool_sha256": _text_digest(name),
                    "arguments_sha256": _native_json_digest(payload["arguments"]),
                    "result_sha256": None,
                    "result_length": None,
                    "status": "missing",
                }
            elif event["type"] == "tool.result":
                call_id = payload["call_id"]
                if type(call_id) is not str:
                    return False
                summary = stream_tools.get(_text_digest(call_id))
                if summary is None or summary["status"] != "missing":
                    return False
                result_sha256, result_length = _native_content_summary(
                    payload["output"]
                )
                summary.update(
                    {
                        "result_sha256": result_sha256,
                        "result_length": result_length,
                        "status": "failed" if payload["is_error"] else "completed",
                    }
                )
    except Exception:
        return False

    native_tools = {tool.call_sha256: tool for tool in observation.tools}
    if set(native_tools) != set(stream_tools):
        return False
    for call_sha256, expected in stream_tools.items():
        tool = native_tools[call_sha256]
        if (
            tool.tool_sha256 != expected["tool_sha256"]
            or tool.arguments_sha256 != expected["arguments_sha256"]
            or tool.result_sha256 != expected["result_sha256"]
            or tool.result_length != expected["result_length"]
            or tool.status != expected["status"]
        ):
            return False
    return True


def _native_json_digest(value: object) -> str | None:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return None
    return _text_digest(rendered)


def _native_content_summary(value: object) -> tuple[str | None, int | None]:
    if value is None:
        return None, None
    if type(value) is str:
        return _text_digest(value), len(value)
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return None, None
    return _text_digest(rendered), len(rendered)


def _trace_status(status: str) -> str:
    return status if status in {"completed", "failed", "cancelled"} else "skipped"
