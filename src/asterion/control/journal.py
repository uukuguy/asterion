"""Append-only canonical control journal and in-memory reference store."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from asterion.control.host import ControlCommand, ControlEvent
from asterion.control.protocol import (
    IDENTIFIER,
    OPAQUE_ID,
    SEMANTIC_VERSION,
    validate_control_command,
    validate_control_event,
)


JOURNAL_RECORD_KINDS = frozenset(
    {
        "system.bound",
        "authority.bound",
        "authority.revised",
        "command.accepted",
        "event.accepted",
        "action.decided",
        "action.receipted",
        "checkpoint.sealed",
        "fault.projected",
    }
)


class JournalConflictError(ValueError):
    """Raised when append, replay or idempotency invariants conflict."""


@dataclass(frozen=True)
class JournalCursor:
    position: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.position, bool)
            or not isinstance(self.position, int)
            or self.position < 0
        ):
            raise JournalConflictError("journal cursor is invalid")


@dataclass(frozen=True)
class JournalRecord:
    record_id: str
    kind: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if OPAQUE_ID.fullmatch(self.record_id) is None or self.kind not in JOURNAL_RECORD_KINDS:
            raise JournalConflictError("journal record identity is invalid")
        _validate_record_payload(self.kind, self.payload)
        object.__setattr__(self, "payload", _freeze_mapping(self.payload))

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            {
                "record_id": self.record_id,
                "kind": self.kind,
                "payload": _json_value(self.payload),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def system_bound(
        cls, *, system_id: str, system_version: str
    ) -> JournalRecord:
        return cls(
            record_id="system-bound",
            kind="system.bound",
            payload={"system_id": system_id, "system_version": system_version},
        )

    @classmethod
    def authority_bound(
        cls, *, authority_id: str, authority_revision: int
    ) -> JournalRecord:
        return cls(
            record_id="authority-bound",
            kind="authority.bound",
            payload={
                "authority_id": authority_id,
                "authority_revision": authority_revision,
            },
        )

    @classmethod
    def fault_projected(
        cls,
        *,
        fault_id: str,
        code: str,
        recoverable: bool,
        evidence_ref: str | None,
    ) -> JournalRecord:
        return cls(
            record_id=f"fault:{fault_id}",
            kind="fault.projected",
            payload={
                "fault_id": fault_id,
                "code": code,
                "recoverable": recoverable,
                "evidence_ref": evidence_ref,
            },
        )

    @classmethod
    def action_decided(
        cls,
        *,
        action_id: str,
        authority_revision: int,
        status: str,
        reason: str,
        proposal_digest: str,
    ) -> JournalRecord:
        return cls(
            record_id=f"decision:{action_id}",
            kind="action.decided",
            payload={
                "action_id": action_id,
                "authority_revision": authority_revision,
                "status": status,
                "reason": reason,
                "proposal_digest": proposal_digest,
            },
        )


@dataclass(frozen=True)
class JournalEntry:
    position: int
    digest: str
    record: JournalRecord

    def __post_init__(self) -> None:
        if (
            isinstance(self.position, bool)
            or not isinstance(self.position, int)
            or self.position < 1
            or self.digest != self.record.digest
        ):
            raise JournalConflictError("journal entry is invalid")


class CanonicalJournal(Protocol):
    @property
    def position(self) -> int:
        """Return the current append position."""

    def append(self, expected_position: int, record: JournalRecord) -> JournalEntry:
        """Compare-and-append one safe record, or replay an equal record."""

    def replay(self, cursor: JournalCursor) -> tuple[JournalEntry, ...]:
        """Return the immutable suffix strictly after the cursor."""


class MemoryCanonicalJournal:
    """In-memory reference implementation of canonical append semantics."""

    def __init__(self, session_id: str) -> None:
        if not isinstance(session_id, str) or OPAQUE_ID.fullmatch(session_id) is None:
            raise JournalConflictError("journal session identity is invalid")
        self._session_id = session_id
        self._entries: list[JournalEntry] = []
        self._by_record_id: dict[str, JournalEntry] = {}

    @property
    def position(self) -> int:
        return len(self._entries)

    def append(self, expected_position: int, record: JournalRecord) -> JournalEntry:
        if not isinstance(record, JournalRecord):
            raise JournalConflictError("journal record is invalid")
        existing = self._by_record_id.get(record.record_id)
        if existing is not None:
            if existing.digest != record.digest:
                raise JournalConflictError("journal record replay conflicts")
            return existing
        if (
            isinstance(expected_position, bool)
            or not isinstance(expected_position, int)
            or expected_position != self.position
        ):
            raise JournalConflictError("journal append position conflicts")
        self._validate_prefix(record)
        self._validate_session(record)
        entry = JournalEntry(
            position=self.position + 1,
            digest=record.digest,
            record=record,
        )
        self._entries.append(entry)
        self._by_record_id[record.record_id] = entry
        return entry

    def replay(self, cursor: JournalCursor) -> tuple[JournalEntry, ...]:
        if not isinstance(cursor, JournalCursor) or cursor.position > self.position:
            raise JournalConflictError("journal replay cursor conflicts")
        return tuple(self._entries[cursor.position :])

    def accept_command(
        self, command: ControlCommand, *, expected_position: int | None = None
    ) -> JournalEntry:
        if not isinstance(command, ControlCommand):
            raise JournalConflictError("journal command is invalid")
        return self.append(
            self.position if expected_position is None else expected_position,
            JournalRecord(
                record_id=f"command:{command.command_id}",
                kind="command.accepted",
                payload={"command": command.to_mapping()},
            ),
        )

    def accept_event(
        self, event: ControlEvent, *, expected_position: int | None = None
    ) -> JournalEntry:
        if not isinstance(event, ControlEvent):
            raise JournalConflictError("journal event is invalid")
        return self.append(
            self.position if expected_position is None else expected_position,
            JournalRecord(
                record_id=f"event:{event.event_id}",
                kind="event.accepted",
                payload={"event": event.to_mapping()},
            ),
        )

    def _validate_prefix(self, record: JournalRecord) -> None:
        if self.position == 0 and record.kind != "system.bound":
            raise JournalConflictError("journal system binding is missing")
        if self.position == 1 and record.kind != "authority.bound":
            raise JournalConflictError("journal authority binding is missing")
        if self.position >= 2 and record.kind in {"system.bound", "authority.bound"}:
            raise JournalConflictError("journal binding record is duplicated")

    def _validate_session(self, record: JournalRecord) -> None:
        field = {
            "command.accepted": "command",
            "event.accepted": "event",
        }.get(record.kind)
        if field is None:
            return
        value = record.payload[field]
        if not isinstance(value, Mapping) or value.get("session_id") != self._session_id:
            raise JournalConflictError("journal record session identity mismatches")


def _validate_record_payload(kind: str, value: object) -> None:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise JournalConflictError("journal record payload is invalid")
    if kind == "system.bound":
        _require_fields(value, {"system_id", "system_version"})
        _require_identifier(value["system_id"], "journal system identity")
        _require_version(value["system_version"], "journal system version")
        return
    if kind in {"authority.bound", "authority.revised"}:
        _require_fields(value, {"authority_id", "authority_revision"})
        _require_opaque_id(value["authority_id"], "journal authority identity")
        _require_positive_integer(
            value["authority_revision"], "journal authority revision"
        )
        return
    if kind == "command.accepted":
        _require_fields(value, {"command"})
        validate_control_command(value["command"])
        return
    if kind == "event.accepted":
        _require_fields(value, {"event"})
        validate_control_event(value["event"])
        return
    if kind == "action.decided":
        _require_fields(
            value,
            {
                "action_id",
                "authority_revision",
                "status",
                "reason",
                "proposal_digest",
            },
        )
        _require_opaque_id(value["action_id"], "journal action identity")
        _require_positive_integer(
            value["authority_revision"], "journal action authority revision"
        )
        if value["status"] not in {"admitted", "rejected"}:
            raise JournalConflictError("journal action decision status is invalid")
        _require_identifier(value["reason"], "journal action decision reason")
        _require_digest(value["proposal_digest"], "journal proposal digest")
        return
    if kind == "action.receipted":
        _require_fields(value, {"action_id", "receipt_ref", "usage"})
        _require_opaque_id(value["action_id"], "journal receipt action")
        _require_opaque_id(value["receipt_ref"], "journal receipt reference")
        _validate_usage(value["usage"])
        return
    if kind == "checkpoint.sealed":
        _require_fields(value, {"checkpoint_event"})
        event = validate_control_event(value["checkpoint_event"])
        if event["type"] != "checkpoint.created":
            raise JournalConflictError("journal checkpoint event is invalid")
        return
    if kind == "fault.projected":
        _require_fields(
            value, {"fault_id", "code", "recoverable", "evidence_ref"}
        )
        _require_opaque_id(value["fault_id"], "journal fault identity")
        _require_identifier(value["code"], "journal fault code")
        if not isinstance(value["recoverable"], bool):
            raise JournalConflictError("journal fault recovery flag is invalid")
        if value["evidence_ref"] is not None:
            _require_opaque_id(value["evidence_ref"], "journal fault evidence")
        return
    raise JournalConflictError("journal record kind is invalid")


def _validate_usage(value: object) -> None:
    if not isinstance(value, Mapping):
        raise JournalConflictError("journal receipt usage is invalid")
    fields = {
        "controller_tokens",
        "application_tokens",
        "child_tokens",
        "aggregate_tokens",
        "cost_micros",
    }
    _require_fields(value, fields)
    for field in fields:
        item = value[field]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise JournalConflictError("journal receipt usage is invalid")


def _require_fields(value: Mapping[str, object], fields: set[str]) -> None:
    if set(value) != fields:
        raise JournalConflictError("journal record payload fields are invalid")


def _require_identifier(value: object, label: str) -> None:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise JournalConflictError(f"{label} is invalid")


def _require_version(value: object, label: str) -> None:
    if not isinstance(value, str) or SEMANTIC_VERSION.fullmatch(value) is None:
        raise JournalConflictError(f"{label} is invalid")


def _require_opaque_id(value: object, label: str) -> None:
    if not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None:
        raise JournalConflictError(f"{label} is invalid")


def _require_positive_integer(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JournalConflictError(f"{label} is invalid")


def _require_digest(value: object, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise JournalConflictError(f"{label} is invalid")


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze(item) for key, item in value.items()})


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value
