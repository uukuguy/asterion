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

    async def test_cancellation_before_or_during_resolution_is_not_private_failure(
        self,
    ) -> None:
        for name, cancel_before_read in {
            "before-read": True,
            "after-read": False,
        }.items():
            with self.subTest(name=name):
                manager, resolver, _, service, _ = _manager()
                cancelled = [cancel_before_read]
                manager._cancelled = lambda: cancelled[0]
                if not cancel_before_read:
                    original = resolver.resolve

                    def cancel_after_read(*args, **kwargs):
                        body = original(*args, **kwargs)
                        cancelled[0] = True
                        return body

                    resolver.resolve = cancel_after_read  # type: ignore[method-assign]
                receipt = await manager.execute(_transaction())
                self.assertEqual(
                    (receipt.status, receipt.reason_code),
                    ("cancelled", "cancelled-before-dispatch"),
                )
                self.assertEqual(resolver.calls, 0 if cancel_before_read else 1)
                self.assertEqual(service.execute_calls, [])

    async def test_malicious_private_store_digest_is_never_accepted(self) -> None:
        manager, _, store, service, _ = _manager()
        transaction = _transaction()
        manager.fail_after = "operation.dispatch.started"
        self.assertEqual((await manager.execute(transaction)).status, "uncertain")
        store.digests[transaction.operation_id] = "a" * 64

        with self.assertRaisesRegex(
            ValueError, "operation private request conflicts"
        ):
            await manager.reconcile(transaction)
        self.assertEqual(service.reconcile_calls, [])
