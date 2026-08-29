"""Offline, injected telemetry observation with a closed public-safe projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from asterion.operation.protocol import (
    EFFECT_COUNTERS,
    MAX_SAFE_INTEGER,
    OperationProtocolError,
    OperationReceipt,
    OperationTransaction,
)
from asterion.operation.services import OperationReconciliationContext


TELEMETRY_USAGE_REQUEST_KIND = "operation.telemetry-usage-request"
TELEMETRY_USAGE_REQUEST_PURPOSE = "operation.telemetry-usage"
TELEMETRY_USAGE_MAX_REQUEST_BYTES = 4096
_REQUEST_FIELDS = frozenset(
    {"source_id", "event_name", "event_count", "result_sha256", "usage"}
)
_USAGE_FIELDS = (
    "aggregate_tokens",
    "application_tokens",
    "child_tokens",
    "controller_tokens",
    "cost_micros",
)
_SOURCE_TOKEN_FIELD = MappingProxyType(
    {
        "application": "application_tokens",
        "child": "child_tokens",
        "controller": "controller_tokens",
    }
)
_EVENT_NAME = "usage.reported"
_DELIVERY_STATUSES = frozenset({"observation-recorded", "observation-failed"})
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


class TelemetryOperationError(OperationProtocolError):
    """Raised without preserving telemetry bodies, sink returns, or failures."""


@dataclass(frozen=True, repr=False)
class UsageSnapshot:
    """Immutable, additive, nonnegative usage totals without provider payloads."""

    aggregate_tokens: int
    application_tokens: int
    child_tokens: int
    controller_tokens: int
    cost_micros: int

    def __post_init__(self) -> None:
        for field in _USAGE_FIELDS:
            _require_nonnegative(getattr(self, field), f"telemetry usage {field}")
        if self.aggregate_tokens != (
            self.application_tokens + self.child_tokens + self.controller_tokens
        ):
            raise TelemetryOperationError("telemetry usage attribution is invalid")

    @classmethod
    def from_mapping(cls, value: object) -> UsageSnapshot:
        if not isinstance(value, Mapping) or set(value) != set(_USAGE_FIELDS):
            raise TelemetryOperationError("telemetry usage is invalid")
        return cls(**{field: value[field] for field in _USAGE_FIELDS})  # type: ignore[arg-type]

    def to_mapping(self) -> Mapping[str, int]:
        return MappingProxyType({field: getattr(self, field) for field in _USAGE_FIELDS})

    def __repr__(self) -> str:
        return "UsageSnapshot(<redacted>)"


@dataclass(frozen=True, repr=False)
class TelemetryObservation:
    """Public-safe metadata passed only to an explicitly injected observer."""

    source_id: str
    event_name: str
    event_count: int
    usage: UsageSnapshot
    result_sha256: str
    delivery_status: str

    def __post_init__(self) -> None:
        _validate_observation_fields(
            self.source_id,
            self.event_name,
            self.event_count,
            self.usage,
            self.result_sha256,
            self.delivery_status,
        )

    def with_delivery_status(self, delivery_status: str) -> TelemetryObservation:
        return TelemetryObservation(
            source_id=self.source_id,
            event_name=self.event_name,
            event_count=self.event_count,
            usage=self.usage,
            result_sha256=self.result_sha256,
            delivery_status=delivery_status,
        )

    def to_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "source_id": self.source_id,
                "event_name": self.event_name,
                "event_count": self.event_count,
                "usage": self.usage.to_mapping(),
                "result_sha256": self.result_sha256,
                "delivery_status": self.delivery_status,
            }
        )

    def __repr__(self) -> str:
        return "TelemetryObservation(<redacted>)"


class TelemetrySink(Protocol):
    """Operator-injected observation boundary with no transport authority."""

    async def record(self, observation: TelemetryObservation) -> None: ...


@dataclass(frozen=True, repr=False)
class TelemetryEffects:
    """Separate local accounting that never represents an external delivery."""

    injected_sink_calls: int = 0

    def __post_init__(self) -> None:
        _require_nonnegative(self.injected_sink_calls, "telemetry injected sink calls")

    def __repr__(self) -> str:
        return "TelemetryEffects(<redacted>)"


def validate_telemetry_usage_request(value: object) -> Mapping[str, object]:
    """Validate and freeze one closed request before a sink is considered."""

    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TelemetryOperationError("telemetry usage request is invalid")
    _reject_forbidden_keys(value)
    if set(value) != _REQUEST_FIELDS:
        raise TelemetryOperationError("telemetry usage request fields are invalid")
    source_id = value.get("source_id")
    event_name = value.get("event_name")
    event_count = value.get("event_count")
    result_sha256 = value.get("result_sha256")
    usage = UsageSnapshot.from_mapping(value.get("usage"))
    _validate_observation_fields(
        source_id, event_name, event_count, usage, result_sha256, "observation-recorded"
    )
    return MappingProxyType(
        {
            "source_id": source_id,
            "event_name": event_name,
            "event_count": event_count,
            "result_sha256": result_sha256,
            "usage": usage.to_mapping(),
        }
    )


class TelemetryOperationService:
    """Create one immutable offline observation for an exact telemetry operation."""

    feature_id = "operation.telemetry-usage"
    request_kind = TELEMETRY_USAGE_REQUEST_KIND
    request_purpose = TELEMETRY_USAGE_REQUEST_PURPOSE
    max_request_bytes = TELEMETRY_USAGE_MAX_REQUEST_BYTES

    def __init__(self, *, sink: TelemetrySink) -> None:
        try:
            record = getattr(sink, "record", None)
        except Exception:
            raise TelemetryOperationError("telemetry sink is invalid") from None
        if not callable(record):
            raise TelemetryOperationError("telemetry sink is invalid")
        self._sink = sink
        self._effects = TelemetryEffects()
        self._observations: tuple[TelemetryObservation, ...] = ()

    @property
    def effects(self) -> TelemetryEffects:
        return self._effects

    @property
    def observations(self) -> tuple[TelemetryObservation, ...]:
        return self._observations

    async def execute(
        self, transaction: OperationTransaction, typed_request: object
    ) -> OperationReceipt:
        self._validate_transaction(transaction)
        request = validate_telemetry_usage_request(typed_request)
        source_id = _string(request["source_id"])
        event_name = _string(request["event_name"])
        event_count = _integer(request["event_count"])
        usage = UsageSnapshot.from_mapping(request["usage"])
        usage_values = (
            usage.aggregate_tokens,
            usage.application_tokens,
            usage.child_tokens,
            usage.controller_tokens,
            usage.cost_micros,
        )
        result_sha256 = _string(request["result_sha256"])
        self._effects = TelemetryEffects(self._effects.injected_sink_calls + 1)
        try:
            await self._sink.record(
                _observation(
                    source_id,
                    event_name,
                    event_count,
                    usage_values,
                    result_sha256,
                    "observation-recorded",
                )
            )
        except Exception:
            self._observations += (
                _observation(
                    source_id,
                    event_name,
                    event_count,
                    usage_values,
                    result_sha256,
                    "observation-failed",
                ),
            )
            return _receipt(transaction, "succeeded", "telemetry-observation-failed")
        self._observations += (
            _observation(
                source_id,
                event_name,
                event_count,
                usage_values,
                result_sha256,
                "observation-recorded",
            ),
        )
        return _receipt(transaction, "succeeded", "telemetry-observed")

    async def cancel(self, transaction: OperationTransaction) -> OperationReceipt:
        self._validate_transaction(transaction)
        return _receipt(transaction, "cancelled", "telemetry-cancelled")

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
            or context.reconciliation_attempt > MAX_SAFE_INTEGER
        ):
            raise TelemetryOperationError("telemetry reconciliation is invalid")
        del typed_request
        return _receipt(transaction, "failed", "telemetry-reconciliation-unavailable")

    @staticmethod
    def _validate_transaction(transaction: object) -> None:
        if (
            not isinstance(transaction, OperationTransaction)
            or transaction.feature_id != "operation.telemetry-usage"
            or transaction.request.request_kind != TELEMETRY_USAGE_REQUEST_KIND
            or transaction.request.purpose != TELEMETRY_USAGE_REQUEST_PURPOSE
            or transaction.request.media_type != "application/json"
            or transaction.request.byte_count > TELEMETRY_USAGE_MAX_REQUEST_BYTES
        ):
            raise TelemetryOperationError("telemetry transaction is invalid")


def _validate_observation_fields(
    source_id: object,
    event_name: object,
    event_count: object,
    usage: object,
    result_sha256: object,
    delivery_status: object,
) -> None:
    if (
        not isinstance(source_id, str)
        or source_id not in _SOURCE_TOKEN_FIELD
        or event_name != _EVENT_NAME
    ):
        raise TelemetryOperationError("telemetry source or event is invalid")
    _require_nonnegative(event_count, "telemetry event count")
    if type(usage) is not UsageSnapshot:
        raise TelemetryOperationError("telemetry usage is invalid")
    source_field = _SOURCE_TOKEN_FIELD[source_id]
    if any(
        getattr(usage, field) != 0
        for field in ("application_tokens", "child_tokens", "controller_tokens")
        if field != source_field
    ) or usage.aggregate_tokens != getattr(usage, source_field):
        raise TelemetryOperationError("telemetry source attribution is invalid")
    _require_digest(result_sha256, "telemetry result digest")
    if not isinstance(delivery_status, str) or delivery_status not in _DELIVERY_STATUSES:
        raise TelemetryOperationError("telemetry delivery status is invalid")


def _observation(
    source_id: str,
    event_name: str,
    event_count: int,
    usage_values: tuple[int, int, int, int, int],
    result_sha256: str,
    delivery_status: str,
) -> TelemetryObservation:
    return TelemetryObservation(
        source_id=source_id,
        event_name=event_name,
        event_count=event_count,
        usage=UsageSnapshot(*usage_values),
        result_sha256=result_sha256,
        delivery_status=delivery_status,
    )


def _receipt(
    transaction: OperationTransaction, status: str, reason_code: str
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
            "reason_code": reason_code,
            "receipt_ref": f"telemetry-receipt-{transaction.operation_id}",
            "reconciliation_ref": None,
            "effect_counts": {counter: 0 for counter in EFFECT_COUNTERS},
            "completed_at": transaction.requested_at,
        }
    )


def _reject_forbidden_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or key in _FORBIDDEN_KEYS:
                raise TelemetryOperationError("telemetry usage request contains a forbidden field")
            _reject_forbidden_keys(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _reject_forbidden_keys(child)


def _require_nonnegative(value: object, label: str) -> None:
    if type(value) is not int or value < 0 or value > MAX_SAFE_INTEGER:
        raise TelemetryOperationError(f"{label} is invalid")


def _require_digest(value: object, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TelemetryOperationError(f"{label} is invalid")


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise TelemetryOperationError("telemetry value is invalid")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise TelemetryOperationError("telemetry value is invalid")
    return value
