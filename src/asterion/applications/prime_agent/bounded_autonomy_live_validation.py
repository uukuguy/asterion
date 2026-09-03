"""Authorization-gated P5 bounded-evidence reducer."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import cast

from asterion.applications.prime_agent.evidence import PrimeEvidenceReceipt
from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel,
    validate_prime_evidence_receipt,
)
from asterion.applications.prime_agent.bounded_autonomy_receipt import (
    BoundedAutonomyTrace,
    validate_bounded_autonomy_trace,
)
from asterion.applications.prime_agent.worker_gate import PrimeWorkerBoundaryReceipt


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_AUTHORIZATION_FIELDS = frozenset({
    "platform_lock_sha256", "real_prime_ipython_attested", "gate_attested",
    "broker_quiescent", "worker_destroyed",
})
_OBSERVATION_FIELDS = frozenset({
    "trace", "platform_lock_sha256", "worker_boundary",
})


class BoundedAutonomyLiveValidationError(ValueError):
    """Raised without exposing private live-run data."""


@dataclass(frozen=True, repr=False)
class BoundedAutonomyLiveAuthorization:
    platform_lock_sha256: str
    real_prime_ipython_attested: bool
    gate_attested: bool
    broker_quiescent: bool
    worker_destroyed: bool


@dataclass(frozen=True, repr=False, init=False)
class BoundedAutonomyLiveObservation:
    trace: BoundedAutonomyTrace
    platform_lock_sha256: str
    worker_boundary: PrimeWorkerBoundaryReceipt

    @classmethod
    def _admit(
        cls, *, trace: object, platform_lock_sha256: object, worker_boundary: object
    ) -> "BoundedAutonomyLiveObservation":
        try:
            validate_bounded_autonomy_trace(trace)
            typed_trace = cast(BoundedAutonomyTrace, trace)
            if (
                type(platform_lock_sha256) is not str
                or _DIGEST.fullmatch(platform_lock_sha256) is None
                or type(worker_boundary) is not PrimeWorkerBoundaryReceipt
                or worker_boundary.scenario_id != "prime.bounded-autonomy/v1"
                or worker_boundary.result_digest != typed_trace.gate_result_sha256
            ):
                raise ValueError
            value = object.__new__(cls)
            object.__setattr__(value, "trace", typed_trace)
            object.__setattr__(value, "platform_lock_sha256", platform_lock_sha256)
            object.__setattr__(value, "worker_boundary", worker_boundary)
            return value
        except (TypeError, ValueError):
            raise BoundedAutonomyLiveValidationError(
                "bounded autonomy live evidence is invalid"
            ) from None


def validate_bounded_autonomy_live_result(
    observation: object, authorization: object
) -> PrimeEvidenceReceipt:
    """Reject every non-admitted observation; no runtime is started here."""

    if (
        type(observation) is not BoundedAutonomyLiveObservation
        or type(authorization) is not BoundedAutonomyLiveAuthorization
        or frozenset(vars(observation)) != _OBSERVATION_FIELDS
        or frozenset(vars(authorization)) != _AUTHORIZATION_FIELDS
        or type(observation.platform_lock_sha256) is not str
        or _DIGEST.fullmatch(observation.platform_lock_sha256) is None
        or observation.platform_lock_sha256 != authorization.platform_lock_sha256
        or type(authorization.platform_lock_sha256) is not str
        or _DIGEST.fullmatch(authorization.platform_lock_sha256) is None
    ):
        raise BoundedAutonomyLiveValidationError(
            "bounded autonomy live evidence is invalid"
        )
    try:
        validate_bounded_autonomy_trace(observation.trace)
        worker = observation.worker_boundary
        if (
            type(worker) is not PrimeWorkerBoundaryReceipt
            or worker.scenario_id != "prime.bounded-autonomy/v1"
            or worker.role_id != "prime.bounded-autonomy"
            or worker.status != "PASS"
            or type(worker.result_digest) is not str
            or _DIGEST.fullmatch(worker.result_digest) is None
            or worker.result_digest != observation.trace.gate_result_sha256
            or any(
                getattr(authorization, name) is not True
                for name in (
                    "real_prime_ipython_attested", "gate_attested",
                    "broker_quiescent", "worker_destroyed",
                )
            )
        ):
            raise ValueError
    except (TypeError, ValueError):
        raise BoundedAutonomyLiveValidationError(
            "bounded autonomy live evidence is invalid"
        ) from None
    return validate_prime_evidence_receipt(
        PrimeEvidenceReceipt(
            "prime.bounded-autonomy/v1", PrimeEvidenceLevel.BOUNDED, "PASS"
        )
    )
