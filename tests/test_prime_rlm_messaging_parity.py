from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
from pathlib import Path

from asterion.control.parity import validate_parity_ledger
from asterion.control.providers.prime.parity_testing import (
    PRIME_RLM_BOUNDED_SCENARIO_IDS,
    PRIME_RLM_PROVIDER_FREE_SCENARIO_IDS,
    PRIME_RLM_SCENARIO_IDS,
    PRIME_RLM_SCENARIO_MATRIX,
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
