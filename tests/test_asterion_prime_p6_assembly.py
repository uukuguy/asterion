"""Tests for the P6 application assembly JSON (Phase 9, Task 2)."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestPrimeP6Assembly(unittest.TestCase):
    def test_assembly_references_capability_package_and_services(self) -> None:
        path = (
            REPO_ROOT
            / "src/asterion/applications/prime/assemblies/prime-continual-improvement.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["protocol"], "asterion.application-assembly/v1")
        self.assertEqual(data["application_id"], "prime.continual-improvement")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["runtime_id"], "asterion.prime")
        self.assertEqual(
            set(data["host_capabilities"]),
            {
                "prime.candidate-store",
                "prime.ipython",
                "prime.p6-oracle",
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
            "prime-continual-improvement-native",
        )
        self.assertEqual(
            data["capability_packages"][0]["version"], "1.0.0"
        )
        self.assertEqual(len(data["capabilities"]), 1)
        self.assertEqual(
            data["capabilities"][0]["capability_id"],
            "policy.continual-loop",
        )
        self.assertEqual(data["capabilities"][0]["version"], "1.0.0")

    def test_assembly_runtime_id_is_asterion_prime(self) -> None:
        path = (
            REPO_ROOT
            / "src/asterion/applications/prime/assemblies/prime-continual-improvement.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["runtime_id"], "asterion.prime")

    def test_assembly_file_ends_with_trailing_newline(self) -> None:
        path = (
            REPO_ROOT
            / "src/asterion/applications/prime/assemblies/prime-continual-improvement.json"
        )
        raw = path.read_bytes()
        self.assertTrue(raw.endswith(b"\n"))


if __name__ == "__main__":
    unittest.main()
