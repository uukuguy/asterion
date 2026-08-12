from __future__ import annotations

import asyncio
import json
import unittest
from collections.abc import Mapping
from pathlib import Path

from asterion.control.parity import validate_parity_ledger
from asterion.control.parity_testing import ParityScenarioRegistry
from asterion.control.providers.prime.parity_testing import (
    PRIME_RLM_BOUNDED_SCENARIO_IDS,
    PRIME_RLM_PROVIDER_FREE_SCENARIO_IDS,
    PRIME_RLM_REQUIRED_CHECK_IDS,
    PRIME_RLM_SCENARIO_IDS,
    PRIME_RLM_SCENARIO_MATRIX,
    PRIME_RLM_VERIFICATION_COMMAND_ID,
    build_prime_rlm_observation,
    register_prime_rlm_scenarios,
)


ROOT = Path(__file__).resolve().parents[1]
LEDGER = (
    ROOT
    / "tests"
    / "fixtures"
    / "prime-parity"
    / "v1"
    / "prime-agent-0.7.1.json"
)


class TestPrimeRlmMessagingParity(unittest.TestCase):
    def test_rlm_adapter_registers_only_provider_free_evidence_as_pass(self) -> None:
        observations = tuple(
            build_prime_rlm_observation(
                scenario_id=scenario_id,
                status=(
                    "EXTERNAL-LIMITED"
                    if scenario_id in PRIME_RLM_BOUNDED_SCENARIO_IDS
                    else "PASS"
                ),
                checks=PRIME_RLM_REQUIRED_CHECK_IDS.get(scenario_id, ()),
                real_prime_runtime=True,
                fake_daemon=False,
                provider_operations=0,
                model_credential_reads=0,
            )
            for scenario_id in PRIME_RLM_SCENARIO_IDS
        )
        registry = ParityScenarioRegistry(
            validate_parity_ledger(json.loads(LEDGER.read_text(encoding="utf-8"))),
            provider_id="asterion.prime-gateway",
        )

        register_prime_rlm_scenarios(
            registry,
            observations,
            provider_factory=lambda: object(),
        )
        report = asyncio.run(registry.run(PRIME_RLM_SCENARIO_IDS))

        self.assertEqual(registry.registered_scenario_ids, PRIME_RLM_SCENARIO_IDS)
        self.assertEqual(report.passed_scenario_ids, PRIME_RLM_PROVIDER_FREE_SCENARIO_IDS)
        self.assertEqual(report.blocking_scenario_ids, PRIME_RLM_BOUNDED_SCENARIO_IDS)

    def test_rlm_observation_only_issues_evidence_for_real_provider_free_runs(self) -> None:
        provider_free = build_prime_rlm_observation(
            scenario_id="prime-parity.rlm.messaging",
            status="PASS",
            checks=PRIME_RLM_REQUIRED_CHECK_IDS["prime-parity.rlm.messaging"],
            real_prime_runtime=True,
            fake_daemon=False,
            provider_operations=0,
            model_credential_reads=0,
        )
        bounded = build_prime_rlm_observation(
            scenario_id="prime-parity.rlm.child-model",
            status="EXTERNAL-LIMITED",
            checks=(),
            real_prime_runtime=True,
            fake_daemon=False,
            provider_operations=0,
            model_credential_reads=0,
        )

        self.assertIsNotNone(provider_free.evidence_id)
        self.assertIsNone(bounded.evidence_id)
        self.assertNotIn("PRIVATE", provider_free.serialized_observations)
        with self.assertRaisesRegex(Exception, "Prime RLM observation is invalid"):
            build_prime_rlm_observation(
                scenario_id="prime-parity.rlm.messaging",
                status="PASS",
                checks=("forged-check",),
                real_prime_runtime=True,
                fake_daemon=False,
                provider_operations=0,
                model_credential_reads=0,
            )

    def test_provider_free_rlm_evidence_contract_distinguishes_native_paths(self) -> None:
        self.assertEqual(
            PRIME_RLM_VERIFICATION_COMMAND_ID,
            "test.prime-rlm-messaging-parity.provider-free",
        )
        self.assertEqual(
            {
                scenario_id: PRIME_RLM_REQUIRED_CHECK_IDS[scenario_id]
                for scenario_id in PRIME_RLM_PROVIDER_FREE_SCENARIO_IDS
            },
            {
                "prime-parity.rlm.cancellation-teardown": (
                    "native-child-teardown-passed",
                    "pinned-prime-rlm-daemon-passed",
                ),
                "prime-parity.rlm.environment": (
                    "closed-home-no-credentials-passed",
                    "pinned-prime-rlm-daemon-passed",
                ),
                "prime-parity.rlm.messaging": (
                    "native-family-message-admitted-passed",
                    "native-message-delivery-recorded-passed",
                ),
                "prime-parity.rlm.recovery": (
                    "native-message-recovery-fenced-passed",
                    "pinned-prime-rlm-daemon-passed",
                ),
                "prime-parity.rlm.registry-lifecycle": (
                    "native-child-registry-delete-passed",
                    "pinned-prime-rlm-daemon-passed",
                ),
                "prime-parity.rlm.usage-cost": (
                    "zero-provider-usage-monotonic-passed",
                    "pinned-prime-rlm-daemon-passed",
                ),
            },
        )

    def test_real_rlm_harness_contract_is_exactly_the_approved_matrix(self) -> None:
        ledger = validate_parity_ledger(json.loads(LEDGER.read_text(encoding="utf-8")))
        scenario_rows = ledger["scenarios"]
        self.assertIsInstance(scenario_rows, tuple)
        assert isinstance(scenario_rows, tuple)
        rows = {
            str(item["scenario_id"]): item
            for item in scenario_rows
            if isinstance(item, Mapping)
            and str(item["scenario_id"]).startswith("prime-parity.rlm.")
        }

        self.assertEqual(tuple(rows), PRIME_RLM_SCENARIO_IDS)
        self.assertEqual(
            PRIME_RLM_PROVIDER_FREE_SCENARIO_IDS,
            (
                "prime-parity.rlm.cancellation-teardown",
                "prime-parity.rlm.environment",
                "prime-parity.rlm.messaging",
                "prime-parity.rlm.recovery",
                "prime-parity.rlm.registry-lifecycle",
                "prime-parity.rlm.usage-cost",
            ),
        )
        self.assertEqual(
            PRIME_RLM_BOUNDED_SCENARIO_IDS,
            (
                "prime-parity.rlm.child-model",
                "prime-parity.rlm.generated-program",
                "prime-parity.rlm.recursion-depth",
            ),
        )
        self.assertEqual(set(PRIME_RLM_SCENARIO_MATRIX), set(rows))
        for scenario_id, contract in PRIME_RLM_SCENARIO_MATRIX.items():
            with self.subTest(scenario_id=scenario_id):
                self.assertEqual(contract["boundary"], rows[scenario_id]["boundary"])
                self.assertEqual(contract["feature_ids"], rows[scenario_id]["feature_ids"])
                self.assertEqual(contract["assertion_ids"], rows[scenario_id]["assertion_ids"])
                self.assertEqual(contract["fault_ids"], rows[scenario_id]["fault_ids"])


if __name__ == "__main__":
    unittest.main()
