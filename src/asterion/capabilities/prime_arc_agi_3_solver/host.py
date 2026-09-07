"""Closed, public-safe receipt boundary for P7's finite solver action."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from typing import Protocol, runtime_checkable


_RUN_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SCORE = re.compile(r"(?:0|[1-9][0-9]{0,2})\.[0-9]{6}\Z")
_FIELDS: frozenset[str] = frozenset((
    "run_id", "scope", "promotion", "completed_level_count", "primitive_action_count",
    "partial_game_score", "receipt_sha256",
))
_UNSIGNED_FIELDS = _FIELDS - {"receipt_sha256"}


class PrimeArcAgi3SolveReceiptError(ValueError):
    """Raised when a public P7 solver receipt is malformed or unsealed."""


def canonical_solve_receipt_sha256(unsigned: object) -> str:
    """Hash exactly the public unsigned receipt schema using canonical JSON."""
    if type(unsigned) is not dict or frozenset(unsigned) != _UNSIGNED_FIELDS:
        raise PrimeArcAgi3SolveReceiptError("P7 solve receipt is invalid")
    try:
        encoded = json.dumps(unsigned, allow_nan=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        raise PrimeArcAgi3SolveReceiptError("P7 solve receipt is invalid") from None
    return "sha256:" + sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PrimeArcAgi3SolveReceipt:
    run_id: str
    scope: str
    promotion: str
    completed_level_count: int
    primitive_action_count: int
    partial_game_score: str
    receipt_sha256: str = field(init=False)

    @classmethod
    def create(
        cls, *, run_id: str, completed_level_count: int,
        primitive_action_count: int, partial_game_score: str,
    ) -> PrimeArcAgi3SolveReceipt:
        unsigned = {
            "run_id": run_id, "scope": "p7-solving", "promotion": "unpromoted",
            "completed_level_count": completed_level_count,
            "primitive_action_count": primitive_action_count,
            "partial_game_score": partial_game_score,
        }
        _validate_unsigned(unsigned)
        receipt = object.__new__(cls)
        for name, value in unsigned.items():
            object.__setattr__(receipt, name, value)
        object.__setattr__(receipt, "receipt_sha256", canonical_solve_receipt_sha256(unsigned))
        return receipt


def validate_prime_arc_agi_3_solve_receipt(receipt: object) -> None:
    """Validate an accessor return value before exposing its safe projection."""
    if type(receipt) is not PrimeArcAgi3SolveReceipt or frozenset(vars(receipt)) != _FIELDS:
        raise PrimeArcAgi3SolveReceiptError("P7 solve receipt is invalid")
    unsigned = {name: getattr(receipt, name) for name in _UNSIGNED_FIELDS}
    _validate_unsigned(unsigned)
    if (
        type(receipt.receipt_sha256) is not str
        or _DIGEST.fullmatch(receipt.receipt_sha256) is None
        or receipt.receipt_sha256 != canonical_solve_receipt_sha256(unsigned)
    ):
        raise PrimeArcAgi3SolveReceiptError("P7 solve receipt is invalid")


def _validate_unsigned(unsigned: object) -> None:
    if type(unsigned) is not dict or frozenset(unsigned) != _UNSIGNED_FIELDS:
        raise PrimeArcAgi3SolveReceiptError("P7 solve receipt is invalid")
    run_id = unsigned["run_id"]
    score = unsigned["partial_game_score"]
    if (
        type(run_id) is not str or _RUN_ID.fullmatch(run_id) is None
        or unsigned["scope"] != "p7-solving" or unsigned["promotion"] != "unpromoted"
        or type(unsigned["completed_level_count"]) is not int or unsigned["completed_level_count"] != 1
        or type(unsigned["primitive_action_count"]) is not int or unsigned["primitive_action_count"] < 0
        or type(score) is not str or _SCORE.fullmatch(score) is None
    ):
        raise PrimeArcAgi3SolveReceiptError("P7 solve receipt is invalid")
    try:
        if not Decimal("0.000000") <= Decimal(score) <= Decimal("100.000000"):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise PrimeArcAgi3SolveReceiptError("P7 solve receipt is invalid") from None


@runtime_checkable
class PrimeArcAgi3SolveReceiptAccessor(Protocol):
    def get_receipt(
        self, *, run_id: str, receipt_sha256: str
    ) -> PrimeArcAgi3SolveReceipt: ...


__all__ = (
    "PrimeArcAgi3SolveReceipt",
    "PrimeArcAgi3SolveReceiptAccessor",
    "PrimeArcAgi3SolveReceiptError",
    "canonical_solve_receipt_sha256",
    "validate_prime_arc_agi_3_solve_receipt",
)
