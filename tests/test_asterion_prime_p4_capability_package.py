"""Tests for the P4 capability-package JSON contracts (Phase 6, Tasks 2+3)."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestPrimeP4CapabilityPackage(unittest.TestCase):
    def test_package_loads_and_lists_required_services(self) -> None:
        path = (
            REPO_ROOT
            / "src/asterion/capabilities/prime_long_session_continuity_native"
            / "payload/capability-package.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["protocol"], "asterion.capability-package/v1")
        self.assertEqual(data["package_id"], "prime-long-session-continuity-native")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(len(data["capabilities"]), 2)
        self.assertEqual(data["capabilities"][0]["capability_id"], "policy.long-session-loop")
        self.assertEqual(data["capabilities"][0]["version"], "1.0.0")
        self.assertEqual(data["benchmark_suites"], [])
        self.assertEqual(data["resources"], [])
        self.assertEqual(data["conformance"], [])

    def test_capability_id_matches_application_id(self) -> None:
        path = (
            REPO_ROOT
            / "src/asterion/capabilities/prime_long_session_continuity_native"
            / "payload/capabilities/prime-long-session-continuity.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["protocol"], "asterion.capability/v1")
        self.assertEqual(data["capability_id"], "prime.long-session-continuity")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["kind"], "capability")
        self.assertEqual(data["provides_capabilities"], ["prime.long-session-continuity"])
        self.assertEqual(data["requires_capabilities"], ["prime.tool.ipython"])
        self.assertEqual(
            data["produces_artifacts"],
            ["application/vnd.asterion.prime.p4-native-receipt+json"],
        )

    def test_assembly_references_capability_package_and_services(self) -> None:
        path = (
            REPO_ROOT
            / "src/asterion/applications/prime/assemblies/prime-long-session-continuity.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["protocol"], "asterion.application-assembly/v1")
        self.assertEqual(data["application_id"], "prime.long-session-continuity")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["runtime_id"], "asterion.prime")
        self.assertEqual(
            data["host_capabilities"],
            [
                "prime.continuity-store",
                "prime.p4-oracle",
                "prime.pi-extension",
                "prime.private-trace",
                "prime.session-backend",
            ],
        )
        self.assertEqual(data["host_policies"], [])
        self.assertEqual(data["host_events"], [])
        self.assertEqual(data["host_artifacts"], [])
        self.assertEqual(len(data["capability_packages"]), 1)
        self.assertEqual(
            data["capability_packages"][0]["package_id"],
            "prime-long-session-continuity-native",
        )
        self.assertEqual(
            data["capability_packages"][0]["version"], "1.0.0"
        )
        self.assertEqual(len(data["capabilities"]), 1)
        self.assertEqual(
            data["capabilities"][0]["capability_id"],
            "policy.long-session-loop",
        )
        self.assertEqual(data["capabilities"][0]["version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()