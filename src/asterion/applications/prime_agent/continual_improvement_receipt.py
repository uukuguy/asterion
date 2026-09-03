"""Closed bounded evidence for Prime continual-harness refinement."""

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
    build_prime_harness_bounded_observation,
)
from asterion.applications.prime_agent.worker_gate import (
    PrimeWorkerBoundaryError,
    PrimeWorkerBoundaryReceipt,
    issue_prime_bounded_evidence,
)


class ContinualImprovementReceiptError(ValueError):
    """Raised when a bounded refinement cannot support the product claim."""


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
    worker_receipt: PrimeWorkerBoundaryReceipt | None = None,
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
    try:
        return issue_prime_bounded_evidence(
            "prime.continual-improvement/v1", observation.source_receipt_digest,
            worker_receipt,  # type: ignore[arg-type]
        )
    except PrimeWorkerBoundaryError:
        raise ContinualImprovementReceiptError(
            "continual improvement receipt is invalid"
        ) from None
