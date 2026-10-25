"""Project one PDF or DOCX into lines a terminal agent can read."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

from asterion.documents.docx import (
    DocumentFormatError as DocxFormatError,
)
from asterion.documents.docx import docx_outline_depths
from asterion.documents.tools import (
    DocumentToolError,
    document_spans,
    read_span,
    verify_public_anchor,
)

PASSAGE_FILE = "passages.txt"
INDEX_FILE = "passage-index.json"
PROJECTION_SCHEMA = "asterion.document-projection/v1"
_MAX_LINE_CHARS = 8192
_MAX_PASSAGES = 999_999
_TRUNCATION = "\n[tool result truncated]"
_PASSAGE_ID = re.compile(r"^P[0-9]{6}$")
_DEPTH = re.compile(r"^H([123])$")


def project_document(
    source_root: Path,
    relative: str,
    destination: Path,
) -> Mapping[str, object]:
    """Write one file's passage view. Raise DocumentToolError on failure.

    No clause numbers are detected. No lines are dropped because of a query.
    """

    _empty_destination(source_root, destination)
    suffix = Path(relative).suffix.casefold()
    if suffix == ".docx":
        tools = "docx"
    elif suffix == ".pdf":
        tools = "pdf"
    else:
        raise DocumentToolError("document tool is unavailable")
    try:
        spans = document_spans(source_root, tools=tools, path=relative)
    except (OSError, ValueError):
        raise DocumentToolError("document tool is unavailable") from None
    if not spans:
        raise DocumentToolError("document tool is unavailable")
    depths = _outline_depths(source_root, relative, tools)
    index = _index(relative, _passages(spans, depths))
    _write(destination, relative, source_root, index)
    return index


def anchors_for_passage_read(
    corpus: Path,
    *,
    path: str,
    output: object,
    is_error: bool,
) -> tuple[Mapping[str, object], ...] | None:
    """Resolve one read of passages.txt.

    None means this corpus has no projection, or the path is not the passage
    file. An empty tuple is a projection read that failed or showed no line.
    """

    index_path = corpus / INDEX_FILE
    if not index_path.is_file():
        return None
    if path != PASSAGE_FILE:
        return None
    if is_error:
        return ()
    index = _load_index(index_path)
    shown = _complete_lines(_output_text(output))
    if not shown:
        raise DocumentToolError("document tool is unavailable")
    anchors: list[Mapping[str, object]] = []
    records = {item["id"]: item for item in index["passages"]}
    for line in shown:
        fields = line.split("\t")
        passage_id = fields[0]
        record = records.get(passage_id)
        if record is None or not isinstance(record, Mapping):
            raise DocumentToolError("document tool is unavailable")
        stored = record["anchors"]
        if not isinstance(stored, list) or not stored:
            raise DocumentToolError("document tool is unavailable")
        verified = tuple(
            verify_public_anchor(corpus, anchor)
            for anchor in stored
            if isinstance(anchor, Mapping)
        )
        if len(verified) != len(stored):
            raise DocumentToolError("document tool is unavailable")
        expected = [_flatten(read_span(corpus, anchor)) for anchor in verified]
        rest = fields[1:]
        depth = record.get("depth")
        if depth is not None:
            if rest[:1] != [f"H{depth}"]:
                raise DocumentToolError("document tool is unavailable")
            rest = rest[1:]
        if rest != expected:
            raise DocumentToolError("document tool is unavailable")
        anchors.extend(verified)
    return tuple(anchors)


def _outline_depths(source_root: Path, relative: str, tools: str) -> dict[int, int]:
    if tools != "docx":
        return {}
    try:
        return docx_outline_depths(source_root / relative)
    except (OSError, DocxFormatError, ValueError):
        raise DocumentToolError("document tool is unavailable") from None


def _passages(
    spans: Sequence[tuple[Mapping[str, object], str]],
    depths: Mapping[int, int],
) -> list[dict[str, object]]:
    passages: list[dict[str, object]] = []
    row_key: tuple[object, object] | None = None
    row: list[tuple[Mapping[str, object], str]] = []

    def flush() -> None:
        nonlocal row_key, row
        if row:
            passages.append(_row_passage(len(passages) + 1, row))
        row_key = None
        row = []

    for anchor, text in spans:
        kind = anchor["kind"]
        if kind == "docx-cell":
            position = anchor["position"]
            key = (position["table"], position["row"])
            if row_key != key:
                flush()
                row_key = key
            row.append((anchor, text))
            continue
        flush()
        depth = None
        if kind == "docx-paragraph":
            depth = depths.get(anchor["position"]["paragraph"])
        passages.append(_text_passage(len(passages) + 1, anchor, text, depth))
    flush()
    if len(passages) > _MAX_PASSAGES:
        raise DocumentToolError("document tool is unavailable")
    return passages


def _text_passage(
    number: int,
    anchor: Mapping[str, object],
    text: str,
    depth: int | None,
) -> dict[str, object]:
    unit = "pdf-line" if anchor["kind"] == "pdf-text" else "paragraph"
    record: dict[str, object] = {
        "id": _passage_id(number),
        "unit": unit,
        "anchors": [_relocated(anchor)],
    }
    if depth is not None:
        record["depth"] = depth
    _rendered(record, text, depth)
    return record


def _row_passage(
    number: int, cells: Sequence[tuple[Mapping[str, object], str]]
) -> dict[str, object]:
    record: dict[str, object] = {
        "id": _passage_id(number),
        "unit": "table-row",
        "anchors": [_relocated(anchor) for anchor, _text in cells],
    }
    _rendered(record, None, None, [text for _anchor, text in cells])
    return record


def _rendered(
    record: dict[str, object],
    text: str | None,
    depth: int | None,
    cells: Sequence[str] | None = None,
) -> None:
    fields = [str(record["id"])]
    if depth is not None:
        fields.append(f"H{depth}")
    if cells is None:
        fields.append(_flatten(text or ""))
    else:
        fields.extend(_flatten(cell) for cell in cells)
    line = "\t".join(fields)
    if len(line) > _MAX_LINE_CHARS:
        raise DocumentToolError("document tool is unavailable")
    record["line"] = line


def _index(origin: str, passages: Sequence[Mapping[str, object]]) -> dict[str, object]:
    stored: list[dict[str, object]] = []
    for passage in passages:
        item = {
            "id": passage["id"],
            "unit": passage["unit"],
            "anchors": passage["anchors"],
        }
        if "depth" in passage:
            item["depth"] = passage["depth"]
        stored.append(item)
    return {
        "schema": PROJECTION_SCHEMA,
        "origin": origin,
        "passage_file": PASSAGE_FILE,
        "passages": stored,
    }


def _write(
    destination: Path,
    origin: str,
    source_root: Path,
    index: Mapping[str, object],
) -> None:
    target = destination / "source" / origin
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_root / origin, target)
    payload = json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2)
    (destination / INDEX_FILE).write_text(payload + "\n", encoding="utf-8")
    text = "\n".join(_passage_lines(index, destination)) + "\n"
    (destination / PASSAGE_FILE).write_text(text, encoding="utf-8")


def _lines_of(index: Mapping[str, object]) -> list[Mapping[str, object]]:
    passages = index["passages"]
    if not isinstance(passages, list):
        raise DocumentToolError("document tool is unavailable")
    return [item for item in passages if isinstance(item, Mapping)]


def _passage_lines(index: Mapping[str, object], destination: Path) -> list[str]:
    """Rebuild passage lines from verified anchors so the text is not stored."""

    lines: list[str] = []
    for passage in _lines_of(index):
        anchors = passage["anchors"]
        if not isinstance(anchors, list):
            raise DocumentToolError("document tool is unavailable")
        fields = [str(passage["id"])]
        depth = passage.get("depth")
        if isinstance(depth, int):
            fields.append(f"H{depth}")
        fields.extend(
            _flatten(read_span(destination, anchor))
            for anchor in anchors
            if isinstance(anchor, Mapping)
        )
        line = "\t".join(fields)
        if len(line) > _MAX_LINE_CHARS:
            raise DocumentToolError("document tool is unavailable")
        lines.append(line)
    return lines


def _relocated(anchor: Mapping[str, object]) -> dict[str, object]:
    position = anchor["position"]
    return {
        "document": "source/" + str(anchor["document"]),
        "source_sha256": anchor["source_sha256"],
        "kind": anchor["kind"],
        "position": {key: position[key] for key in sorted(position)},
        "span_sha256": anchor["span_sha256"],
    }


def _passage_id(number: int) -> str:
    if number < 1 or number > _MAX_PASSAGES:
        raise DocumentToolError("document tool is unavailable")
    return f"P{number:06d}"


def _flatten(text: str) -> str:
    return (
        text.replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("\t", " ")
        .strip()
    )


def _empty_destination(source_root: Path, destination: Path) -> None:
    if (
        not destination.is_dir()
        or destination.is_symlink()
        or any(destination.iterdir())
    ):
        raise DocumentToolError("document tool is unavailable")
    root = source_root.resolve()
    dest = destination.resolve()
    if dest == root or root in dest.parents or dest in root.parents:
        raise DocumentToolError("document tool is unavailable")


def _load_index(path: Path) -> Mapping[str, object]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DocumentToolError("document tool is unavailable") from None
    if (
        not isinstance(loaded, dict)
        or loaded.get("schema") != PROJECTION_SCHEMA
        or loaded.get("passage_file") != PASSAGE_FILE
        or not isinstance(loaded.get("passages"), list)
    ):
        raise DocumentToolError("document tool is unavailable")
    return loaded


def _output_text(output: object) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, Mapping):
        content = output.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if (
                    isinstance(item, Mapping)
                    and item.get("type") == "text"
                    and isinstance(item.get("text"), str)
                ):
                    parts.append(item["text"])
            if parts:
                return "".join(parts)
    raise DocumentToolError("document tool is unavailable")


def _complete_lines(text: str) -> list[str]:
    if _TRUNCATION in text:
        prefix = text.split(_TRUNCATION, 1)[0]
        pieces = prefix.split("\n")
        if not prefix.endswith("\n"):
            pieces = pieces[:-1]
        elif pieces and pieces[-1] == "":
            pieces = pieces[:-1]
    else:
        pieces = text.split("\n")
        if pieces and pieces[-1] == "":
            pieces = pieces[:-1]
    shown: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        if _PASSAGE_ID.match(piece.split("\t", 1)[0]):
            shown.append(piece)
    return shown
