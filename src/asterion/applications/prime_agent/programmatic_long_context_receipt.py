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
_PUBLIC_REPORT_FIELDS = frozenset(
    {
        "format",
        "status",
        "reason",
        "real_prime_runtime",
        "allowed_tool_names",
        "active_tool_names",
        "corpus_sha256",
        "corpus_record_count",
        "selected_record_count",
        "program_sha256",
        "aggregate_sha256",
        "oracle_sha256",
        "ipython_cell_executed",
        "oracle_passed",
        "disposed",
        "reaped",
    }
)


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


def programmatic_long_context_observation_from_public_report(
    report: object,
) -> ProgrammaticLongContextObservation:
    """Convert only one exact successful compatibility report to private facts."""

    if (
        type(report) is not dict
        or frozenset(report) != _PUBLIC_REPORT_FIELDS
        or report["format"]
        != "asterion.prime-programmatic-long-context-compat/v1"
        or report["status"] != "PASS"
        or report["reason"] != "supported"
        or report["real_prime_runtime"] is not True
        or report["allowed_tool_names"] != ["ipython"]
        or report["active_tool_names"] != ["ipython"]
        or report["ipython_cell_executed"] is not True
        or report["oracle_passed"] is not True
        or report["disposed"] is not True
        or report["reaped"] is not True
    ):
        raise ProgrammaticLongContextReceiptError(
            "programmatic long-context receipt is invalid"
        )
    try:
        observation = ProgrammaticLongContextObservation(
            built_in_tools=("ipython",),
            active_tool_names=("ipython",),
            corpus_sha256=report["corpus_sha256"],
            corpus_record_count=report["corpus_record_count"],
            selected_record_count=report["selected_record_count"],
            program_sha256=report["program_sha256"],
            aggregate_sha256=report["aggregate_sha256"],
            oracle_sha256=report["oracle_sha256"],
            ipython_cell_executed=True,
            oracle_passed=True,
        )
        verify_programmatic_long_context_receipt(observation)
    except (KeyError, TypeError, ProgrammaticLongContextReceiptError):
        raise ProgrammaticLongContextReceiptError(
            "programmatic long-context receipt is invalid"
        ) from None
    return observation


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
