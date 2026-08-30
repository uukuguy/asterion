from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest

from asterion.control.authority import (
    AuthorityLedger,
    OperationDecision,
    operation_transaction_digest,
)
from asterion.control.journal import JournalCursor, JournalRecord, MemoryCanonicalJournal
from asterion.operation.manager import OperationManager, OperationManagerError
from asterion.operation.services import (
    OperationDispatcher,
    OperationHandoffProof,
    StagedOperationService,
)
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
    transaction: OperationTransaction,
    status: str = "succeeded",
    reason: str | None = None,
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
            "reason_code": reason or f"operation-{status}",
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


class StagedService(Service, StagedOperationService):
    async def prepare_handoff(
        self, transaction: OperationTransaction, typed_request: object
    ) -> OperationHandoffProof | OperationReceipt:
        assert typed_request == {"action": "read"}
        return OperationHandoffProof("a" * 64)

    async def handoff_prepared(
        self,
        transaction: OperationTransaction,
        typed_request: object,
        proof: OperationHandoffProof,
    ) -> OperationReceipt:
        assert typed_request == {"action": "read"}
        assert proof.digest == "a" * 64
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


def _append_records(journal, records: list[JournalRecord]) -> None:
    position = journal.position
    for record in records:
        position = journal.append(position, record).position


def _recovered_manager(journal):
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
    return manager, resolver, store, service


def _admitted(transaction: OperationTransaction) -> OperationDecision:
    return OperationDecision(
        operation_id=transaction.operation_id,
        authority_id=transaction.authority_id,
        authority_revision=transaction.authority_revision,
        transaction_digest=operation_transaction_digest(transaction),
        feature_id=transaction.feature_id,
        status="admitted",
        reason="admitted",
    )


def _rejected(transaction: OperationTransaction) -> OperationDecision:
    return OperationDecision(
        operation_id=transaction.operation_id,
        authority_id=transaction.authority_id,
        authority_revision=transaction.authority_revision,
        transaction_digest=operation_transaction_digest(transaction),
        feature_id=transaction.feature_id,
        status="rejected",
        reason="host-service-not-authorized",
    )


def _admitted_prefix(transaction: OperationTransaction) -> list[JournalRecord]:
    decision = _admitted(transaction)
    return [
        JournalRecord.operation_transaction_accepted(transaction),
        JournalRecord.operation_admitted(decision),
        JournalRecord.operation_reserved(decision),
    ]


class TestOperationManager(unittest.IsolatedAsyncioTestCase):
    async def test_dispatcher_projects_exact_immutable_identity(self) -> None:
        manager, _, _, _, _ = _manager()

        dispatcher: OperationDispatcher = manager
        self.assertEqual(
            (
                dispatcher.session_id,
                dispatcher.generation,
                dispatcher.authority_id,
                dispatcher.authority_revision,
            ),
            ("session-1", 1, "authority-1", 1),
        )
        for field, value in (
            ("session_id", "hostile-session"),
            ("generation", 2),
            ("authority_id", "hostile-authority"),
            ("authority_revision", 2),
        ):
            with self.subTest(field=field):
                with self.assertRaises(AttributeError):
                    setattr(dispatcher, field, value)
        self.assertEqual(
            (
                dispatcher.session_id,
                dispatcher.generation,
                dispatcher.authority_id,
                dispatcher.authority_revision,
            ),
            ("session-1", 1, "authority-1", 1),
        )

    async def test_dispatcher_identity_ignores_hostile_collaborator_projections(
        self,
    ) -> None:
        class HostileIdentity:
            @property
            def session_id(self) -> str:
                return "collaborator-session"

            @property
            def generation(self) -> int:
                return 900

            @property
            def authority_id(self) -> str:
                return "collaborator-authority"

            @property
            def authority_revision(self) -> int:
                return 900

        class HostileResolver(HostileIdentity, Resolver):
            pass

        class HostileStore(HostileIdentity, Store):
            pass

        class HostileService(HostileIdentity, Service):
            pass

        journal = MemoryCanonicalJournal("selected-session")
        first = journal.append(
            0,
            JournalRecord.system_bound(
                system_id="research.system", system_version="1.0.0"
            ),
        )
        journal.append(
            first.position,
            JournalRecord.authority_bound(
                authority_id="authority-1", authority_revision=1
            ),
        )
        dispatcher: OperationDispatcher = OperationManager(
            authority=AuthorityLedger(
                _envelope(
                    allowed_operations=("operation.auth",),
                    host_service_grants=("operation.auth",),
                )
            ),
            journal=journal,
            resolver=HostileResolver(),
            private_store=HostileStore(),
            services={"operation.auth": HostileService()},
            now_ms=lambda: 1000,
            session_id="selected-session",
            generation=7,
        )

        self.assertEqual(
            (
                dispatcher.session_id,
                dispatcher.generation,
                dispatcher.authority_id,
                dispatcher.authority_revision,
            ),
            ("selected-session", 7, "authority-1", 1),
        )
        for field, value in (
            ("session_id", "hostile-session"),
            ("generation", 8),
            ("authority_id", "hostile-authority"),
            ("authority_revision", 2),
        ):
            with self.subTest(field=field):
                with self.assertRaises(AttributeError):
                    setattr(dispatcher, field, value)

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

    async def test_staged_prepare_cannot_claim_nonterminal_or_success_before_entered_boundary(self) -> None:
        class PrematureSuccess(StagedService):
            status = "succeeded"

            async def prepare_handoff(
                self, transaction: OperationTransaction, typed_request: object
            ) -> OperationHandoffProof | OperationReceipt:
                return _receipt(transaction, self.status)

        for status in ("succeeded", "uncertain"):
            with self.subTest(status=status):
                manager, _, _, _, journal = _manager()
                service = PrematureSuccess()
                service.status = status
                manager._services["operation.auth"] = service
                receipt = await manager.execute(_transaction())
                self.assertEqual((receipt.status, receipt.reason_code), ("failed", "handoff-preparation-failed"))
                self.assertNotIn(
                    "operation.handoff.prepared",
                    [entry.record.kind for entry in journal.replay(JournalCursor(0))],
                )

    async def test_staged_handoff_exception_never_enters_or_becomes_reconcilable(self) -> None:
        class RaisingHandoff(StagedService):
            async def handoff_prepared(self, transaction, typed_request, proof):
                raise RuntimeError("SENTINEL_PRECALL")

        manager, _, _, _, journal = _manager()
        manager._services["operation.auth"] = RaisingHandoff()
        receipt = await manager.execute(_transaction())
        self.assertEqual((receipt.status, receipt.reason_code), ("failed", "handoff-preparation-failed"))
        kinds = [entry.record.kind for entry in journal.replay(JournalCursor(0))]
        self.assertIn("operation.handoff.prepared", kinds)
        self.assertNotIn("operation.handoff.entered", kinds)
        self.assertEqual(await manager.reconcile(_transaction()), receipt)

    async def test_dynamic_service_is_not_probed_for_staged_capability(self) -> None:
        class DynamicService(Service):
            def __init__(self) -> None:
                super().__init__()
                self.probes = 0

            def __getattr__(self, name):
                self.probes += 1
                raise AssertionError(name)

        manager, _, _, _, _ = _manager()
        service = DynamicService()
        manager._services["operation.auth"] = service
        self.assertEqual((await manager.execute(_transaction())).status, "succeeded")
        self.assertEqual(service.probes, 0)

    async def test_feature_grant_is_consumed_after_first_transaction(self) -> None:
        manager, resolver, _, service, _ = _manager()
        await manager.execute(_transaction())
        rejected = await manager.execute(_transaction("operation-2"))
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(resolver.calls, 1)
        self.assertEqual(service.execute_calls, ["operation-1"])

    async def test_rejected_prevalidation_recovery_is_non_settling(self) -> None:
        manager, resolver, _, service, journal = _manager()
        manager._services.clear()
        receipt = await manager.execute(_transaction())
        self.assertEqual(receipt.status, "rejected")
        self.assertEqual((resolver.calls, service.execute_calls), (0, []))
        recovered = OperationManager(
            authority=AuthorityLedger(
                _envelope(
                    allowed_operations=("operation.auth",),
                    host_service_grants=("operation.auth",),
                )
            ),
            journal=journal,
            resolver=Resolver(),
            private_store=Store(),
            services={},
            now_ms=lambda: 1000,
            session_id="session-1",
            generation=1,
        )
        self.assertEqual((await recovered.execute(_transaction())).status, "rejected")
        self.assertEqual(recovered._authority.operation_settlements, {})

    async def test_authority_rejection_recovery_is_non_settling_and_replays(self) -> None:
        _, _, _, _, journal = _manager()
        transaction = _transaction()
        _append_records(
            journal,
            [
                JournalRecord.operation_transaction_accepted(transaction),
                JournalRecord.operation_admitted(_rejected(transaction)),
                JournalRecord.operation_receipted(_receipt(transaction, "rejected")),
            ],
        )

        recovered, resolver, _, service = _recovered_manager(journal)

        self.assertEqual((await recovered.execute(transaction)).status, "rejected")
        self.assertEqual((resolver.calls, service.execute_calls), (0, []))
        self.assertEqual(recovered._authority.operation_settlements, {})

    async def test_recovery_accepts_only_legal_operation_phase_prefixes(self) -> None:
        transaction = _transaction()
        decision = _admitted(transaction)
        accepted = JournalRecord.operation_transaction_accepted(transaction)
        admitted = JournalRecord.operation_admitted(decision)
        reserved = JournalRecord.operation_reserved(decision)
        dispatch = JournalRecord.operation_dispatch_started(transaction)
        handoff = JournalRecord.operation_handoff_fenced(transaction)
        uncertain = JournalRecord.operation_receipted(_receipt(transaction, "uncertain"))
        terminal = JournalRecord.operation_receipted(_receipt(transaction))
        wrong_dispatch = JournalRecord(
            "operation-dispatch-wrong-digest",
            "operation.dispatch.started",
            {
                "operation_id": transaction.operation_id,
                "transaction_digest": "a" * 64,
            },
        )
        duplicate_dispatch = JournalRecord(
            "operation-dispatch-duplicate",
            "operation.dispatch.started",
            dispatch.payload,
        )
        duplicate_handoff = JournalRecord(
            "operation-handoff-duplicate",
            "operation.handoff.fenced",
            handoff.payload,
        )
        duplicate_accepted = JournalRecord(
            "operation-transaction-duplicate",
            "operation.transaction.accepted",
            accepted.payload,
        )
        terminal_after_terminal = JournalRecord.operation_receipted(
            _receipt(transaction, "failed", "private-request-unavailable")
        )
        cases = {
            "decision-without-accepted": [admitted],
            "reserve-without-admitted": [accepted, reserved],
            "dispatch-without-reservation": [accepted, admitted, dispatch],
            "handoff-without-dispatch": [accepted, admitted, reserved, handoff],
            "wrong-dispatch-digest": [accepted, admitted, reserved, wrong_dispatch],
            "duplicate-dispatch": [accepted, admitted, reserved, dispatch, duplicate_dispatch],
            "duplicate-handoff": [accepted, admitted, reserved, dispatch, handoff, duplicate_handoff],
            "duplicate-accepted": [accepted, duplicate_accepted],
            "uncertain-without-dispatch": [accepted, admitted, reserved, uncertain],
            "terminal-without-handoff": [accepted, admitted, reserved, dispatch, terminal],
            "reconcile-without-uncertain": [
                accepted,
                admitted,
                reserved,
                dispatch,
                handoff,
                JournalRecord.operation_reconciliation_recorded(
                    operation_id=transaction.operation_id, attempt=1
                ),
            ],
            "reconcile-attempt-gap": [
                accepted,
                admitted,
                reserved,
                dispatch,
                uncertain,
                JournalRecord.operation_reconciliation_recorded(
                    operation_id=transaction.operation_id, attempt=2
                ),
            ],
            "terminal-after-uncertain-without-reconcile": [
                accepted,
                admitted,
                reserved,
                dispatch,
                uncertain,
                terminal,
            ],
            "terminal-to-terminal": [
                accepted,
                admitted,
                reserved,
                dispatch,
                handoff,
                terminal,
                terminal_after_terminal,
            ],
        }
        for name, records in cases.items():
            with self.subTest(name=name):
                _, _, _, _, journal = _manager()
                _append_records(journal, records)
                with self.assertRaisesRegex(
                    OperationManagerError, "operation recovery is invalid"
                ):
                    _recovered_manager(journal)

    async def test_recovery_accepts_uncertain_reconciliation_and_terminal_prefix(self) -> None:
        transaction = _transaction()
        records = _admitted_prefix(transaction)
        records.extend(
            [
                JournalRecord.operation_dispatch_started(transaction),
                JournalRecord.operation_receipted(_receipt(transaction, "uncertain")),
                JournalRecord.operation_reconciliation_recorded(
                    operation_id=transaction.operation_id, attempt=1
                ),
                JournalRecord.operation_receipted(_receipt(transaction)),
            ]
        )
        _, _, _, _, journal = _manager()
        _append_records(journal, records)

        recovered, resolver, _, service = _recovered_manager(journal)

        self.assertEqual((await recovered.reconcile(transaction)).status, "succeeded")
        self.assertEqual((resolver.calls, service.reconcile_calls), (0, []))
        self.assertEqual(
            set(recovered._authority.operation_settlements), {transaction.operation_id}
        )

    async def test_recovery_turns_unreceipted_dispatch_prefix_into_uncertain_once(self) -> None:
        transaction = _transaction()
        records = _admitted_prefix(transaction)
        records.append(JournalRecord.operation_dispatch_started(transaction))
        _, _, _, _, journal = _manager()
        _append_records(journal, records)

        recovered, resolver, _, service = _recovered_manager(journal)

        self.assertEqual((await recovered.execute(transaction)).status, "uncertain")
        self.assertEqual((resolver.calls, service.execute_calls), (0, []))
        operation_receipts = [
            entry.record
            for entry in journal.replay(JournalCursor(0))
            if entry.record.kind == "operation.receipted"
        ]
        self.assertEqual(len(operation_receipts), 1)
