"""Immutable, public-safe trace graphs for framework execution paths."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TypeAlias


TRACE_SCHEMA = "asterion.pathlight-trace/v1"
SAFE_KINDS = frozenset(
    {
        "plan",
        "assembly",
        "task",
        "runtime",
        "context-frame",
        "model-call",
        "tool-call",
        "host-service",
        "evaluation",
        "artifact",
    }
)
SAFE_STATUSES = frozenset({"started", "completed", "failed", "cancelled", "skipped"})

_TRACE_FIELDS = frozenset({"schema", "trace_id", "events", "trace_sha256"})
_EVENT_FIELDS = frozenset(
    {
        "trace_id",
        "span_id",
        "parent_span_id",
        "sequence",
        "kind",
        "status",
        "attributes",
        "links",
        "timestamp_ns",
    }
)
_LINK_FIELDS = frozenset({"relation", "trace_id", "span_id"})
_SAFE_RELATIONS = frozenset(
    {"caused-next", "consumed-by", "derived-from", "evidence-for", "produced-by", "related-to"}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$")

_DIGEST_ATTRIBUTES = frozenset(
    {"content_sha256", "evidence_ref", "policy_sha256", "scope_sha256", "coverage_sha256"}
)
_IDENTITY_ATTRIBUTES = frozenset(
    {
        "artifact_id",
        "call_id",
        "component_id",
        "failure_class",
        "metric_contract_id",
        "metric_name",
        "model_id",
        "runtime_id",
        "structure_kind",
        "tool_id",
        "unit",
    }
)
_NONNEGATIVE_INT_ATTRIBUTES = frozenset(
    {
        "attempt",
        "content_length",
        "cost_microunits",
        "duration_ns",
        "input_tokens",
        "output_tokens",
    }
)
_INTEGER_ATTRIBUTES = frozenset({"metric_value"})
_BOOLEAN_ATTRIBUTES = frozenset({"is_error", "missing_evidence"})
_SAFE_ATTRIBUTE_KEYS = (
    _DIGEST_ATTRIBUTES
    | _IDENTITY_ATTRIBUTES
    | _NONNEGATIVE_INT_ATTRIBUTES
    | _INTEGER_ATTRIBUTES
    | _BOOLEAN_ATTRIBUTES
)

SafeAttributeValue: TypeAlias = str | int | bool


class PathlightError(ValueError):
    """Raised when a Pathlight trace is unsafe or violates its contract."""


def _is_identifier(value: object) -> bool:
    return type(value) is str and _IDENTITY.fullmatch(value) is not None


def _require_identifier(value: object, *, field_name: str) -> str:
    if not _is_identifier(value):
        raise PathlightError(f"Pathlight {field_name} is invalid")
    assert isinstance(value, str)
    return value


def _require_digest(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise PathlightError(f"Pathlight {field_name} is invalid")
    return value


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise PathlightError(f"Pathlight {field_name} is invalid")
    return value


def _freeze_attributes(attributes: Mapping[str, SafeAttributeValue]) -> Mapping[str, SafeAttributeValue]:
    if not isinstance(attributes, Mapping):
        raise PathlightError("Pathlight event attributes are invalid")
    values = dict(attributes)
    if set(values) - _SAFE_ATTRIBUTE_KEYS:
        raise PathlightError("Pathlight event attributes contain an unsafe key")
    for key, value in values.items():
        if key in _DIGEST_ATTRIBUTES:
            _require_digest(value, field_name=f"attribute {key}")
        elif key in _IDENTITY_ATTRIBUTES:
            _require_identifier(value, field_name=f"attribute {key}")
        elif key in _NONNEGATIVE_INT_ATTRIBUTES:
            _require_nonnegative_int(value, field_name=f"attribute {key}")
        elif key in _INTEGER_ATTRIBUTES:
            if type(value) is not int:
                raise PathlightError(f"Pathlight attribute {key} is invalid")
        elif key in _BOOLEAN_ATTRIBUTES and type(value) is not bool:
            raise PathlightError(f"Pathlight attribute {key} is invalid")
    return MappingProxyType(values)


def _freeze_links(links: Sequence[Mapping[str, str]]) -> tuple[Mapping[str, str], ...]:
    if isinstance(links, (str, bytes)) or not isinstance(links, Sequence):
        raise PathlightError("Pathlight event links are invalid")
    frozen: list[Mapping[str, str]] = []
    keys: list[tuple[str, str, str]] = []
    for link in links:
        if not isinstance(link, Mapping) or set(link) != _LINK_FIELDS:
            raise PathlightError("Pathlight event link fields are invalid")
        relation = link.get("relation")
        trace_id = link.get("trace_id")
        span_id = link.get("span_id")
        if relation not in _SAFE_RELATIONS:
            raise PathlightError("Pathlight event link relation is invalid")
        _require_identifier(trace_id, field_name="link trace identity")
        _require_identifier(span_id, field_name="link span identity")
        assert isinstance(relation, str)
        assert isinstance(trace_id, str)
        assert isinstance(span_id, str)
        keys.append((relation, trace_id, span_id))
        frozen.append(
            MappingProxyType(
                {"relation": relation, "trace_id": trace_id, "span_id": span_id}
            )
        )
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise PathlightError("Pathlight event links are not canonical")
    return tuple(frozen)


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One lifecycle fact in a trace; content-bearing values are never accepted."""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    sequence: int
    kind: str
    status: str
    attributes: Mapping[str, SafeAttributeValue] = field(default_factory=dict)
    links: Sequence[Mapping[str, str]] = ()
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        _require_identifier(self.trace_id, field_name="trace identity")
        _require_identifier(self.span_id, field_name="span identity")
        if self.parent_span_id is not None:
            _require_identifier(self.parent_span_id, field_name="parent span identity")
        if type(self.sequence) is not int or self.sequence < 1:
            raise PathlightError("Pathlight event sequence is invalid")
        if self.kind not in SAFE_KINDS:
            raise PathlightError("Pathlight event kind is invalid")
        if self.status not in SAFE_STATUSES:
            raise PathlightError("Pathlight event status is invalid")
        if type(self.timestamp_ns) is not int or self.timestamp_ns < 0:
            raise PathlightError("Pathlight event timestamp is invalid")
        object.__setattr__(self, "attributes", _freeze_attributes(self.attributes))
        object.__setattr__(self, "links", _freeze_links(self.links))

    @classmethod
    def start(
        cls,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None,
        sequence: int,
        kind: str,
        *,
        attributes: Mapping[str, SafeAttributeValue] | None = None,
        links: Sequence[Mapping[str, str]] = (),
        timestamp_ns: int = 0,
    ) -> TraceEvent:
        return cls(
            trace_id,
            span_id,
            parent_span_id,
            sequence,
            kind,
            "started",
            {} if attributes is None else attributes,
            links,
            timestamp_ns,
        )

    @classmethod
    def terminal(
        cls,
        trace_id: str,
        span_id: str,
        sequence: int,
        status: str,
        *,
        kind: str = "task",
        attributes: Mapping[str, SafeAttributeValue] | None = None,
        links: Sequence[Mapping[str, str]] = (),
        timestamp_ns: int = 0,
    ) -> TraceEvent:
        if status == "started":
            raise PathlightError("Pathlight terminal status is invalid")
        return cls(
            trace_id,
            span_id,
            None,
            sequence,
            kind,
            status,
            {} if attributes is None else attributes,
            links,
            timestamp_ns,
        )

    @classmethod
    def complete(
        cls,
        trace_id: str,
        span_id: str,
        sequence: int,
        *,
        kind: str = "task",
        attributes: Mapping[str, SafeAttributeValue] | None = None,
        links: Sequence[Mapping[str, str]] = (),
        timestamp_ns: int = 0,
    ) -> TraceEvent:
        return cls.terminal(
            trace_id,
            span_id,
            sequence,
            "completed",
            kind=kind,
            attributes=attributes,
            links=links,
            timestamp_ns=timestamp_ns,
        )


@dataclass(frozen=True, slots=True)
class TraceGraph:
    """A complete, deterministic trace with all spans closed."""

    trace_id: str
    events: tuple[TraceEvent, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.trace_id, field_name="trace identity")
        events = tuple(self.events)
        if not all(isinstance(event, TraceEvent) for event in events):
            raise PathlightError("Pathlight graph events are invalid")
        object.__setattr__(self, "events", events)
        _validate_trace_components(self.trace_id, events)

    @classmethod
    def build(
        cls, trace_id: str, events: Sequence[TraceEvent]
    ) -> TraceGraph:
        return cls(trace_id, tuple(events))

    def to_mapping(self) -> dict[str, object]:
        graph: dict[str, object] = {
            "schema": TRACE_SCHEMA,
            "trace_id": self.trace_id,
            "events": [_event_to_mapping(event) for event in self.events],
        }
        graph["trace_sha256"] = trace_graph_digest(graph)
        return graph


def _event_to_mapping(event: TraceEvent) -> dict[str, object]:
    return {
        "trace_id": event.trace_id,
        "span_id": event.span_id,
        "parent_span_id": event.parent_span_id,
        "sequence": event.sequence,
        "kind": event.kind,
        "status": event.status,
        "attributes": dict(event.attributes),
        "links": [dict(link) for link in event.links],
        "timestamp_ns": event.timestamp_ns,
    }


def _event_from_mapping(value: object) -> TraceEvent:
    if not isinstance(value, Mapping) or set(value) != _EVENT_FIELDS:
        raise PathlightError("Pathlight event fields are invalid")
    return TraceEvent(
        trace_id=value.get("trace_id"),
        span_id=value.get("span_id"),
        parent_span_id=value.get("parent_span_id"),
        sequence=value.get("sequence"),
        kind=value.get("kind"),
        status=value.get("status"),
        attributes=value.get("attributes"),
        links=value.get("links"),
        timestamp_ns=value.get("timestamp_ns"),
    )


def _validate_trace_components(trace_id: str, events: tuple[TraceEvent, ...]) -> None:
    if not events:
        raise PathlightError("Pathlight graph must contain events")
    spans: dict[str, TraceEvent] = {}
    open_spans: dict[str, TraceEvent] = {}
    root_span_id: str | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if event.trace_id != trace_id:
            raise PathlightError("Pathlight event trace identity mismatches")
        if event.sequence != expected_sequence:
            raise PathlightError("Pathlight graph sequence is not contiguous")
        if event.status == "started":
            if event.span_id in spans:
                raise PathlightError("Pathlight graph has duplicate span identity")
            if event.parent_span_id is None:
                if root_span_id is not None:
                    raise PathlightError("Pathlight graph has multiple roots")
                root_span_id = event.span_id
            elif event.parent_span_id not in open_spans:
                raise PathlightError("Pathlight graph parent is unknown or closed")
            spans[event.span_id] = event
            open_spans[event.span_id] = event
        else:
            if event.parent_span_id is not None:
                raise PathlightError("Pathlight terminal event has a parent")
            started = open_spans.get(event.span_id)
            if started is None:
                raise PathlightError("Pathlight terminal event is unmatched")
            if event.kind != started.kind:
                raise PathlightError("Pathlight terminal event kind mismatches")
            if any(
                open_event.parent_span_id == event.span_id
                for open_event in open_spans.values()
            ):
                raise PathlightError("Pathlight parent span terminates before its child")
            del open_spans[event.span_id]

    if root_span_id is None:
        raise PathlightError("Pathlight graph has no root")
    if open_spans:
        raise PathlightError("Pathlight graph has unterminated spans")
    for event in events:
        for link in event.links:
            if link["trace_id"] != trace_id:
                raise PathlightError("Pathlight graph link crosses trace boundary")
            if link["span_id"] not in spans:
                raise PathlightError("Pathlight graph link target is unknown")


def _graph_without_digest(graph: Mapping[str, object], *, allow_digest: bool) -> dict[str, object]:
    if not isinstance(graph, Mapping):
        raise PathlightError("Pathlight graph must be an object")
    fields = set(graph)
    expected_fields = _TRACE_FIELDS if allow_digest else _TRACE_FIELDS - {"trace_sha256"}
    if fields != expected_fields:
        raise PathlightError("Pathlight graph fields are invalid")
    if graph.get("schema") != TRACE_SCHEMA:
        raise PathlightError("Pathlight graph schema is invalid")
    trace_id = _require_identifier(graph.get("trace_id"), field_name="trace identity")
    events_value = graph.get("events")
    if not isinstance(events_value, list):
        raise PathlightError("Pathlight graph events are invalid")
    events = tuple(_event_from_mapping(event) for event in events_value)
    _validate_trace_components(trace_id, events)
    return {
        "schema": TRACE_SCHEMA,
        "trace_id": trace_id,
        "events": [_event_to_mapping(event) for event in events],
    }


def trace_graph_digest(graph: Mapping[str, object]) -> str:
    """Return the digest for an otherwise valid graph, ignoring its digest field."""

    if not isinstance(graph, Mapping):
        raise PathlightError("Pathlight graph must be an object")
    canonical = _graph_without_digest(graph, allow_digest="trace_sha256" in graph)
    rendered = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def validate_trace_graph(graph: Mapping[str, object]) -> None:
    """Raise :class:`PathlightError` unless a canonical safe graph is valid."""

    canonical = _graph_without_digest(graph, allow_digest=True)
    expected = _require_digest(graph.get("trace_sha256"), field_name="graph digest")
    rendered = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    actual = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(expected, actual):
        raise PathlightError("Pathlight graph digest mismatches")
