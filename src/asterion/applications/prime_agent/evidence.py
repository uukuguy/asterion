"""Closed, public-safe evidence claims for Prime capability scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final


PRIME_CAPABILITY_SCENARIO_IDS: Final = (
    "prime.arc-agi-3/v1",
    "prime.bounded-autonomy/v1",
    "prime.continual-improvement/v1",
    "prime.ipython-coding/v1",
    "prime.long-session-continuity/v1",
    "prime.programmatic-long-context/v1",
    "prime.recursive-workflow/v1",
)
_RECEIPT_FIELDS: Final = frozenset(
    {"scenario_id", "level", "status", "receipt_scenario_id"}
)


class PrimeCapabilityEvidenceError(ValueError):
    """Raised when a Prime evidence claim crosses a closed boundary."""


class PrimeEvidenceLevel(str, Enum):
    """The non-interchangeable Prime evidence levels."""

    PROVIDER_FREE = "provider-free"
    BOUNDED_SANDBOXED = "bounded-sandboxed"
    FULL_AUTHORIZED = "full-authorized"


@dataclass(frozen=True)
class PrimeEvidenceReceipt:
    """A deliberately small public PASS claim for one exact scenario."""

    scenario_id: str
    level: PrimeEvidenceLevel
    status: str
    receipt_scenario_id: str | None = None


def validate_prime_evidence_receipt(
    receipt: PrimeEvidenceReceipt,
) -> PrimeEvidenceReceipt:
    """Return a valid one-scenario PASS receipt or fail closed."""

    if (
        type(receipt) is not PrimeEvidenceReceipt
        or frozenset(vars(receipt)) != _RECEIPT_FIELDS
        or type(receipt.scenario_id) is not str
        or receipt.scenario_id not in PRIME_CAPABILITY_SCENARIO_IDS
        or type(receipt.level) is not PrimeEvidenceLevel
        or receipt.status != "PASS"
        or receipt.receipt_scenario_id is not None
        and (
            type(receipt.receipt_scenario_id) is not str
            or receipt.receipt_scenario_id != receipt.scenario_id
        )
    ):
        raise PrimeCapabilityEvidenceError("Prime evidence receipt is invalid")
    return receipt


def can_promote(scenario_id: str, source_level: str, target_level: str) -> bool:
    """Whether evidence may retain (never elevate) its exact claim level."""

    try:
        source = PrimeEvidenceLevel(source_level)
        target = PrimeEvidenceLevel(target_level)
    except (TypeError, ValueError):
        return False
    return scenario_id in PRIME_CAPABILITY_SCENARIO_IDS and source is target
