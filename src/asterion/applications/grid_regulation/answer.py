"""Answer one regulation question from passages a research run actually opened."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Protocol

from asterion.applications.grid_regulation.live import GRID_MAX_TURNS
from asterion.applications.grid_regulation.retrieve import (
    RegulationCitationError,
    _heading_id,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.dci.implementation.implementation import (
    DciLocalResearchImplementation,
)
from asterion.capabilities.dci.implementation.research.directive import (
    OutlineEntry,
    apply_corpus_directive,
)
from asterion.capabilities.execution import CapabilityInvocation
from asterion.documents import DocumentToolError, project_document, read_span
from asterion.runtime.host import CancellationSignal, RunEvent


_MAX_SITUATION = 200
_TOOLS = frozenset({"docx", "pdf", "docx,pdf"})
_REPLY = "示范答复：按打开的行处理，并见所引位置。"
_PASSAGE_NAME = "passages.txt"


@dataclass(frozen=True)
class FaultAnswer:
    document: str
    reply: str
    evidence: tuple[Mapping[str, object], ...]
    calls: tuple[str, ...]


class GridResearch(Protocol):
    async def run(
        self,
        *,
        corpus: Path,
        prompt: str,
        signal: CancellationSignal | None,
    ) -> tuple[str, Mapping[str, object], tuple[str, ...]]:
        """Return answer text, locations, and call names."""


class RegulationDirective:
    """Regulation directory and reading rules. The chain does not interpret them."""

    def navigation(self, outline: Sequence[OutlineEntry]) -> str:
        if not outline:
            return ""
        lines = []
        for entry in outline:
            end = int(entry.passage_id[1:]) + entry.following_lines
            lines.append(
                f"{entry.passage_id}\tH{entry.depth}\t{entry.title}\t"
                f"opening-ends P{end:06d}"
            )
        return "\n".join(lines) + "\n"

    def instruction(self, *, document: str, question: str) -> str:
        return fault_prompt(document, question)


def fault_prompt(document: str, question: str) -> str:
    """Task text for one selected regulation. It is not an artifact or a log line."""

    return "\n".join(
        (
            "Read this one regulation the way a person turns its pages.",
            f"File: {document}",
            f"Question: {question}",
            (
                "Start with contents.txt. It is the directory for this file: "
                "heading passage ids, outline depth, and titles. Use it to "
                "choose where to read. Then read passages.txt. Do not search "
                "any other tree. Do not open source/ or passage-index.json to "
                "answer. contents.txt is not a source passage."
            ),
            (
                "Each line is P######, then a TAB, then one paragraph, one "
                "whole table row, or one PDF line. A styled heading paragraph "
                "has H1, H2, or H3 in the next field. That token is outline "
                "depth, not a clause id. A table row's cells are left to right, "
                "TAB-separated, and stay one passage. Read a row as one "
                "condition inside a section, 条件 → 处置 or 条件1 / 条件2 → "
                "处置. The row is not the whole requirement."
            ),
            (
                "A hit line is partial. Before using it, read the leaf that "
                "contains it. A leaf starts at an Hn heading and runs through "
                "the line before the next heading of depth n or less, and only "
                "when no deeper heading appears in that span. If a deeper "
                "heading appears, read the child leaf that contains the hit, "
                "from that child heading through the line before the next "
                "heading of equal or higher rank. Read every paragraph and "
                "every table row in the leaf. A heading with no H token is "
                "still a heading when its text is a numbered title; use the "
                "same span rule."
            ),
            (
                "The leaf is the requirement for the named equipment. It is "
                "not the whole answer. After the leaf is open, read the opening "
                "of each ancestor heading: the lines under that heading before "
                "its first child. Also search the front of the file for "
                "requirements that name the same class of equipment and do not "
                "name only this one device. Read each of those passages in "
                "full. A chapter opening is not a substitute for the leaf, and "
                "the leaf is not a substitute for the chapter opening. Combine "
                "them. Follow a citation with another search only when this "
                "question depends on that cited passage, then read that "
                "passage the same way."
            ),
            (
                "Search with rg -n through bash. Use pipelines when more than "
                "one clue is in play. The six digits in P###### are the "
                "1-based file line number of that passage. Take that line "
                "number from rg -n, or strip P and read the six digits as a "
                "base-10 integer. That number is not the read offset. Do not "
                "guess a line number from the order of hits. Do not pass those "
                "six digits as the read offset. Search output is not an "
                "opened passage. Do not use sed, awk, head, grep, or echo to "
                "print passages.txt."
            ),
            (
                "Read hits with the read tool. The read tool is the only way "
                "a passage is opened. The read offset is that line "
                "number minus at least one, and never below 1, so the previous "
                "line is inside the window when one exists. One read covers "
                "the leaf, the ancestor opening, or the cited passage being "
                "opened. Set limit to that span's line count. If the result "
                "ends with [tool result truncated], continue that same span "
                "from the first unread line. Do not set offset to the hit "
                "itself when the heading is the line above. Do not read the "
                "whole file."
            ),
            (
                "A clause number or chapter number inside a line that was "
                "opened is a citation, not the answer. Search that number "
                "only when this question depends on it, then read it with "
                "offset equal to that line number minus at least one, and "
                "never below 1."
            ),
            (
                "A clause number in the question is not the search key. Search "
                "the equipment and the fault. Do not open a line only because "
                "the question named its number."
            ),
            (
                f"This run allows {GRID_MAX_TURNS} tool turns. Write the "
                "answer as soon as each leaf this question needs, each "
                "ancestor opening, and the class rules this question needs "
                "are open. Leave passages this question does not depend on "
                "unread. Write the answer only from lines actually returned "
                "by read, and only after each leaf the answer depends on has "
                "been read through. If this file does not state a handling, "
                "say so. Do "
                "not invent a handling and do not import a rule from another "
                "edition. A name in the question may not match the file. "
                "Continue with a shorter fragment, or with a spelling that "
                "already appears in a line of this file, then read to confirm "
                "it is the same object. Do not introduce a name that this file "
                "has not shown."
            ),
            (
                "Write the answer in Chinese Markdown. The answer is what "
                "this regulation requires for the question. It is not a "
                "description of the passages you opened, and it is not a "
                "catalogue of related clauses. The desk lists every opened "
                "passage under its section heading, so do not retell those "
                "passages. The first paragraph must stand alone as the "
                "answer: what changes, which limits or actions apply, and "
                "to which equipment. Then write the handling in the file's "
                "order. Use paragraphs for prose. When the handling is a "
                "table, write that table in Markdown, header row included, "
                "with only the rows this question needs. Bold the handling "
                "and each numeric limit. Put a clause number in parentheses "
                "after the statement it supports. Do not use a clause number "
                "as a heading or as the subject of a sentence. Do not "
                "narrate the search in English or in Chinese. Do not write "
                "passage ids, tool names, or file names."
            ),
        )
    )


async def answer_fault(
    source_root: Path,
    *,
    document: str,
    question: str,
    research: GridResearch,
    document_tools: str,
    signal: CancellationSignal | None = None,
) -> FaultAnswer:
    """Project one file, run research, and render the reply and its evidence."""

    _check(document, question, document_tools)
    destination = Path(tempfile.mkdtemp(prefix="asterion-grid-"))
    try:
        os.chmod(destination, 0o700)
        project_document(source_root, document, destination)
        prompt = apply_corpus_directive(
            destination,
            RegulationDirective(),
            document=document,
            question=question,
        )
        reply, locations, calls = await research.run(
            corpus=destination,
            prompt=prompt,
            signal=signal,
        )
        return _render(source_root, document, reply, locations, calls, destination)
    except RegulationCitationError:
        raise
    except Exception:
        raise RegulationCitationError("regulation measures are unavailable") from None
    finally:
        shutil.rmtree(destination, ignore_errors=True)


class ScriptedGridResearch:
    """Replay a fixed tool sequence through the real research recorder.

    This object does not start Pi. ``passage_lines`` are 1-based lines of
    ``passages.txt`` to read after one bash call. An empty sequence reads nothing.
    """

    def __init__(
        self,
        reply: str = _REPLY,
        *,
        passage_lines: tuple[int, ...] = (3, 2),
    ) -> None:
        self.reply = reply
        self.passage_lines = passage_lines
        self.corpus: Path | None = None
        self.prompt = ""
        self.input_text = ""
        self.mode = 0
        self.contents: str | None = None
        self.result: object = None

    async def run(
        self,
        *,
        corpus: Path,
        prompt: str,
        signal: CancellationSignal | None,
    ) -> tuple[str, Mapping[str, object], tuple[str, ...]]:
        self.corpus = corpus
        self.prompt = prompt
        self.mode = corpus.stat().st_mode & 0o777
        contents = corpus / "contents.txt"
        self.contents = (
            contents.read_text(encoding="utf-8") if contents.is_file() else None
        )
        lines = (corpus / _PASSAGE_NAME).read_text(encoding="utf-8").splitlines()
        tools: list[tuple[str, dict[str, object], object, bool]] = [
            ("bash", {"command": "rg -n passages.txt"}, lines[0], False)
        ]
        for number in self.passage_lines:
            if number < 1 or number > len(lines):
                raise IndexError(number)
            tools.append(
                ("read", {"path": "passages.txt"}, lines[number - 1] + "\n", False)
            )
        runtime = _ToolStream(tuple(tools))
        try:
            result = await DciLocalResearchImplementation().execute(
                _invocation(corpus, prompt, runtime, signal)
            )
        finally:
            if runtime.requests:
                self.input_text = runtime.requests[0].input_text
        self.result = result
        locations = result.artifacts[1]["value"]
        calls = result.artifacts[2]["value"]["calls"]
        if not isinstance(locations, Mapping) or not isinstance(calls, tuple):
            raise RegulationCitationError("regulation measures are unavailable")
        return self.reply, locations, calls


class UnavailableResearch:
    """Refuse the desk question. This object does not start Pi."""

    async def run(
        self,
        *,
        corpus: Path,
        prompt: str,
        signal: CancellationSignal | None,
    ) -> tuple[str, Mapping[str, object], tuple[str, ...]]:
        del corpus, prompt, signal
        raise RegulationCitationError("regulation measures are unavailable")


def _check(document: object, question: object, document_tools: object) -> None:
    if (
        type(question) is not str
        or type(document) is not str
        or type(document_tools) is not str
    ):
        raise RegulationCitationError("request is invalid")
    if document == "" or document_tools not in _TOOLS:
        raise RegulationCitationError("request is invalid")
    if question.strip() == "" or len(question) > _MAX_SITUATION:
        raise RegulationCitationError("regulation measures are unavailable")
    if not _relative(document):
        raise RegulationCitationError("regulation measures are unavailable")
    suffix = Path(document).suffix.casefold()
    kind = {".docx": "docx", ".pdf": "pdf"}.get(suffix)
    if kind is None or kind not in document_tools.split(","):
        raise RegulationCitationError("regulation measures are unavailable")


def _relative(value: str) -> bool:
    if value != value.strip() or "\\" in value or value.startswith("./"):
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _render(
    source_root: Path,
    document: str,
    reply: object,
    locations: object,
    calls: object,
    projection: Path,
) -> FaultAnswer:
    if type(reply) is not str or not isinstance(locations, Mapping):
        raise RegulationCitationError("regulation measures are unavailable")
    if not isinstance(calls, tuple) or not all(type(name) is str for name in calls):
        raise RegulationCitationError("regulation measures are unavailable")
    raw = locations.get("anchors")
    if not isinstance(raw, tuple) or not raw:
        raise RegulationCitationError("regulation measures are unavailable")
    chosen = _dedupe(document, raw)
    if not chosen:
        raise RegulationCitationError("regulation measures are unavailable")
    try:
        evidence = _evidence(source_root, chosen, _section_titles(projection))
    except (DocumentToolError, OSError, TypeError, ValueError):
        raise RegulationCitationError("regulation measures are unavailable") from None
    text = reply[:-1] if reply.endswith("\n") else reply
    return FaultAnswer(document, text, evidence, calls)


def _dedupe(document: str, anchors: tuple[object, ...]) -> list[dict[str, object]]:
    seen: set[tuple[object, ...]] = set()
    chosen: list[dict[str, object]] = []
    prefix = "source/" + document
    for anchor in anchors:
        if not isinstance(anchor, Mapping) or anchor.get("document") != prefix:
            raise RegulationCitationError("regulation measures are unavailable")
        kind = anchor.get("kind")
        position = anchor.get("position")
        source = anchor.get("source_sha256")
        span = anchor.get("span_sha256")
        if (
            type(kind) is not str
            or not isinstance(position, Mapping)
            or type(source) is not str
            or type(span) is not str
        ):
            raise RegulationCitationError("regulation measures are unavailable")
        copied = {key: position[key] for key in sorted(position)}
        identity = (document, kind, tuple(sorted(copied.items())), span)
        if identity in seen:
            continue
        seen.add(identity)
        chosen.append(
            {
                "document": document,
                "source_sha256": source,
                "kind": kind,
                "position": copied,
                "span_sha256": span,
            }
        )
    return chosen


def _evidence(
    source_root: Path,
    chosen: Sequence[Mapping[str, object]],
    titles: Mapping[tuple[object, ...], str],
) -> tuple[Mapping[str, object], ...]:
    evidence: list[dict[str, object]] = []
    index = 0
    while index < len(chosen):
        anchor = chosen[index]
        if anchor["kind"] == "docx-cell":
            position = anchor["position"]
            if not isinstance(position, Mapping):
                raise RegulationCitationError("regulation measures are unavailable")
            table = position.get("table")
            row = position.get("row")
            run = [anchor]
            cursor = index + 1
            while cursor < len(chosen):
                nxt = chosen[cursor]
                nxt_position = nxt["position"]
                if (
                    nxt["kind"] != "docx-cell"
                    or not isinstance(nxt_position, Mapping)
                    or nxt_position.get("table") != table
                    or nxt_position.get("row") != row
                ):
                    break
                run.append(nxt)
                cursor += 1
            label = _row_label(source_root, run)
            evidence.extend(
                _item(
                    item, label, read_span(source_root, item), titles.get(_place(item))
                )
                for item in run
            )
            index = cursor
            continue
        text = read_span(source_root, anchor)
        evidence.append(
            _item(anchor, _heading_id(text), text, titles.get(_place(anchor)))
        )
        index += 1
    return tuple(evidence)


def _row_label(source_root: Path, run: Sequence[Mapping[str, object]]) -> str | None:
    ordered = sorted(
        run,
        key=lambda item: _cell(item),
    )
    for item in ordered:
        label = _heading_id(read_span(source_root, item))
        if label is not None:
            return label
    return None


def _cell(item: Mapping[str, object]) -> int:
    position = item["position"]
    if not isinstance(position, Mapping):
        return 0
    cell = position.get("cell")
    return cell if type(cell) is int else 0


def _item(
    anchor: Mapping[str, object],
    label: str | None,
    text: str,
    heading: str | None = None,
) -> dict[str, object]:
    if type(text) is not str:
        raise RegulationCitationError("regulation measures are unavailable")
    item = {
        "document": anchor["document"],
        "kind": anchor["kind"],
        "position": anchor["position"],
        "text": text,
    }
    if type(label) is str:
        item["label"] = label
    if type(heading) is str and heading != "":
        item["heading"] = heading
    return item


def _section_titles(projection: Path) -> dict[tuple[object, ...], str]:
    """Map each passage anchor to the outline path that contains it."""

    try:
        loaded = json.loads(
            (projection / "passage-index.json").read_text(encoding="utf-8")
        )
        lines = (projection / "passages.txt").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    passages = loaded.get("passages") if isinstance(loaded, dict) else None
    if not isinstance(passages, list) or len(passages) != len(lines):
        return {}
    stack: list[tuple[int, str]] = []
    found: dict[tuple[object, ...], str] = {}
    for passage, line in zip(passages, lines, strict=True):
        if not isinstance(passage, Mapping):
            continue
        depth = passage.get("depth")
        if type(depth) is int and depth in (1, 2, 3):
            title = _line_title(line, depth)
            if title:
                while stack and stack[-1][0] >= depth:
                    stack.pop()
                stack.append((depth, title))
        if not stack:
            continue
        path = " / ".join(title for _depth, title in stack)
        anchors = passage.get("anchors")
        if not isinstance(anchors, list):
            continue
        for anchor in anchors:
            if not isinstance(anchor, Mapping):
                continue
            place = _place(anchor)
            if place:
                found[place] = path
    return found


def _line_title(line: str, depth: int) -> str:
    fields = line.split("\t")
    if len(fields) < 3 or fields[1] != f"H{depth}":
        return ""
    return "\t".join(fields[2:]).strip()


def _place(anchor: Mapping[str, object]) -> tuple[object, ...]:
    kind = anchor.get("kind")
    position = anchor.get("position")
    if type(kind) is not str or not isinstance(position, Mapping):
        return ()
    if any(type(position[key]) is not int for key in position):
        return ()
    pairs = tuple(sorted((str(key), position[key]) for key in position))
    return (kind, pairs)


class _Corpus:
    def __init__(self, root: Path) -> None:
        self.root = root


class _ToolStream:
    def __init__(
        self, tools: tuple[tuple[str, dict[str, object], object, bool], ...]
    ) -> None:
        self.tools = tools
        self.requests: list[object] = []

    async def run(
        self,
        request: object,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del signal
        self.requests.append(request)
        sequence = 1
        run_id = getattr(request, "run_id")
        yield RunEvent(run_id, sequence, "run.started", {"capabilities": []})
        for index, (name, arguments, output, is_error) in enumerate(
            self.tools, start=1
        ):
            call_id = f"c{index}"
            sequence += 1
            yield RunEvent(
                run_id,
                sequence,
                "tool.call",
                {"call_id": call_id, "name": name, "arguments": arguments},
            )
            sequence += 1
            yield RunEvent(
                run_id,
                sequence,
                "tool.result",
                {"call_id": call_id, "output": output, "is_error": is_error},
            )
        sequence += 1
        yield RunEvent(
            run_id,
            sequence,
            "artifact.created",
            {
                "artifact": {
                    "artifact_id": "answer",
                    "kind": "answer",
                    "media_type": "text/plain",
                    "uri": "final.txt",
                }
            },
        )
        sequence += 1
        yield RunEvent(run_id, sequence, "run.completed", {"status": "completed"})


def _invocation(
    corpus: Path,
    prompt: str,
    runtime: _ToolStream,
    signal: CancellationSignal | None,
) -> CapabilityInvocation:
    manifest = json.loads(
        resources.files("asterion.capabilities.dci")
        .joinpath("payload/capabilities/dci-research.json")
        .read_text(encoding="utf-8")
    )
    return CapabilityInvocation(
        capability_ref=CapabilityRef("dci.research", "1.0.0"),
        manifest=manifest,
        run_id="grid-scripted",
        input_text=prompt,
        upstream_artifacts=(),
        runtime=runtime,
        host_services={"corpus.local-root": _Corpus(corpus)},
        signal=signal,
    )
