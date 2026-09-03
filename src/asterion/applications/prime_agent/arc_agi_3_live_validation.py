"""Private P7 subset and full-suite evidence authorization reducers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import cast

from asterion.applications.prime_agent.arc_agi_3_receipt import ArcAgi3Trace, validate_arc_agi_3_trace
from asterion.applications.prime_agent.evidence import PrimeEvidenceLevel, PrimeEvidenceReceipt, validate_prime_evidence_receipt
from asterion.applications.prime_agent.operator.arc_agi_3_workload import P7_ARC_AGI_3_FULL_SUITE_SHA256
from asterion.applications.prime_agent.worker_gate import PrimeWorkerBoundaryReceipt


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_AUTH_FIELDS = frozenset({"platform_lock_sha256", "real_prime_ipython_attested", "broker_isolated", "score_replayed", "broker_quiescent", "worker_destroyed"})
_FULL_FIELDS = frozenset({"platform_lock_sha256", "full_suite_sha256", "expected_game_count", "completed_game_count", "full_result_sha256", "budget_authorization_id", "full_reproduction_approved"})
_OBS_FIELDS = frozenset({"trace", "platform_lock_sha256", "worker_boundary"})


class ArcAgi3LiveValidationError(ValueError):
    """Raised without disclosing private ARC or worker data."""


@dataclass(frozen=True, repr=False)
class ArcAgi3LiveAuthorization:
    platform_lock_sha256: str
    real_prime_ipython_attested: bool
    broker_isolated: bool
    score_replayed: bool
    broker_quiescent: bool
    worker_destroyed: bool


@dataclass(frozen=True, repr=False)
class ArcAgi3FullAuthorization:
    platform_lock_sha256: str
    full_suite_sha256: str
    expected_game_count: int
    completed_game_count: int
    full_result_sha256: str
    budget_authorization_id: str
    full_reproduction_approved: bool


@dataclass(frozen=True, repr=False, init=False)
class ArcAgi3LiveObservation:
    trace: ArcAgi3Trace
    platform_lock_sha256: str
    worker_boundary: PrimeWorkerBoundaryReceipt

    @classmethod
    def _admit(cls, *, trace: object, platform_lock_sha256: object, worker_boundary: object) -> "ArcAgi3LiveObservation":
        try:
            validate_arc_agi_3_trace(trace)
            typed = cast(ArcAgi3Trace, trace)
            if type(platform_lock_sha256) is not str or _DIGEST.fullmatch(platform_lock_sha256) is None or type(worker_boundary) is not PrimeWorkerBoundaryReceipt or worker_boundary.scenario_id != "prime.arc-agi-3/v1" or worker_boundary.result_digest != typed.score_sha256:
                raise ValueError
            value = object.__new__(cls)
            object.__setattr__(value, "trace", typed)
            object.__setattr__(value, "platform_lock_sha256", platform_lock_sha256)
            object.__setattr__(value, "worker_boundary", worker_boundary)
            return value
        except (TypeError, ValueError):
            raise ArcAgi3LiveValidationError("ARC-AGI-3 live evidence is invalid") from None


def validate_arc_agi_3_subset_result(observation: object, authorization: object) -> PrimeEvidenceReceipt:
    """Issue bounded-sandboxed subset evidence only from exact live facts."""
    try:
        if type(observation) is not ArcAgi3LiveObservation or type(authorization) is not ArcAgi3LiveAuthorization or frozenset(vars(observation)) != _OBS_FIELDS or frozenset(vars(authorization)) != _AUTH_FIELDS or type(observation.platform_lock_sha256) is not str or _DIGEST.fullmatch(observation.platform_lock_sha256) is None or observation.platform_lock_sha256 != authorization.platform_lock_sha256 or type(authorization.platform_lock_sha256) is not str or _DIGEST.fullmatch(authorization.platform_lock_sha256) is None:
            raise ValueError
        typed_observation = cast(ArcAgi3LiveObservation, observation)
        typed_authorization = cast(ArcAgi3LiveAuthorization, authorization)
        validate_arc_agi_3_trace(typed_observation.trace)
        worker = typed_observation.worker_boundary
        if type(worker) is not PrimeWorkerBoundaryReceipt or worker.scenario_id != "prime.arc-agi-3/v1" or worker.role_id != "prime.arc-agi-3" or worker.status != "PASS" or worker.result_digest != typed_observation.trace.score_sha256 or any(getattr(typed_authorization, name) is not True for name in ("real_prime_ipython_attested", "broker_isolated", "score_replayed", "broker_quiescent", "worker_destroyed")):
            raise ValueError
    except (TypeError, ValueError):
        raise ArcAgi3LiveValidationError("ARC-AGI-3 live evidence is invalid") from None
    return validate_prime_evidence_receipt(PrimeEvidenceReceipt("prime.arc-agi-3/v1", PrimeEvidenceLevel.BOUNDED_SANDBOXED, "PASS"))


def validate_arc_agi_3_full_result(observation: object, authorization: object, full_authorization: object) -> PrimeEvidenceReceipt:
    """Issue full evidence only from an independently authorized full suite."""
    validate_arc_agi_3_subset_result(observation, authorization)
    try:
        typed_observation = cast(ArcAgi3LiveObservation, observation)
        typed_authorization = cast(ArcAgi3LiveAuthorization, authorization)
        if type(full_authorization) is not ArcAgi3FullAuthorization:
            raise ValueError
        typed_full = cast(ArcAgi3FullAuthorization, full_authorization)
        if frozenset(vars(typed_full)) != _FULL_FIELDS or typed_full.platform_lock_sha256 != typed_authorization.platform_lock_sha256 or typed_full.full_suite_sha256 != P7_ARC_AGI_3_FULL_SUITE_SHA256 or type(typed_full.expected_game_count) is not int or typed_full.expected_game_count != 3 or type(typed_full.completed_game_count) is not int or typed_full.completed_game_count != typed_full.expected_game_count or type(typed_full.full_result_sha256) is not str or _DIGEST.fullmatch(typed_full.full_result_sha256) is None or typed_full.full_result_sha256 == typed_observation.trace.score_sha256 or type(typed_full.budget_authorization_id) is not str or not typed_full.budget_authorization_id or typed_full.full_reproduction_approved is not True:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise ArcAgi3LiveValidationError("ARC-AGI-3 live evidence is invalid") from None
    return validate_prime_evidence_receipt(PrimeEvidenceReceipt("prime.arc-agi-3/v1", PrimeEvidenceLevel.FULL_AUTHORIZED, "PASS"))
