"""Typed, local settings and keybindings that remain preferences, never authority."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from asterion.control.protocol import IDENTIFIER, OPAQUE_ID
from asterion.operation.protocol import (
    EFFECT_COUNTERS,
    OperationProtocolError,
    OperationReceipt,
    OperationTransaction,
)
from asterion.operation.services import OperationReconciliationContext


SETTINGS_KEYBINDINGS_REQUEST_KIND = "operation.settings-keybindings-request"
SETTINGS_KEYBINDINGS_REQUEST_PURPOSE = "operation.settings-keybindings"
SETTINGS_KEYBINDINGS_MAX_REQUEST_BYTES = 4096

SettingsAllowlist = MappingProxyType(
    {
        "theme": ("enum", ("dark", "light", "system")),
        "telemetry.enabled": ("boolean",),
        "app.session.new": ("key-chord",),
        "app.input.clear": ("key-chord",),
        "app.interrupt": ("key-chord",),
    }
)

_SETTINGS_FIELDS = frozenset({"type", "name", "scope", "value"})
_PROJECT_FIELDS = _SETTINGS_FIELDS | {"project_id"}
_FORBIDDEN_KEY_PART = re.compile(
    r"(?:api[_-]?key|authorization|body|credential|destination|password|path|prompt|refresh[_-]?token|secret|text|token)",
    re.IGNORECASE,
)
_KEY_CHORD_MODIFIERS = ("Ctrl", "Alt", "Shift", "Meta")
_KEY_CHORD_KEY = re.compile(r"^(?:[A-Z0-9]|F(?:[1-9]|1[0-2])|Enter|Escape|Space|Tab)$")


class OperationServiceError(OperationProtocolError):
    """Raised without private preference values when a settings operation is invalid."""


@dataclass(frozen=True, repr=False)
class PreferenceRecord:
    """One private preference value with a digest-only public persistence receipt."""

    type: str
    name: str
    scope: str
    value: object
    project_id: str | None = None
    value_digest: str = ""
    revision: int = 0
    is_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _validate_record_fields(
            self.type, self.name, self.scope, self.value, self.project_id
        )
        if self.value_digest and self.value_digest != _value_digest(self.value):
            raise OperationServiceError("settings value digest is invalid")
        if type(self.revision) is not int or self.revision < 0:
            raise OperationServiceError("settings revision is invalid")

    @classmethod
    def from_request(cls, value: Mapping[str, object]) -> PreferenceRecord:
        request = validate_settings_keybindings_request(value)
        record_type = _string(request["type"])
        if record_type != "setting":
            raise OperationServiceError("settings record type is invalid")
        return cls(
            type=record_type,
            name=_string(request["name"]),
            scope=_string(request["scope"]),
            value=request["value"],
            project_id=_optional_string(request.get("project_id")),
        )

    def __repr__(self) -> str:
        return "PreferenceRecord(<redacted>)"


@dataclass(frozen=True, repr=False)
class KeybindingRecord(PreferenceRecord):
    """A private keybinding record with the same preference-only semantics."""

    @classmethod
    def from_request(cls, value: Mapping[str, object]) -> KeybindingRecord:
        request = validate_settings_keybindings_request(value)
        record_type = _string(request["type"])
        if record_type != "keybinding":
            raise OperationServiceError("keybinding record type is invalid")
        return cls(
            type=record_type,
            name=_string(request["name"]),
            scope=_string(request["scope"]),
            value=request["value"],
            project_id=_optional_string(request.get("project_id")),
        )

    def __repr__(self) -> str:
        return "KeybindingRecord(<redacted>)"


@dataclass(frozen=True, repr=False)
class PreferenceReceipt:
    """The only persistence-facing projection of a private preference write."""

    type: str
    name: str
    scope: str
    value_digest: str
    revision: int

    def __post_init__(self) -> None:
        _validate_receipt_fields(self.type, self.name, self.scope)
        _require_digest(self.value_digest, "settings value digest")
        if type(self.revision) is not int or self.revision < 1:
            raise OperationServiceError("settings receipt revision is invalid")

    def to_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "type": self.type,
                "name": self.name,
                "scope": self.scope,
                "value_digest": self.value_digest,
                "revision": self.revision,
            }
        )

    def __repr__(self) -> str:
        return "PreferenceReceipt(<redacted>)"


@dataclass(frozen=True, repr=False)
class PreferenceStoreSnapshot:
    """Read-only digest metadata for the exact record currently held by a store."""

    type: str
    name: str
    scope: str
    value_digest: str
    revision: int

    def __post_init__(self) -> None:
        _validate_receipt_fields(self.type, self.name, self.scope)
        _require_digest(self.value_digest, "settings snapshot value digest")
        if type(self.revision) is not int or self.revision < 1:
            raise OperationServiceError("settings snapshot revision is invalid")

    def __repr__(self) -> str:
        return "PreferenceStoreSnapshot(<redacted>)"


class PreferenceStore:
    """In-memory host-owned preferences with exact project-over-global lookup."""

    def __init__(self) -> None:
        self._global: dict[str, PreferenceRecord] = {}
        self._project: dict[tuple[str, str], PreferenceRecord] = {}
        self._revision = 0
        self.last_receipt: PreferenceReceipt | None = None
        self.provider_requests = 0
        self.network_operations = 0
        self.runtime_mutations = 0

    @property
    def records(self) -> tuple[PreferenceRecord, ...]:
        return tuple(
            sorted(
                (*self._global.values(), *self._project.values()),
                key=lambda record: (record.scope, record.project_id or "", record.name),
            )
        )

    def put(self, record: PreferenceRecord) -> PreferenceReceipt:
        if type(record) not in {PreferenceRecord, KeybindingRecord}:
            raise OperationServiceError("settings record is invalid")
        self._revision += 1
        persisted = replace(
            record,
            value_digest=_value_digest(record.value),
            revision=self._revision,
        )
        if persisted.scope == "global":
            self._global[persisted.name] = persisted
        else:
            assert persisted.project_id is not None
            self._project[(persisted.project_id, persisted.name)] = persisted
        receipt = PreferenceReceipt(
            type=persisted.type,
            name=persisted.name,
            scope=persisted.scope,
            value_digest=persisted.value_digest,
            revision=persisted.revision,
        )
        self.last_receipt = receipt
        return receipt

    def next_revision(self) -> int:
        """Return the deterministic revision the next successful local write will use."""

        return self._revision + 1

    def snapshot(self, record: PreferenceRecord) -> PreferenceStoreSnapshot | None:
        """Read the exact persisted record metadata without exposing its value."""

        if type(record) not in {PreferenceRecord, KeybindingRecord}:
            raise OperationServiceError("settings record is invalid")
        if record.scope == "global":
            persisted = self._global.get(record.name)
        else:
            assert record.project_id is not None
            persisted = self._project.get((record.project_id, record.name))
        if persisted is None:
            return None
        return PreferenceStoreSnapshot(
            type=persisted.type,
            name=persisted.name,
            scope=persisted.scope,
            value_digest=persisted.value_digest,
            revision=persisted.revision,
        )

    def resolve(
        self, name: str, *, project_id: str | None = None, inherit_global: bool = True
    ) -> PreferenceRecord | None:
        _require_identifier(name, "settings name")
        if project_id is not None:
            _require_opaque(project_id, "settings project")
            project = self._project.get((project_id, name))
            if project is not None:
                return project
        return self._global.get(name) if inherit_global else None


def validate_settings_keybindings_request(value: object) -> Mapping[str, object]:
    """Validate one closed private preference request without retaining a body."""

    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise OperationServiceError("settings request is invalid")
    _reject_forbidden_keys(value)
    scope = value.get("scope")
    if not isinstance(scope, str) or scope not in {"global", "project"}:
        raise OperationServiceError("settings scope is invalid")
    expected_fields = _SETTINGS_FIELDS if scope == "global" else _PROJECT_FIELDS
    if set(value) != expected_fields:
        raise OperationServiceError("settings request fields are invalid")
    record_type = value.get("type")
    name = value.get("name")
    project_id = value.get("project_id")
    _validate_record_fields(record_type, name, scope, value.get("value"), project_id)
    return MappingProxyType(dict(value))


class SettingsOperationService:
    """Bind typed preference writes to one operation transaction before storage."""

    feature_id = "operation.settings-keybindings"
    request_kind = SETTINGS_KEYBINDINGS_REQUEST_KIND
    request_purpose = SETTINGS_KEYBINDINGS_REQUEST_PURPOSE
    max_request_bytes = SETTINGS_KEYBINDINGS_MAX_REQUEST_BYTES

    def __init__(self, *, store: PreferenceStore) -> None:
        if type(store) is not PreferenceStore:
            raise OperationServiceError("settings store is invalid")
        self._store = store

    async def execute(
        self, transaction: OperationTransaction, typed_request: object
    ) -> OperationReceipt:
        self._validate_transaction(transaction)
        request = validate_settings_keybindings_request(typed_request)
        record = _record(request)
        try:
            expected_revision = self._store.next_revision()
            receipt = self._store.put(record)
            snapshot = self._store.snapshot(record)
            if not _write_matches_record(
                receipt, snapshot, record, expected_revision
            ):
                raise ValueError
        except OperationServiceError:
            raise
        except Exception:
            return _receipt(transaction, "failed", "settings-unavailable")
        return _receipt(transaction, "succeeded", "settings-succeeded")

    async def cancel(self, transaction: OperationTransaction) -> OperationReceipt:
        self._validate_transaction(transaction)
        return _receipt(transaction, "cancelled", "settings-cancelled")

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
            raise OperationServiceError("settings reconciliation is invalid")
        del typed_request
        return _receipt(transaction, "failed", "settings-reconciliation-unavailable")

    @staticmethod
    def _validate_transaction(transaction: object) -> None:
        if (
            not isinstance(transaction, OperationTransaction)
            or transaction.feature_id != "operation.settings-keybindings"
            or transaction.request.request_kind != SETTINGS_KEYBINDINGS_REQUEST_KIND
            or transaction.request.purpose != SETTINGS_KEYBINDINGS_REQUEST_PURPOSE
            or transaction.request.media_type != "application/json"
            or transaction.request.byte_count > SETTINGS_KEYBINDINGS_MAX_REQUEST_BYTES
        ):
            raise OperationServiceError("settings transaction is invalid")


def _record(request: Mapping[str, object]) -> PreferenceRecord:
    return (
        KeybindingRecord.from_request(request)
        if request["type"] == "keybinding"
        else PreferenceRecord.from_request(request)
    )


def _write_matches_record(
    receipt: object,
    snapshot: object,
    record: PreferenceRecord,
    expected_revision: object,
) -> bool:
    return (
        type(expected_revision) is int
        and expected_revision >= 1
        and type(receipt) is PreferenceReceipt
        and receipt.type == record.type
        and receipt.name == record.name
        and receipt.scope == record.scope
        and receipt.value_digest == _value_digest(record.value)
        and receipt.revision == expected_revision
        and type(snapshot) is PreferenceStoreSnapshot
        and snapshot.type == receipt.type
        and snapshot.name == receipt.name
        and snapshot.scope == receipt.scope
        and snapshot.value_digest == receipt.value_digest
        and snapshot.revision == receipt.revision
    )


def _validate_record_fields(
    record_type: object,
    name: object,
    scope: object,
    value: object,
    project_id: object,
) -> None:
    if (
        not isinstance(record_type, str)
        or record_type not in {"setting", "keybinding"}
        or not isinstance(name, str)
    ):
        raise OperationServiceError("settings record is invalid")
    _require_identifier(name, "settings name")
    allowed = SettingsAllowlist.get(name)
    if allowed is None:
        raise OperationServiceError("settings name is invalid")
    expected_type = "keybinding" if allowed[0] == "key-chord" else "setting"
    if record_type != expected_type:
        raise OperationServiceError("settings record type is invalid")
    if not isinstance(scope, str) or scope not in {"global", "project"}:
        raise OperationServiceError("settings scope is invalid")
    if scope == "project":
        _require_opaque(project_id, "settings project")
    elif project_id is not None:
        raise OperationServiceError("settings project is invalid")
    if allowed[0] == "enum":
        if (
            len(allowed) != 2
            or not isinstance(allowed[1], tuple)
            or not all(isinstance(item, str) for item in allowed[1])
            or value not in allowed[1]
        ):
            raise OperationServiceError("settings value is invalid")
    elif allowed[0] == "boolean":
        if type(value) is not bool:
            raise OperationServiceError("settings value is invalid")
    elif allowed[0] == "key-chord":
        _require_key_chord(value)
    else:
        raise OperationServiceError("settings allowlist is invalid")


def _validate_receipt_fields(record_type: object, name: object, scope: object) -> None:
    if (
        not isinstance(record_type, str)
        or record_type not in {"setting", "keybinding"}
        or not isinstance(name, str)
    ):
        raise OperationServiceError("settings receipt is invalid")
    _require_identifier(name, "settings name")
    allowed = SettingsAllowlist.get(name)
    if allowed is None or (allowed[0] == "key-chord") != (record_type == "keybinding"):
        raise OperationServiceError("settings receipt is invalid")
    if not isinstance(scope, str) or scope not in {"global", "project"}:
        raise OperationServiceError("settings receipt scope is invalid")


def _reject_forbidden_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or _FORBIDDEN_KEY_PART.search(key) is not None:
                raise OperationServiceError("settings request contains a forbidden field")
            _reject_forbidden_keys(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _reject_forbidden_keys(child)


def _require_key_chord(value: object) -> None:
    if not isinstance(value, str):
        raise OperationServiceError("keybinding value is invalid")
    pieces = value.split("+")
    if len(pieces) < 2 or len(pieces) > len(_KEY_CHORD_MODIFIERS) + 1:
        raise OperationServiceError("keybinding value is invalid")
    modifiers, key = pieces[:-1], pieces[-1]
    if (
        not all(modifier in _KEY_CHORD_MODIFIERS for modifier in modifiers)
        or tuple(modifiers)
        != tuple(sorted(set(modifiers), key=_KEY_CHORD_MODIFIERS.index))
        or _KEY_CHORD_KEY.fullmatch(key) is None
    ):
        raise OperationServiceError("keybinding value is invalid")


def _require_identifier(value: object, label: str) -> None:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise OperationServiceError(f"{label} is invalid")


def _require_opaque(value: object, label: str) -> None:
    if not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None:
        raise OperationServiceError(f"{label} is invalid")


def _require_digest(value: object, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise OperationServiceError(f"{label} is invalid")


def _value_digest(value: object) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    except (TypeError, ValueError):
        raise OperationServiceError("settings value is invalid") from None
    return hashlib.sha256(encoded).hexdigest()


def _string(value: object) -> str:
    assert isinstance(value, str)
    return value


def _optional_string(value: object) -> str | None:
    assert value is None or isinstance(value, str)
    return value


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
            "receipt_ref": f"settings-receipt-{transaction.operation_id}",
            "reconciliation_ref": None,
            "effect_counts": {counter: 0 for counter in EFFECT_COUNTERS},
            "completed_at": transaction.requested_at,
        }
    )
