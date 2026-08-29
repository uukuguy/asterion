from __future__ import annotations

import unittest

from asterion.operation.protocol import EFFECT_COUNTERS
from tests.test_operation_update_restart import _request, _service, _transaction
from tests.test_prime_operational_auth import (
    _LEDGER_ASSERTIONS,
    _base_scenario_counts,
    _real_prime_receipt,
    _zero_effect_counts,
)


class TestPrimeOperationalUpdateRestart(unittest.IsolatedAsyncioTestCase):
    async def test_controlled_restart_is_fake_coordinator_only_with_no_live_effect_counters(self) -> None:
        service, coordinator = _service()
        receipt = await service.execute(_transaction("restart-prime-1"), _request())
        self.assertEqual(coordinator.calls, ["verify_next", "seal_checkpoint", "handoff"])
        self.assertEqual(receipt.effect_counts, {counter: 0 for counter in EFFECT_COUNTERS})
        self.assertEqual(
            tuple(sorted(receipt.effect_counts)),
            tuple(sorted(EFFECT_COUNTERS)),
        )

    async def test_real_prime_restart_receipt_reconciles_one_uncertain_fake_handoff(self) -> None:
        receipt = _real_prime_receipt("controlled-update-restart")

        self.assertEqual(
            receipt["scenario_counts"],
            {**_base_scenario_counts(), "fake_coordinator_calls": 1, "reconcile_calls": 1},
        )
        self.assertEqual(receipt["effect_counts"], _zero_effect_counts())
        self.assertEqual(receipt["feature_ids"], ["operation.controlled-update-restart"])
        self.assertEqual(receipt["assertion_ids"], _LEDGER_ASSERTIONS)
        self.assertEqual(receipt["fault_ids"], ["restart-after-admission"])
        self.assertEqual(receipt["redaction_status"], "pass")
        self.assertEqual(
            receipt["failure_matrix"],
            [
                {"case_id": "reconcile-identity-mismatch", "status": "rejected"},
                {"case_id": "restart-after-admission", "status": "rejected"},
            ],
        )
        restart = receipt["restart"]
        if not isinstance(restart, list):
            self.fail("restart is not a public list")
        self.assertEqual(restart[:4], ["artifact-prime-1", "prime-daemon-1", "asterion.agent-runtime/v1", "checkpoint-prime-1"])
        self.assertRegex(restart[4], r"^[0-9a-f]{64}$")
        self.assertEqual(restart[5], "uncertain-reconciled")
