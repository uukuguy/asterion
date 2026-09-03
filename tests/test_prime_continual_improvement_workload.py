from __future__ import annotations

from hashlib import sha256
import json
import unittest

from asterion.applications.prime_agent.operator.continual_improvement_workload import (
    P6_CONTINUAL_IMPROVEMENT_MODEL_SHA256,
    P6_CONTINUAL_IMPROVEMENT_ORACLE_SHA256,
    P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST,
    continual_improvement_workload_manifest_bytes,
    is_continual_improvement_workload,
)


class TestContinualImprovementWorkload(unittest.TestCase):
    def test_exposes_one_fixed_ipython_refinement_workload(self) -> None:
        payload = continual_improvement_workload_manifest_bytes()
        manifest = json.loads(payload)
        self.assertEqual(P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST, "sha256:" + sha256(payload).hexdigest())
        self.assertEqual(manifest["scenario_id"], "prime.continual-improvement/v1")
        self.assertEqual(manifest["model_tool_names"], ["ipython"])
        self.assertEqual(manifest["model_sha256"], P6_CONTINUAL_IMPROVEMENT_MODEL_SHA256)
        self.assertEqual(manifest["oracle_sha256"], P6_CONTINUAL_IMPROVEMENT_ORACLE_SHA256)
        self.assertEqual(manifest["candidate_ceiling"], 1)
        self.assertEqual(manifest["holdout_ceiling"], 1)
        self.assertEqual(manifest["rollback_ceiling"], 1)
        self.assertFalse({"prompt", "path", "environment", "credential"} & set(manifest))

    def test_recognizes_only_the_exact_workload_digest(self) -> None:
        self.assertTrue(is_continual_improvement_workload(P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST))
        self.assertFalse(is_continual_improvement_workload("sha256:" + "0" * 64))
