from __future__ import annotations

from hashlib import sha256
import json
import unittest


class TestP7DevelopmentWorkload(unittest.TestCase):
    def test_exposes_the_closed_unpromoted_single_game_declaration(self) -> None:
        from asterion.applications.prime_agent.operator import p7_development_workload as workload

        payload = workload.p7_development_workload_manifest_bytes()
        manifest = json.loads(payload)
        self.assertEqual((workload.P7_DEVELOPMENT_SCOPE, workload.P7_DEVELOPMENT_PROMOTION), ("p7-development", "unpromoted"))
        self.assertEqual(manifest["game_id"], "ls20-9607627b")
        self.assertEqual(manifest["seed"], 0)
        self.assertEqual(manifest["game_count"], 1)
        self.assertEqual(manifest["action_ceiling"], 4)
        self.assertEqual(manifest["prompt_count"], 3)
        self.assertEqual(manifest["provider_callback_count"], 6)
        self.assertEqual(manifest["ipython_call_count"], 3)
        self.assertEqual(manifest["terminal_reasons"], ["action-limit", "engine-terminal"])
        self.assertIn("episode_closed", manifest["receipt_schema"]["boolean_facts"])
        self.assertIn("broker_call_count=action_count+2", manifest["receipt_schema"]["relations"])
        self.assertEqual(workload.P7_DEVELOPMENT_WORKLOAD_DIGEST, "sha256:" + sha256(payload).hexdigest())
        self.assertNotIn("prompt", manifest)
        self.assertTrue(workload.is_p7_development_workload(workload.P7_DEVELOPMENT_WORKLOAD_DIGEST))
