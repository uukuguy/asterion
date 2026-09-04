from __future__ import annotations

import unittest


class TestContinualImprovementWorker(unittest.TestCase):
    def test_adapter_has_only_fixed_p6_execution_identity(self) -> None:
        from asterion.applications.prime_agent.operator.continual_improvement_worker import (
            P6_CONTINUAL_IMPROVEMENT_ADAPTER,
        )

        self.assertEqual(
            P6_CONTINUAL_IMPROVEMENT_ADAPTER.scenario_id,
            "prime.continual-improvement/v1",
        )
        self.assertEqual(
            P6_CONTINUAL_IMPROVEMENT_ADAPTER.entrypoint,
            "/usr/local/bin/prime-continual-improvement.mjs",
        )

    def test_workload_exports_the_p6_scenario_and_role_identity(self) -> None:
        from asterion.applications.prime_agent.operator.continual_improvement_workload import (
            P6_CONTINUAL_IMPROVEMENT_ROLE_ID,
            P6_CONTINUAL_IMPROVEMENT_SCENARIO_ID,
        )

        self.assertEqual(P6_CONTINUAL_IMPROVEMENT_SCENARIO_ID, "prime.continual-improvement/v1")
        self.assertEqual(P6_CONTINUAL_IMPROVEMENT_ROLE_ID, "prime.continual-improvement")
