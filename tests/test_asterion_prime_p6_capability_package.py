"""Tests for the P6 capability-package JSON contracts (Phase 9, Task 1)."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]

PAYLOAD_ROOT = (
    REPO_ROOT
    / "src/asterion/capabilities/prime_continual_improvement_native"
    / "payload"
)
PACKAGE_JSON = PAYLOAD_ROOT / "capability-package.json"
CAPABILITY_JSON = (
    PAYLOAD_ROOT / "capabilities" / "prime-continual-improvement.json"
)

REQUIRED_HOST_SERVICES = {
    "prime.candidate-store",
    "prime.p6-oracle",
    "prime.pi-extension",
    "prime.private-trace",
    "prime.session-backend",
}


class TestPrimeP6CapabilityPackage(unittest.TestCase):
    def test_package_loads_and_lists_required_services(self) -> None:
        data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
        self.assertEqual(data["protocol"], "asterion.capability-package/v1")
        self.assertEqual(data["package_id"], "prime-continual-improvement-native")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(len(data["capabilities"]), 2)
        self.assertEqual(
            data["capabilities"][0]["capability_id"], "policy.continual-loop"
        )
        self.assertEqual(data["capabilities"][0]["version"], "1.0.0")
        self.assertEqual(data["benchmark_suites"], [])
        self.assertEqual(data["resources"], [])
        self.assertEqual(data["conformance"], [])

    def test_capability_id_matches_application_id(self) -> None:
        data = json.loads(CAPABILITY_JSON.read_text(encoding="utf-8"))
        self.assertEqual(data["protocol"], "asterion.capability/v1")
        self.assertEqual(data["capability_id"], "prime.continual-improvement")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["kind"], "capability")
        self.assertEqual(
            data["provides_capabilities"], ["prime.continual-improvement"]
        )
        self.assertEqual(
            set(data["requires_capabilities"]),
            REQUIRED_HOST_SERVICES,
        )
        self.assertEqual(
            data["produces_artifacts"],
            ["application/vnd.asterion.prime.p6-native-receipt+json"],
        )

    def test_package_files_end_with_trailing_newline(self) -> None:
        for path in (PACKAGE_JSON, CAPABILITY_JSON):
            raw = path.read_bytes()
            self.assertTrue(
                raw.endswith(b"\n"),
                msg=f"{path} must end with a trailing newline",
            )


if __name__ == "__main__":
    unittest.main()