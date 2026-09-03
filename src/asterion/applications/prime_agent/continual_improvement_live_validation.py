"""Private admission and exact authorization for live P6 evidence."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import cast

from asterion.applications.prime_agent.continual_improvement_receipt import (
    ContinualImprovementTrace,
    validate_continual_improvement_trace,
)
from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel,
    PrimeEvidenceReceipt,
    validate_prime_evidence_receipt,
)
from asterion.applications.prime_agent.worker_gate import PrimeWorkerBoundaryReceipt


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_AUTHORIZATION_FIELDS = frozenset({
    "platform_lock_sha256", "real_prime_ipython_attested",
    "task_b_oracle_attested", "broker_quiescent", "worker_destroyed",
    "global_activation_approved", "global_scope_sha256",
})
_OBSERVATION_FIELDS = frozenset({
    "trace", "platform_lock_sha256", "worker_boundary",
})


class ContinualImprovementLiveValidationError(ValueError):
    """Raised without exposing private live-run data."""


@dataclass(frozen=True, repr=False)
class ContinualImprovementLiveAuthorization:
    platform_lock_sha256: str
    real_prime_ipython_attested: bool
    task_b_oracle_attested: bool
    broker_quiescent: bool
    worker_destroyed: bool
    global_activation_approved: bool
    global_scope_sha256: str | None


@dataclass(frozen=True, repr=False, init=False)
class ContinualImprovementLiveObservation:
    trace: ContinualImprovementTrace
    platform_lock_sha256: str
    worker_boundary: PrimeWorkerBoundaryReceipt

    @classmethod
    def _admit(
        cls, *, trace: object, platform_lock_sha256: object, worker_boundary: object
    ) -> "ContinualImprovementLiveObservation":
        try:
            validate_continual_improvement_trace(trace)
            typed_trace = cast(ContinualImprovementTrace, trace)
            if (
                type(platform_lock_sha256) is not str
                or _DIGEST.fullmatch(platform_lock_sha256) is None
                or type(worker_boundary) is not PrimeWorkerBoundaryReceipt
                or worker_boundary.scenario_id != "prime.continual-improvement/v1"
                or worker_boundary.result_digest != typed_trace.task_b_result_sha256
            ):
                raise ValueError
            value = object.__new__(cls)
            object.__setattr__(value, "trace", typed_trace)
            object.__setattr__(value, "platform_lock_sha256", platform_lock_sha256)
            object.__setattr__(value, "worker_boundary", worker_boundary)
            return value
        except (TypeError, ValueError):
            raise ContinualImprovementLiveValidationError(
                "continual improvement live evidence is invalid"
            ) from None


def validate_continual_improvement_live_result(
    observation: object, authorization: object
) -> PrimeEvidenceReceipt:
    """Issue bounded P6 evidence only from admitted, authorized live facts."""

    if (
        type(observation) is not ContinualImprovementLiveObservation
        or type(authorization) is not ContinualImprovementLiveAuthorization
        or frozenset(vars(observation)) != _OBSERVATION_FIELDS
        or frozenset(vars(authorization)) != _AUTHORIZATION_FIELDS
        or type(observation.platform_lock_sha256) is not str
        or _DIGEST.fullmatch(observation.platform_lock_sha256) is None
        or observation.platform_lock_sha256 != authorization.platform_lock_sha256
        or type(authorization.platform_lock_sha256) is not str
        or _DIGEST.fullmatch(authorization.platform_lock_sha256) is None
    ):
        raise ContinualImprovementLiveValidationError(
            "continual improvement live evidence is invalid"
        )
    try:
        validate_continual_improvement_trace(observation.trace)
        worker = observation.worker_boundary
        if (
            type(worker) is not PrimeWorkerBoundaryReceipt
            or worker.scenario_id != "prime.continual-improvement/v1"
            or worker.role_id != "prime.continual-improvement"
            or worker.status != "PASS"
            or type(worker.result_digest) is not str
            or _DIGEST.fullmatch(worker.result_digest) is None
            or worker.result_digest != observation.trace.task_b_result_sha256
            or any(
                getattr(authorization, name) is not True
                for name in (
                    "real_prime_ipython_attested", "task_b_oracle_attested",
                    "broker_quiescent", "worker_destroyed",
                )
            )
            or (
                observation.trace.scope_kind == "global"
                and (
                    authorization.global_activation_approved is not True
                    or authorization.global_scope_sha256
                    != observation.trace.scope_sha256
                )
            )
        ):
            raise ValueError
    except (TypeError, ValueError):
        raise ContinualImprovementLiveValidationError(
            "continual improvement live evidence is invalid"
        ) from None
    return validate_prime_evidence_receipt(
        PrimeEvidenceReceipt(
            "prime.continual-improvement/v1", PrimeEvidenceLevel.BOUNDED, "PASS"
        )
    )
