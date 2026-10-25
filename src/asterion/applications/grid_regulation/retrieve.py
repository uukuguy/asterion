"""Cite one grid-regulation clause through native-dci research artifacts."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.dci.implementation.implementation import (
    DciLocalResearchImplementation,
)
from asterion.capabilities.execution import (
    CapabilityExecutionError,
    CapabilityInvocation,
)
from asterion.documents import (
    DocumentToolError,
    document_spans,
    write_docx,
    write_pdf,
)
from asterion.runtime.host import RunEvent, RunRequest


# A longer dotted id is not a shorter clause: 2.10 is not 2.1, and 2.1.1 is not 2.1.
_CLAUSE_ID = re.compile(r"^([0-9]{1,2}(?:\.[0-9]{1,2}){1,4})(?!\d|\.[0-9])")
_CLAUSE_REF = re.compile(r"(?<![0-9.])([0-9]{1,2}(?:\.[0-9]{1,2}){1,4})(?!\d|\.[0-9])")
_HEADING_TAIL = re.compile(r"^[\s.．。:：、]+")
_MAX_CLAUSES = 8
_MAX_SITUATION = 200


class RegulationCitationError(ValueError):
    """Raised when a regulation clause cannot be cited from the corpus."""


@dataclass(frozen=True)
class RegulationQuery:
    clause_id: str
    version: str
    finding: str


@dataclass(frozen=True)
class RegulationCitation:
    clause_id: str
    version: str
    anchors: tuple[Mapping[str, object], ...]
    calls: tuple[str, ...]


@dataclass(frozen=True)
class RegulationMeasures:
    terms: tuple[str, ...]
    limited: bool
    clauses: tuple[Mapping[str, object], ...]
    calls: tuple[str, ...]


@dataclass(frozen=True)
class RegulationChain:
    terms: tuple[str, ...]
    limited: bool
    steps: tuple[Mapping[str, object], ...]
    calls: tuple[str, ...]


async def cite_regulation(
    corpus: Path,
    query: RegulationQuery,
    *,
    document_tools: str,
) -> RegulationCitation:
    """Assemble a dotted clause and record its verified anchors."""

    if not _query_ready(query):
        raise RegulationCitationError("regulation citation is unavailable")
    try:
        accepted = _accepted_anchors(
            document_spans(corpus, tools=document_tools),
            query,
        )
    except DocumentToolError:
        raise RegulationCitationError("regulation citation is unavailable") from None
    if not accepted:
        raise RegulationCitationError("regulation citation is unavailable")
    try:
        result = await DciLocalResearchImplementation().execute(
            _invocation(corpus, accepted)
        )
    except CapabilityExecutionError:
        raise RegulationCitationError("regulation citation is unavailable") from None
    locations = result.artifacts[1]["value"]
    anchors = locations["anchors"]
    calls = result.artifacts[2]["value"]["calls"]
    if anchors != accepted or calls != tuple("document-read" for _item in accepted):
        raise RegulationCitationError("regulation citation is unavailable")
    return RegulationCitation(
        clause_id=query.clause_id,
        version=query.version,
        anchors=tuple(_thaw(anchor) for anchor in anchors),
        calls=tuple(calls),
    )


async def lookup_measures(
    corpus: Path,
    situation: str,
    *,
    document: str | None,
    document_tools: str,
) -> RegulationMeasures:
    """Answer one file's matching clauses, with parent, child, and mentioned clauses.

    The clause text is for the caller. It is not written into the research artifact.
    """

    terms = _terms(situation)
    if document is not None and type(document) is not str:
        raise RegulationCitationError("request is invalid")
    try:
        spans = document_spans(
            corpus,
            tools=document_tools,
            path=document or None,
        )
    except DocumentToolError:
        raise RegulationCitationError("regulation measures are unavailable") from None
    matched, limited = _matching_clauses(spans, terms)
    if not matched:
        raise RegulationCitationError("regulation measures are unavailable")
    chosen = matched
    accepted = tuple(item["basis"] for item in chosen)
    try:
        result = await DciLocalResearchImplementation().execute(
            _invocation(corpus, accepted)
        )
    except CapabilityExecutionError:
        raise RegulationCitationError("regulation measures are unavailable") from None
    anchors = result.artifacts[1]["value"]["anchors"]
    calls = result.artifacts[2]["value"]["calls"]
    if anchors != accepted or calls != tuple("document-read" for _item in accepted):
        raise RegulationCitationError("regulation measures are unavailable")
    clauses = tuple(
        {
            "document": item["document"],
            "clause_id": item["clause_id"],
            "relation": item["relation"],
            "measures": item["measures"],
            "basis": _thaw(anchor),
        }
        for item, anchor in zip(chosen, anchors, strict=True)
    )
    return RegulationMeasures(
        terms=terms,
        limited=limited,
        clauses=clauses,
        calls=tuple(calls),
    )


async def lookup_chain(
    corpus: Path,
    situation: str,
    *,
    document: str | None,
    document_tools: str,
) -> RegulationChain:
    """Open matching passages, then the passages those passages point to.

    A table row stays one step, in cell order. A clause number is a label on
    the passage it heads, and a citation when that passage is opened. The
    choice of which page to open is still the words in the situation.
    """

    terms = _terms(situation)
    if document is not None and type(document) is not str:
        raise RegulationCitationError("request is invalid")
    try:
        spans = document_spans(
            corpus,
            tools=document_tools,
            path=document or None,
        )
    except DocumentToolError:
        raise RegulationCitationError("regulation measures are unavailable") from None
    passages = _passages(spans)
    chosen, limited = _chain_indexes(passages, terms)
    if not chosen:
        raise RegulationCitationError("regulation measures are unavailable")
    accepted = tuple(
        anchor for index in chosen for anchor, _text in passages[index]["anchors"]
    )
    try:
        result = await DciLocalResearchImplementation().execute(
            _invocation(corpus, accepted)
        )
    except CapabilityExecutionError:
        raise RegulationCitationError("regulation measures are unavailable") from None
    anchors = result.artifacts[1]["value"]["anchors"]
    calls = result.artifacts[2]["value"]["calls"]
    if anchors != accepted or calls != tuple("document-read" for _item in accepted):
        raise RegulationCitationError("regulation measures are unavailable")
    steps: list[Mapping[str, object]] = []
    cursor = 0
    for index in chosen:
        passage = passages[index]
        count = len(passage["anchors"])
        recorded = tuple(_thaw(anchor) for anchor in anchors[cursor : cursor + count])
        cursor += count
        steps.append(
            {
                "text": passage["text"],
                "label": passage["label"],
                "anchors": recorded,
            }
        )
    return RegulationChain(
        terms=terms,
        limited=limited,
        steps=tuple(steps),
        calls=tuple(calls),
    )


def _passages(
    spans: tuple[tuple[Mapping[str, object], str], ...]
    | list[tuple[Mapping[str, object], str]],
) -> tuple[dict[str, object], ...]:
    passages: list[dict[str, object]] = []
    index = 0
    while index < len(spans):
        anchor, text = spans[index]
        if anchor["kind"] == "docx-cell":
            position = anchor["position"]
            if not isinstance(position, Mapping):
                index += 1
                continue
            table = position.get("table")
            row = position.get("row")
            cells = [(anchor, text)]
            cursor = index + 1
            while cursor < len(spans):
                nxt, nxt_text = spans[cursor]
                nxt_position = nxt["position"]
                if (
                    nxt["kind"] != "docx-cell"
                    or not isinstance(nxt_position, Mapping)
                    or nxt_position.get("table") != table
                    or nxt_position.get("row") != row
                ):
                    break
                cells.append((nxt, nxt_text))
                cursor += 1
            passages.append(_row_passage(cells))
            index = cursor
            continue
        passages.append(_text_passage(anchor, text))
        index += 1
    return tuple(passages)


def _text_passage(anchor: Mapping[str, object], text: str) -> dict[str, object]:
    label = _heading_id(text)
    return {
        "text": text,
        "anchors": ((anchor, text),),
        "label": label,
        "references": _passage_refs(text, label),
    }


def _row_passage(
    cells: list[tuple[Mapping[str, object], str]],
) -> dict[str, object]:
    label = None
    for _anchor, text in cells:
        heading = _heading_id(text)
        if heading is not None:
            label = heading
            break
    refs: list[str] = []
    seen: set[str] = set()
    for _anchor, text in cells:
        for ref in _passage_refs(text, label):
            if ref not in seen:
                seen.add(ref)
                refs.append(ref)
    return {
        "text": "｜".join(text for _anchor, text in cells),
        "anchors": tuple(cells),
        "label": label,
        "references": tuple(refs),
    }


def _passage_refs(text: str, label: str | None) -> tuple[str, ...]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _CLAUSE_REF.finditer(text):
        ref = match.group(1)
        if ref == label or ref in seen:
            continue
        seen.add(ref)
        found.append(ref)
    return tuple(found)


def _chain_indexes(
    passages: tuple[dict[str, object], ...],
    terms: tuple[str, ...],
) -> tuple[tuple[int, ...], bool]:
    labels: dict[str, int] = {}
    for index, passage in enumerate(passages):
        label = passage["label"]
        if type(label) is str and label not in labels:
            labels[label] = index
    hits = [
        index
        for index, passage in enumerate(passages)
        if all(term in str(passage["text"]) for term in terms)
    ]
    opened: list[int] = []
    seen: set[int] = set()
    limited = False
    for index in hits:
        if len(opened) >= _MAX_CLAUSES:
            limited = True
            break
        opened.append(index)
        seen.add(index)
        references = passages[index]["references"]
        if not isinstance(references, tuple):
            continue
        for ref in references:
            target = labels.get(str(ref))
            if target is None or target in seen:
                continue
            if len(opened) >= _MAX_CLAUSES:
                limited = True
                break
            opened.append(target)
            seen.add(target)
    return tuple(opened), limited


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_thaw(item) for item in value)
    return value


def write_demo_corpus(root: Path) -> None:
    """Write a fictional regulation corpus. It is not an issued standard."""

    write_docx(
        root / "grounding.docx",
        (
            ("示范变电站接地规程", None),
            ("4.1.1 范围 本文件适用于示范变电站。", (1, 1)),
            (
                "4.1.2 接地电阻 DL/T 9000-2024 接地电阻不应大于4欧姆。"
                "内部备注SECRET-SPAN-BODY仅供原件。",
                (1, 1),
            ),
            ("4.1.3 其他 本条不规定电阻限值。", (1, 1)),
        ),
        ((("4.2.1 屏蔽 DL/T 9000-2024 屏蔽层应两端接地。",),),),
    )
    write_pdf(
        root / "patrol.pdf",
        (
            (
                (72, 700, "5.2 巡视 DL/T 9000-2024 巡视周期为每季度一次。"),
                (72, 680, "5.3 记录 本条只要求记录。SECRET-OTHER-PAGE"),
            ),
        ),
    )
    (root / "notes.md").write_text(
        "4.1.2 接地电阻 DL/T 9000-2024 接地电阻不应大于4欧姆。SECRET-MARKDOWN\n",
        encoding="utf-8",
    )


def _terms(situation: str) -> tuple[str, ...]:
    if type(situation) is not str or len(situation) > _MAX_SITUATION:
        raise RegulationCitationError("regulation measures are unavailable")
    terms = tuple(part for part in situation.split() if part)
    if not terms or any(len(term) < 2 for term in terms):
        raise RegulationCitationError("regulation measures are unavailable")
    return terms


def _matching_clauses(
    spans: tuple[tuple[Mapping[str, object], str], ...],
    terms: tuple[str, ...],
) -> tuple[tuple[Mapping[str, object], ...], bool]:
    grouped: dict[str, list[tuple[Mapping[str, object], str]]] = {}
    order: list[str] = []
    for anchor, text in spans:
        document = str(anchor["document"])
        if document not in grouped:
            order.append(document)
            grouped[document] = []
        grouped[document].append((anchor, text))
    matched: list[Mapping[str, object]] = []
    for document in order:
        matched.extend(_file_measures(grouped[document], terms))
    measures = [item for item in matched if item["relation"] == "measure"]
    related = [item for item in matched if item["relation"] != "measure"]
    limited = len(measures) > _MAX_CLAUSES or len(related) > _MAX_CLAUSES
    return tuple([*measures[:_MAX_CLAUSES], *related[:_MAX_CLAUSES]]), limited


def _file_measures(
    spans: list[tuple[Mapping[str, object], str]],
    terms: tuple[str, ...],
) -> tuple[Mapping[str, object], ...]:
    ranges = _clause_ranges(spans)
    matched: list[tuple[int, int, str]] = []
    for start, end, clause_id in ranges:
        if all(term in _join(spans, start, end) for term in terms):
            matched.append((start, end, clause_id))
    chosen = _narrow(matched)
    rows: list[Mapping[str, object]] = []
    seen: set[tuple[int, str]] = set()
    for start, end, clause_id in chosen:
        text, list_children = _measure_text(spans, start, end, clause_id, terms)
        _add_row(rows, seen, spans, start, clause_id, "measure", text)
        parent = _parent_range(ranges, start, end, clause_id)
        if parent is not None:
            parent_start, _parent_end, parent_id = parent
            own_end = _own_end(spans, parent_start, _parent_end, parent_id)
            _add_row(
                rows,
                seen,
                spans,
                parent_start,
                parent_id,
                "parent",
                _join(spans, parent_start, own_end),
            )
        if list_children:
            for child_start, _child_end, child_id in _direct_children(
                ranges, start, end, clause_id
            ):
                _add_row(
                    rows,
                    seen,
                    spans,
                    child_start,
                    child_id,
                    "child",
                    _join(spans, child_start, _child_end),
                )
        skip = _contained_ids(ranges, start, end, clause_id)
        for ref_start, ref_end, ref_id in _referenced(text, ranges, skip):
            _add_row(
                rows,
                seen,
                spans,
                ref_start,
                ref_id,
                "reference",
                _join(spans, ref_start, ref_end),
            )
    pending = [row for row in rows if row["relation"] != "measure"]
    while pending:
        row = pending.pop(0)
        skip = {str(item["clause_id"]) for item in rows}
        for ref_start, ref_end, ref_id in _referenced(
            str(row["measures"]), ranges, skip
        ):
            before = len(rows)
            _add_row(
                rows,
                seen,
                spans,
                ref_start,
                ref_id,
                "reference",
                _join(spans, ref_start, ref_end),
            )
            if len(rows) > before:
                pending.append(rows[-1])
    return tuple(rows)


def _clause_ranges(
    spans: list[tuple[Mapping[str, object], str]],
) -> tuple[tuple[int, int, str], ...]:
    ranges: list[tuple[int, int, str]] = []
    index = 0
    while index < len(spans):
        heading = _heading_id(spans[index][1])
        if heading is None:
            index += 1
            continue
        cursor = index + 1
        while cursor < len(spans):
            child = _heading_id(spans[cursor][1])
            if child is not None and not child.startswith(heading + "."):
                break
            cursor += 1
        ranges.append((index, cursor, heading))
        index += 1
    return tuple(ranges)


def _narrow(
    matched: list[tuple[int, int, str]],
) -> tuple[tuple[int, int, str], ...]:
    chosen: list[tuple[int, int, str]] = []
    for item in matched:
        start, end = item[0], item[1]
        if any(
            other[0] >= start
            and other[1] <= end
            and (other[0] > start or other[1] < end)
            for other in matched
        ):
            continue
        chosen.append(item)
    return tuple(chosen)


def _measure_text(
    spans: list[tuple[Mapping[str, object], str]],
    start: int,
    end: int,
    clause_id: str,
    terms: tuple[str, ...],
) -> tuple[str, bool]:
    own = _join(spans, start, _own_end(spans, start, end, clause_id))
    if all(term in own for term in terms):
        return own, True
    return _join(spans, start, end), False


def _own_end(
    spans: list[tuple[Mapping[str, object], str]],
    start: int,
    end: int,
    clause_id: str,
) -> int:
    for cursor in range(start + 1, end):
        child = _heading_id(spans[cursor][1])
        if child is not None and child.startswith(clause_id + "."):
            return cursor
    return end


def _join(spans: list[tuple[Mapping[str, object], str]], start: int, end: int) -> str:
    return "".join(text for _anchor, text in spans[start:end])


def _parent_range(
    ranges: tuple[tuple[int, int, str], ...],
    start: int,
    end: int,
    clause_id: str,
) -> tuple[int, int, str] | None:
    parent: tuple[int, int, str] | None = None
    for candidate in ranges:
        parent_start, parent_end, parent_id = candidate
        inside = parent_start < start and parent_end >= end
        if inside and clause_id.startswith(parent_id + "."):
            if parent is None or parent_start > parent[0]:
                parent = candidate
    return parent


def _direct_children(
    ranges: tuple[tuple[int, int, str], ...],
    start: int,
    end: int,
    clause_id: str,
) -> tuple[tuple[int, int, str], ...]:
    prefix = clause_id + "."
    return tuple(
        candidate
        for candidate in ranges
        if start < candidate[0] < end
        and candidate[2].startswith(prefix)
        and "." not in candidate[2][len(prefix) :]
    )


def _contained_ids(
    ranges: tuple[tuple[int, int, str], ...],
    start: int,
    end: int,
    clause_id: str,
) -> set[str]:
    contained = {clause_id}
    for child_start, _child_end, child_id in ranges:
        if start < child_start < end and child_id.startswith(clause_id + "."):
            contained.add(child_id)
    return contained


def _referenced(
    text: str,
    ranges: tuple[tuple[int, int, str], ...],
    skip: set[str],
) -> tuple[tuple[int, int, str], ...]:
    found: list[tuple[int, int, str]] = []
    seen = set(skip)
    for match in _CLAUSE_REF.finditer(text):
        clause_id = match.group(1)
        if clause_id in seen:
            continue
        seen.add(clause_id)
        for candidate in ranges:
            if candidate[2] == clause_id:
                found.append(candidate)
                break
    return tuple(found)


def _add_row(
    rows: list[Mapping[str, object]],
    seen: set[tuple[int, str]],
    spans: list[tuple[Mapping[str, object], str]],
    start: int,
    clause_id: str,
    relation: str,
    text: str,
) -> None:
    key = (start, clause_id)
    if key in seen:
        return
    seen.add(key)
    anchor = spans[start][0]
    rows.append(
        {
            "document": str(anchor["document"]),
            "clause_id": clause_id,
            "relation": relation,
            "measures": text,
            "basis": anchor,
        }
    )


def _query_ready(query: RegulationQuery) -> bool:
    return (
        type(query.clause_id) is str
        and type(query.version) is str
        and type(query.finding) is str
        and bool(query.clause_id)
        and bool(query.version.strip())
        and bool(query.finding.strip())
        and _CLAUSE_ID.fullmatch(query.clause_id) is not None
    )


def _accepted_anchors(
    spans: tuple[tuple[Mapping[str, object], str], ...],
    query: RegulationQuery,
) -> tuple[Mapping[str, object], ...]:
    grouped: dict[str, list[tuple[Mapping[str, object], str]]] = {}
    order: list[str] = []
    for anchor, text in spans:
        document = str(anchor["document"])
        if document not in grouped:
            order.append(document)
            grouped[document] = []
        grouped[document].append((anchor, text))
    selected: list[Mapping[str, object]] = []
    for document in order:
        selected.extend(_file_anchors(grouped[document], query))
    return tuple(selected)


def _file_anchors(
    spans: list[tuple[Mapping[str, object], str]],
    query: RegulationQuery,
) -> tuple[Mapping[str, object], ...]:
    version = next(
        (anchor for anchor, text in spans if query.version in text),
        None,
    )
    if version is None:
        return ()
    wanted: set[tuple[object, ...]] = set()
    index = 0
    while index < len(spans):
        heading = _heading_id(spans[index][1])
        if heading != query.clause_id:
            index += 1
            continue
        cursor = index + 1
        while cursor < len(spans):
            child = _heading_id(spans[cursor][1])
            if child is not None and not child.startswith(heading + "."):
                break
            cursor += 1
        body = spans[index:cursor]
        overlapped = _finding_anchors(body, query.finding)
        if overlapped:
            wanted.add(_anchor_key(version))
            wanted.add(_anchor_key(body[0][0]))
            wanted.update(_anchor_key(item) for item in overlapped)
        index = cursor
    return tuple(anchor for anchor, _text in spans if _anchor_key(anchor) in wanted)


def _finding_anchors(
    body: list[tuple[Mapping[str, object], str]],
    finding: str,
) -> tuple[Mapping[str, object], ...]:
    joined = "".join(text for _anchor, text in body)
    start = joined.find(finding)
    if start < 0:
        return ()
    end = start + len(finding)
    offset = 0
    chosen: list[Mapping[str, object]] = []
    for anchor, text in body:
        span_end = offset + len(text)
        if offset < end and span_end > start:
            chosen.append(anchor)
        offset = span_end
    return tuple(chosen)


def _heading_id(text: str) -> str | None:
    stripped = text.strip()
    match = _CLAUSE_ID.match(stripped)
    if match is None:
        return None
    # A span that is only the number points at a clause. It does not start one.
    if not _HEADING_TAIL.sub("", stripped[match.end() :]):
        return None
    return match.group(1)


def _anchor_key(anchor: Mapping[str, object]) -> tuple[object, ...]:
    position = anchor["position"]
    items = position.items() if isinstance(position, Mapping) else ()
    return (
        anchor["document"],
        anchor["source_sha256"],
        anchor["kind"],
        tuple(sorted(items)),
        anchor["span_sha256"],
    )


def _invocation(
    corpus: Path, anchors: tuple[Mapping[str, object], ...]
) -> CapabilityInvocation:
    manifest = json.loads(
        resources.files("asterion.capabilities.dci")
        .joinpath("payload/capabilities/dci-research.json")
        .read_text(encoding="utf-8")
    )
    return CapabilityInvocation(
        capability_ref=CapabilityRef("dci.research", "1.0.0"),
        manifest=manifest,
        run_id="grid-regulation",
        input_text="cite the selected clause",
        upstream_artifacts=(),
        runtime=_DocumentRuntime(anchors),
        host_services={"corpus.local-root": _Corpus(corpus)},
    )


class _Corpus:
    def __init__(self, root: Path) -> None:
        self.root = root


class _DocumentRuntime:
    def __init__(self, anchors: tuple[Mapping[str, object], ...]) -> None:
        self._anchors = anchors

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del signal
        sequence = 1
        yield RunEvent(request.run_id, sequence, "run.started", {"capabilities": []})
        for index, anchor in enumerate(self._anchors, start=1):
            sequence += 1
            yield RunEvent(
                request.run_id,
                sequence,
                "tool.call",
                {
                    "call_id": f"c{index}",
                    "name": "document-read",
                    "arguments": {"anchor": dict(anchor)},
                },
            )
            sequence += 1
            yield RunEvent(
                request.run_id,
                sequence,
                "tool.result",
                {"call_id": f"c{index}", "output": "", "is_error": False},
            )
        sequence += 1
        yield RunEvent(
            request.run_id,
            sequence,
            "artifact.created",
            {
                "artifact": {
                    "artifact_id": "answer",
                    "kind": "answer",
                    "media_type": "text/plain",
                    "uri": "citation.txt",
                }
            },
        )
        sequence += 1
        yield RunEvent(
            request.run_id, sequence, "run.completed", {"status": "completed"}
        )
