"""Closed workload tests for the fixed Prime P7 ARC-AGI-3 subset."""

from __future__ import annotations

from hashlib import sha256
import json
import unittest

from asterion.applications.prime_agent.operator.arc_agi_3_workload import (
    P7_ARC_AGI_3_ACTION_CEILING,
    P7_ARC_AGI_3_MODEL_SHA256,
    P7_ARC_AGI_3_ORACLE_SHA256,
    P7_ARC_AGI_3_ROLE_ID,
    P7_ARC_AGI_3_SCENARIO_ID,
    P7_ARC_AGI_3_SCHEMA_SHA256,
    P7_ARC_AGI_3_USAGE_CEILING,
    P7_ARC_AGI_3_WORKLOAD_DIGEST,
    arc_agi_3_workload_manifest_bytes,
    is_arc_agi_3_workload,
)


class TestArcAgi3Workload(unittest.TestCase):
    def test_exposes_one_canonical_ipython_single_game_workload(self) -> None:
        payload = arc_agi_3_workload_manifest_bytes()
        manifest = json.loads(payload)

        self.assertEqual(
            P7_ARC_AGI_3_WORKLOAD_DIGEST, "sha256:" + sha256(payload).hexdigest()
        )
        self.assertEqual(manifest["scenario_id"], P7_ARC_AGI_3_SCENARIO_ID)
        self.assertEqual(manifest["role_id"], P7_ARC_AGI_3_ROLE_ID)
        self.assertEqual(manifest["model_tool_names"], ["ipython"])
        self.assertEqual(manifest["model_sha256"], P7_ARC_AGI_3_MODEL_SHA256)
        self.assertEqual(manifest["oracle_sha256"], P7_ARC_AGI_3_ORACLE_SHA256)
        self.assertEqual(manifest["schema_sha256"], P7_ARC_AGI_3_SCHEMA_SHA256)
        self.assertEqual(manifest["action_ceiling"], P7_ARC_AGI_3_ACTION_CEILING)
        self.assertEqual(manifest["usage_ceiling"], P7_ARC_AGI_3_USAGE_CEILING)
        self.assertEqual(manifest["game_ceiling"], 1)
        self.assertFalse({"prompt", "path", "credential", "game_id"} & set(manifest))

    def test_recognizes_only_the_exact_workload_digest(self) -> None:
        self.assertTrue(is_arc_agi_3_workload(P7_ARC_AGI_3_WORKLOAD_DIGEST))
        for value in ("sha256:" + "0" * 64, P7_ARC_AGI_3_WORKLOAD_DIGEST.upper(), 1):
            with self.subTest(value=value):
                self.assertFalse(is_arc_agi_3_workload(value))
