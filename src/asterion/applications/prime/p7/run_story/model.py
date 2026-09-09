"""Immutable application-owned facts for one ARC-AGI-3 solve run."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType


SCHEMA = "asterion.prime.arc-agi-3-run-story/v1"


class RunStoryError(RuntimeError):
    """A run-story boundary failed without disclosing private evidence."""


@dataclass(frozen=True, repr=False, slots=True)
class FrameFact:
    index: int
    timestamp: str | None
    state: str
    levels_completed: int
    grid: tuple[tuple[int, ...], ...]
    sha256: str


@dataclass(frozen=True, repr=False, slots=True)
class ActionFact:
    index: int
    name: str
    before_frame: int
    after_frame: int
    before_sha256: str
    after_sha256: str
    levels_completed: int


@dataclass(frozen=True, repr=False, slots=True)
class ReasoningCellFact:
    index: int
    is_error: bool
    code_sha256: str
    output_sha256: str


@dataclass(frozen=True, repr=False, slots=True)
class RunEvidence:
    run_id: str
    game_id: str
    identities: Mapping[str, str]
    frames: tuple[FrameFact, ...]
    actions: tuple[ActionFact, ...]
    reasoning_cells: tuple[ReasoningCellFact, ...]
    score: str | None
    action_limit: int | None
    levels_completed: int
    terminal_reason: str
    verification: str
    replay_verified: bool
    sealed_trace: bool
    worker_cell_count: int
    usage: Mapping[str, int] | None
    source_digests: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "identities", MappingProxyType(dict(self.identities)))
        object.__setattr__(
            self, "source_digests", MappingProxyType(dict(self.source_digests))
        )
        if self.usage is not None:
            object.__setattr__(self, "usage", MappingProxyType(dict(self.usage)))

    def __repr__(self) -> str:
        return (
            f"RunEvidence(run_id={self.run_id!r}, game_id={self.game_id!r}, "
            f"actions={len(self.actions)}, frames={len(self.frames)}, "
            f"verification={self.verification!r})"
        )


def canonical_json(value: object) -> bytes:
    def plain(item: object) -> object:
        if isinstance(item, Mapping):
            return {key: plain(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [plain(child) for child in item]
        return item

    try:
        return (
            json.dumps(
                plain(value),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise RunStoryError("artifact-invalid") from None


def content_id(prefix: str, value: object) -> str:
    if type(prefix) is not str or not prefix:
        raise RunStoryError("artifact-invalid")
    return f"{prefix}-{sha256(canonical_json(value)).hexdigest()[:20]}"


__all__ = (
    "ActionFact",
    "FrameFact",
    "ReasoningCellFact",
    "RunEvidence",
    "RunStoryError",
    "SCHEMA",
    "canonical_json",
    "content_id",
)
