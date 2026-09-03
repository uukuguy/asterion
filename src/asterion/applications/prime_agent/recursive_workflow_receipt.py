"""Closed provider-free evidence for Prime recursive workflows."""

from __future__ import annotations

from dataclasses import dataclass
import re

from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel,
    PrimeEvidenceReceipt,
    validate_prime_evidence_receipt,
)


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_CHILD_COUNT = 2
_PUBLIC_REPORT_FIELDS = frozenset(
    {
        "format",
        "status",
        "reason",
        "real_prime_runtime",
        "allowed_tool_names",
        "active_tool_names",
        "admitted_child_count",
        "bound_child_count",
        "root_to_child_message_count",
        "child_to_root_result_count",
        "terminal_child_count",
        "deleted_child_count",
        "workflow_sha256",
        "aggregation_sha256",
        "oracle_sha256",
        "root_continued_locally",
        "aggregation_passed",
        "disposed",
        "reaped",
    }
)


class RecursiveWorkflowReceiptError(ValueError):
    """Raised when recursive workflow facts cannot support the fixed receipt."""


@dataclass(frozen=True, repr=False)
class RecursiveWorkflowObservation:
    """Private normalized facts; child identities and messages are never retained."""

    built_in_tools: tuple[str, ...]
    active_tool_names: tuple[str, ...]
    admitted_child_count: int
    bound_child_count: int
    root_to_child_message_count: int
    child_to_root_result_count: int
    terminal_child_count: int
    deleted_child_count: int
    workflow_sha256: str
    aggregation_sha256: str
    oracle_sha256: str
    root_continued_locally: bool
    aggregation_passed: bool

    def __repr__(self) -> str:
        return "RecursiveWorkflowObservation(redacted)"


def _digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _fixed_child_count(value: object) -> bool:
    return type(value) is int and value == _CHILD_COUNT


def recursive_workflow_observation_from_public_report(
    report: object,
) -> RecursiveWorkflowObservation:
    """Convert only one exact successful compatibility report to private facts."""

    if (
        type(report) is not dict
        or frozenset(report) != _PUBLIC_REPORT_FIELDS
        or report["format"] != "asterion.prime-recursive-workflow-compat/v1"
        or report["status"] != "PASS"
        or report["reason"] != "supported"
        or report["real_prime_runtime"] is not True
        or report["allowed_tool_names"] != ["ipython"]
        or report["active_tool_names"] != ["ipython"]
        or report["root_continued_locally"] is not True
        or report["aggregation_passed"] is not True
        or report["disposed"] is not True
        or report["reaped"] is not True
    ):
        raise RecursiveWorkflowReceiptError("recursive workflow receipt is invalid")
    try:
        observation = RecursiveWorkflowObservation(
            built_in_tools=("ipython",),
            active_tool_names=("ipython",),
            admitted_child_count=report["admitted_child_count"],
            bound_child_count=report["bound_child_count"],
            root_to_child_message_count=report["root_to_child_message_count"],
            child_to_root_result_count=report["child_to_root_result_count"],
            terminal_child_count=report["terminal_child_count"],
            deleted_child_count=report["deleted_child_count"],
            workflow_sha256=report["workflow_sha256"],
            aggregation_sha256=report["aggregation_sha256"],
            oracle_sha256=report["oracle_sha256"],
            root_continued_locally=True,
            aggregation_passed=True,
        )
        verify_recursive_workflow_receipt(observation)
    except (KeyError, TypeError, RecursiveWorkflowReceiptError):
        raise RecursiveWorkflowReceiptError(
            "recursive workflow receipt is invalid"
        ) from None
    return observation


def verify_recursive_workflow_receipt(
    observation: object,
    requested_level: PrimeEvidenceLevel = PrimeEvidenceLevel.PROVIDER_FREE,
) -> PrimeEvidenceReceipt:
    """Emit the sole provider-free receipt for one fixed recursive workflow."""

    if (
        type(observation) is not RecursiveWorkflowObservation
        or type(requested_level) is not PrimeEvidenceLevel
        or requested_level is not PrimeEvidenceLevel.PROVIDER_FREE
        or observation.built_in_tools != ("ipython",)
        or observation.active_tool_names != ("ipython",)
        or any(
            not _fixed_child_count(value)
            for value in (
                observation.admitted_child_count,
                observation.bound_child_count,
                observation.root_to_child_message_count,
                observation.child_to_root_result_count,
                observation.terminal_child_count,
                observation.deleted_child_count,
            )
        )
        or any(
            not _digest(value)
            for value in (
                observation.workflow_sha256,
                observation.aggregation_sha256,
                observation.oracle_sha256,
            )
        )
        or observation.root_continued_locally is not True
        or observation.aggregation_passed is not True
    ):
        raise RecursiveWorkflowReceiptError("recursive workflow receipt is invalid")
    return validate_prime_evidence_receipt(
        PrimeEvidenceReceipt(
            scenario_id="prime.recursive-workflow/v1",
            level=PrimeEvidenceLevel.PROVIDER_FREE,
            status="PASS",
        )
    )
