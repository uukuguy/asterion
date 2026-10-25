"""Application directory and task text for one projected corpus."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from asterion.documents.projection import INDEX_FILE, PASSAGE_FILE, PROJECTION_SCHEMA


CONTENTS_FILE = "contents.txt"


class CorpusDirectiveError(ValueError):
    """Raised when a projection cannot accept a corpus directive."""


@dataclass(frozen=True)
class OutlineEntry:
    """One styled heading in document order, without body text."""

    passage_id: str
    depth: int
    title: str
    following_lines: int


class CorpusDirective(Protocol):
    """Domain text for one projected file.

    ``navigation`` is written verbatim. ``instruction`` becomes the run input.
    The chain does not interpret either string.
    """

    def navigation(self, outline: Sequence[OutlineEntry]) -> str:
        """Directory text. Empty means the chain writes no directory file."""

    def instruction(self, *, document: str, question: str) -> str:
        """Task text. The chain does not wrap it."""


def apply_corpus_directive(
    projection: Path,
    directive: CorpusDirective,
    *,
    document: str,
    question: str,
) -> str:
    """Write a directory file when navigation is non-empty and return the task."""

    text = directive.navigation(_outline(projection))
    if type(text) is not str:
        raise CorpusDirectiveError("corpus directive is unavailable")
    if text:
        (projection / CONTENTS_FILE).write_text(text, encoding="utf-8")
    task = directive.instruction(document=document, question=question)
    if type(task) is not str or task == "":
        raise CorpusDirectiveError("corpus directive is unavailable")
    return task


def _outline(projection: Path) -> tuple[OutlineEntry, ...]:
    passages = _passages(projection)
    lines = _lines(projection)
    if len(lines) != len(passages):
        raise CorpusDirectiveError("corpus directive is unavailable")
    headings: list[tuple[int, str, int, str]] = []
    for index, passage in enumerate(passages):
        depth = passage.get("depth")
        if depth is None:
            continue
        if depth not in (1, 2, 3) or type(depth) is not int:
            raise CorpusDirectiveError("corpus directive is unavailable")
        fields = lines[index].split("\t")
        passage_id = passage.get("id")
        if (
            type(passage_id) is not str
            or len(fields) != 3
            or fields[0] != passage_id
            or fields[1] != f"H{depth}"
        ):
            raise CorpusDirectiveError("corpus directive is unavailable")
        headings.append((index, passage_id, depth, fields[2]))
    entries: list[OutlineEntry] = []
    for cursor, (index, passage_id, depth, title) in enumerate(headings):
        nxt = headings[cursor + 1][0] if cursor + 1 < len(headings) else len(passages)
        entries.append(OutlineEntry(passage_id, depth, title, nxt - index - 1))
    return tuple(entries)


def _passages(projection: Path) -> list[Mapping[str, object]]:
    try:
        loaded = json.loads((projection / INDEX_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise CorpusDirectiveError("corpus directive is unavailable") from None
    if (
        not isinstance(loaded, dict)
        or loaded.get("schema") != PROJECTION_SCHEMA
        or loaded.get("passage_file") != PASSAGE_FILE
        or not isinstance(loaded.get("passages"), list)
    ):
        raise CorpusDirectiveError("corpus directive is unavailable")
    passages = loaded["passages"]
    if not all(isinstance(item, Mapping) for item in passages):
        raise CorpusDirectiveError("corpus directive is unavailable")
    return list(passages)


def _lines(projection: Path) -> list[str]:
    try:
        text = (projection / PASSAGE_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise CorpusDirectiveError("corpus directive is unavailable") from None
    if text == "" or not text.endswith("\n"):
        raise CorpusDirectiveError("corpus directive is unavailable")
    return text.splitlines()
