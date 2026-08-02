"""Explicit, public-safe Pathlight trace recorders."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Never, Protocol

from asterion.pathlight.protocol import PathlightError, TraceEvent, TraceGraph, validate_trace_graph


class PathlightRecorder(Protocol):
    """Receive safe events and expose an immutable public trace snapshot."""

    @property
    def trace_id(self) -> str | None:
        """Return the exact trace identity, or ``None`` when recording is disabled."""

    @property
    def next_sequence(self) -> int:
        """Return the recorder-owned sequence for the next event."""

    @property
    def active_span_id(self) -> str | None:
        """Return the innermost open span in the recorder's trace."""

    def record(self, event: TraceEvent) -> None:
        """Accept one safe event for this recorder's trace."""

    def record_many(self, events: Sequence[TraceEvent]) -> None:
        """Atomically accept all supplied safe events, or accept none."""

    def snapshot(self) -> Mapping[str, object] | None:
        """Return the validated public graph, or ``None`` for no-op."""


class NoopPathlightRecorder:
    """A recorder that neither retains events nor exposes their contents."""

    @property
    def trace_id(self) -> None:
        return None

    @property
    def next_sequence(self) -> int:
        return 1

    @property
    def active_span_id(self) -> None:
        return None

    def record(self, event: TraceEvent) -> None:
        del event

    def record_many(self, events: Sequence[TraceEvent]) -> None:
        del events

    def snapshot(self) -> Mapping[str, object] | None:
        return None


class MemoryPathlightRecorder:
    """An in-memory recorder for one exact Pathlight trace identity."""

    def __init__(self, trace_id: str) -> None:
        TraceEvent.start(trace_id, trace_id, None, 1, "task")
        self._trace_id = trace_id
        self._events: list[TraceEvent] = []

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def event_count(self) -> int:
        """Return the number of accepted events without exposing their contents."""

        return len(self._events)

    @property
    def next_sequence(self) -> int:
        """Return the only valid sequence for the next event in this trace."""

        return len(self._events) + 1

    @property
    def active_span_id(self) -> str | None:
        """Return the innermost currently-open span, if any."""

        open_spans: list[str] = []
        for event in self._events:
            if event.status == "started":
                open_spans.append(event.span_id)
            elif event.span_id in open_spans:
                open_spans.remove(event.span_id)
        return open_spans[-1] if open_spans else None

    def record(self, event: TraceEvent) -> None:
        if not isinstance(event, TraceEvent) or event.trace_id != self._trace_id:
            raise PathlightError("Pathlight recorder event trace identity mismatches")
        self._events.append(_copy_event(event))

    def record_many(self, events: Sequence[TraceEvent]) -> None:
        """Commit a valid candidate trace prefix only after validating all events."""

        candidates = tuple(_copy_event(event) for event in events)
        combined = (*self._events, *candidates)
        _validate_candidate_prefix(self._trace_id, combined)
        self._events.extend(candidates)

    def snapshot(self) -> Mapping[str, object]:
        graph = TraceGraph.build(self._trace_id, tuple(self._events)).to_mapping()
        validate_trace_graph(graph)
        return _freeze(graph)


class _ImmutableList(list[object]):
    """A list-compatible immutable value for validators that require lists."""

    def _immutable(self, *args: object, **kwargs: object) -> Never:
        del args, kwargs
        raise TypeError("Pathlight snapshot is immutable")

    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    __setitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return _ImmutableList(_freeze(item) for item in value)
    return value


def _copy_event(event: TraceEvent) -> TraceEvent:
    if not isinstance(event, TraceEvent):
        raise PathlightError("Pathlight recorder event is invalid")
    return TraceEvent(
        trace_id=event.trace_id,
        span_id=event.span_id,
        parent_span_id=event.parent_span_id,
        sequence=event.sequence,
        kind=event.kind,
        status=event.status,
        attributes=dict(event.attributes),
        links=tuple(dict(link) for link in event.links),
        timestamp_ns=event.timestamp_ns,
    )


def _validate_candidate_prefix(trace_id: str, events: tuple[TraceEvent, ...]) -> None:
    """Validate a trace candidate while preserving open lifecycle spans."""

    open_spans: dict[str, TraceEvent] = {}
    for event in events:
        if event.status == "started":
            open_spans[event.span_id] = event
        else:
            open_spans.pop(event.span_id, None)
    timestamp_ns = max((event.timestamp_ns for event in events), default=0)
    closures = tuple(
        TraceEvent.terminal(
            trace_id,
            event.span_id,
            len(events) + offset,
            "completed",
            kind=event.kind,
            timestamp_ns=timestamp_ns,
        )
        for offset, event in enumerate(reversed(tuple(open_spans.values())), start=1)
    )
    TraceGraph.build(trace_id, (*events, *closures))


NOOP_PATHLIGHT_RECORDER: PathlightRecorder = NoopPathlightRecorder()
