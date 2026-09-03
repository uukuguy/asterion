"""Authorization-gated bounded P4 evidence reducer."""

from __future__ import annotations
from dataclasses import dataclass
import re
from typing import cast
from asterion.applications.prime_agent.diagnostic_session_recovery_receipt import (
    DiagnosticSessionRecoveryTrace,
    validate_diagnostic_session_recovery_trace,
)
from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel,
    PrimeEvidenceReceipt,
    validate_prime_evidence_receipt,
)
from asterion.applications.prime_agent.worker_gate import PrimeWorkerBoundaryReceipt

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class DiagnosticSessionRecoveryLiveValidationError(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class DiagnosticSessionRecoveryLiveAuthorization:
    platform_lock_sha256: str
    real_prime_ipython_attested: bool
    durable_checkpoint_attested: bool
    gateway_recovery_attested: bool
    broker_quiescent: bool
    worker_destroyed: bool


@dataclass(frozen=True, repr=False, init=False)
class DiagnosticSessionRecoveryLiveObservation:
    trace: DiagnosticSessionRecoveryTrace
    platform_lock_sha256: str
    worker_boundary: PrimeWorkerBoundaryReceipt

    @classmethod
    def _admit(
        cls, *, trace: object, platform_lock_sha256: object, worker_boundary: object
    ) -> "DiagnosticSessionRecoveryLiveObservation":
        try:
            validate_diagnostic_session_recovery_trace(trace)
            typed_trace = cast(DiagnosticSessionRecoveryTrace, trace)
            if (
                type(platform_lock_sha256) is not str
                or _DIGEST.fullmatch(platform_lock_sha256) is None
                or type(worker_boundary) is not PrimeWorkerBoundaryReceipt
                or worker_boundary.scenario_id != "prime.long-session-continuity/v1"
                or worker_boundary.result_digest != typed_trace.diagnostic_result_sha256
            ):
                raise ValueError
            value = object.__new__(cls)
            object.__setattr__(value, "trace", typed_trace)
            object.__setattr__(value, "platform_lock_sha256", platform_lock_sha256)
            object.__setattr__(value, "worker_boundary", worker_boundary)
            return value
        except (TypeError, ValueError):
            raise DiagnosticSessionRecoveryLiveValidationError(
                "diagnostic session recovery live evidence is invalid"
            ) from None


def validate_diagnostic_session_recovery_live_result(
    observation: object, authorization: object
) -> PrimeEvidenceReceipt:
    if (
        type(observation) is not DiagnosticSessionRecoveryLiveObservation
        or type(authorization) is not DiagnosticSessionRecoveryLiveAuthorization
        or observation.platform_lock_sha256 != authorization.platform_lock_sha256
        or _DIGEST.fullmatch(authorization.platform_lock_sha256) is None
        or not all(
            (
                authorization.real_prime_ipython_attested,
                authorization.durable_checkpoint_attested,
                authorization.gateway_recovery_attested,
                authorization.broker_quiescent,
                authorization.worker_destroyed,
            )
        )
    ):
        raise DiagnosticSessionRecoveryLiveValidationError(
            "diagnostic session recovery live evidence is invalid"
        )
    return validate_prime_evidence_receipt(
        PrimeEvidenceReceipt(
            "prime.long-session-continuity/v1", PrimeEvidenceLevel.BOUNDED, "PASS"
        )
    )
