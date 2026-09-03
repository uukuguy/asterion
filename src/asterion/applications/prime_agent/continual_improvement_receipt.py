"""Closed bounded evidence for Prime continual-harness refinement."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Literal

from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel,
    PrimeEvidenceReceipt,
)
from asterion.control.providers.prime.parity_testing import (
    build_prime_harness_bounded_observation,
)
from asterion.applications.prime_agent.operator.continual_improvement_workload import (
    P6_CONTINUAL_IMPROVEMENT_MODEL_SHA256,
    P6_CONTINUAL_IMPROVEMENT_ORACLE_SHA256,
    P6_CONTINUAL_IMPROVEMENT_SCHEMA_SHA256,
    P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST,
    P6_CONTINUAL_IMPROVEMENT_ROLLBACK_AUTHORITY_ID,
    P6_CONTINUAL_IMPROVEMENT_ROLLBACK_PROPOSAL_ID,
    P6_CONTINUAL_IMPROVEMENT_ROLLBACK_RATIONALE_SHA256,
    P6_CONTINUAL_IMPROVEMENT_ROLLBACK_OUTCOME_SHA256,
)


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_TRACE_FIELDS = frozenset({
    "workload_sha256", "baseline_snapshot_sha256", "candidate_snapshot_sha256",
    "candidate_revision_sha256", "task_a_evidence_sha256", "task_b_result_sha256",
    "oracle_sha256", "model_sha256", "schema_sha256", "tool_names", "action_count",
    "usage_count", "candidate_count", "holdout_count", "rollback_count", "outcome",
    "rollback_authority_id", "rollback_authority_revision", "rollback_proposal_id",
    "rollback_rationale_sha256", "rollback_outcome_sha256", "terminal", "disposed", "reaped",
})


class ContinualImprovementReceiptError(ValueError):
    """Raised when a bounded refinement cannot support the product claim."""


@dataclass(frozen=True, repr=False)
class ContinualImprovementTrace:
    workload_sha256: str
    baseline_snapshot_sha256: str
    candidate_snapshot_sha256: str
    candidate_revision_sha256: str
    task_a_evidence_sha256: str
    task_b_result_sha256: str
    oracle_sha256: str
    model_sha256: str
    schema_sha256: str
    tool_names: tuple[str]
    action_count: int
    usage_count: int
    candidate_count: int
    holdout_count: int
    rollback_count: int
    outcome: Literal["preserved", "rolled-back"]
    rollback_authority_id: str
    rollback_authority_revision: int
    rollback_proposal_id: str
    rollback_rationale_sha256: str
    rollback_outcome_sha256: str
    terminal: bool
    disposed: bool
    reaped: bool

    def __repr__(self) -> str:
        return "ContinualImprovementTrace(redacted)"


def validate_continual_improvement_trace(trace: object) -> None:
    """Validate the fixed P6 causal trace without issuing evidence."""

    try:
        if (
            type(trace) is not ContinualImprovementTrace
            or frozenset(vars(trace)) != _TRACE_FIELDS
            or any(
                type(getattr(trace, name)) is not str
                or _DIGEST.fullmatch(getattr(trace, name)) is None
                for name in _TRACE_FIELDS
                if name.endswith("_sha256")
            )
            or trace.workload_sha256 != P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST
            or trace.oracle_sha256 != P6_CONTINUAL_IMPROVEMENT_ORACLE_SHA256
            or trace.model_sha256 != P6_CONTINUAL_IMPROVEMENT_MODEL_SHA256
            or trace.schema_sha256 != P6_CONTINUAL_IMPROVEMENT_SCHEMA_SHA256
            or trace.baseline_snapshot_sha256 == trace.candidate_snapshot_sha256
            or trace.tool_names != ("ipython",)
            or type(trace.action_count) is not int or not 0 < trace.action_count <= 3
            or type(trace.usage_count) is not int or not 0 < trace.usage_count <= 256
            or type(trace.candidate_count) is not int or trace.candidate_count != 1
            or type(trace.holdout_count) is not int or trace.holdout_count != 1
            or type(trace.rollback_count) is not int
            or trace.outcome not in {"preserved", "rolled-back"}
            or (trace.outcome == "preserved" and trace.rollback_count != 0)
            or (trace.outcome == "rolled-back" and trace.rollback_count != 1)
            or trace.rollback_authority_id != P6_CONTINUAL_IMPROVEMENT_ROLLBACK_AUTHORITY_ID
            or type(trace.rollback_authority_revision) is not int or trace.rollback_authority_revision != 1
            or trace.rollback_proposal_id != P6_CONTINUAL_IMPROVEMENT_ROLLBACK_PROPOSAL_ID
            or trace.rollback_rationale_sha256 != P6_CONTINUAL_IMPROVEMENT_ROLLBACK_RATIONALE_SHA256
            or trace.rollback_outcome_sha256 != P6_CONTINUAL_IMPROVEMENT_ROLLBACK_OUTCOME_SHA256
            or any(getattr(trace, name) is not True for name in ("terminal", "disposed", "reaped"))
        ):
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise ContinualImprovementReceiptError("continual improvement trace is invalid") from None


@dataclass(frozen=True, repr=False)
class ContinualImprovementObservation:
    """Private normalized facts without proposal, evidence, or model content."""

    grounded_proposal: bool
    host_admitted: bool
    snapshot_activated: bool
    provider_operation_count: int
    model_credential_read_count: int
    source_receipt_digest: str

    def __repr__(self) -> str:
        return "ContinualImprovementObservation(redacted)"


def continual_improvement_observation_from_receipt(
    receipt: object,
) -> ContinualImprovementObservation:
    """Reduce exactly one finite, grounded refinement receipt to safe facts."""

    if not isinstance(receipt, Mapping):
        raise ContinualImprovementReceiptError(
            "continual improvement receipt is invalid"
        )
    try:
        observation = build_prime_harness_bounded_observation(receipt)
    except Exception:
        raise ContinualImprovementReceiptError(
            "continual improvement receipt is invalid"
        ) from None
    if (
        observation.provider_operations != 1
        or observation.model_credential_reads != 1
        or observation.status != "PASS"
    ):
        raise ContinualImprovementReceiptError(
            "continual improvement receipt is invalid"
        )
    return ContinualImprovementObservation(
        grounded_proposal=True,
        host_admitted=True,
        snapshot_activated=True,
        provider_operation_count=1,
        model_credential_read_count=1,
        source_receipt_digest="sha256:" + hashlib.sha256(json.dumps(
            dict(receipt), ensure_ascii=True, separators=(",", ":"), sort_keys=True,
        ).encode()).hexdigest(),
    )


def verify_continual_improvement_receipt(
    observation: object,
    worker_receipt: object | None = None,
    requested_level: PrimeEvidenceLevel = PrimeEvidenceLevel.BOUNDED_SANDBOXED,
) -> PrimeEvidenceReceipt:
    """Emit the sole bounded-sandboxed receipt for continual improvement."""

    if (
        type(observation) is not ContinualImprovementObservation
        or type(requested_level) is not PrimeEvidenceLevel
        or requested_level is not PrimeEvidenceLevel.BOUNDED_SANDBOXED
        or observation.grounded_proposal is not True
        or observation.host_admitted is not True
        or observation.snapshot_activated is not True
        or observation.provider_operation_count != 1
        or observation.model_credential_read_count != 1
    ):
        raise ContinualImprovementReceiptError(
            "continual improvement receipt is invalid"
        )
    raise ContinualImprovementReceiptError(
        "continual improvement receipt is unavailable"
    )
