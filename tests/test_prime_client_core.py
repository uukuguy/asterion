from __future__ import annotations

import hashlib
import json
import unittest
from typing import TypedDict


_COMMAND = "make test.prime-client-core.provider-free"
_FEATURE_IDS = ("interface.json-stream", "interface.sdk")
_SCENARIO_IDS = ("prime-client-core.jsonl", "prime-client-core.sdk")


class _CoreReceipt(TypedDict):
    command_id: str
    credential_reads: int
    feature_ids: list[str]
    private_service_contract_digest: str
    provider_operations: int
    retained_processes: int
    scenario_ids: list[str]
    stream_contract_digest: str


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _provider_free_receipt() -> _CoreReceipt:
    return {
        "command_id": _COMMAND,
        "credential_reads": 0,
        "feature_ids": list(_FEATURE_IDS),
        "private_service_contract_digest": _digest(
            {
                "purposes": [
                    "extension-ui-response",
                    "headless-final",
                    "interactive-render",
                    "private-export",
                ],
                "resolves": "injected-only",
            }
        ),
        "provider_operations": 0,
        "retained_processes": 0,
        "scenario_ids": list(_SCENARIO_IDS),
        "stream_contract_digest": _digest(
            {
                "framing": "jsonl-lf-only",
                "max_safe_integer": 9_007_199_254_740_991,
                "protocol": "asterion.agent-client/v1",
            }
        ),
    }


class TestPrimeClientCoreReceipt(unittest.TestCase):
    def test_provider_free_receipt_binds_the_exact_core_boundary(self) -> None:
        receipt = _provider_free_receipt()

        self.assertEqual(receipt["command_id"], _COMMAND)
        self.assertEqual(tuple(receipt["feature_ids"]), _FEATURE_IDS)
        self.assertEqual(tuple(receipt["scenario_ids"]), _SCENARIO_IDS)
        self.assertRegex(str(receipt["stream_contract_digest"]), r"^[0-9a-f]{64}$")
        self.assertRegex(str(receipt["private_service_contract_digest"]), r"^[0-9a-f]{64}$")
        self.assertEqual(receipt["provider_operations"], 0)
        self.assertEqual(receipt["credential_reads"], 0)
        self.assertEqual(receipt["retained_processes"], 0)
        self.assertNotIn("SENTINEL_PRIVATE_VALUE", json.dumps(receipt, sort_keys=True))
