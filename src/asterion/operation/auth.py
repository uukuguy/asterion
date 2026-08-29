"""Private, injected auth storage with body-free public operation receipts."""

from __future__ import annotations

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


AUTH_REQUEST_KIND = "operation.auth-request"
AUTH_REQUEST_PURPOSE = "operation.auth"
AUTH_MAX_REQUEST_BYTES = 4096
_ACTIONS = frozenset({"auth.status", "auth.store", "auth.clear", "auth.refresh"})
_ACTION_FIELDS = {
    "auth.status": frozenset({"action"}),
    "auth.store": frozenset({"action", "credential_ref", "subject_digest", "precedence"}),
    "auth.clear": frozenset({"action", "credential_ref"}),
    "auth.refresh": frozenset({"action", "refresh_ref", "subject_digest", "precedence"}),
}
_CANDIDATE_KINDS = frozenset({"runtime", "environment", "prime_cli", "stored", "fallback"})
_FORBIDDEN_KEYS = frozenset({
    "api_key", "authorization", "body", "credential", "destination", "path",
    "prompt", "refresh_token", "text", "token",
})
_PRIME_PRECEDENCE = {"runtime": 1, "environment": 2, "prime_cli": 3, "stored": 4, "fallback": 5}
_OTHER_PRECEDENCE = {"runtime": 1, "stored": 2, "environment": 3, "fallback": 4}


class AuthOperationError(OperationProtocolError):
    """Raised without credential values when private auth input is invalid."""


@dataclass(frozen=True, repr=False)
class AuthStatus:
    """Body-free metadata for one injected candidate; it never carries a value."""

    provider_id: str
    candidate_kind: str
    stale: bool
    precedence: int
    subject_digest: str
    value_digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider_id, str)
            or IDENTIFIER.fullmatch(self.provider_id) is None
            or self.candidate_kind not in _CANDIDATE_KINDS
            or type(self.stale) is not bool
            or type(self.precedence) is not int
            or self.precedence < 1
            or self.precedence > 5
        ):
            raise AuthOperationError("auth status is invalid")
        _require_digest(self.subject_digest, "auth status subject")
        _require_digest(self.value_digest, "auth status value")

    def __repr__(self) -> str:
        return "AuthStatus(<redacted>)"


class AuthStorageBackend(Protocol):
    """Operator-injected opaque storage; it is the only storage effect boundary."""

    def put(self, credential_ref: str, *, subject_digest: str, precedence: int) -> str: ...
    def status(self) -> tuple[AuthStatus, ...]: ...
    def clear(self, credential_ref: str) -> None: ...


class OAuthRefresher(Protocol):
    """Injected test-double boundary; production auth transport is deliberately absent."""

    async def refresh(self, refresh_ref: str) -> str: ...


def validate_auth_request(value: object) -> Mapping[str, object]:
    """Validate one closed, private auth document without retaining its body."""

    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise AuthOperationError("auth request is invalid")
    _reject_forbidden_keys(value)
    action = value.get("action")
    if not isinstance(action, str) or action not in _ACTIONS or set(value) != _ACTION_FIELDS[action]:
        raise AuthOperationError("auth request fields are invalid")
    if action in {"auth.store", "auth.clear"}:
        _require_opaque(value.get("credential_ref"), "auth credential reference")
    if action == "auth.refresh":
        _require_opaque(value.get("refresh_ref"), "auth refresh reference")
    if action in {"auth.store", "auth.refresh"}:
        _require_digest(value.get("subject_digest"), "auth subject")
        precedence = value.get("precedence")
        if type(precedence) is not int or precedence < 1 or precedence > 5:
            raise AuthOperationError("auth precedence is invalid")
    return MappingProxyType(dict(value))


class AuthOperationService:
    """OperationService binding that validates before every injected mutation."""

    feature_id = "operation.auth"
    request_kind = AUTH_REQUEST_KIND
    request_purpose = AUTH_REQUEST_PURPOSE
    max_request_bytes = AUTH_MAX_REQUEST_BYTES

    def __init__(self, *, storage: AuthStorageBackend, refresher: OAuthRefresher | None = None) -> None:
        self._storage = storage
        self._refresher = refresher
        self._last_status: tuple[AuthStatus, ...] = ()

    def status(self) -> tuple[AuthStatus, ...]:
        """Return deterministic, stale-filtered injected metadata without discovery."""

        try:
            statuses = self._storage.status()
            if not isinstance(statuses, tuple) or not all(isinstance(item, AuthStatus) for item in statuses):
                raise ValueError
            selected: list[AuthStatus] = []
            by_provider: dict[str, list[AuthStatus]] = {}
            for item in statuses:
                expected = _precedence(item.provider_id, item.candidate_kind)
                if item.precedence != expected:
                    raise ValueError
                by_provider.setdefault(item.provider_id, []).append(item)
            for provider_id in sorted(by_provider):
                candidates = by_provider[provider_id]
                if len({candidate.precedence for candidate in candidates}) != len(candidates):
                    raise ValueError
                ordered = sorted(candidates, key=lambda candidate: (candidate.precedence, candidate.candidate_kind, candidate.subject_digest, candidate.value_digest))
                fresh = next((candidate for candidate in ordered if not candidate.stale), None)
                if fresh is not None:
                    selected.append(fresh)
            self._last_status = tuple(selected)
            return self._last_status
        except AuthOperationError:
            raise
        except Exception:
            raise AuthOperationError("auth status is unavailable") from None

    async def execute(self, transaction: OperationTransaction, typed_request: object) -> OperationReceipt:
        self._validate_transaction(transaction)
        request = validate_auth_request(typed_request)
        action = request["action"]
        try:
            if action == "auth.status":
                self.status()
            elif action == "auth.store":
                self._put(request["credential_ref"], request["subject_digest"], request["precedence"])
            elif action == "auth.clear":
                self._storage.clear(_opaque(request["credential_ref"]))
            else:
                if self._refresher is None:
                    raise AuthOperationError("auth refresh is unavailable")
                credential_ref = await self._refresher.refresh(_opaque(request["refresh_ref"]))
                _require_opaque(credential_ref, "auth refreshed reference")
                self._put(credential_ref, request["subject_digest"], request["precedence"])
            return _receipt(transaction, "succeeded", "auth-succeeded")
        except AuthOperationError:
            raise
        except Exception:
            raise AuthOperationError("auth operation is unavailable") from None

    async def cancel(self, transaction: OperationTransaction) -> OperationReceipt:
        self._validate_transaction(transaction)
        return _receipt(transaction, "cancelled", "auth-cancelled")

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
            raise AuthOperationError("auth reconciliation is invalid")
        del typed_request
        return _receipt(transaction, "failed", "auth-reconciliation-unavailable")

    def _put(self, credential_ref: object, subject_digest: object, precedence: object) -> None:
        value_digest = self._storage.put(
            _opaque(credential_ref), subject_digest=_digest(subject_digest), precedence=_precedence_value(precedence)
        )
        _require_digest(value_digest, "auth stored value")

    @staticmethod
    def _validate_transaction(transaction: object) -> None:
        if (
            not isinstance(transaction, OperationTransaction)
            or transaction.feature_id != "operation.auth"
            or transaction.request.request_kind != AUTH_REQUEST_KIND
            or transaction.request.purpose != AUTH_REQUEST_PURPOSE
            or transaction.request.media_type != "application/json"
            or transaction.request.byte_count > AUTH_MAX_REQUEST_BYTES
        ):
            raise AuthOperationError("auth transaction is invalid")


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
            "receipt_ref": f"auth-receipt-{transaction.operation_id}",
            "reconciliation_ref": None,
            "effect_counts": {counter: 0 for counter in EFFECT_COUNTERS},
            "completed_at": transaction.requested_at,
        }
    )


def _precedence(provider_id: str, candidate_kind: str) -> int:
    table = _PRIME_PRECEDENCE if provider_id == "prime-inference" else _OTHER_PRECEDENCE
    try:
        return table[candidate_kind]
    except KeyError:
        raise AuthOperationError("auth candidate kind is invalid") from None


def _reject_forbidden_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or key in _FORBIDDEN_KEYS:
                raise AuthOperationError("auth request contains a forbidden field")
            _reject_forbidden_keys(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _reject_forbidden_keys(child)


def _require_opaque(value: object, label: str) -> None:
    if not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None:
        raise AuthOperationError(f"{label} is invalid")


def _require_digest(value: object, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise AuthOperationError(f"{label} is invalid")


def _opaque(value: object) -> str:
    _require_opaque(value, "auth reference")
    assert isinstance(value, str)
    return value


def _digest(value: object) -> str:
    _require_digest(value, "auth digest")
    assert isinstance(value, str)
    return value


def _precedence_value(value: object) -> int:
    if type(value) is not int or value < 1 or value > 5:
        raise AuthOperationError("auth precedence is invalid")
    return value
