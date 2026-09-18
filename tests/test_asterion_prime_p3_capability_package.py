"""Tests for the P3 capability-package JSON contracts (Phase 7, Task 1)."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestPrimeP3CapabilityPackage(unittest.TestCase):
    def test_package_loads_and_lists_required_services(self) -> None:
        path = (
            REPO_ROOT
            / "src/asterion/capabilities/prime_recursive_workflow_native"
            / "payload/capability-package.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["protocol"], "asterion.capability-package/v1")
        self.assertEqual(data["package_id"], "prime-recursive-workflow-native")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(len(data["capabilities"]), 1)
        self.assertEqual(data["capabilities"][0]["capability_id"], "prime.recursive-workflow")
        self.assertEqual(data["capabilities"][0]["version"], "1.0.0")
        self.assertEqual(data["benchmark_suites"], [])
        self.assertEqual(data["resources"], [])
        self.assertEqual(data["conformance"], [])

    def test_capability_id_matches_application_id(self) -> None:
        path = (
            REPO_ROOT
            / "src/asterion/capabilities/prime_recursive_workflow_native"
            / "payload/capabilities/prime-recursive-workflow.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["protocol"], "asterion.capability/v1")
        self.assertEqual(data["capability_id"], "prime.recursive-workflow")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["kind"], "capability")
        self.assertEqual(data["provides_capabilities"], ["prime.recursive-workflow"])
        self.assertEqual(
            data["requires_capabilities"],
            [
                "prime.child-runner",
                "prime.p3-oracle",
                "prime.pi-extension",
                "prime.private-trace",
                "prime.session-backend",
            ],
        )
        self.assertEqual(
            set(data["requires_capabilities"]),
            {
                "prime.child-runner",
                "prime.p3-oracle",
                "prime.pi-extension",
                "prime.private-trace",
                "prime.session-backend",
            },
        )
        self.assertEqual(
            data["produces_artifacts"],
            ["application/vnd.asterion.prime.p3-native-receipt+json"],
        )


if __name__ == "__main__":
    unittest.main()