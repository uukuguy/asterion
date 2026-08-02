"""Observe validated runtime calls without retaining their private content."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from types import MappingProxyType
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
    ) -> None:
        self._runtime = runtime
        self._pathlight = pathlight
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
        input_digest = hashlib.sha256(request.input_text.encode("utf-8")).hexdigest()
        try:
            async for event in self._runtime.run(request, signal=signal):
                events.append(event.to_mapping())
                yield event
            evidence = collect_workflow_evidence(events, input_digest=input_digest)
            _RuntimePathlightProjection(self._pathlight).project(request, events)
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

    def start(self, request: RunRequest) -> None:
        """Start with the request's digest and length, never the request itself."""

        self._root_span_id = self._start("runtime", self._parent_span_id)
        self._context_span_id = self._start_context(
            {
                "content_sha256": _text_digest(request.input_text),
                "content_length": len(request.input_text.encode("utf-8")),
                # Runtime v1 has no model-request/model-response boundary.
                "missing_evidence": True,
            }
        )

    def project(self, request: RunRequest, events: list[Mapping[str, object]]) -> None:
        """Record spans only after the complete stream has been validated."""

        self.start(request)
        for event in events:
            payload = event["payload"]
            assert isinstance(payload, Mapping)
            event_type = event["type"]
            if event_type == "tool.call":
                self._project_tool_call(payload)
            elif event_type == "tool.result":
                self._project_tool_result(payload)
            elif event_type == "usage.reported":
                self._project_usage(payload)
            elif event_type == "run.completed":
                self.complete(str(payload["status"]))
            elif event_type == "run.failed":
                self._close_context()
                self._terminal(
                    self._root_span_id,
                    "failed",
                    "runtime",
                    attributes={"failure_class": "unknown"},
                )

    def complete(self, status: str) -> None:
        self._close_context()
        self._terminal(
            self._root_span_id,
            "cancelled" if status == "cancelled" else "completed",
            "runtime",
            attributes={"failure_class": "cancelled"} if status == "cancelled" else None,
        )

    def _project_tool_call(self, payload: Mapping[str, object]) -> None:
        context_span_id = self._context_span_id
        self._close_context()
        call_id = str(payload["call_id"])
        arguments = _content_summary(payload["arguments"])
        attributes: dict[str, str | int | bool] = {
            "call_id": _text_digest(call_id),
            "tool_id": _text_digest(str(payload["name"])),
        }
        attributes.update(arguments)
        span_id = self._start("tool-call", self._root_span_id, attributes=attributes)
        if span_id is not None:
            self._tool_spans[call_id] = (span_id, context_span_id)

    def _project_tool_result(self, payload: Mapping[str, object]) -> None:
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
        )
        if span_id is not None:
            self._context_span_id = self._start_context(
                {"missing_evidence": True},
                links=self._link_to(span_id, "derived-from"),
            )

    def _project_usage(self, payload: Mapping[str, object]) -> None:
        for metric_name, value in (
            ("input-tokens", int(payload["input_tokens"])),
            ("output-tokens", int(payload["output_tokens"])),
        ):
            span_id = self._start(
                "runtime",
                self._root_span_id,
                attributes={
                    "metric_name": metric_name,
                    "metric_value": value,
                    "unit": "tokens",
                },
            )
            self._terminal(span_id, "completed", "runtime")

    def _start_context(
        self,
        attributes: Mapping[str, str | int | bool],
        *,
        links: tuple[Mapping[str, str], ...] = (),
    ) -> str | None:
        return self._start(
            "context-frame", self._root_span_id, attributes=attributes, links=links
        )

    def _close_context(self) -> None:
        self._terminal(self._context_span_id, "completed", "context-frame")
        self._context_span_id = None

    def _start(
        self,
        kind: str,
        parent_span_id: str | None,
        *,
        attributes: Mapping[str, str | int | bool] | None = None,
        links: tuple[Mapping[str, str], ...] = (),
    ) -> str | None:
        if self._trace_id is None:
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
            )
        except Exception:
            self._disable()
            return None
        self._sequence = sequence
        self._record(event)
        return span_id

    def _terminal(
        self,
        span_id: str | None,
        status: str,
        kind: str,
        *,
        attributes: Mapping[str, str | int | bool] | None = None,
        links: tuple[Mapping[str, str], ...] = (),
    ) -> None:
        if self._trace_id is None or span_id is None:
            return
        sequence = self._sequence + 1
        try:
            event = TraceEvent.terminal(
                self._trace_id,
                span_id,
                sequence,
                status,
                kind=kind,
                attributes=attributes,
                links=links,
            )
        except Exception:
            self._disable()
            return
        self._sequence = sequence
        self._record(event)

    def _record(self, event: TraceEvent) -> None:
        assert self._recorder is not None
        try:
            self._recorder.record(event)
        except Exception:
            self._disable()

    def _disable(self) -> None:
        self._recorder = None
        self._trace_id = None

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
