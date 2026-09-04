from __future__ import annotations

import unittest

from asterion.applications.prime_agent.bounded_autonomy_receipt import (
    BoundedAutonomyTrace,
)
from asterion.applications.prime_agent.operator.bounded_autonomy_completion import (
    BoundedAutonomyCompletion,
    canonical_bounded_autonomy_completion_bytes,
)
from asterion.applications.prime_agent.operator.bounded_autonomy_worker import (
    BoundedAutonomyWorker,
    P5_BOUNDED_AUTONOMY_ADAPTER,
)
from asterion.applications.prime_agent.operator.bounded_autonomy_workload import (
    P5_BOUNDED_AUTONOMY_MODEL_SHA256,
    P5_BOUNDED_AUTONOMY_ORACLE_SHA256,
    P5_BOUNDED_AUTONOMY_SCHEMA_SHA256,
    P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.operator.continual_improvement_completion import (
    ContinualImprovementCompletion,
    canonical_continual_improvement_completion_bytes,
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
from asterion.applications.prime_agent.operator.restricted_scenario_worker import (
    RestrictedScenarioInspection,
)
from asterion.services.restricted_worker import (
    RestrictedWorkerError,
    RestrictedWorkerLease,
    RestrictedWorkerRequest,
)


def _digest(letter: str) -> str:
    return "sha256:" + letter * 64


class TestBoundedAutonomyWorker(unittest.IsolatedAsyncioTestCase):
    async def test_p5_worker_rejects_a_p6_completion(self) -> None:
        p5 = BoundedAutonomyTrace(
            P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST, _digest("a"), _digest("b"),
            _digest("c"), _digest("d"), P5_BOUNDED_AUTONOMY_ORACLE_SHA256,
            P5_BOUNDED_AUTONOMY_MODEL_SHA256, P5_BOUNDED_AUTONOMY_SCHEMA_SHA256,
            ("ipython",), 2, 2, 2, 1, True, True, True, True, True, True,
        )
        p6 = ContinualImprovementTrace(
            P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST, _digest("a"), _digest("b"),
            _digest("c"), _digest("d"), _digest("e"), _digest("f"), "project",
            P6_CONTINUAL_IMPROVEMENT_ORACLE_SHA256,
            P6_CONTINUAL_IMPROVEMENT_MODEL_SHA256,
            P6_CONTINUAL_IMPROVEMENT_SCHEMA_SHA256, ("ipython",), 3, 10, 1, 1,
            0, "preserved", P6_CONTINUAL_IMPROVEMENT_ROLLBACK_AUTHORITY_ID, 1,
            P6_CONTINUAL_IMPROVEMENT_ROLLBACK_PROPOSAL_ID,
            P6_CONTINUAL_IMPROVEMENT_ROLLBACK_RATIONALE_SHA256,
            P6_CONTINUAL_IMPROVEMENT_ROLLBACK_OUTCOME_SHA256, True, True, True,
        )
        class Engine:
            def __init__(self, completion: bytes) -> None:
                self.completion = completion

            async def launch(self, **kwargs: object) -> RestrictedWorkerLease:
                return RestrictedWorkerLease(
                    "worker-p5", P5_BOUNDED_AUTONOMY_ADAPTER.role_id, "run-p5",
                    _digest("0"), P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST,
                )

            async def completion_bytes(self, lease: RestrictedWorkerLease) -> bytes:
                return self.completion

            async def inspect(
                self, lease: RestrictedWorkerLease
            ) -> RestrictedScenarioInspection:
                raise AssertionError("not used")

            async def remove(self, lease: RestrictedWorkerLease) -> None:
                return None

        request = RestrictedWorkerRequest(
            P5_BOUNDED_AUTONOMY_ADAPTER.role_id, _digest("f"), "run-p5",
            _digest("0"), P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST, 300, 4096,
        )
        valid_worker = BoundedAutonomyWorker(
            image_digest=_digest("f"),
            engine=Engine(
                canonical_bounded_autonomy_completion_bytes(BoundedAutonomyCompletion(p5))
            ),
        )
        async with valid_worker.open(request) as lease:
            self.assertEqual(
                (await valid_worker.execution_receipt(lease)).workload_digest,
                P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST,
            )

        foreign_worker = BoundedAutonomyWorker(
            image_digest=_digest("f"),
            engine=Engine(
                canonical_continual_improvement_completion_bytes(
                    ContinualImprovementCompletion(p6)
                )
            ),
        )
        context = foreign_worker.open(request)
        lease = await context.__aenter__()
        with self.assertRaises(RestrictedWorkerError):
            await foreign_worker.execution_receipt(lease)
        with self.assertRaises(RestrictedWorkerError):
            await context.__aexit__(None, None, None)
