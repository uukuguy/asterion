from __future__ import annotations

import copy
import asyncio
import hashlib
import json
import unittest
from pathlib import Path

from asterion.control.parity_testing import ParityScenarioRegistry
from asterion.control.providers.prime.client_parity_testing import (
    PRIME_CLIENT_SCENARIO_IDS,
    PrimeClientParityError,
    build_prime_client_observations,
    register_prime_client_scenarios,
)


_ARTIFACT_LOCK = "c64aecdec9ddff21fb7ed493cc1837eb68bf428fc94803a65e6c185aca0fbba3"
_MODULE_LOCK = "7d63efa7f1588ecb652b316dc3959c9c8565d9f039aeac5eb3dce0264a790bcb"
_MODULE = "266698144670d880438696592fb67f5fb669c7cea7868f93d1c27cd7ff2b6a7f"
_SOURCE = "a18809e00ea30638584d87b3afea7285a9d7296c"
_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json"
)
_EVIDENCE = (
    ("identity.source-module-artifact", "rejected", "identity_mismatch"),
    ("stream.cursor-gap", "rejected", "cursor_gap"),
    ("stream.partial-oversized", "rejected", "jsonl_frame_rejected"),
    ("redaction.body-credential", "rejected", "private_value_rejected"),
    ("lifecycle.disconnect-cancel", "cancelled", "disconnect_cancelled"),
    ("lifecycle.retained-process", "cleaned", "no_retained_process"),
    ("stdout.protocol-purity", "clean", "stdout_protocol_pure"),
    ("interactive.command-rollback", "rejected", "command_revision_rollback"),
    ("interactive.ui-timeout", "cancelled", "ui_timeout"),
    ("export.public-private-read", "succeeded", "public_export_no_private_read"),
    ("share.unauthorized-upload", "rejected", "upload_unauthorized"),
)


def _scenario_evidence() -> list[dict[str, object]]:
    evidence = []
    for scenario_id, outcome, error_code in _EVIDENCE:
        counters = {
                "credential_reads": 0,
                "network_requests": 0,
                "private_reads": 0,
                "provider_operations": 0,
                "retained_processes": 0,
                "scenario_calls": 1,
                "stdout_writes": 0,
                "unauthorized_uploads": 0,
            **(
                {
                    "ui_cancellations": 1,
                    "ui_renders": 1,
                    "ui_submits": 0,
                }
                if scenario_id == "interactive.ui-timeout"
                else {}
            ),
        }
        body = {
            "counters": counters,
            "error_code": error_code,
            "id": scenario_id,
            "outcome": outcome,
        }
        evidence.append(
            {
                **body,
                "digest": hashlib.sha256(
                    json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            }
        )
    return evidence


def _receipt(
    package: str,
    feature_ids: list[str],
    scenario_ids: list[str],
    *,
    gate_id: str,
    module_ids: list[str],
    details: dict[str, object],
) -> dict[str, object]:
    return {
        "artifact_lock_digest": _ARTIFACT_LOCK,
        "credential_reads": 0,
        "feature_count": len(feature_ids),
        "feature_ids": feature_ids,
        "gate_id": gate_id,
        "module_digest": _MODULE,
        "module_ids": module_ids,
        "module_lock_digest": _MODULE_LOCK,
        "package": package,
        "private_reads": 0,
        "provider_operations": 0,
        "retained_processes": 0,
        "scenario_count": len(scenario_ids),
        "scenario_evidence": _scenario_evidence(),
        "scenario_ids": scenario_ids,
        "source_commit": _SOURCE,
        "stdout_writes": 0,
        "unauthorized_uploads": 0,
        **details,
    }


def _four_receipts() -> list[dict[str, object]]:
    return [
        _receipt(
            "core",
            ["interface.json-stream", "interface.sdk"],
            ["prime-client-core.jsonl", "prime-client-core.sdk"],
            gate_id="test.prime-client-core.provider-free",
            module_ids=["tests.test_client_sdk_jsonl", "tests.test_prime_client_core"],
            details={
                "private_service_contract_digest": "253fd97dfe3a84ec859474538bc0998afa8182ae420d5bc5b1e46460a91ea85b",
                "stream_contract_digest": "7859db9960e895e4ffd60d90c06f54471897409c753ee7dbb7eed23a1369a1f4",
            },
        ),
        _receipt(
            "protocols",
            ["interface.acp", "interface.rpc"],
            ["prime-parity.interface.acp", "prime-parity.interface.rpc"],
            gate_id="test.prime-client-protocols.provider-free",
            module_ids=["tests.test_client_rpc_acp", "tests.test_prime_client_protocols"],
            details={
                "acp_event_methods": {
                    "artifact.available": "artifact_update",
                    "fault.raised": "session_error",
                    "message.available": "agent_message_chunk",
                    "session.state": "session_update",
                    "session.terminal": "session_end",
                    "tool.completed": "tool_call_update",
                    "tool.started": "tool_call",
                    "usage.reported": "usage_update",
                },
                "protocol_digest": "2c1f61b6920342893dc9aeef10e232e87251db50c7fbcceb187c78e1826c35ab",
                "redaction_status": "pass",
                "rpc_methods": [
                    "command.invoke",
                    "export.request",
                    "extension-ui.respond",
                    "input.submit",
                    "session.attach",
                    "session.cancel",
                    "session.create",
                    "session.detach",
                    "session.pause",
                    "session.resume",
                    "share.request",
                ],
            },
        ),
        _receipt(
            "interactive",
            [
                "interface.cli-interactive",
                "interface.headless-print",
                "interface.tui-commands",
                "interface.tui-extension-ui",
            ],
            [
                "prime-client-interactive.cli",
                "prime-client-interactive.headless",
                "prime-client-interactive.commands",
                "prime-client-interactive.extension-ui",
            ],
            gate_id="test.prime-client-interactive.provider-free",
            module_ids=[
                "tests.test_client_interactive",
                "tests.test_asterion_cli",
                "tests.test_prime_client_interactive",
            ],
            details={
                "private_service_contract_digest": "2698bba4cdb115363cc5cb0af1b45b52f4e17a20f890a9afec7478270913b403",
                "redaction_status": "pass",
                "stream_contract_digest": "b4727b9bbedfa05b9bba658462562f6c5e61bde8a8608d7b2277620c6d134c72",
            },
        ),
        _receipt(
            "export-share",
            ["interface.export-share"],
            ["prime-client-export-share.public"],
            gate_id="test.prime-client-export-share.provider-free",
            module_ids=["tests.test_client_export_share", "tests.test_prime_client_export_share"],
            details={
                "redaction_status": "pass",
                "stream_digest": "5cb4d5887deb470266ba91a0d41ad3871753c8b2fd365edb27351c0d73151e7d",
            },
        ),
    ]


class TestPrimeClientParity(unittest.TestCase):
    def test_four_receipts_cover_exact_nine_without_provider_work(self) -> None:
        observations = build_prime_client_observations(_four_receipts())

        self.assertEqual(
            tuple(item.scenario_id for item in observations),
            PRIME_CLIENT_SCENARIO_IDS,
        )
        self.assertEqual(len(observations), 9)
        self.assertTrue(all(item.provider_operations == 0 for item in observations))

    def test_wrong_identity_count_or_extra_key_rejects_atomically(self) -> None:
        cases: list[list[dict[str, object]]] = []
        for index, key, value in (
            (0, "source_commit", "b" * 40),
            (1, "feature_count", 3),
            (2, "provider_operations", True),
            (3, "unauthorized_uploads", 1),
            (0, "extra", "value"),
            (1, "feature_ids", ["interface.rpc", "interface.acp"]),
            (2, "scenario_evidence", []),
            (3, "stream_digest", "SENTINEL_PRIVATE_VALUE"),
        ):
            receipts = copy.deepcopy(_four_receipts())
            receipts[index][key] = value
            cases.append(receipts)

        for receipts in cases:
            with self.subTest(receipts=receipts), self.assertRaises(
                PrimeClientParityError
            ):
                build_prime_client_observations(receipts)

    def test_registers_exact_provider_free_runners(self) -> None:
        registry = ParityScenarioRegistry(
            json.loads(_FIXTURE.read_text(encoding="utf-8")),
            provider_id="asterion.prime-gateway",
        )
        register_prime_client_scenarios(
            registry,
            build_prime_client_observations(_four_receipts()),
            provider_factory=lambda: object(),
        )

        report = asyncio.run(registry.run(PRIME_CLIENT_SCENARIO_IDS))

        self.assertEqual(report.blocking_scenario_ids, ())
        self.assertEqual(report.passed_scenario_ids, PRIME_CLIENT_SCENARIO_IDS)
