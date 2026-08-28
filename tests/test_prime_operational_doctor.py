from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.test_operation_doctor import _doctor_request, _doctor_service, _doctor_transaction
from tests.test_prime_operational_auth import (
    _LEDGER_ASSERTIONS,
    _base_scenario_counts,
    _real_prime_receipt,
    _zero_effect_counts,
)
from tests.test_prime_operational_harness import (
    PINNED_ROOT,
    RESOURCE_ROOT,
    _external_pinned_root,
    _rebuild_locked_workspaces,
    _run_fixture,
)
from tests.test_prime_operational_telemetry import _tampered_resource


class TestPrimeOperationalDoctor(unittest.IsolatedAsyncioTestCase):
    async def test_doctor_is_read_only_and_never_claims_repair(self) -> None:
        service, probes = _doctor_service()

        receipt = await service.execute(_doctor_transaction("doctor-prime-1"), _doctor_request())

        self.assertEqual((receipt.status, receipt.reason_code), ("succeeded", "doctor-report-ready"))
        self.assertEqual(len(service.reports), 1)
        self.assertEqual([probe.calls for probe in probes], [1, 1])  # type: ignore[attr-defined]
        for counter, count in receipt.effect_counts.items():
            with self.subTest(counter=counter):
                self.assertEqual(count, 0)

    async def test_real_prime_doctor_receipt_reports_read_only_inspection_failure(self) -> None:
        receipt = _real_prime_receipt("doctor")

        self.assertEqual(receipt["scenario_counts"], _base_scenario_counts())
        self.assertEqual(receipt["effect_counts"], _zero_effect_counts())
        self.assertEqual(receipt["feature_ids"], ["operation.doctor"])
        self.assertEqual(receipt["assertion_ids"], _LEDGER_ASSERTIONS)
        self.assertEqual(receipt["fault_ids"], ["restart-after-admission"])
        self.assertEqual(receipt["redaction_status"], "pass")
        self.assertEqual(
            receipt["failure_matrix"],
            [
                {"case_id": "diagnostic-inspection-failure", "status": "rejected"},
                {"case_id": "restart-after-admission", "status": "rejected"},
            ],
        )
        diagnostic = receipt["diagnostic"]
        if not isinstance(diagnostic, list):
            self.fail("diagnostic is not a public list")
        self.assertEqual(
            diagnostic[:3],
            ["resource-loader.theme", "warning", "theme-path-missing"],
        )
        self.assertRegex(diagnostic[3], r"^[0-9a-f]{64}$")
        self.assertNotIn("SENTINEL_RESOURCE_LOADER_PATH", repr(receipt))
        self.assertNotIn("Theme path does not exist", repr(receipt))

    def test_operational_lock_keeps_resource_loader_runtime_anchors_sorted(self) -> None:
        lock = json.loads(
            (RESOURCE_ROOT / "prime-operational-module-lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            tuple(lock["source_anchor_digests"]),
            tuple(sorted(lock["source_anchor_digests"])),
        )
        self.assertEqual(
            tuple(lock["built_anchor_digests"]),
            tuple(sorted(lock["built_anchor_digests"])),
        )
        self.assertIn(
            "packages/coding-agent/src/core/resource-loader.ts",
            lock["source_anchor_digests"],
        )
        self.assertIn(
            "packages/coding-agent/dist/core/resource-loader.js",
            lock["built_anchor_digests"],
        )

    def test_real_prime_doctor_rejects_absent_mutated_or_local_fake_diagnostic(self) -> None:
        cases = (
            ("absent", "const observed = loader.getThemes();", "const observed = { diagnostics: [], themes: [] };"),
            ("mutated", "const result = observed.diagnostics[0];", 'const result = Object.freeze({ ...observed.diagnostics[0], message: "SENTINEL_MUTATED_DIAGNOSTIC" });'),
            ("local-fake", "const loader = new DefaultResourceLoader({", "const loader = new (class LocalFakeResourceLoader { getThemes() { return { diagnostics: [], themes: [] }; } async reload() {} })({"),
        )
        with tempfile.TemporaryDirectory(prefix="asterion-prime-operational-doctor-tamper-") as temporary:
            parent = Path(temporary)
            source = _external_pinned_root(parent)
            try:
                _rebuild_locked_workspaces(source)
                for name, needle, replacement in cases:
                    with self.subTest(name=name):
                        completed = _run_fixture(
                            _tampered_resource(parent, name, needle, replacement),
                            source,
                            "doctor",
                        )
                        self.assertNotEqual(completed.returncode, 0)
                        self.assertNotIn("SENTINEL_MUTATED_DIAGNOSTIC", completed.stdout + completed.stderr)
                        self.assertNotIn(str(source), completed.stdout + completed.stderr)
            finally:
                subprocess.run(
                    ("git", "-C", str(PINNED_ROOT), "worktree", "remove", "--force", str(source)),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
