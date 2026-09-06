from __future__ import annotations

from hashlib import sha256
import json
import unittest


class TestP6DevelopmentWorkload(unittest.TestCase):
    def test_exposes_fixed_project_clamp_contract_with_canonical_hashes(self) -> None:
        from asterion.applications.prime_agent.operator.p6_development_workload import (
            P6_DEVELOPMENT_BASELINE_SNAPSHOT_SHA256,
            P6_DEVELOPMENT_CANDIDATE_SNAPSHOT_SHA256,
            P6_DEVELOPMENT_PROMOTION,
            P6_DEVELOPMENT_SCOPE,
            P6_DEVELOPMENT_WORKLOAD_DIGEST,
            p6_development_workload_manifest_bytes,
        )

        payload = p6_development_workload_manifest_bytes()
        manifest = json.loads(payload)
        self.assertEqual(
            (P6_DEVELOPMENT_SCOPE, P6_DEVELOPMENT_PROMOTION),
            ("p6-development", "unpromoted"),
        )
        self.assertEqual(manifest["scope_kind"], "project")
        self.assertEqual(manifest["prompt_count"], 3)
        self.assertEqual(manifest["provider_callback_count"], 6)
        self.assertEqual(manifest["ipython_call_count"], 3)
        self.assertEqual(manifest["candidate_count"], 1)
        self.assertEqual(manifest["holdout_count"], 1)
        self.assertEqual(manifest["rollback_ceiling"], 1)
        self.assertEqual(
            P6_DEVELOPMENT_WORKLOAD_DIGEST,
            "sha256:" + sha256(payload).hexdigest(),
        )
        self.assertRegex(P6_DEVELOPMENT_BASELINE_SNAPSHOT_SHA256, r"\Asha256:[0-9a-f]{64}\Z")
        self.assertRegex(P6_DEVELOPMENT_CANDIDATE_SNAPSHOT_SHA256, r"\Asha256:[0-9a-f]{64}\Z")
        self.assertNotIn("prompt", {key for key in manifest if key.endswith("_body")})
