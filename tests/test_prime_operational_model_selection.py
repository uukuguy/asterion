from __future__ import annotations

import unittest

from tests.test_operation_model_selection import _model_selection_request, _model_service, _model_transaction


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
