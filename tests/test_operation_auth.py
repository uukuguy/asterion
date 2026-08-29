from __future__ import annotations

import hashlib
import unittest

from asterion.operation.auth import (
    AuthOperationError,
    AuthOperationService,
    AuthStatus,
    validate_auth_request,
)
from asterion.operation.protocol import EFFECT_COUNTERS, OperationReceipt, OperationTransaction
from asterion.operation.services import OperationReconciliationContext


def _transaction(
    operation_id: str,
    *,
    feature_id: str = "operation.auth",
    request_kind: str = "operation.auth-request",
    purpose: str = "operation.auth",
    media_type: str = "application/json",
    byte_count: int = 1,
) -> OperationTransaction:
    return OperationTransaction.from_mapping(
        {
            "protocol": "asterion.operation/v1",
            "operation_id": operation_id,
            "request": {
                "protocol": "asterion.operation/v1",
                "request_kind": request_kind,
                "request_ref": f"request-{operation_id}",
                "request_sha256": "a" * 64,
                "media_type": media_type,
                "byte_count": byte_count,
                "purpose": purpose,
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
            "feature_id": feature_id,
            "requested_at": "2026-08-10T15:00:00Z",
        }
    )


def _request(action: str, **values: object) -> dict[str, object]:
    return {"action": action, **values}


class _Storage:
    def __init__(self, statuses: tuple[AuthStatus, ...] = ()) -> None:
        self.statuses = statuses
        self.puts: list[tuple[str, str, int]] = []
        self.clears: list[str] = []
        self.status_calls = 0

    def put(self, credential_ref: str, *, subject_digest: str, precedence: int) -> str:
        self.puts.append((credential_ref, subject_digest, precedence))
        return hashlib.sha256(credential_ref.encode()).hexdigest()

    def status(self) -> tuple[AuthStatus, ...]:
        self.status_calls += 1
        return self.statuses

    def clear(self, credential_ref: str) -> None:
        self.clears.append(credential_ref)


class _Refresher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def refresh(self, refresh_ref: str) -> str:
        self.calls.append(refresh_ref)
        return "credential-ref-refreshed"


class TestAuthRequest(unittest.TestCase):
    def test_closed_action_variants_reject_secrets_and_forbidden_fields(self) -> None:
        request = validate_auth_request(
            _request(
                "auth.store",
                credential_ref="credential-ref-1",
                subject_digest="a" * 64,
                precedence=4,
            )
        )
        self.assertEqual(request["action"], "auth.store")
        with self.assertRaises(AuthOperationError):
            validate_auth_request(
                _request(
                    "auth.store",
                    credential_ref="credential-ref-1",
                    subject_digest="a" * 64,
                    precedence=4,
                    token="SENTINEL_SECRET",
                )
            )
        with self.assertRaises(AuthOperationError):
            validate_auth_request(_request("auth.clear", refresh_ref="refresh-ref-1"))


class TestAuthOperationService(unittest.IsolatedAsyncioTestCase):
    async def test_service_rejects_wrong_transaction_before_store_or_refresh_effects(self) -> None:
        invalid_transactions = {
            "feature": _transaction("auth-wrong-feature", feature_id="operation.doctor"),
            "kind": _transaction("auth-wrong-kind", request_kind="operation.other-request"),
            "purpose": _transaction("auth-wrong-purpose", purpose="operation.other"),
            "media": _transaction("auth-wrong-media", media_type="text/plain"),
            "bytes": _transaction("auth-wrong-bytes", byte_count=4097),
        }
        requests = {
            "store": _request("auth.store", credential_ref="credential-ref-1", subject_digest="a" * 64, precedence=4),
            "refresh": _request("auth.refresh", refresh_ref="refresh-ref-1", subject_digest="a" * 64, precedence=4),
        }
        for transaction_name, transaction in invalid_transactions.items():
            for action, request in requests.items():
                with self.subTest(transaction=transaction_name, action=action):
                    storage, refresher = _Storage(), _Refresher()
                    service = AuthOperationService(storage=storage, refresher=refresher)
                    with self.assertRaises(AuthOperationError):
                        await service.execute(transaction, request)
                    self.assertEqual((storage.puts, storage.clears, storage.status_calls), ([], [], 0))
                    self.assertEqual(refresher.calls, [])

    async def test_cancel_and_reconcile_reject_wrong_transaction_or_context(self) -> None:
        service = AuthOperationService(storage=_Storage())
        wrong = _transaction("auth-cancel-wrong", feature_id="operation.doctor")
        with self.assertRaises(AuthOperationError):
            await service.cancel(wrong)
        with self.assertRaises(AuthOperationError):
            await service.reconcile(
                wrong,
                _request("auth.status"),
                OperationReconciliationContext(wrong.operation_id, wrong.authority_revision, 1),
            )
        transaction = _transaction("auth-reconcile-1")
        for context in (
            OperationReconciliationContext("other-operation", 1, 1),
            OperationReconciliationContext(transaction.operation_id, 2, 1),
            OperationReconciliationContext(transaction.operation_id, 1, 0),
        ):
            with self.subTest(context=context):
                with self.assertRaises(AuthOperationError):
                    await service.reconcile(transaction, _request("auth.status"), context)

    async def test_status_uses_exact_prime_precedence_and_stale_filtering(self) -> None:
        storage = _Storage(
            (
                AuthStatus("prime-inference", "runtime", True, 1, "a" * 64, "b" * 64),
                AuthStatus("prime-inference", "environment", False, 2, "c" * 64, "d" * 64),
                AuthStatus("other-provider", "environment", False, 3, "e" * 64, "f" * 64),
                AuthStatus("other-provider", "stored", False, 2, "1" * 64, "2" * 64),
            )
        )
        service = AuthOperationService(storage=storage)

        receipt = await service.execute(_transaction("auth-status-1"), _request("auth.status"))

        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(
            [(status.provider_id, status.candidate_kind) for status in service.status()],
            [("other-provider", "stored"), ("prime-inference", "environment")],
        )
        self.assertNotIn("SENTINEL_SECRET", repr(receipt))

    async def test_status_omits_all_stale_prime_and_other_provider_candidates(self) -> None:
        storage = _Storage(
            (
                AuthStatus("prime-inference", "runtime", True, 1, "a" * 64, "b" * 64),
                AuthStatus("prime-inference", "environment", True, 2, "c" * 64, "d" * 64),
                AuthStatus("other-provider", "runtime", True, 1, "e" * 64, "f" * 64),
                AuthStatus("other-provider", "stored", True, 2, "1" * 64, "2" * 64),
            )
        )
        service = AuthOperationService(storage=storage)

        receipt = await service.execute(_transaction("auth-status-all-stale"), _request("auth.status"))

        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(service.status(), ())
        self.assertNotIn("SENTINEL_SECRET", repr(receipt))

    async def test_precedence_tie_rejects_before_effects(self) -> None:
        storage = _Storage(
            (
                AuthStatus("prime-inference", "environment", False, 2, "a" * 64, "b" * 64),
                AuthStatus("prime-inference", "environment", False, 2, "c" * 64, "d" * 64),
            )
        )
        service = AuthOperationService(storage=storage)

        with self.assertRaises(AuthOperationError):
            await service.execute(_transaction("auth-status-tie"), _request("auth.status"))
        self.assertEqual(storage.puts, [])

    async def test_store_clear_and_refresh_validate_before_storage_or_refresher(self) -> None:
        storage, refresher = _Storage(), _Refresher()
        service = AuthOperationService(storage=storage, refresher=refresher)

        await service.execute(
            _transaction("auth-store-1"),
            _request("auth.store", credential_ref="credential-ref-1", subject_digest="a" * 64, precedence=4),
        )
        await service.execute(
            _transaction("auth-refresh-1"),
            _request("auth.refresh", refresh_ref="refresh-ref-1", subject_digest="b" * 64, precedence=4),
        )
        await service.execute(_transaction("auth-clear-1"), _request("auth.clear", credential_ref="credential-ref-1"))
        await service.execute(_transaction("auth-clear-2"), _request("auth.clear", credential_ref="credential-ref-1"))

        self.assertEqual(storage.puts[0], ("credential-ref-1", "a" * 64, 4))
        self.assertEqual(storage.puts[1], ("credential-ref-refreshed", "b" * 64, 4))
        self.assertEqual(refresher.calls, ["refresh-ref-1"])
        self.assertEqual(storage.clears, ["credential-ref-1", "credential-ref-1"])
        with self.assertRaises(AuthOperationError):
            await service.execute(
                _transaction("auth-invalid-1"),
                _request("auth.refresh", refresh_ref="refresh-ref-1", subject_digest="b" * 64, precedence=4, body="SENTINEL_SECRET"),
            )
        self.assertEqual(refresher.calls, ["refresh-ref-1"])

    async def test_service_receipts_are_public_safe_and_prohibited_effect_free(self) -> None:
        receipt = await AuthOperationService(storage=_Storage()).execute(
            _transaction("auth-receipt-1"), _request("auth.status")
        )
        self.assertIsInstance(receipt, OperationReceipt)
        self.assertEqual(receipt.effect_counts, {key: 0 for key in EFFECT_COUNTERS})
        self.assertNotIn("credential-ref", repr(receipt))
