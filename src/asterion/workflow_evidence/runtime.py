"""Observe validated runtime calls without retaining their private content."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import AsyncIterator, Mapping
from types import MappingProxyType
from typing import Callable
from uuid import uuid4

from asterion.pathlight import PathlightRecorder, TraceEvent

from asterion.runtime.host import (
    AgentRuntimeClient,
    CancellationSignal,
    RunEvent,
    RunRequest,
    RuntimeManifest,
)

from asterion.workflow_evidence.collector import collect_workflow_evidence


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
            try:
                _RuntimePathlightProjection(self._pathlight).project(
                    request,
                    observations,
                    evidence=evidence,
                    runtime_id=self.manifest.runtime_id,
                    invocation_started_ns=invocation_started_ns,
                    invocation_ended_ns=invocation_ended_ns,
                )
            except Exception:
                # Optional observation cannot replace runtime or evidence results.
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
        self._started_ns: dict[str, int] = {}
        self._events: list[TraceEvent] = []
        self._input_tokens = 0
        self._output_tokens = 0

    def start(
        self,
        request: RunRequest,
        *,
        runtime_id: str,
        timestamp_ns: int | None,
    ) -> None:
        """Start with the request's digest and length, never the request itself."""

        self._root_span_id = self._start(
            "runtime",
            self._parent_span_id,
            attributes={
                "run_sha256": _text_digest(request.run_id),
                "runtime_sha256": _text_digest(runtime_id),
            },
            timestamp_ns=timestamp_ns,
        )
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
        observations: list[
            tuple[Mapping[str, object], int | None, int | None]
        ],
        *,
        evidence: Mapping[str, object],
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
            timestamp_ns=invocation_started_ns,
        )
        for event, observed_started_ns, observed_ended_ns in observations:
            payload = event["payload"]
            assert isinstance(payload, Mapping)
            event_type = event["type"]
            if event_type == "tool.call":
                self._project_tool_call(payload, timestamp_ns=observed_started_ns)
            elif event_type == "tool.result":
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
            },
            timestamp_ns=runtime_ended_ns,
        )

    def _project_tool_call(
        self, payload: Mapping[str, object], *, timestamp_ns: int | None
    ) -> None:
        context_span_id = self._context_span_id
        self._close_context(timestamp_ns=timestamp_ns)
        call_id = str(payload["call_id"])
        arguments = _content_summary(payload["arguments"])
        attributes: dict[str, str | int | bool] = {
            "call_id": _text_digest(call_id),
            "tool_id": _text_digest(str(payload["name"])),
        }
        attributes.update(arguments)
        span_id = self._start(
            "tool-call",
            self._root_span_id,
            attributes=attributes,
            timestamp_ns=timestamp_ns,
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
        summary["is_error"] = bool(payload["is_error"])
        self._terminal(
            span_id,
            "failed" if payload["is_error"] else "completed",
            "tool-call",
            attributes=summary,
            links=self._link_to(context_span_id, "derived-from"),
            timestamp_ns=timestamp_ns,
        )
        if span_id is not None:
            self._context_span_id = self._start_context(
                {"missing_evidence": True},
                links=self._link_to(span_id, "derived-from"),
                timestamp_ns=timestamp_ns,
            )

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
    ) -> str | None:
        if self._trace_id is None or timestamp_ns is None:
            return None
        span_id = str(uuid4())
        sequence = self._sequence + 1
        try:
            event = TraceEvent.start(
                self._trace_id,
                span_id,
                parent_span_id,
                sequence,
                kind,
                attributes=attributes,
                links=links,
                timestamp_ns=timestamp_ns,
            )
        except Exception:
            self._disable()
            return None
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
        if started_ns is None or timestamp_ns <= started_ns:
            self._disable()
            return
        terminal_attributes: dict[str, str | int | bool] = dict(attributes or {})
        terminal_attributes["duration_ns"] = timestamp_ns - started_ns
        sequence = self._sequence + 1
        try:
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
        except Exception:
            self._disable()
            return
        self._sequence = sequence
        self._events.append(event)
        self._started_ns.pop(span_id, None)

    def _publish(self) -> None:
        if self._recorder is None or self._trace_id is None:
            return
        try:
            self._recorder.record_many(tuple(self._events))
        except Exception:
            self._disable()

    def _disable(self) -> None:
        self._recorder = None
        self._trace_id = None
        self._events.clear()

    def _link_to(self, span_id: str | None, relation: str) -> tuple[Mapping[str, str], ...]:
        if self._trace_id is None or span_id is None:
            return ()
        return (
            {
                "relation": relation,
                "trace_id": self._trace_id,
                "span_id": span_id,
            },
        )


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_digest(value: object) -> str:
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


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
        content = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        return {"missing_evidence": True}
    return {
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "content_length": len(content),
    }
