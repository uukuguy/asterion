from __future__ import annotations

import hashlib
import json
import unittest

from asterion.applications.prime_agent.operator.diagnostic_session_recovery_workload import (
    P4_DIAGNOSTIC_RECOVERY_MODEL_SHA256,
    P4_DIAGNOSTIC_RECOVERY_ORACLE_SHA256,
    P4_DIAGNOSTIC_RECOVERY_ROLE_ID,
    P4_DIAGNOSTIC_RECOVERY_SCENARIO_ID,
    P4_DIAGNOSTIC_RECOVERY_SCHEMA_SHA256,
    P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST,
    diagnostic_session_recovery_workload_manifest_bytes,
    is_diagnostic_session_recovery_workload,
)


class TestDiagnosticSessionRecoveryWorkload(unittest.TestCase):
    def test_exposes_one_canonical_fixed_ipython_manifest(self) -> None:
        payload = diagnostic_session_recovery_workload_manifest_bytes()
        manifest = json.loads(payload)

        self.assertEqual(manifest["scenario_id"], P4_DIAGNOSTIC_RECOVERY_SCENARIO_ID)
        self.assertEqual(manifest["role_id"], P4_DIAGNOSTIC_RECOVERY_ROLE_ID)
        self.assertEqual(manifest["model_tool_names"], ["ipython"])
        self.assertEqual(manifest["model_sha256"], P4_DIAGNOSTIC_RECOVERY_MODEL_SHA256)
        self.assertEqual(manifest["oracle_sha256"], P4_DIAGNOSTIC_RECOVERY_ORACLE_SHA256)
        self.assertEqual(manifest["schema_sha256"], P4_DIAGNOSTIC_RECOVERY_SCHEMA_SHA256)
        self.assertEqual(manifest["detach_count"], 1)
        self.assertEqual(manifest["attach_count"], 1)
        self.assertEqual(manifest["compaction_count"], 1)
        self.assertEqual(manifest["supervisor_recovery_count"], 1)
        self.assertGreater(manifest["root_action_ceiling"], 0)
        self.assertGreater(manifest["child_action_ceiling"], 0)
        self.assertGreater(manifest["root_usage_ceiling"], 0)
        self.assertGreater(manifest["child_usage_ceiling"], 0)
        self.assertFalse({"prompt", "path", "environment", "credential"} & set(manifest))
        self.assertEqual(
            P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST,
            "sha256:" + hashlib.sha256(payload).hexdigest(),
        )

    def test_recognizes_only_the_exact_workload_digest(self) -> None:
        self.assertTrue(is_diagnostic_session_recovery_workload(
            P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST
        ))
        for value in ("sha256:" + "0" * 64, P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST.upper(), 1):
            with self.subTest(value=value):
                self.assertFalse(is_diagnostic_session_recovery_workload(value))
