from __future__ import annotations

import unittest

from tests.test_operation_model_selection import _model_selection_request, _model_service, _model_transaction
from tests.test_prime_operational_auth import (
    _FAILURE_MATRICES,
    _base_scenario_counts,
    _real_prime_receipt,
    _zero_effect_counts,
)


class TestPrimeOperationalModelSelection(unittest.IsolatedAsyncioTestCase):
    async def test_fixture_catalog_selection_is_provider_free_and_does_not_mutate_runtime(self) -> None:
        service, catalog, store = _model_service()

        receipt = await service.execute(
            _model_transaction("model-prime-1"), _model_selection_request()
        )

        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(catalog.network_operations, 0)
        self.assertEqual(receipt.effect_counts["provider_model_requests"], 0)
        self.assertEqual(receipt.effect_counts["network_operations"], 0)
        self.assertEqual(len(store.writes), 1)

    async def test_real_prime_model_receipt_is_fixture_only_and_failure_closed(self) -> None:
        receipt = _real_prime_receipt("model-selection")

        self.assertEqual(receipt["scenario_counts"], _base_scenario_counts())
        self.assertEqual(receipt["effect_counts"], _zero_effect_counts())
        self.assertEqual(receipt["status"], "pass")
        self.assertEqual(
            receipt["model_transition"],
            ["fixture-catalog-1", "1", "fixture.model.small", "low", "standard", "fixture.transport-1"],
        )
        self.assertEqual(receipt["failure_matrix"], _FAILURE_MATRICES["model-selection"])
