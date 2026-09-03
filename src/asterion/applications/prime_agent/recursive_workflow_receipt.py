"""Closed bounded evidence for an observed real Prime recursive workflow."""

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
_TRACE_FIELDS = frozenset(
    {
        "workload_sha256",
        "root_artifact_sha256",
        "first_child_role_digests",
        "first_child_result_digests",
        "first_child_usage_digests",
        "follow_up_digest",
        "aggregation_sha256",
        "oracle_sha256",
        "model_sha256",
        "usage_sha256",
        "root_to_child_message_count",
        "child_to_root_result_count",
        "follow_up_count",
        "root_deleted_child_count",
        "root_continued_locally",
        "root_work_before_children",
        "child_tool_names",
        "child_ipython_action_counts",
        "revoked",
        "disposed",
        "reaped",
    }
)


class RecursiveWorkflowReceiptError(ValueError):
    """Raised when a real recursive-workflow trace is incomplete or invalid."""


@dataclass(frozen=True, repr=False)
class RecursiveWorkflowTrace:
    """Private, normalized facts for the one bounded real-RLM workflow."""

    workload_sha256: str
    root_artifact_sha256: str
    first_child_role_digests: tuple[str, str]
    first_child_result_digests: tuple[str, str]
    first_child_usage_digests: tuple[str, str]
    follow_up_digest: str
    aggregation_sha256: str
    oracle_sha256: str
    model_sha256: str
    usage_sha256: str
    root_to_child_message_count: int
    child_to_root_result_count: int
    follow_up_count: int
    root_deleted_child_count: int
    root_continued_locally: bool
    root_work_before_children: bool
    child_tool_names: tuple[tuple[str], tuple[str]]
    child_ipython_action_counts: tuple[int, int]
    revoked: bool
    disposed: bool
    reaped: bool

    def __repr__(self) -> str:
        return "RecursiveWorkflowTrace(redacted)"


def _digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _two_digests(value: object) -> bool:
    return (
        type(value) is tuple
        and len(value) == _CHILD_COUNT
        and all(_digest(item) for item in value)
    )


def _distinct_two_digests(value: object) -> bool:
    return _two_digests(value) and value[0] != value[1]  # type: ignore[index]


def _positive_child_actions(value: object) -> bool:
    return (
        type(value) is tuple
        and len(value) == _CHILD_COUNT
        and all(type(item) is int and item > 0 for item in value)
    )


def _ipython_only(value: object) -> bool:
    return (
        type(value) is tuple
        and len(value) == _CHILD_COUNT
        and all(
            type(child_tools) is tuple
            and len(child_tools) == 1
            and type(child_tools[0]) is str
            and child_tools[0] == "ipython"
            for child_tools in value
        )
    )


def verify_real_recursive_workflow_trace(
    trace: object,
    requested_level: PrimeEvidenceLevel = PrimeEvidenceLevel.BOUNDED,
) -> PrimeEvidenceReceipt:
    """Issue bounded evidence only for the complete fixed real-RLM trace."""

    if (
        type(trace) is not RecursiveWorkflowTrace
        or frozenset(vars(trace)) != _TRACE_FIELDS
        or type(requested_level) is not PrimeEvidenceLevel
        or requested_level is not PrimeEvidenceLevel.BOUNDED
        or not _digest(trace.workload_sha256)
        or not _digest(trace.root_artifact_sha256)
        or not _distinct_two_digests(trace.first_child_role_digests)
        or not _distinct_two_digests(trace.first_child_result_digests)
        or not _distinct_two_digests(trace.first_child_usage_digests)
        or any(
            not _digest(value)
            for value in (
                trace.follow_up_digest,
                trace.aggregation_sha256,
                trace.oracle_sha256,
                trace.model_sha256,
                trace.usage_sha256,
            )
        )
        or type(trace.root_to_child_message_count) is not int
        or trace.root_to_child_message_count != _CHILD_COUNT
        or type(trace.child_to_root_result_count) is not int
        or trace.child_to_root_result_count != 3
        or type(trace.follow_up_count) is not int
        or trace.follow_up_count != 1
        or type(trace.root_deleted_child_count) is not int
        or trace.root_deleted_child_count != _CHILD_COUNT
        or trace.root_continued_locally is not True
        or trace.root_work_before_children is not True
        or not _ipython_only(trace.child_tool_names)
        or not _positive_child_actions(trace.child_ipython_action_counts)
        or trace.revoked is not True
        or trace.disposed is not True
        or trace.reaped is not True
    ):
        raise RecursiveWorkflowReceiptError("real recursive workflow trace is invalid")
    return validate_prime_evidence_receipt(
        PrimeEvidenceReceipt(
            scenario_id="prime.recursive-workflow/v1",
            level=PrimeEvidenceLevel.BOUNDED,
            status="PASS",
        )
    )
