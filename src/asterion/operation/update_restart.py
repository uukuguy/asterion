"""Deterministic, injected coordination for a controlled update/restart operation."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from asterion.control.protocol import IDENTIFIER, OPAQUE_ID
from asterion.operation.protocol import (
    EFFECT_COUNTERS,
    MAX_SAFE_INTEGER,
    OperationProtocolError,
    OperationReceipt,
    OperationTransaction,
)
from asterion.operation.services import (
    OperationHandoffProof,
    OperationReconciliationContext,
    StagedOperationService,
)


CONTROLLED_UPDATE_RESTART_REQUEST_KIND = "operation.controlled-update-restart-request"
CONTROLLED_UPDATE_RESTART_REQUEST_PURPOSE = "operation.controlled-update-restart"
CONTROLLED_UPDATE_RESTART_MAX_REQUEST_BYTES = 4096
_REQUEST_FIELDS = frozenset({"current_artifact", "next_artifact", "checkpoint_ref"})
_ARTIFACT_FIELDS = frozenset(
    {"artifact_id", "artifact_sha256", "daemon_id", "protocol_compatibility_id"}
)
_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "body",
        "credential",
        "destination",
        "path",
        "prompt",
        "refresh_token",
        "text",
        "token",
    }
)


class ControlledUpdateRestartOperationError(OperationProtocolError):
    """Raised with a fixed message, never coordinator or private-request details."""


@dataclass(frozen=True, repr=False)
class ArtifactIdentity:
    """One exact public-safe artifact and daemon compatibility identity."""

    artifact_id: str
    artifact_sha256: str
    daemon_id: str
    protocol_compatibility_id: str

    def __post_init__(self) -> None:
        _validate_artifact_fields(
            self.artifact_id,
            self.artifact_sha256,
            self.daemon_id,
            self.protocol_compatibility_id,
        )

    @classmethod
    def from_mapping(cls, value: object) -> ArtifactIdentity:
        mapping = _closed_mapping(value, _ARTIFACT_FIELDS, "artifact identity")
        _reject_forbidden_keys(mapping)
        return cls(
            artifact_id=_opaque(mapping["artifact_id"]),
            artifact_sha256=_digest(mapping["artifact_sha256"]),
            daemon_id=_opaque(mapping["daemon_id"]),
            protocol_compatibility_id=_identifier(mapping["protocol_compatibility_id"]),
        )

    def to_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "artifact_id": self.artifact_id,
                "artifact_sha256": self.artifact_sha256,
                "daemon_id": self.daemon_id,
                "protocol_compatibility_id": self.protocol_compatibility_id,
            }
        )

    def __repr__(self) -> str:
        return "ArtifactIdentity(<redacted>)"


@dataclass(frozen=True, repr=False)
class RestartCapsule:
    """Exact immutable handoff identity reconstructed only by this service."""

    operation_id: str
    authority_id: str
    authority_revision: int
    current_artifact: ArtifactIdentity
    next_artifact: ArtifactIdentity
    checkpoint_ref: str
    capsule_digest: str

    def __post_init__(self) -> None:
        _opaque(self.operation_id)
        _opaque(self.authority_id)
        if type(self.authority_revision) is not int or not 1 <= self.authority_revision <= MAX_SAFE_INTEGER:
            raise ControlledUpdateRestartOperationError("controlled restart capsule is invalid")
        current = _copy_artifact(self.current_artifact)
        next_artifact = _copy_artifact(self.next_artifact)
        checkpoint_ref = _opaque(self.checkpoint_ref)
        expected = _capsule_digest(
            self.operation_id,
            self.authority_id,
            self.authority_revision,
            current,
            next_artifact,
            checkpoint_ref,
        )
        if self.capsule_digest != expected:
            raise ControlledUpdateRestartOperationError("controlled restart capsule is invalid")
        object.__setattr__(self, "current_artifact", current)
        object.__setattr__(self, "next_artifact", next_artifact)

    def __repr__(self) -> str:
        return "RestartCapsule(<redacted>)"


class UpdateRestartCoordinator(Protocol):
    """The sole injected effect boundary; no production coordinator is supplied."""

    async def verify_next(self, expected: ArtifactIdentity) -> ArtifactIdentity: ...

    async def seal_checkpoint(self, capsule: RestartCapsule) -> str: ...

    async def handoff(self, capsule: RestartCapsule) -> str: ...

    async def reconcile(self, operation_id: str, capsule_digest: str) -> str | None: ...

    async def cancel(self, operation_id: str) -> str: ...


@dataclass(frozen=True, repr=False)
class _RestartRecord:
    transaction: OperationTransaction
    transaction_digest: str
    request_digest: str | None
    capsule: RestartCapsule | None
    phase: str
    receipt: OperationReceipt | None


def validate_controlled_update_restart_request(value: object) -> Mapping[str, object]:
    """Validate a closed, body-free request without reaching a coordinator."""

    mapping = _closed_mapping(value, _REQUEST_FIELDS, "controlled restart request")
    _reject_forbidden_keys(mapping)
    current = ArtifactIdentity.from_mapping(mapping["current_artifact"])
    next_artifact = ArtifactIdentity.from_mapping(mapping["next_artifact"])
    checkpoint_ref = _opaque(mapping["checkpoint_ref"])
    return MappingProxyType(
        {
            "current_artifact": current.to_mapping(),
            "next_artifact": next_artifact.to_mapping(),
            "checkpoint_ref": checkpoint_ref,
        }
    )


class UpdateRestartOperationService(StagedOperationService):
    """Coordinate exactly one sealed handoff per immutable operation identity."""

    feature_id = "operation.controlled-update-restart"
    request_kind = CONTROLLED_UPDATE_RESTART_REQUEST_KIND
    request_purpose = CONTROLLED_UPDATE_RESTART_REQUEST_PURPOSE
    max_request_bytes = CONTROLLED_UPDATE_RESTART_MAX_REQUEST_BYTES

    def __init__(self, *, coordinator: UpdateRestartCoordinator) -> None:
        if coordinator is None:
            raise ControlledUpdateRestartOperationError("controlled restart coordinator is invalid")
        self._coordinator = coordinator
        self._records: dict[str, _RestartRecord] = {}

    @property
    def fenced_capsules(self) -> tuple[RestartCapsule, ...]:
        return tuple(
            _copy_capsule(record.capsule)
            for record in self._records.values()
            if record.phase in {"handoff-fenced", "settled"} and record.capsule is not None
        )

    async def execute(
        self, transaction: OperationTransaction, typed_request: object
    ) -> OperationReceipt:
        prepared = await self.prepare_handoff(transaction, typed_request)
        if isinstance(prepared, OperationReceipt):
            return prepared
        return await self.handoff_prepared(transaction, typed_request, prepared)

    async def prepare_handoff(
        self, transaction: OperationTransaction, typed_request: object
    ) -> OperationHandoffProof | OperationReceipt:
        validated_transaction = self._validate_transaction(transaction)
        request = validate_controlled_update_restart_request(typed_request)
        _validate_request_binding(validated_transaction, request)
        transaction_digest = _transaction_digest(validated_transaction)
        request_digest = _request_digest(request)
        existing = self._records.get(validated_transaction.operation_id)
        if existing is not None:
            self._require_same_record(existing, transaction_digest, request_digest)
            if existing.receipt is not None:
                return _copy_receipt(existing.receipt)
            if existing.phase == "prepared":
                return OperationHandoffProof(
                    _copy_capsule(existing.capsule).capsule_digest
                )
            if existing.phase == "preparing":
                return self._store_failed(
                    existing.transaction, "restart-pre-handoff-incomplete"
                )
            return _uncertain_receipt(existing.transaction)

        stored_transaction = _copy_transaction(validated_transaction)
        capsule = _capsule_from(stored_transaction, request)
        self._records[stored_transaction.operation_id] = _RestartRecord(
            stored_transaction, transaction_digest, request_digest, capsule, "preparing", None
        )
        try:
            verified = await self._coordinator.verify_next(_copy_artifact(capsule.next_artifact))
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except Exception:
            return self._store_failed(stored_transaction, "restart-verification-failed")
        try:
            if _copy_artifact(verified) != capsule.next_artifact:
                return self._store_failed(stored_transaction, "restart-verification-failed")
        except ControlledUpdateRestartOperationError:
            return self._store_failed(stored_transaction, "restart-verification-failed")
        cancelled = self._terminal_record_receipt(stored_transaction.operation_id)
        if cancelled is not None:
            return cancelled
        try:
            sealed = await self._coordinator.seal_checkpoint(_copy_capsule(capsule))
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except Exception:
            return self._store_failed(stored_transaction, "restart-checkpoint-failed")
        if not _is_exact_digest(sealed, capsule.capsule_digest):
            return self._store_failed(stored_transaction, "restart-checkpoint-failed")
        cancelled = self._terminal_record_receipt(stored_transaction.operation_id)
        if cancelled is not None:
            return cancelled

        self._records[stored_transaction.operation_id] = _RestartRecord(
            stored_transaction, transaction_digest, request_digest, capsule, "prepared", None
        )
        return OperationHandoffProof(capsule.capsule_digest)

    async def handoff_prepared(
        self,
        transaction: OperationTransaction,
        typed_request: object,
        proof: OperationHandoffProof,
    ) -> OperationReceipt:
        validated_transaction = self._validate_transaction(transaction)
        request = validate_controlled_update_restart_request(typed_request)
        _validate_request_binding(validated_transaction, request)
        transaction_digest = _transaction_digest(validated_transaction)
        request_digest = _request_digest(request)
        if type(proof) is not OperationHandoffProof or not _is_digest(proof.digest):
            raise ControlledUpdateRestartOperationError("controlled restart handoff proof is invalid")
        record = self._records.get(validated_transaction.operation_id)
        if record is None:
            raise ControlledUpdateRestartOperationError("controlled restart handoff proof is invalid")
        self._require_same_record(record, transaction_digest, request_digest)
        if record.receipt is not None:
            return _copy_receipt(record.receipt)
        if (
            record.phase != "prepared"
            or record.capsule is None
            or proof.digest != record.capsule.capsule_digest
        ):
            raise ControlledUpdateRestartOperationError("controlled restart handoff proof is invalid")
        capsule = record.capsule
        self._records[validated_transaction.operation_id] = _RestartRecord(
            record.transaction,
            record.transaction_digest,
            record.request_digest,
            capsule,
            "handoff-fenced",
            None,
        )
        try:
            result = await self._coordinator.handoff(_copy_capsule(capsule))
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except Exception:
            return self._store_uncertain(validated_transaction)
        if not _is_exact_digest(result, capsule.capsule_digest):
            return self._store_uncertain(validated_transaction)
        receipt = _receipt(record.transaction, "succeeded", "restart-handoff-confirmed")
        self._records[record.transaction.operation_id] = _RestartRecord(
            record.transaction,
            record.transaction_digest,
            record.request_digest,
            capsule,
            "settled",
            receipt,
        )
        return _copy_receipt(receipt)

    async def cancel(self, transaction: OperationTransaction) -> OperationReceipt:
        validated_transaction = self._validate_transaction(transaction)
        transaction_digest = _transaction_digest(validated_transaction)
        existing = self._records.get(validated_transaction.operation_id)
        if existing is not None:
            if existing.transaction_digest != transaction_digest:
                raise ControlledUpdateRestartOperationError("controlled restart identity is invalid")
            if existing.receipt is not None:
                return _copy_receipt(existing.receipt)
            if existing.phase in {"preparing", "prepared"}:
                return await self._cancel_prepared(existing)
            return _uncertain_receipt(existing.transaction)
        try:
            result = await self._coordinator.cancel(validated_transaction.operation_id)
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except Exception:
            raise ControlledUpdateRestartOperationError("controlled restart cancellation is unavailable") from None
        if result != validated_transaction.operation_id:
            raise ControlledUpdateRestartOperationError("controlled restart cancellation is invalid")
        stored_transaction = _copy_transaction(validated_transaction)
        receipt = _receipt(stored_transaction, "cancelled", "restart-cancelled")
        self._records[stored_transaction.operation_id] = _RestartRecord(
            stored_transaction, transaction_digest, None, None, "settled", receipt
        )
        return _copy_receipt(receipt)

    async def _cancel_prepared(self, record: _RestartRecord) -> OperationReceipt:
        try:
            result = await self._coordinator.cancel(record.transaction.operation_id)
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except Exception:
            raise ControlledUpdateRestartOperationError("controlled restart cancellation is unavailable") from None
        if result != record.transaction.operation_id:
            raise ControlledUpdateRestartOperationError("controlled restart cancellation is invalid")
        receipt = _receipt(record.transaction, "cancelled", "restart-cancelled")
        self._records[record.transaction.operation_id] = _RestartRecord(
            record.transaction,
            record.transaction_digest,
            record.request_digest,
            record.capsule,
            "settled",
            receipt,
        )
        return _copy_receipt(receipt)

    def _terminal_record_receipt(self, operation_id: str) -> OperationReceipt | None:
        record = self._records.get(operation_id)
        if record is None or record.receipt is None:
            return None
        return _copy_receipt(record.receipt)

    async def reconcile(
        self,
        transaction: OperationTransaction,
        typed_request: object,
        context: OperationReconciliationContext,
    ) -> OperationReceipt:
        validated_transaction = self._validate_transaction(transaction)
        request = validate_controlled_update_restart_request(typed_request)
        _validate_request_binding(validated_transaction, request)
        transaction_digest = _transaction_digest(validated_transaction)
        request_digest = _request_digest(request)
        if (
            type(context) is not OperationReconciliationContext
            or context.operation_id != validated_transaction.operation_id
            or context.authority_revision != validated_transaction.authority_revision
            or type(context.reconciliation_attempt) is not int
            or not 1 <= context.reconciliation_attempt <= MAX_SAFE_INTEGER
            or not _is_exact_digest(
                context.handoff_proof_digest, _capsule_from(validated_transaction, request).capsule_digest
            )
        ):
            raise ControlledUpdateRestartOperationError("controlled restart reconciliation is invalid")
        record = self._records.get(validated_transaction.operation_id)
        if record is None:
            if self._records:
                raise ControlledUpdateRestartOperationError(
                    "controlled restart reconciliation is invalid"
                )
            stored_transaction = _copy_transaction(validated_transaction)
            capsule = _capsule_from(stored_transaction, request)
            record = _RestartRecord(
                stored_transaction,
                transaction_digest,
                request_digest,
                capsule,
                "handoff-fenced",
                _uncertain_receipt(stored_transaction),
            )
            self._records[stored_transaction.operation_id] = record
        self._require_same_record(record, transaction_digest, request_digest)
        if (
            record.phase != "handoff-fenced"
            or record.capsule is None
            or context.handoff_proof_digest != record.capsule.capsule_digest
        ):
            if record.receipt is not None and record.receipt.status != "uncertain":
                return _copy_receipt(record.receipt)
            raise ControlledUpdateRestartOperationError("controlled restart reconciliation is invalid")
        if record.receipt is not None and record.receipt.status != "uncertain":
            return _copy_receipt(record.receipt)
        try:
            result = await self._coordinator.reconcile(
                record.capsule.operation_id, record.capsule.capsule_digest
            )
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except Exception:
            return self._store_uncertain(record.transaction)
        if not _is_exact_digest(result, record.capsule.capsule_digest):
            return self._store_uncertain(record.transaction)
        receipt = _receipt(record.transaction, "succeeded", "restart-reconciled")
        self._records[record.transaction.operation_id] = _RestartRecord(
            record.transaction,
            record.transaction_digest,
            record.request_digest,
            record.capsule,
            "settled",
            receipt,
        )
        return _copy_receipt(receipt)

    def _store_uncertain(self, transaction: OperationTransaction) -> OperationReceipt:
        record = self._records[transaction.operation_id]
        receipt = _uncertain_receipt(record.transaction)
        self._records[transaction.operation_id] = _RestartRecord(
            record.transaction,
            record.transaction_digest,
            record.request_digest,
            record.capsule,
            "handoff-fenced",
            receipt,
        )
        return _copy_receipt(receipt)

    def _store_failed(
        self, transaction: OperationTransaction, reason_code: str
    ) -> OperationReceipt:
        record = self._records[transaction.operation_id]
        receipt = _receipt(record.transaction, "failed", reason_code)
        self._records[transaction.operation_id] = _RestartRecord(
            record.transaction,
            record.transaction_digest,
            record.request_digest,
            record.capsule,
            "settled",
            receipt,
        )
        return _copy_receipt(receipt)

    @staticmethod
    def _validate_transaction(transaction: object) -> OperationTransaction:
        if type(transaction) is not OperationTransaction:
            raise ControlledUpdateRestartOperationError("controlled restart transaction is invalid")
        try:
            copied = _copy_transaction(transaction)
        except Exception:
            raise ControlledUpdateRestartOperationError("controlled restart transaction is invalid") from None
        if (
            copied.feature_id != "operation.controlled-update-restart"
            or copied.request.request_kind != CONTROLLED_UPDATE_RESTART_REQUEST_KIND
            or copied.request.purpose != CONTROLLED_UPDATE_RESTART_REQUEST_PURPOSE
            or copied.request.media_type != "application/json"
            or copied.request.byte_count > CONTROLLED_UPDATE_RESTART_MAX_REQUEST_BYTES
        ):
            raise ControlledUpdateRestartOperationError("controlled restart transaction is invalid")
        return copied

    @staticmethod
    def _require_same_record(
        record: _RestartRecord, transaction_digest: str, request_digest: str
    ) -> None:
        if record.transaction_digest != transaction_digest or record.request_digest != request_digest:
            raise ControlledUpdateRestartOperationError("controlled restart identity is invalid")


def _capsule_from(
    transaction: OperationTransaction, request: Mapping[str, object]
) -> RestartCapsule:
    current = ArtifactIdentity.from_mapping(request["current_artifact"])
    next_artifact = ArtifactIdentity.from_mapping(request["next_artifact"])
    checkpoint_ref = _opaque(request["checkpoint_ref"])
    digest = _capsule_digest(
        transaction.operation_id,
        transaction.authority_id,
        transaction.authority_revision,
        current,
        next_artifact,
        checkpoint_ref,
    )
    return RestartCapsule(
        transaction.operation_id,
        transaction.authority_id,
        transaction.authority_revision,
        current,
        next_artifact,
        checkpoint_ref,
        digest,
    )


def _capsule_digest(
    operation_id: str,
    authority_id: str,
    authority_revision: int,
    current: ArtifactIdentity,
    next_artifact: ArtifactIdentity,
    checkpoint_ref: str,
) -> str:
    payload = {
        "authority_id": authority_id,
        "authority_revision": authority_revision,
        "checkpoint_ref": checkpoint_ref,
        "current_artifact": dict(current.to_mapping()),
        "next_artifact": dict(next_artifact.to_mapping()),
        "operation_id": operation_id,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _transaction_digest(transaction: OperationTransaction) -> str:
    return hashlib.sha256(
        json.dumps(_json_value(transaction.to_mapping()), separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _request_digest(request: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(_json_value(request), separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _validate_request_binding(
    transaction: OperationTransaction, request: Mapping[str, object]
) -> None:
    body = json.dumps(
        _json_value(request), separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    if (
        len(body) != transaction.request.byte_count
        or hashlib.sha256(body).hexdigest() != transaction.request.request_sha256
    ):
        raise ControlledUpdateRestartOperationError("controlled restart request is invalid")


def _copy_transaction(transaction: OperationTransaction) -> OperationTransaction:
    return OperationTransaction.from_mapping(transaction.to_mapping())


def _copy_artifact(value: object) -> ArtifactIdentity:
    if type(value) is not ArtifactIdentity:
        raise ControlledUpdateRestartOperationError("controlled restart artifact is invalid")
    return ArtifactIdentity(value.artifact_id, value.artifact_sha256, value.daemon_id, value.protocol_compatibility_id)


def _copy_capsule(value: RestartCapsule | None) -> RestartCapsule:
    if type(value) is not RestartCapsule:
        raise ControlledUpdateRestartOperationError("controlled restart capsule is invalid")
    return RestartCapsule(
        value.operation_id,
        value.authority_id,
        value.authority_revision,
        _copy_artifact(value.current_artifact),
        _copy_artifact(value.next_artifact),
        value.checkpoint_ref,
        value.capsule_digest,
    )


def _copy_receipt(receipt: OperationReceipt) -> OperationReceipt:
    return OperationReceipt.from_mapping(receipt.to_mapping())


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
            "receipt_ref": f"restart-capsule-{transaction.operation_id}",
            "reconciliation_ref": None,
            "effect_counts": {counter: 0 for counter in EFFECT_COUNTERS},
            "completed_at": transaction.requested_at,
        }
    )


def _uncertain_receipt(transaction: OperationTransaction) -> OperationReceipt:
    return _receipt(transaction, "uncertain", "restart-handoff-uncertain")


def _closed_mapping(value: object, fields: frozenset[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(type(key) is str for key in value):
        raise ControlledUpdateRestartOperationError(f"controlled restart {label} is invalid")
    if set(value) != fields:
        raise ControlledUpdateRestartOperationError(f"controlled restart {label} is invalid")
    return value


def _reject_forbidden_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if type(key) is not str or key in _FORBIDDEN_KEYS:
                raise ControlledUpdateRestartOperationError("controlled restart request is invalid")
            _reject_forbidden_keys(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        raise ControlledUpdateRestartOperationError("controlled restart request is invalid")


def _validate_artifact_fields(
    artifact_id: object, artifact_sha256: object, daemon_id: object, protocol_compatibility_id: object
) -> None:
    _opaque(artifact_id)
    _digest(artifact_sha256)
    _opaque(daemon_id)
    _identifier(protocol_compatibility_id)


def _opaque(value: object) -> str:
    if type(value) is not str or OPAQUE_ID.fullmatch(value) is None:
        raise ControlledUpdateRestartOperationError("controlled restart value is invalid")
    return value


def _identifier(value: object) -> str:
    if type(value) is not str or IDENTIFIER.fullmatch(value) is None:
        raise ControlledUpdateRestartOperationError("controlled restart value is invalid")
    return value


def _digest(value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ControlledUpdateRestartOperationError("controlled restart value is invalid")
    return value


def _is_exact_digest(value: object, expected: str) -> bool:
    return type(value) is str and value == expected


def _is_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_json_value(child) for child in value]
    return value
