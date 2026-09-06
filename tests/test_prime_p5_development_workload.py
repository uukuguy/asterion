from __future__ import annotations

import hashlib
import json
import unittest


class TestP5DevelopmentWorkload(unittest.TestCase):
    def test_exposes_the_fixed_unpromoted_repair_contract(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_workload import (
            P5_DEVELOPMENT_PROMOTION,
            P5_DEVELOPMENT_SCOPE,
            P5_DEVELOPMENT_WORKLOAD_DIGEST,
            p5_development_workload_manifest_bytes,
        )

        payload = p5_development_workload_manifest_bytes()
        manifest = json.loads(payload)
        self.assertEqual((P5_DEVELOPMENT_SCOPE, P5_DEVELOPMENT_PROMOTION), ("p5-development", "unpromoted"))
        self.assertEqual(manifest["repair"], "clamp-defect")
        self.assertEqual(manifest["prompt_count"], 2)
        self.assertEqual(manifest["provider_callback_count"], 4)
        self.assertEqual(manifest["ipython_call_count"], 2)
        self.assertEqual(manifest["result_gate_count"], 2)
        self.assertEqual(manifest["quality_gate_count"], 2)
        self.assertEqual(manifest["feedback_count"], 1)
        self.assertEqual(manifest["repair_count"], 1)
        self.assertEqual(manifest["retry_count"], 0)
        self.assertEqual(manifest["child_count"], 0)
        self.assertEqual(manifest["compact_count"], 0)
        self.assertEqual(P5_DEVELOPMENT_WORKLOAD_DIGEST, "sha256:" + hashlib.sha256(payload).hexdigest())
        self.assertFalse({"prompt", "provider", "workspace", "source"} & set(manifest))
