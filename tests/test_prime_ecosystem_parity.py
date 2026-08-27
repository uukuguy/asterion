from __future__ import annotations

import asyncio
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import tools.check_prime_parity as parity_checker
from asterion.control.parity_testing import (
    ParityScenarioRegistry,
    ParityScenarioRegistryError,
)
from asterion.control.providers.prime.ecosystem_parity_testing import (
    PRIME_ECOSYSTEM_ARTIFACT_LOCK_SHA256,
    PRIME_ECOSYSTEM_MODULE_LOCK_SHA256,
    PRIME_ECOSYSTEM_SCENARIO_IDS,
    PRIME_ECOSYSTEM_SOURCE_COMMIT,
    build_prime_ecosystem_observations,
    register_prime_ecosystem_scenarios,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json"
HEX_A = "a" * 64
HEX_B = "b" * 64


def _base_metadata(command_id: str) -> dict[str, object]:
    return {
        "artifact_lock_sha256": PRIME_ECOSYSTEM_ARTIFACT_LOCK_SHA256,
        "command_id": command_id,
        "module_lock_sha256": PRIME_ECOSYSTEM_MODULE_LOCK_SHA256,
        "portfolio_digest": HEX_A,
        "source_commit": PRIME_ECOSYSTEM_SOURCE_COMMIT,
    }


def _four_receipts() -> list[dict[str, object]]:
    return [
        {
            **_base_metadata("test.prime-ecosystem-resources.provider-free"),
            "assertion_ids": [
                "resources.collision-digest",
                "resources.context-order",
                "resources.no-python-import",
                "resources.prompt-expansion",
                "resources.redacted-receipt",
                "resources.skill-identities",
            ],
            "collision_count": 1,
            "collision_digest": HEX_B,
            "context_count": 2,
            "feature_ids": [
                "ecosystem.collision-diagnostics",
                "ecosystem.context-files",
                "ecosystem.prompt-templates",
                "ecosystem.skills",
            ],
            "format": "asterion.prime-ecosystem-observation/v1",
            "model_credential_reads": 0,
            "observation_digest": HEX_B,
            "owned_process_count_after_close": 0,
            "prompt_count": 3,
            "provider_operations": 0,
            "resource_count": 7,
            "scenario_package": "resources",
            "skill_count": 2,
            "status": "PASS",
        },
        {
            **_base_metadata("test.prime-ecosystem-extensions.provider-free"),
            "assertion_ids": [
                "extensions.command-state-digest",
                "extensions.lifecycle-order",
                "extensions.no-provider-invocation",
                "extensions.provider-model-lookup",
                "extensions.tool-output-digest",
            ],
            "command_count": 1,
            "command_state_digest": HEX_B,
            "failure_matrix_count": 4,
            "failure_matrix_digest": HEX_B,
            "feature_ids": [
                "ecosystem.custom-providers-models",
                "ecosystem.extension-state-commands",
                "ecosystem.extensions-lifecycle",
                "ecosystem.tools",
            ],
            "format": "asterion.prime-ecosystem-observation/v1",
            "lifecycle_count": 1,
            "model_credential_reads": 0,
            "observation_digest": HEX_B,
            "owned_process_count_after_close": 0,
            "provider_model_count": 1,
            "provider_operations": 0,
            "reopened_command_state_digest": HEX_B,
            "reopened_nonterminal_status": "uncertain",
            "registration_count": 3,
            "resource_count": 1,
            "scenario_package": "extensions",
            "status": "PASS",
            "tool_count": 1,
        },
        {
            **_base_metadata("test.prime-ecosystem-packages.provider-free"),
            "assertion_ids": [
                "packages.no-install",
                "packages.no-source-fallback",
                "packages.prime-package-manager",
                "packages.selected-source-digest",
            ],
            "fallback_attempt_count": 0,
            "feature_ids": ["ecosystem.packages"],
            "format": "asterion.prime-ecosystem-observation/v1",
            "install_attempt_count": 0,
            "model_credential_reads": 0,
            "network_attempt_count": 0,
            "observation_digest": HEX_B,
            "owned_process_count_after_close": 0,
            "package_count": 1,
            "prime_payload_digest": HEX_B,
            "prime_resource_digest": HEX_B,
            "prime_selected_identity_digest": HEX_B,
            "provider_operations": 0,
            "resource_count": 1,
            "scenario_package": "packages",
            "selected_payload_digest": HEX_B,
            "selected_resource_digest": HEX_B,
            "selected_source_digest": HEX_B,
            "status": "PASS",
        },
        {
            **_base_metadata("test.prime-ecosystem-mcp.provider-free"),
            "assertion_ids": [
                "mcp.exact-local-server",
                "mcp.manager-and-oauth-surface",
                "mcp.no-provider-invocation",
                "mcp.redacted-receipt",
            ],
            "feature_ids": ["ecosystem.mcp"],
            "format": "asterion.prime-ecosystem-observation/v1",
            "mcp_count": 1,
            "mcp_surface_digest": HEX_B,
            "model_credential_reads": 0,
            "observation_digest": HEX_B,
            "owned_process_count_after_close": 0,
            "provider_operations": 0,
            "resource_count": 1,
            "scenario_package": "mcp",
            "status": "PASS",
        },
    ]


class TestPrimeEcosystemParity(unittest.TestCase):
    def test_observations_cover_exact_ten_without_provider_work(self) -> None:
        observations = build_prime_ecosystem_observations(_four_receipts())

        self.assertEqual(
            tuple(item.scenario_id for item in observations),
            PRIME_ECOSYSTEM_SCENARIO_IDS,
        )
        self.assertEqual(len({item.evidence_id for item in observations}), 10)
        self.assertTrue(all(item.provider_operations == 0 for item in observations))
        self.assertTrue(all(item.model_credential_reads == 0 for item in observations))
        self.assertTrue(
            all(item.owned_process_count_after_close == 0 for item in observations)
        )
        self.assertNotIn("opaque-mcp-refresh-token", repr(observations[0]))

    def test_ecosystem_domain_closes_only_with_all_ten(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = parity_checker.main(
                [
                    "--domain",
                    "ecosystem.capabilities",
                    "--provider",
                    "asterion.prime-gateway",
                ]
            )

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["selected_feature_count"], 10)
        self.assertEqual(report["passed_feature_count"], 10)
        self.assertEqual(report["blocking_feature_count"], 0)
        self.assertEqual(report["status"], "PASS")

    def test_wrong_identity_or_nonzero_counts_reject_atomically(self) -> None:
        mutations = (
            (0, "command_id", "test.other"),
            (0, "source_commit", "b" * 40),
            (1, "module_lock_sha256", "c" * 64),
            (1, "portfolio_digest", "not-a-digest"),
            (2, "provider_operations", 1),
            (3, "model_credential_reads", 1),
            (3, "feature_ids", ["ecosystem.other"]),
        )
        for index, key, value in mutations:
            receipts = copy.deepcopy(_four_receipts())
            receipts[index][key] = value
            with self.subTest(key=key), self.assertRaises(ParityScenarioRegistryError):
                build_prime_ecosystem_observations(receipts)

    def test_registers_exact_provider_free_runners(self) -> None:
        ledger = json.loads(FIXTURE.read_text(encoding="utf-8"))
        registry = ParityScenarioRegistry(
            ledger,
            provider_id="asterion.prime-gateway",
        )
        observations = build_prime_ecosystem_observations(_four_receipts())

        register_prime_ecosystem_scenarios(
            registry,
            observations,
            provider_factory=lambda: object(),
        )
        report = asyncio.run(registry.run(PRIME_ECOSYSTEM_SCENARIO_IDS))

        self.assertEqual(report.blocking_scenario_ids, ())
        self.assertEqual(report.passed_scenario_ids, PRIME_ECOSYSTEM_SCENARIO_IDS)
        self.assertTrue(all(item.evidence_id is not None for item in report.results))


if __name__ == "__main__":
    unittest.main()
