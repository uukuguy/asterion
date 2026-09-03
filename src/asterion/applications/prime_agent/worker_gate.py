"""One-way admission of verified Prime restricted-worker evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Literal

from asterion.applications.prime_agent.restricted_worker import (
    PrimeRestrictedWorkerError,
    PrimeRestrictedWorkerProfile,
    validate_prime_restricted_worker,
)
from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel,
    PrimeEvidenceReceipt,
    validate_prime_evidence_receipt,
)
from asterion.services.restricted_worker import (
    RestrictedWorkerAttestation,
    RestrictedWorkerCleanupReceipt,
    RestrictedWorkerExecutionReceipt,
    RestrictedWorkerError,
    RestrictedWorkerLease,
    RestrictedWorkerRequest,
    verify_restricted_worker_receipts,
)


class PrimeWorkerBoundaryError(ValueError):
    """Raised when Prime worker evidence cannot be admitted."""


PRIME_SCENARIO_WORKER_ROLES = MappingProxyType({
    "prime.ipython-coding/v1": "prime.ipython-coding",
    "prime.programmatic-long-context/v1": "prime.programmatic-long-context",
    "prime.recursive-workflow/v1": "prime.recursive-workflow",
    "prime.long-session-continuity/v1": "prime.long-session-continuity",
    "prime.bounded-autonomy/v1": "prime.bounded-autonomy",
    "prime.continual-improvement/v1": "prime.continual-improvement",
    "prime.arc-agi-3/v1": "prime.arc-agi-3",
})
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, init=False)
class PrimeWorkerBoundaryReceipt:
    """Public-safe proof of one admitted restricted-worker lifecycle."""

    scenario_id: str
    role_id: str
    worker_id: str
    run_id: str
    challenge_digest: str
    workload_digest: str
    result_digest: str
    image_digest: str
    status: Literal["PASS"] = field(default="PASS", init=False)

    @classmethod
    def _admit(
        cls,
        *,
        scenario_id: str,
        role_id: str,
        worker_id: str,
        run_id: str,
        challenge_digest: str,
        workload_digest: str,
        result_digest: str,
        image_digest: str,
    ) -> "PrimeWorkerBoundaryReceipt":
        receipt = object.__new__(cls)
        for field_name, value in (
            ("scenario_id", scenario_id),
            ("role_id", role_id),
            ("worker_id", worker_id),
            ("run_id", run_id),
            ("challenge_digest", challenge_digest),
            ("workload_digest", workload_digest),
            ("result_digest", result_digest),
            ("image_digest", image_digest),
            ("status", "PASS"),
        ):
            object.__setattr__(receipt, field_name, value)
        return receipt


def verify_prime_worker_boundary(
    scenario_id: str,
    profile: PrimeRestrictedWorkerProfile,
    request: RestrictedWorkerRequest,
    lease: RestrictedWorkerLease,
    attestation: RestrictedWorkerAttestation,
    execution: RestrictedWorkerExecutionReceipt,
    cleanup: RestrictedWorkerCleanupReceipt,
) -> PrimeWorkerBoundaryReceipt:
    """Admit only a fully verified worker lifecycle as public-safe evidence."""
    try:
        validate_prime_restricted_worker(profile)
        expected_role = PRIME_SCENARIO_WORKER_ROLES[scenario_id]
        verify_restricted_worker_receipts(request, lease, attestation, execution, cleanup)
    except (KeyError, PrimeRestrictedWorkerError, RestrictedWorkerError):
        raise PrimeWorkerBoundaryError("prime worker boundary is invalid") from None

    if (
        request.role_id != expected_role
        or request.image_digest != profile.image_digest
        or request.max_runtime_seconds != profile.max_runtime_seconds
        or request.max_output_bytes != profile.max_output_bytes
        or any(
            value is not True
            for value in (
                attestation.network_isolated,
                attestation.root_read_only,
                attestation.workspace_disposable,
                attestation.credentials_absent,
                attestation.kernel_credential_absent,
                attestation.source_read_only,
                attestation.resource_limited,
            )
        )
        or cleanup.destroyed is not True
    ):
        raise PrimeWorkerBoundaryError("prime worker boundary is invalid")

    return PrimeWorkerBoundaryReceipt._admit(
        scenario_id=scenario_id,
        role_id=expected_role,
        worker_id=lease.worker_id,
        run_id=lease.run_id,
        challenge_digest=lease.challenge_digest,
        workload_digest=lease.workload_digest,
        result_digest=execution.result_digest,
        image_digest=profile.image_digest,
    )


def issue_prime_bounded_evidence(
    scenario_id: str,
    source_receipt_digest: str,
    worker_receipt: PrimeWorkerBoundaryReceipt,
) -> PrimeEvidenceReceipt:
    """Issue bounded evidence only from the exact worker-bound source result."""
    try:
        expected_role = PRIME_SCENARIO_WORKER_ROLES[scenario_id]
        if (
            _DIGEST.fullmatch(source_receipt_digest) is None
            or type(worker_receipt) is not PrimeWorkerBoundaryReceipt
            or worker_receipt.status != "PASS"
            or worker_receipt.scenario_id != scenario_id
            or worker_receipt.role_id != expected_role
            or worker_receipt.result_digest != source_receipt_digest
        ):
            raise ValueError
        return validate_prime_evidence_receipt(PrimeEvidenceReceipt(
            scenario_id=scenario_id,
            level=PrimeEvidenceLevel.BOUNDED_SANDBOXED,
            status="PASS",
        ))
    except (KeyError, TypeError, ValueError):
        raise PrimeWorkerBoundaryError("prime worker boundary is invalid") from None
