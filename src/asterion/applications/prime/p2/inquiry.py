"""Model-written P2 queries. The corpus scanner stays in this application.

Prime stores the accepted note. It does not choose bounds, read the corpus,
or accept an answer whose fragment identity disagrees with the slice.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Protocol

from asterion.agents.prime.memory import ResearchMemoryStore
from asterion.agents.prime.research_notes import ResearchNotes
from asterion.applications.prime.p2.context_service import (
    P2ContextService,
    P2ContextServiceError,
)
from asterion.applications.prime.p2.task import P2_TASK_STATEMENT
from asterion.applications.prime.p2.worker import P2ContextServiceWorker


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_POINTER = "asterion.p2-notes-epoch/v1"
_MAX_ANSWER_BYTES = 4096


class P2InquiryError(ValueError):
    def __init__(self) -> None:
        super().__init__("P2 inquiry rejected")


class P2InquiryModel(Protocol):
    """The model writes both turns. The host only carries them out."""

    def write_query(self, task: str) -> Mapping: ...

    def write_answer(self, task: str, fragment: Mapping) -> Mapping: ...


@dataclass(frozen=True, slots=True)
class P2InquiryResult:
    status: str
    operation: str
    bounds: tuple[int, int]
    fragment_sha256: str
    notes_revision: str

    def __post_init__(self) -> None:
        if (
            self.status != "verified"
            or self.operation not in {"retrieve", "transform"}
            or type(self.bounds) is not tuple
            or len(self.bounds) != 2
            or self.bounds[0] > self.bounds[1]
            or _DIGEST.fullmatch(self.fragment_sha256) is None
            or not self.notes_revision.startswith("sha256:")
        ):
            raise P2InquiryError()

    def __repr__(self) -> str:
        return "<P2InquiryResult redacted>"


def _query(value: object) -> tuple[str, tuple[int, int], tuple[str, ...]]:
    if type(value) is not dict:
        raise P2InquiryError()
    operation = value.get("operation")
    bounds = value.get("bounds")
    if operation == "retrieve" and set(value) != {"operation", "bounds"}:
        raise P2InquiryError()
    if operation == "transform" and set(value) != {"operation", "bounds", "select_keys"}:
        raise P2InquiryError()
    if operation not in {"retrieve", "transform"}:
        raise P2InquiryError()
    if (
        type(bounds) not in (list, tuple)
        or len(bounds) != 2
        or any(type(part) is not int or part < 0 for part in bounds)
        or bounds[0] > bounds[1]
    ):
        raise P2InquiryError()
    if operation == "retrieve":
        return operation, (bounds[0], bounds[1]), ()
    keys = value["select_keys"]
    if (
        type(keys) not in (list, tuple)
        or not 1 <= len(keys) <= 16
        or any(type(key) is not str or not key or len(key) > 64 for key in keys)
    ):
        raise P2InquiryError()
    return operation, (bounds[0], bounds[1]), tuple(keys)


def _answer(value: object, fragment_sha256: str) -> str:
    if type(value) is not dict or set(value) != {"text", "fragment_sha256"}:
        raise P2InquiryError()
    text, cited = value["text"], value["fragment_sha256"]
    if type(text) is not str or not text.strip() or type(cited) is not str:
        raise P2InquiryError()
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError:
        raise P2InquiryError() from None
    if size > _MAX_ANSWER_BYTES or _DIGEST.fullmatch(cited) is None or cited != fragment_sha256:
        raise P2InquiryError()
    return text


def _pointer(root: Path) -> str | None:
    path = root / "accepted.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError, UnicodeError):
        raise P2InquiryError() from None
    if (
        type(value) is not dict
        or set(value) != {"version", "revision"}
        or value["version"] != _POINTER
        or type(value["revision"]) is not str
    ):
        raise P2InquiryError()
    return value["revision"]


def _commit(root: Path, revision: str) -> None:
    path = root / "accepted.json"
    temporary = path.with_name(path.name + ".tmp")
    payload = json.dumps(
        {"version": _POINTER, "revision": revision},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run_model_inquiry(
    *,
    service: P2ContextService,
    model: P2InquiryModel,
    notes_root: Path,
) -> P2InquiryResult:
    """Run one model query against the operator corpus and commit the answer."""
    if type(service) is not P2ContextService or not callable(getattr(model, "write_query", None)):
        raise P2InquiryError()
    if not callable(getattr(model, "write_answer", None)):
        raise P2InquiryError()
    root = Path(notes_root)
    if root.is_symlink():
        raise P2InquiryError()
    root.mkdir(parents=True, exist_ok=True)
    worker = P2ContextServiceWorker(service)
    scope = {
        "application_id": "prime.programmatic-long-context",
        "corpus_sha256": worker.corpus_sha256,
    }
    try:
        store = ResearchMemoryStore(root=root / "memory", scope=scope)
        notes = ResearchNotes(store, accepted_revision=_pointer(root))
        operation, bounds, keys = _query(model.write_query(P2_TASK_STATEMENT))
        slice_ = (
            service.retrieve(bounds=bounds)
            if operation == "retrieve"
            else service.transform(select_keys=keys, bounds=bounds)
        )
    except P2ContextServiceError:
        raise P2InquiryError() from None
    fragment = {
        "operation": slice_.operation,
        "bounds": [slice_.bounds[0], slice_.bounds[1]],
        "records": [dict(record) for record in slice_.payload],
        "fragment_sha256": slice_.payload_sha256,
    }
    text = _answer(model.write_answer(P2_TASK_STATEMENT, fragment), slice_.payload_sha256)
    saved = notes.save(
        text,
        evidence_refs=[{
            "fragment_sha256": slice_.payload_sha256,
            "operation": slice_.operation,
            "bounds": [slice_.bounds[0], slice_.bounds[1]],
        }],
    )
    _commit(root, saved["revision"])
    return P2InquiryResult(
        status="verified",
        operation=slice_.operation,
        bounds=slice_.bounds,
        fragment_sha256=slice_.payload_sha256,
        notes_revision=saved["revision"],
    )


__all__ = (
    "P2InquiryError",
    "P2InquiryModel",
    "P2InquiryResult",
    "run_model_inquiry",
)
