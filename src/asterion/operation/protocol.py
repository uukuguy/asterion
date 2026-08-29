"""Closed public descriptors, transactions, and receipts for host operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from asterion.control.protocol import IDENTIFIER, MEDIA_TYPE, OPAQUE_ID, UTC_TIMESTAMP


OPERATION_PROTOCOL = "asterion.operation/v1"
OPERATION_FEATURE_IDS = frozenset(
    {
        "operation.auth",
        "operation.controlled-update-restart",
        "operation.doctor",
        "operation.model-selection",
        "operation.settings-keybindings",
        "operation.telemetry-usage",
    }
)
EFFECT_COUNTERS = (
    "credential_value_reads",
    "provider_model_requests",
    "network_operations",
    "package_manager_operations",
    "os_process_restart_operations",
    "external_telemetry_deliveries",
    "uploads",
)
MAX_SAFE_INTEGER = 9_007_199_254_740_991

_DESCRIPTOR_FIELDS = {
    "protocol",
    "request_kind",
    "request_ref",
    "request_sha256",
    "media_type",
    "byte_count",
    "purpose",
    "client_id",
    "session_id",
    "generation",
    "authority_revision",
}
_TRANSACTION_FIELDS = {
    "protocol",
    "operation_id",
    "request",
    "session_id",
    "client_id",
    "generation",
    "authority_revision",
    "authority_id",
    "idempotency_key",
    "feature_id",
    "requested_at",
}
_RECEIPT_FIELDS = {
    "protocol",
    "receipt_id",
    "operation_id",
    "request_ref",
    "request_sha256",
    "purpose",
    "session_id",
    "client_id",
    "generation",
    "authority_revision",
    "authority_id",
    "idempotency_key",
    "feature_id",
    "status",
    "reason_code",
    "receipt_ref",
    "reconciliation_ref",
    "effect_counts",
    "completed_at",
}
_RECEIPT_STATUSES = frozenset(
    {"succeeded", "rejected", "failed", "cancelled", "uncertain"}
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


class OperationProtocolError(ValueError):
    """Raised when a public operation value is invalid or body-bearing."""


def validate_operation_request_descriptor(value: object) -> Mapping[str, object]:
    """Validate a single immutable, body-free private-request descriptor."""

    descriptor = _closed(value, _DESCRIPTOR_FIELDS, "operation request descriptor")
    _reject_forbidden_keys(descriptor)
    _require_protocol(descriptor)
    _require_identifier(descriptor.get("request_kind"), "operation request kind")
    for field in ("request_ref", "client_id", "session_id"):
        _require_opaque(descriptor.get(field), f"operation request {field}")
    _require_sha256(descriptor.get("request_sha256"), "operation request digest")
    _require_media_type(descriptor.get("media_type"), "operation request media type")
    _require_nonnegative(descriptor.get("byte_count"), "operation request byte count")
    _require_identifier(descriptor.get("purpose"), "operation request purpose")
    _require_positive(descriptor.get("generation"), "operation request generation")
    _require_positive(
        descriptor.get("authority_revision"), "operation request authority revision"
    )
    return _freeze_mapping(descriptor)


def validate_operation_transaction(value: object) -> Mapping[str, object]:
    """Validate a closed transaction and bind it exactly to its descriptor."""

    transaction = _closed(value, _TRANSACTION_FIELDS, "operation transaction")
    _reject_forbidden_keys(transaction)
    _require_protocol(transaction)
    for field in (
        "operation_id",
        "session_id",
        "client_id",
        "authority_id",
        "idempotency_key",
    ):
        _require_opaque(transaction.get(field), f"operation transaction {field}")
    _require_positive(transaction.get("generation"), "operation transaction generation")
    _require_positive(
        transaction.get("authority_revision"),
        "operation transaction authority revision",
    )
    feature_id = transaction.get("feature_id")
    _require_feature(feature_id, "operation transaction feature")
    _require_timestamp(
        transaction.get("requested_at"), "operation transaction timestamp"
    )
    request = validate_operation_request_descriptor(transaction.get("request"))
    for field in ("session_id", "client_id", "generation", "authority_revision"):
        if transaction[field] != request[field]:
            raise OperationProtocolError(
                "operation transaction identity does not match request"
            )
    return _freeze_mapping(transaction)


def validate_operation_receipt(value: object) -> Mapping[str, object]:
    """Validate one public-safe receipt with a zeroed prohibited effect vector."""

    receipt = _closed(value, _RECEIPT_FIELDS, "operation receipt")
    _reject_forbidden_keys(receipt)
    _require_protocol(receipt)
    for field in (
        "receipt_id",
        "operation_id",
        "request_ref",
        "session_id",
        "client_id",
        "authority_id",
        "idempotency_key",
        "receipt_ref",
    ):
        _require_opaque(receipt.get(field), f"operation receipt {field}")
    _require_nullable_opaque(
        receipt.get("reconciliation_ref"), "operation receipt reconciliation"
    )
    _require_sha256(receipt.get("request_sha256"), "operation receipt request digest")
    _require_identifier(receipt.get("purpose"), "operation receipt purpose")
    _require_feature(receipt.get("feature_id"), "operation receipt feature")
    _require_positive(receipt.get("generation"), "operation receipt generation")
    _require_positive(
        receipt.get("authority_revision"), "operation receipt authority revision"
    )
    status = receipt.get("status")
    if not isinstance(status, str) or status not in _RECEIPT_STATUSES:
        raise OperationProtocolError("operation receipt status is invalid")
    _require_identifier(receipt.get("reason_code"), "operation receipt reason")
    _require_effect_counts(receipt.get("effect_counts"))
    _require_timestamp(receipt.get("completed_at"), "operation receipt timestamp")
    return _freeze_mapping(receipt)


@dataclass(frozen=True, repr=False)
class OperationRequestDescriptor:
    """The only public boundary for a private operation request document."""

    request_kind: str
    request_ref: str
    request_sha256: str
    media_type: str
    byte_count: int
    purpose: str
    client_id: str
    session_id: str
    generation: int
    authority_revision: int
    protocol: str = OPERATION_PROTOCOL

    def __post_init__(self) -> None:
        snapshot = validate_operation_request_descriptor(self._mapping())
        for field in _DESCRIPTOR_FIELDS - {"protocol"}:
            object.__setattr__(self, field, snapshot[field])

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> OperationRequestDescriptor:
        snapshot = validate_operation_request_descriptor(value)
        return cls(**{field: snapshot[field] for field in _DESCRIPTOR_FIELDS})  # type: ignore[arg-type]

    def _mapping(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in _DESCRIPTOR_FIELDS}

    def to_mapping(self) -> Mapping[str, object]:
        return validate_operation_request_descriptor(self._mapping())

    def __repr__(self) -> str:
        return "OperationRequestDescriptor(<redacted>)"


@dataclass(frozen=True, repr=False)
class OperationTransaction:
    """Immutable operation transaction bound exactly to its request descriptor."""

    operation_id: str
    request: OperationRequestDescriptor
    session_id: str
    client_id: str
    generation: int
    authority_revision: int
    authority_id: str
    idempotency_key: str
    feature_id: str
    requested_at: str
    protocol: str = OPERATION_PROTOCOL

    def __post_init__(self) -> None:
        snapshot = validate_operation_transaction(self._mapping())
        request = snapshot["request"]
        assert isinstance(request, Mapping)
        object.__setattr__(
            self, "request", OperationRequestDescriptor.from_mapping(request)
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> OperationTransaction:
        snapshot = validate_operation_transaction(value)
        request = snapshot["request"]
        assert isinstance(request, Mapping)
        fields = {field: snapshot[field] for field in _TRANSACTION_FIELDS - {"request"}}
        return cls(request=OperationRequestDescriptor.from_mapping(request), **fields)  # type: ignore[arg-type]

    def _mapping(self) -> dict[str, object]:
        return {
            "protocol": self.protocol,
            "operation_id": self.operation_id,
            "request": dict(self.request.to_mapping()),
            "session_id": self.session_id,
            "client_id": self.client_id,
            "generation": self.generation,
            "authority_revision": self.authority_revision,
            "authority_id": self.authority_id,
            "idempotency_key": self.idempotency_key,
            "feature_id": self.feature_id,
            "requested_at": self.requested_at,
        }

    def to_mapping(self) -> Mapping[str, object]:
        return validate_operation_transaction(self._mapping())

    def __repr__(self) -> str:
        return "OperationTransaction(<redacted>)"


@dataclass(frozen=True, repr=False)
class OperationReceipt:
    """Immutable public receipt that contains no private request body or effects."""

    receipt_id: str
    operation_id: str
    request_ref: str
    request_sha256: str
    purpose: str
    session_id: str
    client_id: str
    generation: int
    authority_revision: int
    authority_id: str
    idempotency_key: str
    feature_id: str
    status: str
    reason_code: str
    receipt_ref: str
    reconciliation_ref: str | None
    effect_counts: Mapping[str, int]
    completed_at: str
    protocol: str = OPERATION_PROTOCOL

    def __post_init__(self) -> None:
        snapshot = validate_operation_receipt(self._mapping())
        effects = snapshot["effect_counts"]
        assert isinstance(effects, Mapping)
        object.__setattr__(self, "effect_counts", effects)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> OperationReceipt:
        snapshot = validate_operation_receipt(value)
        fields = {field: snapshot[field] for field in _RECEIPT_FIELDS}
        return cls(**fields)  # type: ignore[arg-type]

    def _mapping(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in _RECEIPT_FIELDS}

    def to_mapping(self) -> Mapping[str, object]:
        return validate_operation_receipt(self._mapping())

    def __repr__(self) -> str:
        return "OperationReceipt(<redacted>)"


def _closed(value: object, fields: set[str], label: str) -> Mapping[str, object]:
    if (
        not isinstance(value, Mapping)
        or not all(isinstance(key, str) for key in value)
        or set(value) != fields
    ):
        raise OperationProtocolError(f"{label} fields are invalid")
    return value


def _reject_forbidden_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or key in _FORBIDDEN_KEYS:
                raise OperationProtocolError(
                    "operation value contains a forbidden field"
                )
            _reject_forbidden_keys(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _reject_forbidden_keys(child)


def _require_protocol(value: Mapping[str, object]) -> None:
    if value.get("protocol") != OPERATION_PROTOCOL:
        raise OperationProtocolError("operation protocol is invalid")


def _require_identifier(value: object, label: str) -> None:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise OperationProtocolError(f"{label} is invalid")


def _require_opaque(value: object, label: str) -> None:
    if not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None:
        raise OperationProtocolError(f"{label} is invalid")


def _require_nullable_opaque(value: object, label: str) -> None:
    if value is not None:
        _require_opaque(value, label)


def _require_feature(value: object, label: str) -> None:
    if not isinstance(value, str) or value not in OPERATION_FEATURE_IDS:
        raise OperationProtocolError(f"{label} is invalid")


def _require_media_type(value: object, label: str) -> None:
    if not isinstance(value, str) or MEDIA_TYPE.fullmatch(value) is None:
        raise OperationProtocolError(f"{label} is invalid")


def _require_sha256(value: object, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise OperationProtocolError(f"{label} is invalid")


def _require_positive(value: object, label: str) -> None:
    if type(value) is not int or value < 1 or value > MAX_SAFE_INTEGER:
        raise OperationProtocolError(f"{label} is invalid")


def _require_nonnegative(value: object, label: str) -> None:
    if type(value) is not int or value < 0 or value > MAX_SAFE_INTEGER:
        raise OperationProtocolError(f"{label} is invalid")


def _require_timestamp(value: object, label: str) -> None:
    if not isinstance(value, str) or UTC_TIMESTAMP.fullmatch(value) is None:
        raise OperationProtocolError(f"{label} is invalid")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise OperationProtocolError(f"{label} is invalid") from None


def _require_effect_counts(value: object) -> None:
    effects = _closed(value, set(EFFECT_COUNTERS), "operation receipt effect counts")
    for counter in EFFECT_COUNTERS:
        _require_nonnegative(effects.get(counter), f"operation receipt {counter}")
        if effects[counter] != 0:
            raise OperationProtocolError(
                "operation receipt prohibited effect count is nonzero"
            )


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze(item) for key, item in value.items()})


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    return value
