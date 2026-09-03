"""Provider-free P4 recovery acceptance boundary."""

from __future__ import annotations
from dataclasses import dataclass
from asterion.applications.prime_agent.diagnostic_session_recovery_adapter import (
    recover_diagnostic_session,
)
from asterion.applications.prime_agent.operator.diagnostic_session_recovery_completion import (
    DiagnosticSessionRecoveryCompletion,
)
from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel,
    PrimeEvidenceReceipt,
    validate_prime_evidence_receipt,
)


class DiagnosticSessionRecoveryAcceptanceError(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class DiagnosticRecoveryProviderFreeObservation:
    completion: DiagnosticSessionRecoveryCompletion
    disposed: bool
    reaped: bool


async def accept_diagnostic_session_recovery(
    *, gateway: object, checkpoint: object, before_detach: object, observation: object
) -> PrimeEvidenceReceipt:
    try:
        if (
            type(observation) is not DiagnosticRecoveryProviderFreeObservation
            or type(observation.completion) is not DiagnosticSessionRecoveryCompletion
            or observation.disposed is not True
            or observation.reaped is not True
        ):
            raise ValueError
        await recover_diagnostic_session(gateway, checkpoint, before_detach)
        return validate_prime_evidence_receipt(
            PrimeEvidenceReceipt(
                "prime.long-session-continuity/v1",
                PrimeEvidenceLevel.PROVIDER_FREE,
                "PASS",
            )
        )
    except (TypeError, ValueError):
        raise DiagnosticSessionRecoveryAcceptanceError(
            "diagnostic session recovery acceptance is invalid"
        ) from None
