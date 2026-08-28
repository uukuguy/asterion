from __future__ import annotations

import unittest

from asterion.operation.protocol import EFFECT_COUNTERS
from tests.test_operation_update_restart import _request, _service, _transaction


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
