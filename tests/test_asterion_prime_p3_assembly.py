"""Tests for the P3 application assembly JSON (Phase 7, Task 2)."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestPrimeP3Assembly(unittest.TestCase):
    def test_assembly_references_capability_package_and_services(self) -> None:
        path = (
            REPO_ROOT
            / "src/asterion/applications/prime/assemblies/prime-recursive-workflow.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["protocol"], "asterion.application-assembly/v1")
        self.assertEqual(data["application_id"], "prime.recursive-workflow")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["runtime_id"], "asterion.prime")
        self.assertEqual(
            set(data["host_capabilities"]),
            {
                "prime.child-runner",
                "prime.p3-oracle",
                "prime.pi-extension",
                "prime.private-trace",
                "prime.session-backend",
            },
        )
        self.assertEqual(data["host_policies"], [])
        self.assertEqual(data["host_events"], [])
        self.assertEqual(data["host_artifacts"], [])
        self.assertEqual(len(data["capability_packages"]), 1)
        self.assertEqual(
            data["capability_packages"][0]["package_id"],
            "prime-recursive-workflow-native",
        )
        self.assertEqual(
            data["capability_packages"][0]["version"], "1.0.0"
        )
        self.assertEqual(len(data["capabilities"]), 1)
        self.assertEqual(
            data["capabilities"][0]["capability_id"],
            "prime.recursive-workflow",
        )
        self.assertEqual(data["capabilities"][0]["version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
