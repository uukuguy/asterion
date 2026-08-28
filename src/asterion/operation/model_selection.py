"""Fixture-catalog model selection with no provider discovery authority."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from asterion.control.protocol import IDENTIFIER, OPAQUE_ID
from asterion.operation.protocol import (
    EFFECT_COUNTERS,
    OperationProtocolError,
    OperationReceipt,
    OperationTransaction,
)
from asterion.operation.services import OperationReconciliationContext


MODEL_SELECTION_REQUEST_KIND = "operation.model-selection-request"
MODEL_SELECTION_REQUEST_PURPOSE = "operation.model-selection"
MODEL_SELECTION_MAX_REQUEST_BYTES = 4096
_REQUEST_FIELDS = (
    "catalog_id",
    "model_id",
    "thinking_level",
    "service_tier",
    "transport_id",
)
_FORBIDDEN_KEYS = frozenset({
    "api_key", "authorization", "body", "credential", "destination", "path",
    "prompt", "refresh_token", "text", "token",
})


class ModelSelectionOperationError(OperationProtocolError):
    """Raised without private request, catalog, or store details."""


@dataclass(frozen=True, repr=False)
class ModelSelection:
    """The exact catalog tuple; no provider, credential, or runtime value is retained."""

    catalog_id: str
    model_id: str
    thinking_level: str
    service_tier: str
    transport_id: str

    def __post_init__(self) -> None:
        for field in _REQUEST_FIELDS:
            _require_identifier(getattr(self, field), f"model selection {field}")

    def __repr__(self) -> str:
        return "ModelSelection(<redacted>)"


@dataclass(frozen=True, repr=False)
class ModelSelectionStoreReceipt:
    """Opaque proof that a store persisted only the selected tuple and digest."""

    operation_id: str
    selection_ref: str
    selection_digest: str

    def __post_init__(self) -> None:
        _require_opaque(self.operation_id, "model selection store operation")
        _require_opaque(self.selection_ref, "model selection store reference")
        _require_digest(self.selection_digest, "model selection store digest")

    def __repr__(self) -> str:
        return "ModelSelectionStoreReceipt(<redacted>)"


class ModelCatalog(Protocol):
    """A fixture-only catalog injected by the host; it has no discovery capability."""

    catalog_id: str

    def select(self, selection: ModelSelection) -> ModelSelection: ...


class ModelSelectionStore(Protocol):
    """Operator-owned store for canonical tuple identifiers and their digest only."""

    def put(
        self,
        transaction: OperationTransaction,
        selection: ModelSelection,
        selection_digest: str,
    ) -> ModelSelectionStoreReceipt: ...


def validate_model_selection_request(value: object) -> Mapping[str, object]:
    """Validate the closed five-field private selection document."""

    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ModelSelectionOperationError("model selection request is invalid")
    _reject_forbidden_keys(value)
    if tuple(value) != _REQUEST_FIELDS and set(value) != set(_REQUEST_FIELDS):
        raise ModelSelectionOperationError("model selection request fields are invalid")
    snapshot = {field: value.get(field) for field in _REQUEST_FIELDS}
    for field, item in snapshot.items():
        _require_identifier(item, f"model selection {field}")
    return MappingProxyType(snapshot)


class ModelSelectionOperationService:
    """Resolve only one exact injected fixture tuple before a digest-bound store write."""

    feature_id = "operation.model-selection"
    request_kind = MODEL_SELECTION_REQUEST_KIND
    request_purpose = MODEL_SELECTION_REQUEST_PURPOSE
    max_request_bytes = MODEL_SELECTION_MAX_REQUEST_BYTES

    def __init__(self, *, catalog: ModelCatalog, store: ModelSelectionStore) -> None:
        self._catalog = catalog
        self._store = store

    async def execute(
        self, transaction: OperationTransaction, typed_request: object
    ) -> OperationReceipt:
        self._validate_transaction(transaction)
        selection = _selection(validate_model_selection_request(typed_request))
        if not isinstance(self._catalog.catalog_id, str) or self._catalog.catalog_id != selection.catalog_id:
            return _receipt(transaction, "failed", "model-selection-unavailable")
        try:
            selected = self._catalog.select(selection)
            if type(selected) is not ModelSelection or selected != selection:
                raise ValueError
            digest = _selection_digest(selection)
            stored = self._store.put(transaction, selection, digest)
            if (
                type(stored) is not ModelSelectionStoreReceipt
                or stored.operation_id != transaction.operation_id
                or stored.selection_digest != digest
            ):
                raise ValueError
        except Exception:
            return _receipt(transaction, "failed", "model-selection-unavailable")
        return _receipt(transaction, "succeeded", "model-selection-succeeded")

    async def cancel(self, transaction: OperationTransaction) -> OperationReceipt:
        self._validate_transaction(transaction)
        return _receipt(transaction, "cancelled", "model-selection-cancelled")

    async def reconcile(
        self,
        transaction: OperationTransaction,
        typed_request: object,
        context: OperationReconciliationContext,
    ) -> OperationReceipt:
        self._validate_transaction(transaction)
        if (
            not isinstance(context, OperationReconciliationContext)
            or context.operation_id != transaction.operation_id
            or context.authority_revision != transaction.authority_revision
            or type(context.reconciliation_attempt) is not int
            or context.reconciliation_attempt < 1
        ):
            raise ModelSelectionOperationError("model selection reconciliation is invalid")
        del typed_request
        return _receipt(transaction, "failed", "model-selection-reconciliation-unavailable")

    @staticmethod
    def _validate_transaction(transaction: object) -> None:
        if (
            not isinstance(transaction, OperationTransaction)
            or transaction.feature_id != "operation.model-selection"
            or transaction.request.request_kind != MODEL_SELECTION_REQUEST_KIND
            or transaction.request.purpose != MODEL_SELECTION_REQUEST_PURPOSE
            or transaction.request.media_type != "application/json"
            or transaction.request.byte_count > MODEL_SELECTION_MAX_REQUEST_BYTES
        ):
            raise ModelSelectionOperationError("model selection transaction is invalid")


def _selection(value: Mapping[str, object]) -> ModelSelection:
    return ModelSelection(**{field: value[field] for field in _REQUEST_FIELDS})  # type: ignore[arg-type]


def _selection_digest(selection: ModelSelection) -> str:
    canonical = json.dumps(
        {field: getattr(selection, field) for field in _REQUEST_FIELDS},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _receipt(transaction: OperationTransaction, status: str, reason_code: str) -> OperationReceipt:
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
            "reason_code": reason_code,
            "receipt_ref": f"model-selection-receipt-{transaction.operation_id}",
            "reconciliation_ref": None,
            "effect_counts": {counter: 0 for counter in EFFECT_COUNTERS},
            "completed_at": transaction.requested_at,
        }
    )


def _reject_forbidden_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or key in _FORBIDDEN_KEYS:
                raise ModelSelectionOperationError("model selection request contains a forbidden field")
            _reject_forbidden_keys(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _reject_forbidden_keys(child)


def _require_identifier(value: object, label: str) -> None:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise ModelSelectionOperationError(f"{label} is invalid")


def _require_opaque(value: object, label: str) -> None:
    if not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None:
        raise ModelSelectionOperationError(f"{label} is invalid")


def _require_digest(value: object, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ModelSelectionOperationError(f"{label} is invalid")
