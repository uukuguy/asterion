from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_operation_telemetry import _telemetry_request, _telemetry_service, _telemetry_transaction
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


def _tampered_resource(parent: Path, name: str, needle: str, replacement: str) -> Path:
    resource = parent / name
    shutil.copytree(RESOURCE_ROOT, resource, symlinks=False)
    module = resource / "prime-operational-module.mjs"
    body = module.read_text(encoding="utf-8")
    if body.count(needle) != 1:
        raise AssertionError("test tamper anchor is not exact")
    module.write_text(body.replace(needle, replacement), encoding="utf-8")
    lock = resource / "prime-operational-module-lock.json"
    value = json.loads(lock.read_text(encoding="utf-8"))
    value["module_digest"] = hashlib.sha256(module.read_bytes()).hexdigest()
    lock.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return resource


class TestPrimeOperationalTelemetry(unittest.IsolatedAsyncioTestCase):
    async def test_offline_usage_observation_has_no_provider_network_or_delivery_effect(self) -> None:
        service, sink = _telemetry_service()

        receipt = await service.execute(
            _telemetry_transaction("telemetry-prime-1"), _telemetry_request()
        )

        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(service.effects.injected_sink_calls, 1)
        self.assertEqual(len(sink.calls), 1)
        for counter in (
            "provider_model_requests",
            "network_operations",
            "external_telemetry_deliveries",
            "uploads",
        ):
            with self.subTest(counter=counter):
                self.assertEqual(receipt.effect_counts[counter], 0)

    async def test_real_prime_telemetry_receipt_observes_sink_failure_without_rewriting_usage(self) -> None:
        receipt = _real_prime_receipt("telemetry-usage")

        self.assertEqual(
            receipt["scenario_counts"],
            {**_base_scenario_counts(), "injected_sink_calls": 1},
        )
        self.assertEqual(receipt["effect_counts"], _zero_effect_counts())
        self.assertEqual(receipt["feature_ids"], ["operation.telemetry-usage"])
        self.assertEqual(receipt["assertion_ids"], _LEDGER_ASSERTIONS)
        self.assertEqual(receipt["fault_ids"], ["restart-after-admission"])
        self.assertEqual(receipt["redaction_status"], "pass")
        self.assertEqual(
            receipt["failure_matrix"],
            [
                {"case_id": "injected-sink-failure", "status": "rejected"},
                {"case_id": "restart-after-admission", "status": "rejected"},
            ],
        )
        self.assertEqual(
            receipt["usage_observation"],
            ["fixture.source", "agent run completed", 0, 0, "sink-failure-observed"],
        )

    def test_real_prime_fixture_rejects_counter_identity_and_matrix_receipt_tampering(self) -> None:
        cases = (
            (
                "counter",
                'key === "scenario_calls" || key === "host_service_calls" ||',
                '(key === "scenario_calls" && packageId !== "telemetry-usage") || key === "host_service_calls" ||',
            ),
            (
                "identity",
                "source_commit: locks.sourceCommit, status: \"pass\",",
                'source_commit: "0".repeat(40), status: "pass",',
            ),
            (
                "matrix",
                'failureMatrix.push(assertRejected(restartRejected, "restart-after-admission"));',
                'failureMatrix.push(assertRejected(restartRejected, "restart-after-admission-tampered"));',
            ),
        )
        with tempfile.TemporaryDirectory(prefix="asterion-prime-operational-tamper-") as temporary:
            parent = Path(temporary)
            source = _external_pinned_root(parent)
            try:
                _rebuild_locked_workspaces(source)
                for name, needle, replacement in cases:
                    with self.subTest(name=name):
                        completed = _run_fixture(
                            _tampered_resource(parent, name, needle, replacement),
                            source,
                            "telemetry-usage",
                        )
                        self.assertNotEqual(completed.returncode, 0)
                        self.assertNotIn(str(source), completed.stdout + completed.stderr)
            finally:
                subprocess.run(
                    ("git", "-C", str(PINNED_ROOT), "worktree", "remove", "--force", str(source)),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
