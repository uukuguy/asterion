from __future__ import annotations

import unittest


from tests.test_operation_manager import _manager, _transaction


class TestOperationPrivateResolver(unittest.IsolatedAsyncioTestCase):
    async def test_reconcile_reuses_original_purpose_for_exactly_one_second_read(
        self,
    ) -> None:
        manager, resolver, store, service, _ = _manager()
        transaction = _transaction()
        service.fail_execute = True
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
        receipt = await manager.execute(_transaction())
        self.assertEqual(receipt.status, "failed")
        self.assertNotIn("SENTINEL_SECRET", repr(receipt))
        self.assertEqual(service.execute_calls, [])
