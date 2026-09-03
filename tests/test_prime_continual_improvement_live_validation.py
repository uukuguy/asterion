from __future__ import annotations

import unittest
from typing import Literal

from asterion.applications.prime_agent.continual_improvement_live_validation import (
    ContinualImprovementLiveAuthorization,
    ContinualImprovementLiveObservation,
    ContinualImprovementLiveValidationError,
    validate_continual_improvement_live_result,
)
from asterion.applications.prime_agent.continual_improvement_receipt import (
    ContinualImprovementTrace,
)
from asterion.applications.prime_agent.operator.continual_improvement_workload import (
    P6_CONTINUAL_IMPROVEMENT_MODEL_SHA256,
    P6_CONTINUAL_IMPROVEMENT_ORACLE_SHA256,
    P6_CONTINUAL_IMPROVEMENT_ROLLBACK_AUTHORITY_ID,
    P6_CONTINUAL_IMPROVEMENT_ROLLBACK_OUTCOME_SHA256,
    P6_CONTINUAL_IMPROVEMENT_ROLLBACK_PROPOSAL_ID,
    P6_CONTINUAL_IMPROVEMENT_ROLLBACK_RATIONALE_SHA256,
    P6_CONTINUAL_IMPROVEMENT_SCHEMA_SHA256,
    P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.worker_gate import PrimeWorkerBoundaryReceipt


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _trace(
    *, scope_kind: Literal["session", "project", "global"] = "project"
) -> ContinualImprovementTrace:
    return ContinualImprovementTrace(
        P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST,
        _digest("a"), _digest("b"), _digest("c"), _digest("d"), _digest("e"),
        _digest("f"), scope_kind, P6_CONTINUAL_IMPROVEMENT_ORACLE_SHA256,
        P6_CONTINUAL_IMPROVEMENT_MODEL_SHA256,
        P6_CONTINUAL_IMPROVEMENT_SCHEMA_SHA256, ("ipython",), 3, 10, 1, 1, 0,
        "preserved", P6_CONTINUAL_IMPROVEMENT_ROLLBACK_AUTHORITY_ID, 1,
        P6_CONTINUAL_IMPROVEMENT_ROLLBACK_PROPOSAL_ID,
        P6_CONTINUAL_IMPROVEMENT_ROLLBACK_RATIONALE_SHA256,
        P6_CONTINUAL_IMPROVEMENT_ROLLBACK_OUTCOME_SHA256, True, True, True,
    )


def _worker(result_digest: str) -> PrimeWorkerBoundaryReceipt:
    return PrimeWorkerBoundaryReceipt._admit(
        scenario_id="prime.continual-improvement/v1",
        role_id="prime.continual-improvement",
        worker_id="worker-1", run_id="run-1", challenge_digest=_digest("1"),
        workload_digest=_digest("2"), result_digest=result_digest,
        image_digest=_digest("3"),
    )


def _observation(
    *, scope_kind: Literal["session", "project", "global"] = "project"
) -> ContinualImprovementLiveObservation:
    trace = _trace(scope_kind=scope_kind)
    return ContinualImprovementLiveObservation._admit(
        trace=trace, platform_lock_sha256=_digest("4"),
        worker_boundary=_worker(trace.task_b_result_sha256),
    )


def _authorization(**changes: object) -> ContinualImprovementLiveAuthorization:
    values: dict[str, object] = {
        "platform_lock_sha256": _digest("4"),
        "real_prime_ipython_attested": True,
        "task_b_oracle_attested": True,
        "broker_quiescent": True,
        "worker_destroyed": True,
        "global_activation_approved": False,
        "global_scope_sha256": None,
    }
    values.update(changes)
    return ContinualImprovementLiveAuthorization(**values)  # type: ignore[arg-type]


class TestContinualImprovementLiveValidation(unittest.TestCase):
    def test_admitted_authorized_observation_issues_bounded_evidence(self) -> None:
        receipt = validate_continual_improvement_live_result(
            _observation(), _authorization()
        )
        self.assertEqual(receipt.scenario_id, "prime.continual-improvement/v1")
        self.assertEqual(receipt.level.value, "bounded")

    def test_requires_every_exact_authorization_attestation(self) -> None:
        for field in (
            "real_prime_ipython_attested", "task_b_oracle_attested",
            "broker_quiescent", "worker_destroyed",
        ):
            with self.subTest(field=field), self.assertRaises(
                ContinualImprovementLiveValidationError
            ):
                validate_continual_improvement_live_result(
                    _observation(), _authorization(**{field: False})
                )

    def test_requires_global_approval_bound_to_the_trace_scope(self) -> None:
        observation = _observation(scope_kind="global")
        for authorization in (
            _authorization(),
            _authorization(global_activation_approved=True, global_scope_sha256=_digest("9")),
        ):
            with self.subTest(authorization=authorization), self.assertRaises(
                ContinualImprovementLiveValidationError
            ):
                validate_continual_improvement_live_result(observation, authorization)

        receipt = validate_continual_improvement_live_result(
            observation,
            _authorization(
                global_activation_approved=True,
                global_scope_sha256=observation.trace.scope_sha256,
            ),
        )
        self.assertEqual(receipt.level.value, "bounded")

    def test_raw_trace_and_tampered_worker_are_rejected(self) -> None:
        with self.assertRaises(ContinualImprovementLiveValidationError):
            validate_continual_improvement_live_result(object(), _authorization())

        observation = _observation()
        object.__setattr__(observation, "worker_boundary", _worker(_digest("9")))
        with self.assertRaises(ContinualImprovementLiveValidationError):
            validate_continual_improvement_live_result(observation, _authorization())
