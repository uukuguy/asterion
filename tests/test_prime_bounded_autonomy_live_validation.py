from __future__ import annotations

import unittest

from asterion.applications.prime_agent.bounded_autonomy_live_validation import (
    BoundedAutonomyLiveAuthorization,
    BoundedAutonomyLiveObservation,
    BoundedAutonomyLiveValidationError,
    validate_bounded_autonomy_live_result,
)
from asterion.applications.prime_agent.bounded_autonomy_receipt import (
    BoundedAutonomyTrace,
)
from asterion.applications.prime_agent.worker_gate import PrimeWorkerBoundaryReceipt
from asterion.applications.prime_agent.operator.bounded_autonomy_workload import (
    P5_BOUNDED_AUTONOMY_MODEL_SHA256,
    P5_BOUNDED_AUTONOMY_ORACLE_SHA256,
    P5_BOUNDED_AUTONOMY_SCHEMA_SHA256,
    P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST,
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _trace() -> BoundedAutonomyTrace:
    return BoundedAutonomyTrace(
        P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST, _digest("b"), _digest("c"), _digest("d"), _digest("e"),
        P5_BOUNDED_AUTONOMY_ORACLE_SHA256, P5_BOUNDED_AUTONOMY_MODEL_SHA256, P5_BOUNDED_AUTONOMY_SCHEMA_SHA256, ("ipython",), 2, 2, 2, 1,
        True, True, True, True, True, True,
    )


def _worker(result_digest: str) -> PrimeWorkerBoundaryReceipt:
    return PrimeWorkerBoundaryReceipt._admit(
        scenario_id="prime.bounded-autonomy/v1",
        role_id="prime.bounded-autonomy",
        worker_id="worker-1",
        run_id="run-1",
        challenge_digest=_digest("2"),
        workload_digest=_digest("3"),
        result_digest=result_digest,
        image_digest=_digest("4"),
    )


def _observation() -> BoundedAutonomyLiveObservation:
    trace = _trace()
    return BoundedAutonomyLiveObservation._admit(
        trace=trace,
        platform_lock_sha256=_digest("5"),
        worker_boundary=_worker(trace.gate_result_sha256),
    )


def _authorization(**changes: object) -> BoundedAutonomyLiveAuthorization:
    values: dict[str, object] = {
        "platform_lock_sha256": _digest("5"),
        "real_prime_ipython_attested": True,
        "gate_attested": True,
        "broker_quiescent": True,
        "worker_destroyed": True,
    }
    values.update(changes)
    return BoundedAutonomyLiveAuthorization(**values)  # type: ignore[arg-type]


class TestBoundedAutonomyLiveValidation(unittest.TestCase):
    def test_admitted_authorized_observation_issues_bounded_evidence(self) -> None:
        receipt = validate_bounded_autonomy_live_result(
            _observation(), _authorization()
        )
        self.assertEqual(receipt.scenario_id, "prime.bounded-autonomy/v1")
        self.assertEqual(receipt.level.value, "bounded")

    def test_requires_every_exact_authorization_attestation(self) -> None:
        for field in (
            "real_prime_ipython_attested", "gate_attested", "broker_quiescent",
            "worker_destroyed",
        ):
            with self.subTest(field=field), self.assertRaises(
                BoundedAutonomyLiveValidationError
            ):
                validate_bounded_autonomy_live_result(
                    _observation(), _authorization(**{field: False})
                )

    def test_revalidates_worker_and_platform_binding_after_admission(self) -> None:
        observation = _observation()
        object.__setattr__(observation, "worker_boundary", _worker(_digest("9")))
        with self.assertRaises(BoundedAutonomyLiveValidationError):
            validate_bounded_autonomy_live_result(observation, _authorization())

        observation = _observation()
        object.__setattr__(observation, "platform_lock_sha256", "not-a-digest")
        with self.assertRaises(BoundedAutonomyLiveValidationError):
            validate_bounded_autonomy_live_result(observation, _authorization())

    def test_raw_trace_and_missing_authorization_are_rejected(self) -> None:
        authorization = _authorization()
        with self.assertRaises(BoundedAutonomyLiveValidationError):
            validate_bounded_autonomy_live_result(object(), authorization)
        with self.assertRaises(BoundedAutonomyLiveValidationError):
            validate_bounded_autonomy_live_result(object(), object())
