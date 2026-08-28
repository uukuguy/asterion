from __future__ import annotations

from functools import cache
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from asterion.operation.auth import AuthOperationService

from tests.test_operation_auth import _Refresher, _Storage, _request, _transaction
from tests.test_prime_operational_harness import (
    PINNED_ROOT,
    REAL_HARNESS,
    RESOURCE_ROOT,
    _external_pinned_root,
    _rebuild_locked_workspaces,
)
from tools.setup_prime_agent import _resolve_operational_node


ROOT = Path(__file__).resolve().parents[1]
_EFFECT_COUNTS = {
    "credential_reads": 0,
    "network_requests": 0,
    "provider_operations": 0,
    "retained_processes": 0,
    "stdout_writes": 0,
    "unauthorized_uploads": 0,
}
_LEDGER_ASSERTIONS = [
    "authority-preserved",
    "feature-reachable",
    "identity-stable",
    "public-redacted",
]
_FAILURE_MATRICES = {
    "auth": [
        {"case_id": "mock-refresh-failure", "status": "rejected"},
        {"case_id": "restart-after-admission", "status": "rejected"},
    ],
    "model-selection": [
        {"case_id": "fixture-catalog-mismatch", "status": "rejected"},
        {"case_id": "restart-after-admission", "status": "rejected"},
    ],
    "settings-keybindings": [
        {"case_id": "legacy-alias", "status": "rejected"},
        {"case_id": "restart-after-admission", "status": "rejected"},
    ],
}


def _base_scenario_counts() -> dict[str, int]:
    return {
        "fake_coordinator_calls": 0,
        "host_service_calls": 1,
        "injected_sink_calls": 0,
        "mock_refresh_calls": 0,
        "reconcile_calls": 0,
        "scenario_calls": 1,
    }


def _zero_effect_counts() -> dict[str, int]:
    return dict(_EFFECT_COUNTS)


@cache
def _real_prime_receipt(package: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="asterion-prime-operational-receipt-") as temporary:
        parent = Path(temporary)
        source = _external_pinned_root(parent)
        resources = parent / "resources"
        shutil.copytree(RESOURCE_ROOT, resources, symlinks=False)
        try:
            _rebuild_locked_workspaces(source)
            completed = subprocess.run(
                (
                    str(_resolve_operational_node()), str(REAL_HARNESS), "--resource-root", str(resources),
                    "--source-root", str(source), "--package", package,
                ),
                cwd=ROOT, check=False, capture_output=True, text=True, timeout=60,
            )
            if completed.returncode != 0:
                raise AssertionError(completed.stderr)
            return json.loads(completed.stdout)
        finally:
            subprocess.run(
                ("git", "-C", str(PINNED_ROOT), "worktree", "remove", "--force", str(source)),
                check=False, capture_output=True, text=True, timeout=20,
            )


class TestPrimeOperationalAuth(unittest.IsolatedAsyncioTestCase):
    async def test_mock_refresh_is_injected_and_never_authorizes_model_work(self) -> None:
        storage, refresher = _Storage(), _Refresher()
        service = AuthOperationService(storage=storage, refresher=refresher)

        receipt = await service.execute(
            _transaction("auth-refresh-prime-1"),
            _request("auth.refresh", refresh_ref="oauth-ref-1", subject_digest="a" * 64, precedence=4),
        )

        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(len(refresher.calls), 1)
        self.assertEqual(
            (receipt.effect_counts["network_operations"], receipt.effect_counts["provider_model_requests"]),
            (0, 0),
        )

    async def test_auth_model_settings_receipts_have_exact_allowed_scenario_counters(self) -> None:
        auth, model, settings = (
            _real_prime_receipt(name) for name in ("auth", "model-selection", "settings-keybindings")
        )

        self.assertEqual(auth["scenario_counts"], {**_base_scenario_counts(), "mock_refresh_calls": 1})
        self.assertEqual(auth["refresh_outcomes"], ["failure-rejected", "success-redacted"])
        self.assertEqual(model["scenario_counts"], _base_scenario_counts())
        self.assertEqual(settings["scenario_counts"], _base_scenario_counts())
        self.assertEqual(auth["effect_counts"], _zero_effect_counts())
        self.assertEqual(model["effect_counts"], _zero_effect_counts())
        self.assertEqual(settings["effect_counts"], _zero_effect_counts())
        for package, feature in (
            (auth, "operation.auth"),
            (model, "operation.model-selection"),
            (settings, "operation.settings-keybindings"),
        ):
            with self.subTest(feature=feature):
                self.assertEqual(package["feature_ids"], [feature])
                self.assertEqual(package["assertion_ids"], _LEDGER_ASSERTIONS)
                self.assertEqual(package["fault_ids"], ["restart-after-admission"])
                self.assertEqual(package["redaction_status"], "pass")
                dependency_tree_digest = package["dependency_tree_digest"]
                if not isinstance(dependency_tree_digest, str):
                    self.fail("dependency tree digest is not public text")
                self.assertRegex(dependency_tree_digest, r"^[0-9a-f]{64}$")
        self.assertEqual(auth["failure_matrix"], _FAILURE_MATRICES["auth"])
        self.assertEqual(model["failure_matrix"], _FAILURE_MATRICES["model-selection"])
        self.assertEqual(settings["failure_matrix"], _FAILURE_MATRICES["settings-keybindings"])
