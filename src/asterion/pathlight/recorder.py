"""Explicit, public-safe Pathlight trace recorders."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Never, Protocol

from asterion.pathlight.protocol import PathlightError, TraceEvent, TraceGraph, validate_trace_graph


class PathlightRecorder(Protocol):
    """Receive safe events and expose an immutable public trace snapshot."""

    @property
    def trace_id(self) -> str | None:
        """Return the exact trace identity, or ``None`` when recording is disabled."""

    def record(self, event: TraceEvent) -> None:
        """Accept one safe event for this recorder's trace."""

    def snapshot(self) -> Mapping[str, object] | None:
        """Return the validated public graph, or ``None`` for no-op."""


class NoopPathlightRecorder:
    """A recorder that neither retains events nor exposes their contents."""

    @property
    def trace_id(self) -> None:
        return None

    def record(self, event: TraceEvent) -> None:
        del event

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

    def record(self, event: TraceEvent) -> None:
        if not isinstance(event, TraceEvent) or event.trace_id != self._trace_id:
            raise PathlightError("Pathlight recorder event trace identity mismatches")
        self._events.append(
            TraceEvent(
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
        )

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


NOOP_PATHLIGHT_RECORDER: PathlightRecorder = NoopPathlightRecorder()
