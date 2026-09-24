"""Immutable private per-game evidence and its scoreless host boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from typing import Protocol, runtime_checkable

_RUN_ID = re.compile(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*\Z")
_GAME_ID = re.compile(r"[A-Za-z0-9]+-[A-Za-z0-9]+\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UNSIGNED_FIELDS = frozenset(
    (
        "run_id",
        "game_id",
        "guid",
        "win_levels",
        "action_cap",
        "completed_level_count",
        "primitive_action_count",
        "sdk_state",
        "terminal_reason",
        "trace_sha256",
    )
)
_FIELDS = _UNSIGNED_FIELDS | {"evidence_sha256"}
_TERMINALS = frozenset(
    (
        "game-won",
        "game-incomplete",
        "game-over",
        "action-cap",
        "action-unavailable",
        "engine-uncertain",
        "engine-invalid",
    )
)


class PrimeArcAgi3GameplayEvidenceError(ValueError):
    """The private gameplay evidence is malformed or unsealed."""


def _validate_unsigned(value: object) -> None:
    invalid = "P7 gameplay evidence is invalid"
    if type(value) is not dict or frozenset(value) != _UNSIGNED_FIELDS:
        raise PrimeArcAgi3GameplayEvidenceError(invalid)
    for key, pattern in (
        ("run_id", _RUN_ID),
        ("game_id", _GAME_ID),
        ("trace_sha256", _DIGEST),
    ):
        if type(value[key]) is not str or pattern.fullmatch(value[key]) is None:
            raise PrimeArcAgi3GameplayEvidenceError(invalid)
    if (
        type(value["guid"]) is not str
        or not value["guid"]
        or len(value["guid"]) > 256
        or not value["guid"].isascii()
        or any(ord(char) <= 32 or ord(char) == 127 for char in value["guid"])
    ):
        raise PrimeArcAgi3GameplayEvidenceError(invalid)
    for key in (
        "win_levels",
        "action_cap",
        "completed_level_count",
        "primitive_action_count",
    ):
        if type(value[key]) is not int:
            raise PrimeArcAgi3GameplayEvidenceError(invalid)
    if not (
        1 <= value["win_levels"] <= 5000
        and 1 <= value["action_cap"] <= 5000
        and 0 <= value["completed_level_count"] <= value["win_levels"]
        and value["completed_level_count"]
        <= value["primitive_action_count"]
        <= value["action_cap"]
    ):
        raise PrimeArcAgi3GameplayEvidenceError(invalid)
    state, reason = value["sdk_state"], value["terminal_reason"]
    if (
        type(state) is not str
        or state not in {"NOT_PLAYED", "NOT_FINISHED", "WIN", "GAME_OVER"}
        or type(reason) is not str
        or reason not in _TERMINALS
    ):
        raise PrimeArcAgi3GameplayEvidenceError(invalid)
    won = state == "WIN" and value["completed_level_count"] == value["win_levels"]
    if (
        (reason == "game-won") != won
        or state == "WIN"
        and not won
        or reason == "game-over"
        and state != "GAME_OVER"
        or reason == "action-cap"
        and value["primitive_action_count"] != value["action_cap"]
        or reason == "game-incomplete"
        and value["completed_level_count"] != value["win_levels"]
    ):
        raise PrimeArcAgi3GameplayEvidenceError(invalid)


def canonical_gameplay_evidence_sha256(unsigned: object) -> str:
    """Seal exact validated private evidence with deterministic JSON."""
    _validate_unsigned(unsigned)
    encoded = json.dumps(
        unsigned, allow_nan=False, separators=(",", ":"), sort_keys=True
    )
    return "sha256:" + sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PrimeArcAgi3GameplayEvidence:
    run_id: str
    game_id: str
    guid: str = field(repr=False)
    win_levels: int
    action_cap: int
    completed_level_count: int
    primitive_action_count: int
    sdk_state: str
    terminal_reason: str
    trace_sha256: str = field(repr=False)
    evidence_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        unsigned = {name: getattr(self, name) for name in _UNSIGNED_FIELDS}
        object.__setattr__(
            self, "evidence_sha256", canonical_gameplay_evidence_sha256(unsigned)
        )

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        game_id: str,
        guid: str,
        win_levels: int,
        action_cap: int,
        completed_level_count: int,
        primitive_action_count: int,
        sdk_state: str,
        terminal_reason: str,
        trace_sha256: str,
    ) -> PrimeArcAgi3GameplayEvidence:
        return cls(
            run_id,
            game_id,
            guid,
            win_levels,
            action_cap,
            completed_level_count,
            primitive_action_count,
            sdk_state,
            terminal_reason,
            trace_sha256,
        )

    @property
    def outcome(self) -> str:
        return "game-won" if self.terminal_reason == "game-won" else "failed"


def validate_prime_arc_agi_3_gameplay_evidence(evidence: object) -> None:
    """Reject altered values and extra fields before public projection."""
    if (
        type(evidence) is not PrimeArcAgi3GameplayEvidence
        or frozenset(vars(evidence)) != _FIELDS
    ):
        raise PrimeArcAgi3GameplayEvidenceError("P7 gameplay evidence is invalid")
    unsigned = {name: getattr(evidence, name) for name in _UNSIGNED_FIELDS}
    expected = canonical_gameplay_evidence_sha256(unsigned)
    if (
        type(evidence.evidence_sha256) is not str
        or evidence.evidence_sha256 != expected
    ):
        raise PrimeArcAgi3GameplayEvidenceError("P7 gameplay evidence is invalid")


@runtime_checkable
class PrimeArcAgi3GameplayEvidenceAccessor(Protocol):
    def get_evidence(
        self,
        *,
        run_id: str,
        evidence_sha256: str,
    ) -> PrimeArcAgi3GameplayEvidence: ...


__all__ = (
    "PrimeArcAgi3GameplayEvidence",
    "PrimeArcAgi3GameplayEvidenceAccessor",
    "PrimeArcAgi3GameplayEvidenceError",
    "canonical_gameplay_evidence_sha256",
    "validate_prime_arc_agi_3_gameplay_evidence",
)
