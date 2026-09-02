"""Private one-shot ordering barrier for an admitted Prime worker."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from asterion.services.restricted_worker import (
    RestrictedWorkerAttestation,
    RestrictedWorkerLease,
)


class PrimeLauncherBarrierError(ValueError):
    """Raised when a Prime launcher ordering or identity check fails."""


@dataclass(frozen=True, repr=False)
class PrimeLauncherAdmission:
    """Public-safe acknowledgement of admission, not worker evidence."""

    status: Literal["admitted"] = field(default="admitted", init=False)

    def __repr__(self) -> str:
        return "PrimeLauncherAdmission(redacted)"


class PrimeLauncherBarrier:
    """Bind one verified worker to one private launch release.

    This is an ordering and identity contract only.  It does not broker worker
    communication and makes no sandbox or evidence claim.
    """

    def __init__(self, *, run_id: str, challenge_digest: str) -> None:
        try:
            # Reuse the closed lease validator without retaining a synthetic worker.
            RestrictedWorkerLease("barrier", run_id, challenge_digest)
        except ValueError:
            raise PrimeLauncherBarrierError("prime launcher barrier is invalid") from None
        self._run_id = run_id
        self._challenge_digest = challenge_digest
        self._worker_id: str | None = None
        self._released = False

    def __repr__(self) -> str:
        return "PrimeLauncherBarrier(redacted)"

    def admit(
        self,
        lease: RestrictedWorkerLease,
        attestation: RestrictedWorkerAttestation,
    ) -> PrimeLauncherAdmission:
        """Record the exact verified worker identity before it can be released."""
        if self._worker_id is not None or not self._matches_attestation(lease, attestation):
            raise PrimeLauncherBarrierError("prime launcher barrier is invalid")
        self._worker_id = lease.worker_id
        return PrimeLauncherAdmission()

    def release(self, lease: RestrictedWorkerLease, action: Callable[[], None]) -> None:
        """Invoke the opaque launch action once for the admitted lease only."""
        if (
            self._released
            or not callable(action)
            or type(lease) is not RestrictedWorkerLease
            or self._worker_id is None
            or lease.worker_id != self._worker_id
            or lease.run_id != self._run_id
            or lease.challenge_digest != self._challenge_digest
        ):
            raise PrimeLauncherBarrierError("prime launcher barrier is invalid")
        self._released = True
        action()

    def _matches_attestation(
        self,
        lease: RestrictedWorkerLease,
        attestation: RestrictedWorkerAttestation,
    ) -> bool:
        return (
            type(lease) is RestrictedWorkerLease
            and type(attestation) is RestrictedWorkerAttestation
            and lease.run_id == self._run_id
            and lease.challenge_digest == self._challenge_digest
            and lease.worker_id == attestation.worker_id
            and lease.run_id == attestation.run_id
            and lease.challenge_digest == attestation.challenge_digest
            and all(
                value is True
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
        )
