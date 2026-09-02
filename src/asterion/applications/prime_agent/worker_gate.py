"""One-way admission of verified Prime restricted-worker evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from asterion.applications.prime_agent.restricted_worker import (
    PrimeRestrictedWorkerError,
    PrimeRestrictedWorkerProfile,
    validate_prime_restricted_worker,
)
from asterion.services.restricted_worker import (
    RestrictedWorkerAttestation,
    RestrictedWorkerCleanupReceipt,
    RestrictedWorkerError,
    RestrictedWorkerLease,
    RestrictedWorkerRequest,
    verify_restricted_worker_receipts,
)


class PrimeWorkerBoundaryError(ValueError):
    """Raised when Prime worker evidence cannot be admitted."""


@dataclass(frozen=True)
class PrimeWorkerBoundaryReceipt:
    """Public-safe proof of one admitted restricted-worker lifecycle."""

    worker_id: str
    run_id: str
    challenge_digest: str
    image_digest: str
    status: Literal["PASS"] = field(default="PASS", init=False)


def verify_prime_worker_boundary(
    profile: PrimeRestrictedWorkerProfile,
    request: RestrictedWorkerRequest,
    lease: RestrictedWorkerLease,
    attestation: RestrictedWorkerAttestation,
    cleanup: RestrictedWorkerCleanupReceipt,
) -> PrimeWorkerBoundaryReceipt:
    """Admit only a fully verified worker lifecycle as public-safe evidence."""
    try:
        validate_prime_restricted_worker(profile)
        verify_restricted_worker_receipts(request, lease, attestation, cleanup)
    except (PrimeRestrictedWorkerError, RestrictedWorkerError):
        raise PrimeWorkerBoundaryError("prime worker boundary is invalid") from None

    if (
        request.role_id != "prime.ipython-coding"
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

    return PrimeWorkerBoundaryReceipt(
        worker_id=lease.worker_id,
        run_id=lease.run_id,
        challenge_digest=lease.challenge_digest,
        image_digest=profile.image_digest,
    )
