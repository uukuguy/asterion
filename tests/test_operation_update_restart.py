from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from pathlib import Path

from asterion.operation.protocol import EFFECT_COUNTERS, OperationTransaction
from asterion.operation.services import OperationReconciliationContext
from asterion.control.authority import (
    AuthorityLedger,
    OperationDecision,
    operation_transaction_digest,
)
from asterion.control.journal import JournalCursor, JournalRecord, MemoryCanonicalJournal
from asterion.control.recovery import recover_control_host_state
from asterion.operation.manager import OperationManager, OperationManagerError
from asterion.operation.update_restart import (
    ArtifactIdentity,
    ControlledUpdateRestartOperationError,
    RestartCapsule,
    UpdateRestartOperationService,
    validate_controlled_update_restart_request,
)
from tests.test_control_authority import _envelope


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "operation" / "v1"


def _fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _request(**overrides: object) -> dict[str, object]:
    value = _fixture("valid-controlled-update-restart-request.json")
    value.update(overrides)
    return value


def _transaction(operation_id: str = "restart-1", **overrides: object) -> OperationTransaction:
    request = _request()
    body = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    value: dict[str, object] = {
        "protocol": "asterion.operation/v1",
        "operation_id": operation_id,
        "request": {
            "protocol": "asterion.operation/v1",
            "request_kind": "operation.controlled-update-restart-request",
            "request_ref": f"request-{operation_id}",
            "request_sha256": hashlib.sha256(body).hexdigest(),
            "media_type": "application/json",
            "byte_count": len(body),
            "purpose": "operation.controlled-update-restart",
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
        "feature_id": "operation.controlled-update-restart",
        "requested_at": "2026-08-28T15:00:00Z",
    }
    value.update(overrides)
    return OperationTransaction.from_mapping(value)


class _FakeCoordinator:
    def __init__(
        self,
        *,
        disconnect_after_handoff: bool = False,
        verified: ArtifactIdentity | None = None,
        seal_result: str | None = None,
        handoff_result: str | None = None,
        reconcile_result: str | None = None,
        known_reconciliation: tuple[str, str] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.disconnect_after_handoff = disconnect_after_handoff
        self.verified = verified
        self.seal_result = seal_result
        self.handoff_result = handoff_result
        self.reconcile_result = reconcile_result
        self.known_reconciliation = known_reconciliation
        self.last_capsule = None
        self.cancelled: list[str] = []

    async def verify_next(self, expected: ArtifactIdentity) -> ArtifactIdentity:
        self.calls.append("verify_next")
        return self.verified or expected

    async def seal_checkpoint(self, capsule: RestartCapsule) -> str:
        self.calls.append("seal_checkpoint")
        self.last_capsule = capsule
        return self.seal_result or capsule.capsule_digest

    async def handoff(self, capsule: RestartCapsule) -> str:
        self.calls.append("handoff")
        self.last_capsule = capsule
        if self.disconnect_after_handoff:
            raise ConnectionError("SENTINEL_COORDINATOR_DISCONNECT")
        return self.handoff_result or capsule.capsule_digest

    async def reconcile(self, operation_id: str, capsule_digest: str) -> str | None:
        self.calls.append("reconcile")
        if self.known_reconciliation == (operation_id, capsule_digest):
            return self.reconcile_result or capsule_digest
        if self.last_capsule is None:
            return None
        if operation_id != self.last_capsule.operation_id or capsule_digest != self.last_capsule.capsule_digest:
            return None
        return self.reconcile_result or capsule_digest

    async def cancel(self, operation_id: str) -> str:
        self.calls.append("cancel")
        self.cancelled.append(operation_id)
        return operation_id


def _service(
    *,
    disconnect_after_handoff: bool = False,
    verified: ArtifactIdentity | None = None,
    seal_result: str | None = None,
    handoff_result: str | None = None,
    reconcile_result: str | None = None,
    known_reconciliation: tuple[str, str] | None = None,
) -> tuple[UpdateRestartOperationService, _FakeCoordinator]:
    coordinator = _FakeCoordinator(
        disconnect_after_handoff=disconnect_after_handoff,
        verified=verified,
        seal_result=seal_result,
        handoff_result=handoff_result,
        reconcile_result=reconcile_result,
        known_reconciliation=known_reconciliation,
    )
    return UpdateRestartOperationService(coordinator=coordinator), coordinator


class _RestartResolver:
    def __init__(self, request: dict[str, object]) -> None:
        self.calls = 0
        self.body = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def resolve(self, descriptor: object, **kwargs: object) -> bytes:
        del descriptor, kwargs
        self.calls += 1
        return self.body


class _RestartStore:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.digests: dict[str, str] = {}

    def put(self, transaction: OperationTransaction, typed_request: object) -> str:
        self.values[transaction.operation_id] = typed_request
        digest = hashlib.sha256(
            json.dumps(typed_request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.digests[transaction.operation_id] = digest
        return digest

    def get(self, transaction: OperationTransaction) -> object | None:
        return self.values.get(transaction.operation_id)

    def get_digest(self, transaction: OperationTransaction) -> str | None:
        return self.digests.get(transaction.operation_id)


def _restart_manager(
    *,
    service: UpdateRestartOperationService,
    request: dict[str, object],
    journal: MemoryCanonicalJournal | None = None,
    store: _RestartStore | None = None,
) -> tuple[OperationManager, _RestartResolver, _RestartStore, MemoryCanonicalJournal]:
    operation_journal = journal or MemoryCanonicalJournal("session-1")
    if journal is None:
        bound = operation_journal.append(
            0, JournalRecord.system_bound(system_id="research.system", system_version="1.0.0")
        )
        operation_journal.append(
            bound.position,
            JournalRecord.authority_bound(authority_id="authority-1", authority_revision=1),
        )
    resolver = _RestartResolver(request)
    private_store = store or _RestartStore()
    return (
        OperationManager(
            authority=AuthorityLedger(
                _envelope(
                    allowed_operations=("operation.controlled-update-restart",),
                    host_service_grants=("operation.controlled-update-restart",),
                )
            ),
            journal=operation_journal,
            resolver=resolver,
            private_store=private_store,
            services={"operation.controlled-update-restart": service},
            now_ms=lambda: 1000,
            session_id="session-1",
            generation=1,
        ),
        resolver,
        private_store,
        operation_journal,
    )


class TestControlledUpdateRestartRequest(unittest.TestCase):
    def test_request_is_closed_immutable_and_does_not_accept_paths_or_bodies(self) -> None:
        request = validate_controlled_update_restart_request(
            _fixture("valid-controlled-update-restart-request.json")
        )
        self.assertEqual(request["checkpoint_ref"], "checkpoint-1")
        with self.assertRaises(TypeError):
            request["checkpoint_ref"] = "forged"  # type: ignore[index]
        for value in (
            _fixture("invalid-controlled-update-restart-request-path.json"),
            _request(body="SENTINEL_BODY"),
            _request(current_artifact={"artifact_id": "artifact-current-1"}),
            _request(checkpoint_ref=["checkpoint-1"]),
        ):
            with self.subTest(value=value):
                with self.assertRaises(ControlledUpdateRestartOperationError) as raised:
                    validate_controlled_update_restart_request(value)
                self.assertNotIn("SENTINEL", str(raised.exception))


class TestUpdateRestartOperationService(unittest.IsolatedAsyncioTestCase):
    async def test_verified_next_identity_seals_checkpoint_then_handoffs_once(self) -> None:
        service, coordinator = _service()
        receipt = await service.execute(_transaction(), _request())
        self.assertEqual((receipt.status, receipt.reason_code), ("succeeded", "restart-handoff-confirmed"))
        self.assertEqual(coordinator.calls, ["verify_next", "seal_checkpoint", "handoff"])
        self.assertTrue(service.fenced_capsules)
        self.assertEqual(receipt.effect_counts, {counter: 0 for counter in EFFECT_COUNTERS})

    async def test_invalid_transaction_or_next_identity_fails_before_coordinator_effects(self) -> None:
        service, coordinator = _service()
        with self.assertRaises(ControlledUpdateRestartOperationError):
            await service.execute(_transaction(feature_id="operation.auth"), _request())
        self.assertEqual(coordinator.calls, [])

        bad_next = ArtifactIdentity("artifact-next-2", "b" * 64, "prime-daemon-1", "asterion.agent-runtime.v1")
        service, coordinator = _service(verified=bad_next)
        receipt = await service.execute(_transaction("restart-bad-next"), _request())
        self.assertEqual((receipt.status, receipt.reason_code), ("failed", "restart-verification-failed"))
        self.assertEqual(coordinator.calls, ["verify_next"])

    async def test_hostile_coordinator_receipts_cannot_forge_handoff_success_or_leak_values(self) -> None:
        service, coordinator = _service(seal_result="SENTINEL_FORGED_SEAL")
        receipt = await service.execute(_transaction("restart-forged-seal"), _request())
        self.assertEqual((receipt.status, receipt.reason_code), ("failed", "restart-checkpoint-failed"))
        self.assertEqual(coordinator.calls, ["verify_next", "seal_checkpoint"])
        self.assertNotIn("SENTINEL", repr(receipt))

        service, coordinator = _service(handoff_result="SENTINEL_FORGED_HANDOFF")
        receipt = await service.execute(_transaction("restart-forged-handoff"), _request())
        self.assertEqual(receipt.status, "uncertain")
        self.assertEqual(coordinator.calls, ["verify_next", "seal_checkpoint", "handoff"])
        self.assertNotIn("SENTINEL", repr(receipt))

    async def test_pre_handoff_failures_are_terminal_failed_and_identical_retries_do_not_become_uncertain(self) -> None:
        class _VerifyFailure(_FakeCoordinator):
            async def verify_next(self, expected: ArtifactIdentity) -> ArtifactIdentity:
                self.calls.append("verify_next")
                raise RuntimeError("SENTINEL_VERIFY_FAILURE")

        class _SealFailure(_FakeCoordinator):
            async def seal_checkpoint(self, capsule: RestartCapsule) -> str:
                self.calls.append("seal_checkpoint")
                raise RuntimeError("SENTINEL_SEAL_FAILURE")

        services = (
            (
                _FakeCoordinator(
                    verified=ArtifactIdentity(
                        "artifact-other-1", "b" * 64, "prime-daemon-1", "asterion.agent-runtime.v1"
                    )
                ),
                "restart-verify-mismatch",
                ("verify_next",),
                "restart-verification-failed",
            ),
            (
                _FakeCoordinator(seal_result="SENTINEL_WRONG_SEAL"),
                "restart-seal-mismatch",
                ("verify_next", "seal_checkpoint"),
                "restart-checkpoint-failed",
            ),
            (
                _VerifyFailure(),
                "restart-verify-error",
                ("verify_next",),
                "restart-verification-failed",
            ),
            (
                _SealFailure(),
                "restart-seal-error",
                ("verify_next", "seal_checkpoint"),
                "restart-checkpoint-failed",
            ),
        )
        for coordinator, operation_id, calls, reason in services:
            with self.subTest(operation_id=operation_id):
                service = UpdateRestartOperationService(coordinator=coordinator)
                transaction = _transaction(operation_id)
                first = await service.execute(transaction, _request())
                again = await service.execute(transaction, _request())
                self.assertEqual((first.status, first.reason_code), ("failed", reason))
                self.assertEqual(again, first)
                self.assertEqual(coordinator.calls, list(calls))
                self.assertNotIn("SENTINEL", repr(first))


    async def test_handoff_disconnect_is_uncertain_until_same_capsule_reconciles_without_rehandoff(self) -> None:
        service, coordinator = _service(disconnect_after_handoff=True)
        transaction = _transaction("restart-disconnect")
        first = await service.execute(transaction, _request())
        self.assertEqual(first.status, "uncertain")
        self.assertEqual(coordinator.calls, ["verify_next", "seal_checkpoint", "handoff"])
        capsule = coordinator.last_capsule
        assert type(capsule) is RestartCapsule
        context = OperationReconciliationContext(
            "restart-disconnect", authority_revision=1, reconciliation_attempt=1,
            handoff_proof_digest=capsule.capsule_digest,
        )
        result = await service.reconcile(transaction, _request(), context)
        self.assertEqual((result.status, result.reason_code), ("succeeded", "restart-reconciled"))
        self.assertEqual(coordinator.calls, ["verify_next", "seal_checkpoint", "handoff", "reconcile"])

    async def test_manager_recovery_reconstructs_exact_capsule_for_a_fresh_service_without_rehandoff(self) -> None:
        request = _request()
        transaction = _transaction("restart-manager-recovery")
        first_service, first_coordinator = _service()
        manager, resolver, store, journal = _restart_manager(
            service=first_service, request=request
        )
        manager.fail_after = "operation.handoff.fenced"
        first = await manager.execute(transaction)
        self.assertEqual(first.status, "uncertain")
        self.assertEqual(first_coordinator.calls, ["verify_next", "seal_checkpoint", "handoff"])
        journal_kinds = [entry.record.kind for entry in journal.replay(JournalCursor(0))]
        self.assertIn("operation.handoff.prepared", journal_kinds)
        self.assertIn("operation.handoff.entered", journal_kinds)
        self.assertNotIn("operation.handoff.fenced", journal_kinds)
        self.assertEqual(resolver.calls, 1)
        capsule = first_coordinator.last_capsule
        assert type(capsule) is RestartCapsule

        recovered_service, recovered_coordinator = _service(
            known_reconciliation=(transaction.operation_id, capsule.capsule_digest)
        )
        recovered, recovered_resolver, _, _ = _restart_manager(
            service=recovered_service,
            request=request,
            journal=journal,
            store=store,
        )
        result = await recovered.reconcile(transaction)
        self.assertEqual((result.status, result.reason_code), ("succeeded", "restart-reconciled"))
        self.assertEqual(recovered_coordinator.calls, ["reconcile"])
        self.assertEqual(recovered_resolver.calls, 0)
        self.assertEqual(first_coordinator.calls, ["verify_next", "seal_checkpoint", "handoff"])

    async def test_fresh_direct_reconcile_without_manager_proof_rejects_before_coordinator(self) -> None:
        transaction = _transaction("restart-direct-fresh")
        service, coordinator = _service(
            known_reconciliation=(transaction.operation_id, "a" * 64)
        )
        with self.assertRaises(ControlledUpdateRestartOperationError):
            await service.reconcile(
                transaction,
                _request(),
                OperationReconciliationContext(transaction.operation_id, 1, 1),
            )
        self.assertEqual(coordinator.calls, [])

    async def test_actual_disconnect_records_prepared_entered_then_recovers_once(self) -> None:
        request = _request()
        transaction = _transaction("restart-actual-disconnect")
        service, coordinator = _service(disconnect_after_handoff=True)
        manager, _, store, journal = _restart_manager(service=service, request=request)
        first = await manager.execute(transaction)
        self.assertEqual(first.status, "uncertain")
        kinds = [entry.record.kind for entry in journal.replay(JournalCursor(0))]
        self.assertEqual(
            kinds[-3:],
            [
                "operation.handoff.prepared",
                "operation.handoff.entered",
                "operation.receipted",
            ],
        )
        capsule = coordinator.last_capsule
        assert type(capsule) is RestartCapsule
        recovered_service, recovered_coordinator = _service(
            known_reconciliation=(transaction.operation_id, capsule.capsule_digest)
        )
        recovered, _, _, _ = _restart_manager(
            service=recovered_service, request=request, journal=journal, store=store
        )
        result = await recovered.reconcile(transaction)
        self.assertEqual((result.status, result.reason_code), ("succeeded", "restart-reconciled"))
        self.assertEqual(recovered_coordinator.calls, ["reconcile"])

    async def test_successful_staged_handoff_journal_recovers_in_control_host(self) -> None:
        request = _request()
        transaction = _transaction("restart-control-recovery")
        service, _ = _service()
        manager, _, _, journal = _restart_manager(service=service, request=request)
        receipt = await manager.execute(transaction)
        self.assertEqual(receipt.status, "succeeded")
        recovered = recover_control_host_state(
            journal.replay(JournalCursor(0)),
            _envelope(
                allowed_operations=("operation.controlled-update-restart",),
                host_service_grants=("operation.controlled-update-restart",),
            ),
            expected_session_id="session-1",
            expected_generation=1,
        )
        self.assertEqual(recovered.authority.operation_settlements.keys(), {transaction.operation_id})

    async def test_recovered_manager_rejects_missing_or_tampered_handoff_proof_before_coordinator(self) -> None:
        request = _request()
        transaction = _transaction("restart-proof-recovery")
        service, coordinator = _service()
        manager, _, store, journal = _restart_manager(service=service, request=request)
        manager.fail_after = "operation.handoff.fenced"
        uncertain = await manager.execute(transaction)
        self.assertEqual(uncertain.status, "uncertain")
        records = [entry.record for entry in journal.replay(JournalCursor(0))]
        for mode, handoff in (
            ("missing", JournalRecord.operation_handoff_prepared(transaction, handoff_proof_digest="a" * 64)),
            (
                "tampered",
                JournalRecord.operation_handoff_entered(
                    transaction, handoff_proof_digest="a" * 64
                ),
            ),
        ):
            with self.subTest(mode=mode):
                replay = MemoryCanonicalJournal("session-1")
                for record in records:
                    if mode == "missing" and record.kind == "operation.handoff.entered":
                        continue
                    replay.append(
                        replay.position,
                        handoff if record.kind == "operation.handoff.entered" else record,
                    )
                recovered_service, recovered_coordinator = _service()
                if mode in {"missing", "tampered"}:
                    with self.assertRaises(OperationManagerError):
                        _restart_manager(
                            service=recovered_service, request=request, journal=replay, store=store
                        )
                self.assertEqual(recovered_coordinator.calls, [])
        self.assertEqual(coordinator.calls, ["verify_next", "seal_checkpoint", "handoff"])

    async def test_staged_dispatch_prefix_terminalizes_without_uncertainty_or_reconciliation(self) -> None:
        request = _request()
        transaction = _transaction("restart-dispatch-prefix")
        service, coordinator = _service()
        manager, _, _, journal = _restart_manager(service=service, request=request)
        manager.fail_after = "operation.dispatch.started"
        receipt = await manager.execute(transaction)
        self.assertEqual(
            (receipt.status, receipt.reason_code),
            ("failed", "handoff-preparation-incomplete"),
        )
        self.assertEqual(coordinator.calls, [])
        self.assertNotIn(
            "operation.reconciliation.recorded",
            [entry.record.kind for entry in journal.replay(JournalCursor(0))],
        )
        self.assertEqual(await manager.reconcile(transaction), receipt)

    async def test_recovered_staged_dispatch_prefix_terminalizes_without_uncertainty(self) -> None:
        request = _request()
        transaction = _transaction("restart-recovered-dispatch-prefix")
        service, coordinator = _service()
        _, _, store, journal = _restart_manager(service=service, request=request)
        decision = OperationDecision(
            operation_id=transaction.operation_id,
            authority_id=transaction.authority_id,
            authority_revision=transaction.authority_revision,
            transaction_digest=operation_transaction_digest(transaction),
            feature_id=transaction.feature_id,
            status="admitted",
            reason="admitted",
        )
        for record in (
            JournalRecord.operation_transaction_accepted(transaction),
            JournalRecord.operation_admitted(decision),
            JournalRecord.operation_reserved(decision),
            JournalRecord.operation_dispatch_started(transaction),
        ):
            journal.append(journal.position, record)
        recovered, _, _, _ = _restart_manager(
            service=UpdateRestartOperationService(coordinator=coordinator),
            request=request,
            journal=journal,
            store=store,
        )
        receipt = await recovered.execute(transaction)
        self.assertEqual(
            (receipt.status, receipt.reason_code),
            ("failed", "handoff-preparation-incomplete"),
        )
        self.assertEqual(coordinator.calls, [])

    async def test_manager_records_pre_handoff_verification_failure_as_terminal_not_uncertain(self) -> None:
        request = _request()
        transaction = _transaction("restart-manager-pre-handoff-failure")
        service, coordinator = _service(
            verified=ArtifactIdentity(
                "artifact-other-1", "b" * 64, "prime-daemon-1", "asterion.agent-runtime.v1"
            )
        )
        manager, _, store, journal = _restart_manager(service=service, request=request)
        first = await manager.execute(transaction)
        again = await manager.execute(transaction)
        self.assertEqual((first.status, first.reason_code), ("failed", "restart-verification-failed"))
        self.assertEqual(again, first)
        self.assertEqual(coordinator.calls, ["verify_next"])
        self.assertNotIn(
            "operation.handoff.fenced",
            [entry.record.kind for entry in manager._journal.replay(JournalCursor(0))],
        )
        recovered, _, _, _ = _restart_manager(
            service=UpdateRestartOperationService(coordinator=_FakeCoordinator()),
            request=request,
            journal=journal,
            store=store,
        )
        self.assertEqual(await recovered.execute(transaction), first)

    async def test_manager_recovery_rejects_reconstructed_request_drift_before_coordinator_reconciliation(self) -> None:
        request = _request()
        transaction = _transaction("restart-manager-drift")
        first_service, first_coordinator = _service(disconnect_after_handoff=True)
        manager, _, store, journal = _restart_manager(service=first_service, request=request)
        self.assertEqual((await manager.execute(transaction)).status, "uncertain")
        capsule = first_coordinator.last_capsule
        assert type(capsule) is RestartCapsule
        drifted = _request(checkpoint_ref="checkpoint-drift")
        store.values[transaction.operation_id] = drifted
        store.digests[transaction.operation_id] = hashlib.sha256(
            json.dumps(drifted, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        recovered_service, recovered_coordinator = _service(
            known_reconciliation=(transaction.operation_id, capsule.capsule_digest)
        )
        recovered, _, _, _ = _restart_manager(
            service=recovered_service, request=request, journal=journal, store=store
        )
        with self.assertRaises(OperationManagerError):
            await recovered.reconcile(transaction)
        self.assertEqual(recovered_coordinator.calls, [])

    async def test_reconcile_requires_same_transaction_request_context_and_safe_attempt_bound(self) -> None:
        service, _ = _service(disconnect_after_handoff=True)
        transaction = _transaction("restart-reconcile")
        await service.execute(transaction, _request())
        cases = (
            (_transaction("other-operation"), _request(), OperationReconciliationContext("other-operation", 1, 1)),
            (transaction, _request(checkpoint_ref="checkpoint-other"), OperationReconciliationContext("restart-reconcile", 1, 1)),
            (transaction, _request(), OperationReconciliationContext("restart-reconcile", 2, 1)),
            (transaction, _request(), OperationReconciliationContext("restart-reconcile", 1, 0)),
        )
        for supplied_transaction, request, context in cases:
            with self.subTest(context=context):
                with self.assertRaises(ControlledUpdateRestartOperationError):
                    await service.reconcile(supplied_transaction, request, context)

    async def test_cancellation_before_handoff_calls_exact_coordinator_identity_once(self) -> None:
        service, coordinator = _service()
        transaction = _transaction("restart-cancel")
        receipt = await service.cancel(transaction)
        again = await service.cancel(transaction)
        self.assertEqual((receipt.status, receipt.reason_code), ("cancelled", "restart-cancelled"))
        self.assertEqual(receipt, again)
        self.assertEqual(coordinator.calls, ["cancel"])
        self.assertEqual(coordinator.cancelled, ["restart-cancel"])

    async def test_cancellation_after_preparation_but_before_handoff_cancels_the_same_operation(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        class _BlockingCoordinator(_FakeCoordinator):
            async def verify_next(self, expected: ArtifactIdentity) -> ArtifactIdentity:
                self.calls.append("verify_next")
                started.set()
                await release.wait()
                return expected

        coordinator = _BlockingCoordinator()
        service = UpdateRestartOperationService(coordinator=coordinator)
        transaction = _transaction("restart-prepared-cancel")
        execution = asyncio.create_task(service.execute(transaction, _request()))
        await started.wait()
        receipt = await service.cancel(transaction)
        release.set()
        self.assertEqual((receipt.status, receipt.reason_code), ("cancelled", "restart-cancelled"))
        self.assertEqual(coordinator.cancelled, ["restart-prepared-cancel"])
        self.assertEqual(await execution, receipt)
        self.assertEqual(coordinator.calls, ["verify_next", "cancel"])

    async def test_cancellation_and_coordinator_cancellation_propagate(self) -> None:
        class _CancellingCoordinator(_FakeCoordinator):
            async def verify_next(self, expected: ArtifactIdentity) -> ArtifactIdentity:
                raise asyncio.CancelledError("SENTINEL_CANCEL")

        service = UpdateRestartOperationService(coordinator=_CancellingCoordinator())
        transaction = _transaction("restart-cancel-propagation")
        with self.assertRaises(asyncio.CancelledError):
            await service.execute(transaction, _request())
        retry = await service.execute(transaction, _request())
        self.assertEqual(
            (retry.status, retry.reason_code),
            ("failed", "restart-pre-handoff-incomplete"),
        )
