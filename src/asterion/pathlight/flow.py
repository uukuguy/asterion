"""Provider-free, public-safe projections of verified ContextFrame flow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from asterion.pathlight.protocol import PathlightError, validate_trace_graph


_FLOW_KINDS = frozenset({"context-frame", "model-call", "tool-call"})
_FLOW_RELATIONS = frozenset(
    {"caused-next", "consumed-by", "derived-from", "produced-by"}
)
_FLOW_ATTRIBUTE_KEYS = frozenset(
    {
        "call_id",
        "content_length",
        "content_sha256",
        "duration_ns",
        "failure_class",
        "frame_index",
        "input_tokens",
        "is_error",
        "model_id",
        "observation_sha256",
        "output_tokens",
        "request_sha256",
        "response_length",
        "response_sha256",
        "segment_count",
        "tool_id",
    }
)


class _FrozenDict(dict[str, object]):
    """A JSON-encodable mapping that rejects public mutation."""

    def __init__(self, values: Mapping[str, object]) -> None:
        dict.__init__(self, values)

    def __delitem__(self, key: str) -> None:
        del key
        raise TypeError("Pathlight flow projection is immutable")

    def __ior__(self, value: object) -> _FrozenDict:
        del value
        raise TypeError("Pathlight flow projection is immutable")

    def __setitem__(self, key: str, value: object) -> None:
        del key, value
        raise TypeError("Pathlight flow projection is immutable")

    def clear(self) -> None:
        raise TypeError("Pathlight flow projection is immutable")

    def pop(self, key: str, default: object = None) -> object:
        del key, default
        raise TypeError("Pathlight flow projection is immutable")

    def popitem(self) -> tuple[str, object]:
        raise TypeError("Pathlight flow projection is immutable")

    def setdefault(self, key: str, default: object = None) -> object:
        del key, default
        raise TypeError("Pathlight flow projection is immutable")

    def update(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError("Pathlight flow projection is immutable")


@dataclass(frozen=True, slots=True)
class _Span:
    span_id: str
    parent_span_id: str | None
    sequence: int
    kind: str
    status: str
    attributes: Mapping[str, object]
    links: tuple[Mapping[str, str], ...]


def project_trace_flow(trace: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    """Return the ordered ContextFrame/model/tool mainline from one verified trace.

    The projection intentionally consumes only the closed public TraceGraph mapping;
    it never loads a runtime or interprets content-bearing runtime values.
    """

    try:
        canonical = _json_copy(trace)
        if not isinstance(canonical, Mapping):
            raise PathlightError("Pathlight trace flow is invalid")
        validate_trace_graph(canonical)
        spans = _spans_from_trace(canonical)
        selected = _select_mainline(spans)
        return _project_mainline(spans, selected)
    except Exception:
        raise PathlightError("Pathlight trace flow is invalid") from None


def _json_copy(value: object) -> object:
    if isinstance(value, Mapping):
        copied: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise PathlightError("Pathlight trace flow is invalid")
            copied[key] = _json_copy(item)
        return copied
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        if value is None or type(value) in {str, int, bool}:
            return value
        raise PathlightError("Pathlight trace flow is invalid")
    return [_json_copy(item) for item in value]


def _spans_from_trace(trace: Mapping[str, object]) -> Mapping[str, _Span]:
    events = trace["events"]
    if not isinstance(events, list):
        raise PathlightError("Pathlight trace flow is invalid")
    starts: dict[str, Mapping[str, object]] = {}
    terminals: dict[str, Mapping[str, object]] = {}
    for event in events:
        if not isinstance(event, Mapping):
            raise PathlightError("Pathlight trace flow is invalid")
        span_id = event["span_id"]
        status = event["status"]
        if type(span_id) is not str or type(status) is not str:
            raise PathlightError("Pathlight trace flow is invalid")
        if status == "started":
            starts[span_id] = event
        else:
            terminals[span_id] = event

    spans: dict[str, _Span] = {}
    for span_id, started in starts.items():
        terminal = terminals.get(span_id)
        if terminal is None:
            raise PathlightError("Pathlight trace flow is invalid")
        parent_span_id = started["parent_span_id"]
        sequence = started["sequence"]
        kind = started["kind"]
        status = terminal["status"]
        attributes = _combined_attributes(started["attributes"], terminal["attributes"])
        links = _combined_links(started["links"], terminal["links"])
        if (
            parent_span_id is not None
            and type(parent_span_id) is not str
            or type(sequence) is not int
            or type(kind) is not str
            or type(status) is not str
        ):
            raise PathlightError("Pathlight trace flow is invalid")
        spans[span_id] = _Span(
            span_id, parent_span_id, sequence, kind, status, attributes, links
        )
    if set(starts) != set(terminals):
        raise PathlightError("Pathlight trace flow is invalid")
    return spans


def _combined_attributes(started: object, terminal: object) -> Mapping[str, object]:
    if not isinstance(started, Mapping) or not isinstance(terminal, Mapping):
        raise PathlightError("Pathlight trace flow is invalid")
    attributes = dict(started)
    for key, value in terminal.items():
        if key in attributes and attributes[key] != value:
            raise PathlightError("Pathlight trace flow is invalid")
        attributes[key] = value
    return attributes


def _combined_links(started: object, terminal: object) -> tuple[Mapping[str, str], ...]:
    if not isinstance(started, list) or not isinstance(terminal, list):
        raise PathlightError("Pathlight trace flow is invalid")
    links = tuple((*started, *terminal))
    if any(not isinstance(link, Mapping) for link in links):
        raise PathlightError("Pathlight trace flow is invalid")
    return links  # type: ignore[return-value]


def _select_mainline(spans: Mapping[str, _Span]) -> tuple[str, ...]:
    selected: list[str] = []
    for span in sorted(spans.values(), key=lambda value: value.sequence):
        if span.kind not in _FLOW_KINDS:
            continue
        parent_span_id = span.parent_span_id
        while parent_span_id is not None:
            parent = spans.get(parent_span_id)
            if parent is None:
                raise PathlightError("Pathlight trace flow is invalid")
            if parent.kind in _FLOW_KINDS:
                break
            parent_span_id = parent.parent_span_id
        else:
            selected.append(span.span_id)
            continue
        if parent is None:
            raise PathlightError("Pathlight trace flow is invalid")
        if parent.kind not in _FLOW_KINDS:
            selected.append(span.span_id)
    return tuple(selected)


def _project_mainline(
    spans: Mapping[str, _Span], selected: tuple[str, ...]
) -> tuple[Mapping[str, object], ...]:
    selected_ids = frozenset(selected)
    selected_by_id = {span_id: spans[span_id] for span_id in selected}
    caused_by: dict[str, set[int]] = {span_id: set() for span_id in selected}
    consumed_by: dict[str, set[int]] = {span_id: set() for span_id in selected}
    produced_by: dict[str, set[int]] = {span_id: set() for span_id in selected}
    missing_evidence: dict[str, bool] = {
        span_id: bool(selected_by_id[span_id].attributes.get("missing_evidence", False))
        for span_id in selected
    }

    for span in spans.values():
        source = _selected_ancestor(span.span_id, spans, selected_ids)
        if source is not None and bool(span.attributes.get("missing_evidence", False)):
            missing_evidence[source] = True
        for link in span.links:
            relation = link.get("relation")
            target_id = link.get("span_id")
            if relation not in _FLOW_RELATIONS or type(target_id) is not str:
                raise PathlightError("Pathlight trace flow is invalid")
            target = _selected_ancestor(target_id, spans, selected_ids)
            if source is None or target is None:
                continue
            if source == target:
                raise PathlightError("Pathlight trace flow is invalid")
            if relation == "consumed-by":
                _require_forward_link(selected_by_id[source], selected_by_id[target])
                consumed_by[source].add(selected_by_id[target].sequence)
            elif relation == "caused-next":
                _record_cause(
                    caused_by, selected_by_id, cause=source, effect=target
                )
            else:
                _record_cause(
                    caused_by, selected_by_id, cause=target, effect=source
                )
                if relation == "produced-by":
                    produced_by[source].add(selected_by_id[target].sequence)

    _reject_cycles(caused_by, selected_by_id)
    nodes: list[Mapping[str, object]] = []
    for span_id in selected:
        span = selected_by_id[span_id]
        parent_sequence = _parent_sequence(span, spans)
        causes = caused_by[span_id]
        if len(causes) > 1:
            raise PathlightError("Pathlight trace flow is invalid")
        safe_attributes = {
            key: span.attributes[key]
            for key in sorted(_FLOW_ATTRIBUTE_KEYS & set(span.attributes))
        }
        nodes.append(
            _FrozenDict(
                {
                    "sequence": span.sequence,
                    "kind": span.kind,
                    "status": span.status,
                    "parent_sequence": parent_sequence,
                    "caused_by_sequence": next(iter(causes), None),
                    "consumed_by_sequences": tuple(sorted(consumed_by[span_id])),
                    "produced_by_sequences": tuple(sorted(produced_by[span_id])),
                    "attributes": _FrozenDict(safe_attributes),
                    "missing_evidence": missing_evidence[span_id],
                }
            )
        )
    return tuple(nodes)


def _selected_ancestor(
    span_id: str, spans: Mapping[str, _Span], selected_ids: frozenset[str]
) -> str | None:
    current_id: str | None = span_id
    while current_id is not None:
        if current_id in selected_ids:
            return current_id
        current = spans.get(current_id)
        if current is None:
            raise PathlightError("Pathlight trace flow is invalid")
        current_id = current.parent_span_id
    return None


def _require_forward_link(cause: _Span, effect: _Span) -> None:
    if cause.sequence >= effect.sequence:
        raise PathlightError("Pathlight trace flow is invalid")


def _record_cause(
    caused_by: Mapping[str, set[int]],
    selected_by_id: Mapping[str, _Span],
    *,
    cause: str,
    effect: str,
) -> None:
    _require_forward_link(selected_by_id[cause], selected_by_id[effect])
    caused_by[effect].add(selected_by_id[cause].sequence)


def _reject_cycles(
    caused_by: Mapping[str, set[int]], selected_by_id: Mapping[str, _Span]
) -> None:
    span_by_sequence = {span.sequence: span_id for span_id, span in selected_by_id.items()}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(span_id: str) -> None:
        if span_id in visiting:
            raise PathlightError("Pathlight trace flow is invalid")
        if span_id in visited:
            return
        visiting.add(span_id)
        for sequence in caused_by[span_id]:
            visit(span_by_sequence[sequence])
        visiting.remove(span_id)
        visited.add(span_id)

    for span_id in selected_by_id:
        visit(span_id)


def _parent_sequence(span: _Span, spans: Mapping[str, _Span]) -> int | None:
    if span.parent_span_id is None:
        return None
    parent = spans.get(span.parent_span_id)
    if parent is None:
        raise PathlightError("Pathlight trace flow is invalid")
    return parent.sequence
