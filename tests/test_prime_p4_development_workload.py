from __future__ import annotations

import hashlib
import json
import unittest

from asterion.applications.prime_agent.operator.p4_development_workload import (
    P4_DEVELOPMENT_ORACLE_DIGEST,
    P4_DEVELOPMENT_SCHEMA_DIGEST,
    P4_DEVELOPMENT_SCOPE,
    P4_DEVELOPMENT_WORKLOAD_DIGEST,
    is_p4_development_workload,
    p4_development_workload_manifest_bytes,
)


class TestP4DevelopmentWorkload(unittest.TestCase):
    def test_exposes_the_fixed_unpromoted_native_reattach_contract(self) -> None:
        payload = p4_development_workload_manifest_bytes()
        manifest = json.loads(payload)

        self.assertEqual(manifest["scope"], P4_DEVELOPMENT_SCOPE)
        self.assertEqual(manifest["recovery_mode"], "native-direct-reattach")
        self.assertEqual(manifest["supervisor_recovery_count"], 0)
        self.assertEqual(manifest["daemon_restart_count"], 0)
        self.assertEqual(manifest["initial_attach_count"], 1)
        self.assertEqual(manifest["detach_count"], 1)
        self.assertEqual(manifest["reattach_count"], 1)
        self.assertEqual(manifest["prompt_count"], 2)
        self.assertEqual(manifest["provider_callback_count"], 5)
        self.assertEqual(manifest["ipython_call_count"], 2)
        self.assertEqual(manifest["manual_compact_count"], 1)
        self.assertEqual(manifest["runtime_identity_count"], 1)
        self.assertEqual(manifest["session_identity_count"], 1)
        self.assertEqual(manifest["transcript_identity_count"], 1)
        self.assertEqual(manifest["kernel_identity_count"], 1)
        self.assertEqual(manifest["kernel_restart_count"], 0)
        self.assertEqual(manifest["child_count"], 0)
        self.assertEqual(manifest["replay_mode"], "zero-gap-exact")
        self.assertEqual(manifest["checkpoint_mode"], "readback")
        self.assertEqual(manifest["model_state"], "settled")
        self.assertEqual(manifest["tool_state"], "settled")
        self.assertEqual(manifest["oracle_continuity"], "same")
        self.assertEqual(manifest["cleanup"], "full")
        self.assertEqual(manifest["oracle_sha256"], P4_DEVELOPMENT_ORACLE_DIGEST)
        self.assertEqual(manifest["schema_sha256"], P4_DEVELOPMENT_SCHEMA_DIGEST)
        self.assertFalse(
            {"prompt", "prompts", "provider", "provider_config", "authority"}
            & set(manifest)
        )
        self.assertEqual(
            P4_DEVELOPMENT_WORKLOAD_DIGEST,
            "sha256:" + hashlib.sha256(payload).hexdigest(),
        )

    def test_recognizes_only_the_canonical_digest(self) -> None:
        self.assertTrue(is_p4_development_workload(P4_DEVELOPMENT_WORKLOAD_DIGEST))
        self.assertFalse(is_p4_development_workload("sha256:" + "0" * 64))
        self.assertFalse(is_p4_development_workload(True))
