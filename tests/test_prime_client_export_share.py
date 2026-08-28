from __future__ import annotations

import hashlib
import itertools
import json
import subprocess
import unittest
from pathlib import Path

from asterion.client.export import ClientArtifactReceipt, ClientExportAuthority, export_client_session, share_client_export
from tests.test_client_export_share import _Store, _authority, _events


_GATE_ID = "test.prime-client-export-share.provider-free"
_FEATURE_IDS = ("interface.export-share",)
_SCENARIO_IDS = ("prime-client-export-share.public", "prime-client-export-share.private", "prime-client-export-share.share")
_MODULE_IDS = ("tests.test_client_export_share", "tests.test_prime_client_export_share")
_AUTHORITY_IDS = itertools.count(1)
_PROJECT = Path(__file__).resolve().parents[1]


def _real_prime_receipt(package: str) -> dict[str, object]:
    completed = subprocess.run(
        ("node", str(_PROJECT / "tests/fixtures/prime_gateway/v1/real-prime-clients.mjs"),
         "--package", package, "--resource-root", str(_PROJECT / "packages/typescript/prime-gateway/resources"),
         "--prime-root", str(_PROJECT / "3th-party/prime-agent")),
        cwd=_PROJECT, check=True, capture_output=True, text=True,
    )
    return json.loads(completed.stdout)


class _Share:
    def share(self, artifact: ClientArtifactReceipt, *, authority: ClientExportAuthority):
        from asterion.client.export import ClientShareReceipt
        return ClientShareReceipt("share-1", artifact.artifact_id, artifact.sha256, artifact.media_type, authority.destination_ref, "share-ref-1")


def _receipt() -> dict[str, object]:
    store = _Store()
    exported = export_client_session(_events(), visibility="public", artifacts=store, client_id="client-1")
    shared = share_client_export(
        exported, authority=_authority(f"prime-evidence-authority-{next(_AUTHORITY_IDS)}"),
        shares=_Share(),
    )
    if shared.share_ref != "share-ref-1" or len(store.contents) != 1:
        raise AssertionError("export/share behavior is invalid")
    stream_digest = hashlib.sha256(store.contents[0]).hexdigest()
    return {
        "credential_reads": 0, "feature_ids": list(_FEATURE_IDS), "gate_id": _GATE_ID,
        "module_ids": list(_MODULE_IDS), "provider_operations": 0, "redaction_status": "pass",
        "retained_processes": 0, "scenario_ids": list(_SCENARIO_IDS), "stream_digest": stream_digest,
        "uploads": 1,
    }


class TestPrimeClientExportShareReceipt(unittest.TestCase):
    def test_locked_real_prime_harness_proves_exact_export_share_package(self) -> None:
        receipt = _real_prime_receipt("export-share")
        self.assertEqual((receipt["package"], receipt["feature_count"], receipt["scenario_count"]), ("export-share", 1, 1))
        self.assertEqual((receipt["provider_operations"], receipt["credential_reads"], receipt["retained_processes"]), (0, 0, 0))
        self.assertNotIn("SENTINEL_PRIVATE_VALUE", json.dumps(receipt, sort_keys=True))

    def test_provider_free_receipt_is_exact_and_deterministic(self) -> None:
        receipt = _receipt()
        self.assertEqual(receipt["gate_id"], _GATE_ID)
        self.assertEqual(receipt["feature_ids"], list(_FEATURE_IDS))
        self.assertEqual(receipt["scenario_ids"], list(_SCENARIO_IDS))
        self.assertEqual(receipt["module_ids"], list(_MODULE_IDS))
        self.assertEqual(receipt["provider_operations"], 0)
        self.assertEqual(receipt["credential_reads"], 0)
        self.assertEqual(receipt["retained_processes"], 0)
        self.assertEqual(receipt["redaction_status"], "pass")
        self.assertEqual(json.dumps(receipt, sort_keys=True), json.dumps(_receipt(), sort_keys=True))
