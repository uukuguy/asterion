from __future__ import annotations

import unittest

from asterion.applications.prime_agent.arc_agi_3_live_validation import (
    ArcAgi3FullAuthorization, ArcAgi3LiveAuthorization, ArcAgi3LiveObservation,
    ArcAgi3LiveValidationError, validate_arc_agi_3_full_result,
    validate_arc_agi_3_subset_result,
)
from asterion.applications.prime_agent.arc_agi_3_receipt import ArcAgi3Trace
from asterion.applications.prime_agent.operator.arc_agi_3_workload import (
    P7_ARC_AGI_3_FULL_SUITE_SHA256, P7_ARC_AGI_3_MODEL_SHA256,
    P7_ARC_AGI_3_ORACLE_SHA256, P7_ARC_AGI_3_SCHEMA_SHA256,
    P7_ARC_AGI_3_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.worker_gate import PrimeWorkerBoundaryReceipt


def _digest(character: str) -> str: return "sha256:" + character * 64


def _trace() -> ArcAgi3Trace:
    return ArcAgi3Trace(P7_ARC_AGI_3_WORKLOAD_DIGEST, _digest("a"), _digest("b"), _digest("c"), _digest("d"), P7_ARC_AGI_3_ORACLE_SHA256, P7_ARC_AGI_3_MODEL_SHA256, P7_ARC_AGI_3_SCHEMA_SHA256, ("ipython",), 1, 1, 4, 4, 1, 2, 1, 12, True, True, True, True)


def _worker(result: str) -> PrimeWorkerBoundaryReceipt:
    return PrimeWorkerBoundaryReceipt._admit(scenario_id="prime.arc-agi-3/v1", role_id="prime.arc-agi-3", worker_id="worker-1", run_id="run-1", challenge_digest=_digest("1"), workload_digest=_digest("2"), result_digest=result, image_digest=_digest("3"))


def _observation() -> ArcAgi3LiveObservation:
    trace = _trace()
    return ArcAgi3LiveObservation._admit(trace=trace, platform_lock_sha256=_digest("4"), worker_boundary=_worker(trace.score_sha256))


def _authorization(**changes: object) -> ArcAgi3LiveAuthorization:
    values: dict[str, object] = {"platform_lock_sha256": _digest("4"), "real_prime_ipython_attested": True, "broker_isolated": True, "score_replayed": True, "broker_quiescent": True, "worker_destroyed": True}
    values.update(changes)
    return ArcAgi3LiveAuthorization(**values)  # type: ignore[arg-type]


def _full_authorization(**changes: object) -> ArcAgi3FullAuthorization:
    values: dict[str, object] = {"platform_lock_sha256": _digest("4"), "full_suite_sha256": P7_ARC_AGI_3_FULL_SUITE_SHA256, "expected_game_count": 3, "completed_game_count": 3, "full_result_sha256": _digest("5"), "budget_authorization_id": "p7-full-budget", "full_reproduction_approved": True}
    values.update(changes)
    return ArcAgi3FullAuthorization(**values)  # type: ignore[arg-type]


class TestArcAgi3LiveValidation(unittest.TestCase):
    def test_issues_bounded_sandboxed_subset_only_from_complete_authorization(self) -> None:
        receipt = validate_arc_agi_3_subset_result(_observation(), _authorization())
        self.assertEqual(receipt.level.value, "bounded-sandboxed")

    def test_rejects_missing_subset_attestation_and_tampered_worker(self) -> None:
        for field in ("real_prime_ipython_attested", "broker_isolated", "score_replayed", "broker_quiescent", "worker_destroyed"):
            with self.subTest(field=field), self.assertRaises(ArcAgi3LiveValidationError):
                validate_arc_agi_3_subset_result(_observation(), _authorization(**{field: False}))
        observation = _observation()
        object.__setattr__(observation, "worker_boundary", _worker(_digest("9")))
        with self.assertRaises(ArcAgi3LiveValidationError):
            validate_arc_agi_3_subset_result(observation, _authorization())

    def test_full_authorization_cannot_be_inferred_from_subset(self) -> None:
        observation, authorization = _observation(), _authorization()
        with self.assertRaises(ArcAgi3LiveValidationError):
            validate_arc_agi_3_full_result(observation, authorization, _full_authorization(full_reproduction_approved=False))
        with self.assertRaises(ArcAgi3LiveValidationError):
            validate_arc_agi_3_full_result(observation, authorization, _full_authorization(completed_game_count=2))
        receipt = validate_arc_agi_3_full_result(observation, authorization, _full_authorization())
        self.assertEqual(receipt.level.value, "full-authorized")
