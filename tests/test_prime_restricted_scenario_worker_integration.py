"""Provider-free cross-scenario closure for P4--P7 sealed worker adapters."""

from __future__ import annotations

from dataclasses import replace
import unittest
from typing import cast

from asterion.applications.prime_agent.operator.arc_agi_3_worker import (
    P7_ARC_AGI_3_ADAPTER,
)
from asterion.applications.prime_agent.operator.bounded_autonomy_worker import (
    P5_BOUNDED_AUTONOMY_ADAPTER,
)
from asterion.applications.prime_agent.operator.continual_improvement_worker import (
    P6_CONTINUAL_IMPROVEMENT_ADAPTER,
)
from asterion.applications.prime_agent.operator.diagnostic_session_recovery_worker import (
    P4_DIAGNOSTIC_SESSION_RECOVERY_ADAPTER,
)
from asterion.applications.prime_agent.operator.restricted_scenario_worker import (
    RestrictedScenarioAdapter,
    RestrictedScenarioEngine,
    RestrictedScenarioWorker,
)
from asterion.services.restricted_worker import (
    RestrictedWorkerError,
    RestrictedWorkerRequest,
)


_IMAGE = "sha256:" + "a" * 64
_CHALLENGE = "sha256:" + "b" * 64
_ADAPTERS = (
    P4_DIAGNOSTIC_SESSION_RECOVERY_ADAPTER,
    P5_BOUNDED_AUTONOMY_ADAPTER,
    P6_CONTINUAL_IMPROVEMENT_ADAPTER,
    P7_ARC_AGI_3_ADAPTER,
)


class TestRestrictedScenarioWorkerIntegration(unittest.TestCase):
    def test_each_adapter_rejects_every_foreign_role_and_workload_before_launch(
        self,
    ) -> None:
        class Engine:
            pass

        for adapter in _ADAPTERS:
            with self.subTest(adapter=adapter.scenario_id):
                worker = RestrictedScenarioWorker(
                    image_digest=_IMAGE,
                    engine=cast(RestrictedScenarioEngine, Engine()),
                    adapter=adapter,
                )
                request = RestrictedWorkerRequest(
                    adapter.role_id,
                    _IMAGE,
                    "run-1",
                    _CHALLENGE,
                    adapter.workload_digest,
                    adapter.max_runtime_seconds,
                    adapter.max_output_bytes,
                )
                for foreign in _ADAPTERS:
                    if foreign is adapter:
                        continue
                    with self.subTest(foreign=foreign.scenario_id), self.assertRaises(
                        RestrictedWorkerError
                    ):
                        worker.open(
                            replace(
                                request,
                                role_id=foreign.role_id,
                                workload_digest=foreign.workload_digest,
                            )
                        )

    def test_adapter_identities_are_unique_fixed_pairs(self) -> None:
        pairs = tuple((adapter.role_id, adapter.workload_digest) for adapter in _ADAPTERS)
        self.assertEqual(len(pairs), len(set(pairs)))
        self.assertTrue(all(type(adapter) is RestrictedScenarioAdapter for adapter in _ADAPTERS))
