from __future__ import annotations

import unittest

from asterion.operation.manager import OperationManagerError

from tests.test_operation_manager import _manager, _transaction


class TestOperationPrivateResolver(unittest.IsolatedAsyncioTestCase):
    async def test_reconcile_reuses_original_purpose_for_exactly_one_second_read(
        self,
    ) -> None:
        manager, resolver, store, _, _ = _manager()
        transaction = _transaction()
        await manager.execute(transaction)
        store.evict(transaction.operation_id)
        await manager.reconcile(transaction)
        self.assertEqual(
            resolver.purposes,
            [transaction.request.purpose, transaction.request.purpose],
        )
        self.assertEqual(resolver.calls, 2)

    async def test_resolver_failure_is_redacted_and_does_not_call_service(self) -> None:
        manager, resolver, _, service, _ = _manager()

        def fail(*args, **kwargs):
            raise RuntimeError("SENTINEL_SECRET")

        resolver.resolve = fail  # type: ignore[method-assign]
        with self.assertRaises(OperationManagerError) as raised:
            await manager.execute(_transaction())
        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
        self.assertEqual(service.execute_calls, [])
