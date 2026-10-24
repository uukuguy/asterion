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
    match = _CLAUSE_ID.match(text.strip())
    if match is None:
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
