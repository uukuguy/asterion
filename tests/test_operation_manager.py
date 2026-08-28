from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest

from asterion.control.authority import AuthorityLedger
from asterion.control.journal import JournalRecord, MemoryCanonicalJournal
from asterion.operation.manager import OperationManager, OperationManagerError
from asterion.operation.protocol import (
    EFFECT_COUNTERS,
    OperationReceipt,
    OperationTransaction,
)

from tests.test_control_authority import _envelope


def _transaction(
    operation_id: str = "operation-1", *, request_ref: str = "request-1"
) -> OperationTransaction:
    body = b'{"action":"read"}'
    return OperationTransaction.from_mapping(
        {
            "protocol": "asterion.operation/v1",
            "operation_id": operation_id,
            "request": {
                "protocol": "asterion.operation/v1",
                "request_kind": "operation.auth-request",
                "request_ref": request_ref,
                "request_sha256": hashlib.sha256(body).hexdigest(),
                "media_type": "application/json",
                "byte_count": len(body),
                "purpose": "operation.auth",
                "client_id": "client-1",
                "session_id": "session-1",
                "generation": 1,
                "authority_revision": 1,
            },
            "session_id": "session-1",
            "client_id": "client-1",
            "generation": 1,
            "authority_revision": 1,
            "authority_id": "authority-1",
            "idempotency_key": f"key-{operation_id}",
            "feature_id": "operation.auth",
            "requested_at": "2026-08-10T15:00:00Z",
        }
    )


def _receipt(
    transaction: OperationTransaction, status: str = "succeeded"
) -> OperationReceipt:
    return OperationReceipt.from_mapping(
        {
            "protocol": "asterion.operation/v1",
            "receipt_id": f"receipt-{transaction.operation_id}",
            "operation_id": transaction.operation_id,
            "request_ref": transaction.request.request_ref,
            "request_sha256": transaction.request.request_sha256,
            "purpose": transaction.request.purpose,
            "session_id": transaction.session_id,
            "client_id": transaction.client_id,
            "generation": transaction.generation,
            "authority_revision": transaction.authority_revision,
            "authority_id": transaction.authority_id,
            "idempotency_key": transaction.idempotency_key,
            "feature_id": transaction.feature_id,
            "status": status,
            "reason_code": f"operation-{status}",
            "receipt_ref": f"public-{transaction.operation_id}",
            "reconciliation_ref": None,
            "effect_counts": {key: 0 for key in EFFECT_COUNTERS},
            "completed_at": "2026-08-10T15:00:01Z",
        }
    )


class Resolver:
    def __init__(self) -> None:
        self.calls = 0
        self.purposes: list[str] = []

    def resolve(
        self,
        descriptor,
        *,
        purpose,
        max_bytes,
        deadline_ms,
        authority_revision,
        cancelled,
    ):
        del descriptor, max_bytes, deadline_ms, authority_revision, cancelled
        self.calls += 1
        self.purposes.append(purpose)
        return b'{"action":"read"}'


class Store:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.digests: dict[str, str] = {}

    def put(self, transaction, typed_request):
        self.values[transaction.operation_id] = typed_request
        digest = hashlib.sha256(
            json.dumps(typed_request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.digests[transaction.operation_id] = digest
        return digest

    def get(self, transaction):
        return self.values.get(transaction.operation_id)

    def get_digest(self, transaction):
        return self.digests.get(transaction.operation_id)

    def evict(self, operation_id):
        self.values.pop(operation_id, None)


class Service:
    feature_id = "operation.auth"
    request_kind = "operation.auth-request"
    request_purpose = "operation.auth"
    max_request_bytes = 100

    def __init__(self) -> None:
        self.execute_calls: list[str] = []
        self.reconcile_calls: list[str] = []
        self.fail_execute = False

    async def execute(self, transaction, typed_request):
        self.execute_calls.append(transaction.operation_id)
        assert typed_request == {"action": "read"}
        if self.fail_execute:
            raise RuntimeError("transport")
        return _receipt(transaction)

    async def cancel(self, transaction):
        return _receipt(transaction, "cancelled")

    async def reconcile(self, transaction, typed_request, context):
        self.reconcile_calls.append(context.operation_id)
        assert typed_request == {"action": "read"}
        return _receipt(transaction)


def _manager():
    journal = MemoryCanonicalJournal("session-1")
    first = journal.append(
        0,
        JournalRecord.system_bound(system_id="research.system", system_version="1.0.0"),
    )
    journal.append(
        first.position,
        JournalRecord.authority_bound(authority_id="authority-1", authority_revision=1),
    )
    resolver, store, service = Resolver(), Store(), Service()
    manager = OperationManager(
        authority=AuthorityLedger(
            _envelope(
                allowed_operations=("operation.auth",),
                host_service_grants=("operation.auth",),
            )
        ),
        journal=journal,
        resolver=resolver,
        private_store=store,
        services={"operation.auth": service},
        now_ms=lambda: 1000,
        session_id="session-1",
        generation=1,
    )
    return manager, resolver, store, service, journal


class TestOperationManager(unittest.IsolatedAsyncioTestCase):
    async def test_operation_protocol_imports_in_fresh_process(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", "import asterion.operation.protocol"],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    async def test_identical_retry_reuses_receipt_and_conflict_never_calls_service(
        self,
    ) -> None:
        manager, resolver, _, service, _ = _manager()
        first = await manager.execute(_transaction())
        self.assertEqual(first, await manager.execute(_transaction()))
        self.assertEqual((resolver.calls, service.execute_calls), (1, ["operation-1"]))
        with self.assertRaises(OperationManagerError):
            await manager.execute(_transaction(request_ref="request-other"))
        self.assertEqual(service.execute_calls, ["operation-1"])

    async def test_started_dispatch_is_uncertain_and_reconciles_without_redispatch(
        self,
    ) -> None:
        manager, _, store, service, _ = _manager()
        manager.fail_after = "operation.dispatch.started"
        receipt = await manager.execute(_transaction())
        self.assertEqual(receipt.status, "uncertain")
        store.evict("operation-1")
        self.assertEqual((await manager.reconcile(_transaction())).status, "succeeded")
        self.assertEqual(service.execute_calls, [])
        self.assertEqual(service.reconcile_calls, ["operation-1"])

    async def test_feature_grant_is_consumed_after_first_transaction(self) -> None:
        manager, resolver, _, service, _ = _manager()
        await manager.execute(_transaction())
        rejected = await manager.execute(_transaction("operation-2"))
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(resolver.calls, 1)
        self.assertEqual(service.execute_calls, ["operation-1"])
