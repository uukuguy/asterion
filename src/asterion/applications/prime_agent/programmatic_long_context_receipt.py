"""Closed provider-free evidence for Prime programmatic long context."""

from __future__ import annotations

from dataclasses import dataclass
import re

from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel,
    PrimeEvidenceReceipt,
    validate_prime_evidence_receipt,
)


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class ProgrammaticLongContextReceiptError(ValueError):
    """Raised when long-context facts cannot support the fixed receipt."""


@dataclass(frozen=True, repr=False)
class ProgrammaticLongContextObservation:
    """Private normalized facts; corpus and program contents are never retained."""

    built_in_tools: tuple[str, ...]
    active_tool_names: tuple[str, ...]
    corpus_sha256: str
    corpus_record_count: int
    selected_record_count: int
    program_sha256: str
    aggregate_sha256: str
    oracle_sha256: str
    ipython_cell_executed: bool
    oracle_passed: bool

    def __repr__(self) -> str:
        return "ProgrammaticLongContextObservation(redacted)"


def _positive_integer(value: object) -> bool:
    return type(value) is int and value > 0


def _digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def verify_programmatic_long_context_receipt(
    observation: object,
    requested_level: PrimeEvidenceLevel = PrimeEvidenceLevel.PROVIDER_FREE,
) -> PrimeEvidenceReceipt:
    """Emit the sole provider-free receipt for one verified programmatic run."""

    if (
        type(observation) is not ProgrammaticLongContextObservation
        or type(requested_level) is not PrimeEvidenceLevel
        or requested_level is not PrimeEvidenceLevel.PROVIDER_FREE
        or observation.built_in_tools != ("ipython",)
        or observation.active_tool_names != ("ipython",)
        or not _positive_integer(observation.corpus_record_count)
        or not _positive_integer(observation.selected_record_count)
        or observation.selected_record_count > observation.corpus_record_count
        or any(
            not _digest(value)
            for value in (
                observation.corpus_sha256,
                observation.program_sha256,
                observation.aggregate_sha256,
                observation.oracle_sha256,
            )
        )
        or observation.ipython_cell_executed is not True
        or observation.oracle_passed is not True
    ):
        raise ProgrammaticLongContextReceiptError(
            "programmatic long-context receipt is invalid"
        )
    return validate_prime_evidence_receipt(
        PrimeEvidenceReceipt(
            scenario_id="prime.programmatic-long-context/v1",
            level=PrimeEvidenceLevel.PROVIDER_FREE,
            status="PASS",
        )
    )
