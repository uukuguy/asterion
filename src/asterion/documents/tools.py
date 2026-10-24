"""Select and resolve corpus-relative PDF and DOCX citation anchors."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from asterion.documents.docx import docx_spans
from asterion.documents.pdf import pdf_spans

_KINDS = ("docx", "pdf")
_ANCHOR_KINDS = ("docx-cell", "docx-paragraph", "pdf-text")
_ANCHOR_KEYS = ("document", "kind", "position", "source_sha256", "span_sha256")
_MAX_FILE_BYTES = 32 * 1024 * 1024
_MAX_HITS = 32


class DocumentToolError(ValueError):
    """Raised when a document tool request cannot be resolved."""


def parse_document_tools(value: str | None) -> tuple[str, ...]:
    """Return the enabled document kinds. Empty means plain files only."""

    if value is None or value == "":
        return ()
    if type(value) is not str:
        raise DocumentToolError("document tool configuration is invalid")
    parts = tuple(value.split(","))
    if (
        any(part not in _KINDS for part in parts)
        or len(set(parts)) != len(parts)
        or ",".join(kind for kind in _KINDS if kind in parts) != value
    ):
        raise DocumentToolError("document tool configuration is invalid")
    return tuple(kind for kind in _KINDS if kind in parts)


def search_documents(
    root: Path,
    query: str,
    *,
    tools: str | None,
    path: str | None = None,
) -> tuple[Mapping[str, object], ...]:
    """Return public anchors whose spans contain the query. No span text."""

    enabled = parse_document_tools(tools)
    if not enabled:
        raise DocumentToolError("document tool is unavailable")
    if type(query) is not str or not query.strip():
        raise DocumentToolError("document tool is unavailable")
    needle = query.strip()
    hits: list[Mapping[str, object]] = []
    for relative, file_path in _files(root, enabled, path):
        source_sha256 = _sha256(_read_bytes(file_path))
        for anchor, text in _spans(file_path, relative, source_sha256):
            if needle in text:
                hits.append(anchor)
                if len(hits) > _MAX_HITS:
                    raise DocumentToolError("document tool is unavailable")
    return tuple(hits)


def read_span(root: Path, anchor: Mapping[str, object]) -> str:
    """Re-read one verified anchor. The caller keeps the span private."""

    return _resolve(root, _public_anchor(anchor))[1]


def verify_public_anchor(
    root: Path, anchor: Mapping[str, object]
) -> Mapping[str, object]:
    """Return the anchor when its source and span digests still match."""

    public, _text = _resolve(root, _public_anchor(anchor))
    return public


def _resolve(
    root: Path, anchor: Mapping[str, object]
) -> tuple[Mapping[str, object], str]:
    file_path = _resolve_file(root, str(anchor["document"]))
    source_sha256 = _sha256(_read_bytes(file_path))
    if source_sha256 != anchor["source_sha256"]:
        raise DocumentToolError("document anchor is unavailable")
    for found, text in _spans(file_path, str(anchor["document"]), source_sha256):
        if found == anchor:
            return found, text
    raise DocumentToolError("document anchor is unavailable")


def _spans(
    file_path: Path, relative: str, source_sha256: str
) -> tuple[tuple[Mapping[str, object], str], ...]:
    suffix = file_path.suffix.casefold()
    try:
        if suffix == ".docx":
            extracted = docx_spans(file_path)
        elif suffix == ".pdf":
            extracted = pdf_spans(file_path)
        else:
            raise DocumentToolError("document tool is unavailable")
    except (OSError, ValueError):
        raise DocumentToolError("document tool is unavailable") from None
    return tuple(
        (
            _make_anchor(relative, source_sha256, kind, position, text),
            text,
        )
        for kind, position, text in extracted
        if text.strip()
    )


def _make_anchor(
    document: str,
    source_sha256: str,
    kind: str,
    position: Mapping[str, int],
    text: str,
) -> Mapping[str, object]:
    return {
        "document": document,
        "source_sha256": source_sha256,
        "kind": kind,
        "position": dict(position),
        "span_sha256": _sha256(text.encode()),
    }


def _public_anchor(value: Mapping[str, object]) -> Mapping[str, object]:
    if set(value) != set(_ANCHOR_KEYS):
        raise DocumentToolError("document anchor is unavailable")
    document = value["document"]
    kind = value["kind"]
    position = value["position"]
    source_sha256 = value["source_sha256"]
    span_sha256 = value["span_sha256"]
    if (
        not isinstance(document, str)
        or not _corpus_relative(document)
        or kind not in _ANCHOR_KINDS
        or not isinstance(position, Mapping)
        or not _sha256_text(source_sha256)
        or not _sha256_text(span_sha256)
        or not _position(kind, position)
    ):
        raise DocumentToolError("document anchor is unavailable")
    return {
        "document": document,
        "source_sha256": source_sha256,
        "kind": kind,
        "position": {key: position[key] for key in sorted(position)},
        "span_sha256": span_sha256,
    }


def _position(kind: str, position: Mapping[str, object]) -> bool:
    if kind == "docx-paragraph":
        keys = set(position)
        numbered = {"paragraph", "numbering_id", "numbering_level"}
        if keys != {"paragraph"} and keys != numbered:
            return False
    elif kind == "docx-cell":
        if set(position) != {"cell", "row", "table"}:
            return False
    elif set(position) != {"item", "page", "x", "y"}:
        return False
    if any(type(item) is not int for item in position.values()):
        return False
    if kind == "pdf-text":
        return position["page"] >= 1 and position["item"] >= 0
    if kind == "docx-paragraph":
        numbered = "numbering_id" in position
        return position["paragraph"] >= 0 and (
            not numbered
            or (position["numbering_level"] >= 0 and position["numbering_id"] >= 1)
        )
    return position["table"] >= 0 and position["row"] >= 0 and position["cell"] >= 0


def _files(
    root: Path, enabled: Sequence[str], only: str | None
) -> tuple[tuple[str, Path], ...]:
    suffixes = tuple(f".{kind}" for kind in enabled)
    if only is not None:
        if not _corpus_relative(only) or not only.casefold().endswith(suffixes):
            raise DocumentToolError("document tool is unavailable")
        return ((only, _resolve_file(root, only)),)
    found: list[tuple[str, Path]] = []
    root_resolved = root.resolve()
    for directory, dirnames, filenames in _walk(root):
        folder = Path(directory)
        kept: list[str] = []
        for name in dirnames:
            child = folder / name
            if not child.is_symlink():
                kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            candidate = folder / name
            if candidate.is_symlink() or not name.casefold().endswith(suffixes):
                continue
            resolved = candidate.resolve()
            try:
                relative = resolved.relative_to(root_resolved).as_posix()
            except ValueError:
                raise DocumentToolError("document anchor is unavailable") from None
            if _corpus_relative(relative):
                found.append((relative, resolved))
    found.sort()
    return tuple(found)


def _walk(root: Path):
    if not root.is_dir() or root.is_symlink():
        raise DocumentToolError("document tool is unavailable")
    return os.walk(root, followlinks=False)


def _resolve_file(root: Path, relative: str) -> Path:
    if not root.is_dir() or root.is_symlink() or not _corpus_relative(relative):
        raise DocumentToolError("document anchor is unavailable")
    candidate = root / relative
    if candidate.is_symlink():
        raise DocumentToolError("document anchor is unavailable")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise DocumentToolError("document anchor is unavailable") from None
    if not resolved.is_file():
        raise DocumentToolError("document anchor is unavailable")
    return resolved


def _read_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) > _MAX_FILE_BYTES:
        raise DocumentToolError("document tool is unavailable")
    return data


def _corpus_relative(value: str) -> bool:
    if not value or value != value.strip() or "\\" in value or value.startswith("./"):
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts and value not in {".", ""}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
