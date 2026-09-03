"""Closed bounded evidence for Prime autonomous goal completion."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json

from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel,
    PrimeEvidenceReceipt,
)
from asterion.control.providers.prime.parity_testing import (
    build_prime_long_running_bounded_observation,
)
from asterion.applications.prime_agent.worker_gate import (
    PrimeWorkerBoundaryError,
    PrimeWorkerBoundaryReceipt,
    issue_prime_bounded_evidence,
)


class BoundedAutonomyReceiptError(ValueError):
    """Raised when a bounded autonomy receipt cannot support the claim."""


@dataclass(frozen=True, repr=False)
class BoundedAutonomyObservation:
    """Private normalized facts without goal, model, or provider content."""

    goal_completed: bool
    host_quiescent: bool
    orphan_audit_clean: bool
    provider_operation_count: int
    model_credential_read_count: int
    source_receipt_digest: str

    def __repr__(self) -> str:
        return "BoundedAutonomyObservation(redacted)"


def bounded_autonomy_observation_from_receipt(
    receipt: object,
) -> BoundedAutonomyObservation:
    """Reduce one exact finite provider receipt to non-sensitive facts."""

    if not isinstance(receipt, Mapping):
        raise BoundedAutonomyReceiptError("bounded autonomy receipt is invalid")
    try:
        observation = build_prime_long_running_bounded_observation(receipt)
    except Exception:
        raise BoundedAutonomyReceiptError("bounded autonomy receipt is invalid") from None
    if (
        observation.provider_operations != 1
        or observation.model_credential_reads != 1
        or observation.status != "PASS"
    ):
        raise BoundedAutonomyReceiptError("bounded autonomy receipt is invalid")
    return BoundedAutonomyObservation(
        goal_completed=True,
        host_quiescent=True,
        orphan_audit_clean=True,
        provider_operation_count=1,
        model_credential_read_count=1,
        source_receipt_digest="sha256:" + hashlib.sha256(json.dumps(
            dict(receipt), ensure_ascii=True, separators=(",", ":"), sort_keys=True,
        ).encode()).hexdigest(),
    )


def verify_bounded_autonomy_receipt(
    observation: object,
    worker_receipt: PrimeWorkerBoundaryReceipt | None = None,
    requested_level: PrimeEvidenceLevel = PrimeEvidenceLevel.BOUNDED_SANDBOXED,
) -> PrimeEvidenceReceipt:
    """Emit the sole bounded-sandboxed receipt for Prime autonomy."""

    if (
        type(observation) is not BoundedAutonomyObservation
        or type(requested_level) is not PrimeEvidenceLevel
        or requested_level is not PrimeEvidenceLevel.BOUNDED_SANDBOXED
        or observation.goal_completed is not True
        or observation.host_quiescent is not True
        or observation.orphan_audit_clean is not True
        or observation.provider_operation_count != 1
        or observation.model_credential_read_count != 1
    ):
        raise BoundedAutonomyReceiptError("bounded autonomy receipt is invalid")
    try:
        return issue_prime_bounded_evidence(
            "prime.bounded-autonomy/v1", observation.source_receipt_digest,
            worker_receipt,  # type: ignore[arg-type]
        )
    except PrimeWorkerBoundaryError:
        raise BoundedAutonomyReceiptError("bounded autonomy receipt is invalid") from None
