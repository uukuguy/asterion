from __future__ import annotations

import json
import unittest
from pathlib import Path

from typing import cast

from asterion.operation.model_selection import (
    ModelCatalog,
    ModelSelection,
    ModelSelectionOperationError,
    ModelSelectionOperationService,
    ModelSelectionStore,
    ModelSelectionStoreReceipt,
    validate_model_selection_request,
)
from asterion.operation.protocol import EFFECT_COUNTERS, OperationReceipt, OperationTransaction
from asterion.operation.services import OperationReconciliationContext


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "operation" / "v1"


def _fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _model_selection_request(
    model_id: str = "fixture.model.small", **overrides: object
) -> dict[str, object]:
    return {
        "catalog_id": "fixture-catalog-1",
        "model_id": model_id,
        "thinking_level": "low",
        "service_tier": "standard",
        "transport_id": "fixture.transport-1",
        **overrides,
    }


def _model_transaction(
    operation_id: str,
    *,
    feature_id: str = "operation.model-selection",
    request_kind: str = "operation.model-selection-request",
    purpose: str = "operation.model-selection",
    media_type: str = "application/json",
    byte_count: int = 512,
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


class _Catalog:
    catalog_id = "fixture-catalog-1"

    def __init__(self, *selections: object) -> None:
        self.selections = selections or (
            ModelSelection(
                "fixture-catalog-1",
                "fixture.model.small",
                "low",
                "standard",
                "fixture.transport-1",
            ),
        )
        self.lookup_calls: list[tuple[str, str]] = []
        self.network_operations = 0

    def select(self, selection: ModelSelection) -> object:
        self.lookup_calls.append((selection.catalog_id, selection.model_id))
        matches = tuple(item for item in self.selections if item == selection)
        if len(matches) == 1:
            return matches[0]
        if len(matches) == 0:
            raise LookupError("not found")
        return matches


class _Store:
    def __init__(self, *, fail: bool = False, receipt: object | None = None) -> None:
        self.fail = fail
        self.receipt = receipt
        self.writes: list[tuple[str, ModelSelection, str]] = []

    def put(
        self,
        transaction: OperationTransaction,
        selection: ModelSelection,
        selection_digest: str,
    ) -> object:
        self.writes.append((transaction.operation_id, selection, selection_digest))
        if self.fail:
            raise RuntimeError("SENTINEL_SECRET")
        if self.receipt is not None:
            return self.receipt
        return ModelSelectionStoreReceipt(
            transaction.operation_id,
            f"model-selection-{transaction.operation_id}",
            selection_digest,
        )


def _model_service(
    *, catalog: _Catalog | None = None, store: _Store | None = None
) -> tuple[ModelSelectionOperationService, _Catalog, _Store]:
    fixture_catalog = catalog or _Catalog()
    fixture_store = store or _Store()
    return (
        ModelSelectionOperationService(
            catalog=cast(ModelCatalog, fixture_catalog),
            store=cast(ModelSelectionStore, fixture_store),
        ),
        fixture_catalog,
        fixture_store,
    )


class TestModelSelectionRequest(unittest.TestCase):
    def test_request_is_closed_immutable_and_has_only_the_exact_selection_fields(self) -> None:
        request = validate_model_selection_request(
            _fixture("valid-model-selection-request.json")
        )
        self.assertEqual(tuple(request), (
            "catalog_id", "model_id", "thinking_level", "service_tier", "transport_id"
        ))
        with self.assertRaises(TypeError):
            request["model_id"] = "changed"  # type: ignore[index]
        with self.assertRaises(ModelSelectionOperationError) as raised:
            validate_model_selection_request(
                _fixture("invalid-model-selection-request-extra.json")
            )
        self.assertNotIn("SENTINEL_BODY", str(raised.exception))


class TestModelSelectionOperationService(unittest.IsolatedAsyncioTestCase):
    async def test_selection_requires_exact_catalog_tuple_and_is_not_provider_discovery(self) -> None:
        service, catalog, store = _model_service()

        receipt = await service.execute(
            _model_transaction("model-1"), _model_selection_request()
        )

        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(catalog.lookup_calls, [("fixture-catalog-1", "fixture.model.small")])
        self.assertEqual(catalog.network_operations, 0)
        self.assertEqual(len(store.writes), 1)
        self.assertEqual(receipt.effect_counts, {counter: 0 for counter in EFFECT_COUNTERS})

    async def test_wrong_service_binding_rejects_before_catalog_or_store_effects(self) -> None:
        invalid_transactions = {
            "feature": _model_transaction("model-feature", feature_id="operation.auth"),
            "kind": _model_transaction("model-kind", request_kind="operation.auth-request"),
            "purpose": _model_transaction("model-purpose", purpose="operation.auth"),
            "media": _model_transaction("model-media", media_type="text/plain"),
            "bytes": _model_transaction("model-bytes", byte_count=4097),
        }
        for name, transaction in invalid_transactions.items():
            with self.subTest(name=name):
                service, catalog, store = _model_service()
                with self.assertRaises(ModelSelectionOperationError):
                    await service.execute(transaction, _model_selection_request())
                self.assertEqual((catalog.lookup_calls, store.writes), ([], []))

    async def test_catalog_id_version_or_full_tuple_mismatch_fails_before_store_mutation(self) -> None:
        cases = {
            "catalog-id": _model_selection_request(catalog_id="fixture-catalog-2"),
            "model": _model_selection_request(model_id="fixture.model.large"),
            "thinking": _model_selection_request(thinking_level="high"),
            "tier": _model_selection_request(service_tier="priority"),
            "transport": _model_selection_request(transport_id="fixture.transport-2"),
        }
        for name, request in cases.items():
            with self.subTest(name=name):
                service, catalog, store = _model_service()
                receipt = await service.execute(_model_transaction(f"model-{name}"), request)
                self.assertEqual((receipt.status, receipt.reason_code), ("failed", "model-selection-unavailable"))
                self.assertEqual(store.writes, [])
                self.assertEqual(catalog.network_operations, 0)

    async def test_duplicate_or_malformed_catalog_output_fails_closed_before_store_mutation(self) -> None:
        selection = ModelSelection(
            "fixture-catalog-1", "fixture.model.small", "low", "standard", "fixture.transport-1"
        )
        for name, catalog in (
            ("duplicate", _Catalog(selection, selection)),
            ("wrong-returned-tuple", _Catalog(ModelSelection("fixture-catalog-1", "fixture.model.small", "high", "standard", "fixture.transport-1"))),
        ):
            with self.subTest(name=name):
                service, _, store = _model_service(catalog=catalog)
                receipt = await service.execute(_model_transaction(f"model-{name}"), _model_selection_request())
                self.assertEqual((receipt.status, receipt.reason_code), ("failed", "model-selection-unavailable"))
                self.assertEqual(store.writes, [])

    async def test_store_receipt_must_match_transaction_and_canonical_selection_digest(self) -> None:
        selection = ModelSelection(
            "fixture-catalog-1", "fixture.model.small", "low", "standard", "fixture.transport-1"
        )
        bad_store = _Store(
            receipt=ModelSelectionStoreReceipt("other-operation", "selection-ref-1", "b" * 64)
        )
        service, _, store = _model_service(catalog=_Catalog(selection), store=bad_store)

        receipt = await service.execute(_model_transaction("model-store-bad"), _model_selection_request())

        self.assertEqual((receipt.status, receipt.reason_code), ("failed", "model-selection-unavailable"))
        self.assertEqual(len(store.writes), 1)
        self.assertNotIn("SENTINEL_SECRET", repr(receipt))

    async def test_store_failure_returns_public_safe_unavailable_receipt(self) -> None:
        service, _, store = _model_service(store=_Store(fail=True))

        receipt = await service.execute(_model_transaction("model-store-failure"), _model_selection_request())

        self.assertEqual((receipt.status, receipt.reason_code), ("failed", "model-selection-unavailable"))
        self.assertEqual(len(store.writes), 1)
        self.assertNotIn("SENTINEL_SECRET", repr(receipt))

    async def test_cancel_and_reconcile_validate_context_without_catalog_or_store_effects(self) -> None:
        service, catalog, store = _model_service()
        transaction = _model_transaction("model-cancel")
        wrong = _model_transaction("model-wrong", feature_id="operation.auth")
        with self.assertRaises(ModelSelectionOperationError):
            await service.cancel(wrong)
        with self.assertRaises(ModelSelectionOperationError):
            await service.reconcile(
                transaction,
                _model_selection_request(),
                OperationReconciliationContext("other-operation", 1, 1),
            )
        receipt = await service.cancel(transaction)
        self.assertEqual((receipt.status, receipt.reason_code), ("cancelled", "model-selection-cancelled"))
        self.assertEqual((catalog.lookup_calls, store.writes), ([], []))

    async def test_service_receipt_keeps_exact_transaction_identity_and_no_private_values(self) -> None:
        service, _, _ = _model_service()
        transaction = _model_transaction("model-receipt")

        receipt = await service.execute(transaction, _model_selection_request())

        self.assertIsInstance(receipt, OperationReceipt)
        self.assertEqual(receipt.operation_id, transaction.operation_id)
        self.assertEqual(receipt.request_sha256, transaction.request.request_sha256)
        self.assertEqual(receipt.purpose, transaction.request.purpose)
        self.assertEqual(receipt.effect_counts, {counter: 0 for counter in EFFECT_COUNTERS})
        self.assertNotIn("fixture.model.small", repr(receipt))
