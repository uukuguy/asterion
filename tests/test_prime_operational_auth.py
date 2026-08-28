from __future__ import annotations

import unittest

from asterion.operation.auth import AuthOperationService

from tests.test_operation_auth import _Refresher, _Storage, _request, _transaction


class TestPrimeOperationalAuth(unittest.IsolatedAsyncioTestCase):
    async def test_mock_refresh_is_injected_and_never_authorizes_model_work(self) -> None:
        storage, refresher = _Storage(), _Refresher()
        service = AuthOperationService(storage=storage, refresher=refresher)

        receipt = await service.execute(
            _transaction("auth-refresh-prime-1"),
            _request("auth.refresh", refresh_ref="oauth-ref-1", subject_digest="a" * 64, precedence=4),
        )

        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(len(refresher.calls), 1)
        self.assertEqual(
            (receipt.effect_counts["network_operations"], receipt.effect_counts["provider_model_requests"]),
            (0, 0),
        )
