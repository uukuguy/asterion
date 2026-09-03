"""Closed workload identity tests for the fixed Prime P5 repair loop."""

from __future__ import annotations

from hashlib import sha256
import json
import unittest

from asterion.applications.prime_agent.operator.bounded_autonomy_workload import (
    P5_BOUNDED_AUTONOMY_ACTION_CEILING,
    P5_BOUNDED_AUTONOMY_MODEL_SHA256,
    P5_BOUNDED_AUTONOMY_ORACLE_SHA256,
    P5_BOUNDED_AUTONOMY_ROLE_ID,
    P5_BOUNDED_AUTONOMY_SCENARIO_ID,
    P5_BOUNDED_AUTONOMY_SCHEMA_SHA256,
    P5_BOUNDED_AUTONOMY_USAGE_CEILING,
    P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST,
    bounded_autonomy_workload_manifest_bytes,
    is_bounded_autonomy_workload,
)


class TestBoundedAutonomyWorkload(unittest.TestCase):
    def test_exposes_one_canonical_fixed_ipython_repair_loop(self) -> None:
        payload = bounded_autonomy_workload_manifest_bytes()
        manifest = json.loads(payload)

        self.assertEqual(
            P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST,
            "sha256:" + sha256(payload).hexdigest(),
        )
        self.assertEqual(manifest["scenario_id"], P5_BOUNDED_AUTONOMY_SCENARIO_ID)
        self.assertEqual(manifest["role_id"], P5_BOUNDED_AUTONOMY_ROLE_ID)
        self.assertEqual(manifest["model_tool_names"], ["ipython"])
        self.assertEqual(manifest["model_sha256"], P5_BOUNDED_AUTONOMY_MODEL_SHA256)
        self.assertEqual(manifest["oracle_sha256"], P5_BOUNDED_AUTONOMY_ORACLE_SHA256)
        self.assertEqual(manifest["schema_sha256"], P5_BOUNDED_AUTONOMY_SCHEMA_SHA256)
        self.assertEqual(manifest["action_ceiling"], P5_BOUNDED_AUTONOMY_ACTION_CEILING)
        self.assertEqual(manifest["usage_ceiling"], P5_BOUNDED_AUTONOMY_USAGE_CEILING)
        self.assertEqual(manifest["gate_ceiling"], 2)
        self.assertEqual(manifest["feedback_ceiling"], 1)
        self.assertFalse({"prompt", "path", "environment", "credential"} & set(manifest))

    def test_recognizes_only_the_exact_workload_digest(self) -> None:
        self.assertTrue(is_bounded_autonomy_workload(P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST))
        for value in ("sha256:" + "0" * 64, P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST.upper(), 1):
            with self.subTest(value=value):
                self.assertFalse(is_bounded_autonomy_workload(value))
