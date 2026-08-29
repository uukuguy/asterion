"""Append-only canonical control journal and in-memory reference store."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

import fcntl

from asterion.control.authority import OperationDecision, SessionContextDecision

if TYPE_CHECKING:
    from asterion.operation.protocol import OperationReceipt, OperationTransaction
from asterion.control.host import ControlCommand, ControlEvent
from asterion.control.protocol import (
    IDENTIFIER,
    MEDIA_TYPE,
    OPAQUE_ID,
    SEMANTIC_VERSION,
    validate_control_command,
    validate_control_event,
)
from asterion.control.session_context import (
    SESSION_CONTEXT_OPERATIONS,
    SessionContextCommand,
    SessionContextReceipt,
    validate_session_context_command,
    validate_session_context_receipt,
)
from asterion.protocol_ordering import is_sorted_unique_scalar_strings


JOURNAL_RECORD_KINDS = frozenset(
    {
        "system.bound",
        "authority.bound",
        "authority.revised",
        "command.accepted",
        "event.accepted",
        "client.intent.accepted",
        "client.observation.accepted",
        "client.event.accepted",
        "client.export.receipted",
        "client.share.receipted",
        "action.decided",
        "action.running",
        "action.receipted",
        "context.command.accepted",
        "context.operation.decided",
        "context.operation.receipted",
        "operation.transaction.accepted",
        "operation.admitted",
        "operation.reserved",
        "operation.dispatch.started",
        "operation.handoff.prepared",
        "operation.handoff.entered",
        "operation.handoff.fenced",
        "operation.receipted",
        "operation.reconciliation.recorded",
        "checkpoint.sealed",
        "fault.projected",
        "harness.proposed",
        "harness.effect-started",
        "harness.effect-terminal",
        "harness.snapshot-activated",
        "harness.effect-uncertain",
        "long-running.registered",
        "long-running.intent",
        "long-running.receipted",
        "long-running.controller-retained",
        "long-running.controller-attached",
        "long-running.controller-evicted",
        "long-running.task-started",
        "long-running.closed",
    }
)
JOURNAL_FILE_VERSION = "asterion.control-journal/v1"
_FILE_ROW_FIELDS = frozenset(
    {"version", "position", "previous_digest", "record_digest", "record"}
)
_RECORD_FIELDS = frozenset({"record_id", "kind", "payload"})
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


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


@dataclass(frozen=True, repr=False)
class JournalRecord:
    record_id: str
    kind: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if (
            OPAQUE_ID.fullmatch(self.record_id) is None
            or self.kind not in JOURNAL_RECORD_KINDS
        ):
            raise JournalConflictError("journal record identity is invalid")
        try:
            _validate_record_payload(self.kind, self.payload)
        except JournalConflictError:
            raise
        except (TypeError, ValueError):
            raise JournalConflictError("journal record payload is invalid") from None
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

    def __repr__(self) -> str:
        return (
            "JournalRecord("
            f"record_id={self.record_id!r}, kind={self.kind!r}, "
            f"digest={self.digest!r})"
        )

    @classmethod
    def system_bound(cls, *, system_id: str, system_version: str) -> JournalRecord:
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
    def authority_revised(
        cls, *, authority_id: str, authority_revision: int
    ) -> JournalRecord:
        return cls(
            record_id=f"authority-revision:{authority_revision}",
            kind="authority.revised",
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
    def client_intent_accepted(cls, intent: object) -> JournalRecord:
        from asterion.client.protocol import validate_client_intent

        accepted = validate_client_intent(intent)
        return cls(
            record_id=f"client-intent:{accepted.intent_id}",
            kind="client.intent.accepted",
            payload={"intent": accepted.to_mapping()},
        )

    @classmethod
    def client_observation_accepted(
        cls, observation: Mapping[str, object]
    ) -> JournalRecord:
        try:
            accepted = _canonical_client_observation(observation)
        except (TypeError, ValueError):
            raise JournalConflictError(
                "journal client observation is invalid"
            ) from None
        return cls(
            record_id=f"client-observation:{accepted['observation_id']}",
            kind="client.observation.accepted",
            payload={"observation": accepted},
        )

    @classmethod
    def client_event_accepted(cls, event: object) -> JournalRecord:
        from asterion.client.protocol import validate_client_event

        accepted = validate_client_event(event)
        return cls(
            record_id=f"client-event:{accepted.event_id}",
            kind="client.event.accepted",
            payload={"event": accepted.to_mapping()},
        )

    @classmethod
    def client_export_receipted(
        cls,
        *,
        client_id: str,
        session_id: str,
        generation: int,
        artifact: object,
        visibility: str,
    ) -> JournalRecord:
        values = _client_artifact_receipt_values(artifact)
        return cls(
            record_id=f"client-export:{values['artifact_id']}",
            kind="client.export.receipted",
            payload={
                "artifact_id": values["artifact_id"],
                "client_id": client_id,
                "generation": generation,
                "media_type": values["media_type"],
                "sha256": values["sha256"],
                "size": values["size"],
                "storage_ref": values["storage_ref"],
                "session_id": session_id,
                "visibility": visibility,
            },
        )

    @classmethod
    def client_share_receipted(
        cls,
        *,
        client_id: str,
        session_id: str,
        generation: int,
        artifact: object,
        share: object,
    ) -> JournalRecord:
        artifact_values = _client_artifact_receipt_values(artifact)
        share_values = _client_share_receipt_values(share)
        return cls(
            record_id=f"client-share:{share_values['share_id']}",
            kind="client.share.receipted",
            payload={
                "artifact_id": artifact_values["artifact_id"],
                "client_id": client_id,
                "generation": generation,
                "media_type": artifact_values["media_type"],
                "session_id": session_id,
                "sha256": artifact_values["sha256"],
                "share_id": share_values["share_id"],
                "share_ref": share_values["share_ref"],
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

    @classmethod
    def action_receipted(
        cls,
        *,
        action_id: str,
        receipt_ref: str,
        usage: object,
        artifact_ids: tuple[str, ...] = (),
        media_types: tuple[str, ...] = (),
    ) -> JournalRecord:
        return cls(
            record_id=f"receipt:{action_id}",
            kind="action.receipted",
            payload={
                "action_id": action_id,
                "artifact_ids": artifact_ids,
                "media_types": media_types,
                "receipt_ref": receipt_ref,
                "usage": _public_usage(usage),
            },
        )

    @classmethod
    def action_running(cls, *, action_id: str, proposal_digest: str) -> JournalRecord:
        return cls(
            record_id=f"running:{action_id}",
            kind="action.running",
            payload={
                "action_id": action_id,
                "proposal_digest": proposal_digest,
            },
        )

    @classmethod
    def context_operation_decided(
        cls,
        decision: SessionContextDecision,
    ) -> JournalRecord:
        if not isinstance(decision, SessionContextDecision):
            raise JournalConflictError("journal context decision is invalid")
        return cls(
            record_id=f"context-decision:{decision.command_id}",
            kind="context.operation.decided",
            payload={
                "command_id": decision.command_id,
                "idempotency_key": decision.idempotency_key,
                "authority_revision": decision.authority_revision,
                "operation": decision.operation,
                "command_digest": decision.command_digest,
                "status": decision.status,
                "reason": decision.reason,
            },
        )

    @classmethod
    def context_operation_receipted(
        cls,
        receipt: SessionContextReceipt,
        *,
        usage: object | None,
    ) -> JournalRecord:
        if not isinstance(receipt, SessionContextReceipt):
            raise JournalConflictError("journal context receipt is invalid")
        return cls(
            record_id=f"context-receipt:{receipt.command_id}",
            kind="context.operation.receipted",
            payload={
                "receipt": receipt.to_mapping(),
                "usage": None if usage is None else _public_usage(usage),
            },
        )

    @classmethod
    def operation_transaction_accepted(
        cls, transaction: OperationTransaction
    ) -> JournalRecord:
        from asterion.operation.protocol import OperationTransaction

        if not isinstance(transaction, OperationTransaction):
            raise JournalConflictError("journal operation transaction is invalid")
        return cls(
            record_id=f"operation-transaction:{transaction.operation_id}",
            kind="operation.transaction.accepted",
            payload={"transaction": transaction.to_mapping()},
        )

    @classmethod
    def operation_admitted(cls, decision: OperationDecision) -> JournalRecord:
        return cls(
            record_id=f"operation-decision:{decision.operation_id}",
            kind="operation.admitted",
            payload={
                "operation_id": decision.operation_id,
                "authority_id": decision.authority_id,
                "authority_revision": decision.authority_revision,
                "transaction_digest": decision.transaction_digest,
                "feature_id": decision.feature_id,
                "status": decision.status,
                "reason": decision.reason,
            },
        )

    @classmethod
    def operation_reserved(cls, decision: OperationDecision) -> JournalRecord:
        return cls(
            record_id=f"operation-reservation:{decision.operation_id}",
            kind="operation.reserved",
            payload={
                "operation_id": decision.operation_id,
                "transaction_digest": decision.transaction_digest,
            },
        )

    @classmethod
    def operation_dispatch_started(
        cls, transaction: OperationTransaction
    ) -> JournalRecord:
        from asterion.operation.protocol import OperationTransaction

        if not isinstance(transaction, OperationTransaction):
            raise JournalConflictError("journal operation transaction is invalid")
        return cls(
            record_id=f"operation-dispatch:{transaction.operation_id}",
            kind="operation.dispatch.started",
            payload={
                "operation_id": transaction.operation_id,
                "transaction_digest": _operation_digest(transaction),
            },
        )

    @classmethod
    def operation_handoff_fenced(
        cls, transaction: OperationTransaction
    ) -> JournalRecord:
        from asterion.operation.protocol import OperationTransaction

        if not isinstance(transaction, OperationTransaction):
            raise JournalConflictError("journal operation transaction is invalid")
        return cls(
            record_id=f"operation-handoff:{transaction.operation_id}",
            kind="operation.handoff.fenced",
            payload={
                "operation_id": transaction.operation_id,
                "transaction_digest": _operation_digest(transaction),
            },
        )

    @classmethod
    def operation_handoff_prepared(
        cls, transaction: OperationTransaction, *, handoff_proof_digest: str
    ) -> JournalRecord:
        return cls._operation_handoff_proof_record(
            transaction,
            kind="operation.handoff.prepared",
            record_id_prefix="operation-handoff-prepared",
            handoff_proof_digest=handoff_proof_digest,
        )

    @classmethod
    def operation_handoff_entered(
        cls, transaction: OperationTransaction, *, handoff_proof_digest: str
    ) -> JournalRecord:
        return cls._operation_handoff_proof_record(
            transaction,
            kind="operation.handoff.entered",
            record_id_prefix="operation-handoff-entered",
            handoff_proof_digest=handoff_proof_digest,
        )

    @classmethod
    def _operation_handoff_proof_record(
        cls,
        transaction: OperationTransaction,
        *,
        kind: str,
        record_id_prefix: str,
        handoff_proof_digest: str,
    ) -> JournalRecord:
        from asterion.operation.protocol import OperationTransaction

        if not isinstance(transaction, OperationTransaction):
            raise JournalConflictError("journal operation transaction is invalid")
        _require_digest(handoff_proof_digest, "journal handoff proof digest")
        return cls(
            record_id=f"{record_id_prefix}:{transaction.operation_id}",
            kind=kind,
            payload={
                "operation_id": transaction.operation_id,
                "transaction_digest": _operation_digest(transaction),
                "handoff_proof_digest": handoff_proof_digest,
            },
        )

    @classmethod
    def operation_receipted(cls, receipt: OperationReceipt) -> JournalRecord:
        from asterion.operation.protocol import OperationReceipt

        if not isinstance(receipt, OperationReceipt):
            raise JournalConflictError("journal operation receipt is invalid")
        return cls(
            record_id=f"operation-receipt:{receipt.operation_id}:{receipt.status}",
            kind="operation.receipted",
            payload={"receipt": receipt.to_mapping()},
        )

    @classmethod
    def operation_reconciliation_recorded(
        cls, *, operation_id: str, attempt: int
    ) -> JournalRecord:
        return cls(
            record_id=f"operation-reconcile:{operation_id}:{attempt}",
            kind="operation.reconciliation.recorded",
            payload={"operation_id": operation_id, "attempt": attempt},
        )

    @classmethod
    def checkpoint_sealed(cls, *, checkpoint_event: ControlEvent) -> JournalRecord:
        if not isinstance(checkpoint_event, ControlEvent):
            raise JournalConflictError("journal checkpoint event is invalid")
        checkpoint_id = checkpoint_event.payload.get("checkpoint_id")
        return cls(
            record_id=f"checkpoint:{checkpoint_id}",
            kind="checkpoint.sealed",
            payload={"checkpoint_event": checkpoint_event.to_mapping()},
        )

    @classmethod
    def harness_proposed(
        cls,
        *,
        scope: Mapping[str, object],
        proposal_id: str,
        proposal_digest: str,
        authority_id: str,
        authority_revision: int,
        baseline_snapshot_id: str,
        revision_id: str,
        sequence: int,
        edit_count: int,
        evidence_count: int,
        rollback_revision_id: str | None,
    ) -> JournalRecord:
        return cls(
            record_id=f"harness-proposed:{proposal_id}",
            kind="harness.proposed",
            payload={
                "authority_id": authority_id,
                "authority_revision": authority_revision,
                "baseline_snapshot_id": baseline_snapshot_id,
                "edit_count": edit_count,
                "evidence_count": evidence_count,
                "proposal_digest": proposal_digest,
                "proposal_id": proposal_id,
                "revision_id": revision_id,
                "rollback_revision_id": rollback_revision_id,
                "scope": scope,
                "sequence": sequence,
            },
        )

    @classmethod
    def harness_effect_started(
        cls,
        *,
        scope: Mapping[str, object],
        proposal_id: str,
        proposal_digest: str,
        revision_id: str,
        sequence: int,
        effect_digest: str,
    ) -> JournalRecord:
        return cls(
            record_id=f"harness-started:{revision_id}",
            kind="harness.effect-started",
            payload={
                "effect_digest": effect_digest,
                "proposal_digest": proposal_digest,
                "proposal_id": proposal_id,
                "revision_id": revision_id,
                "scope": scope,
                "sequence": sequence,
            },
        )

    @classmethod
    def harness_effect_terminal(
        cls,
        *,
        scope: Mapping[str, object],
        proposal_id: str,
        proposal_digest: str,
        revision_id: str,
        sequence: int,
        effect_digest: str,
        status: str,
        result_snapshot_id: str,
        entries: tuple[Mapping[str, object], ...],
        usage: Mapping[str, int],
    ) -> JournalRecord:
        return cls(
            record_id=f"harness-terminal:{revision_id}",
            kind="harness.effect-terminal",
            payload={
                "effect_digest": effect_digest,
                "entries": entries,
                "proposal_digest": proposal_digest,
                "proposal_id": proposal_id,
                "result_snapshot_id": result_snapshot_id,
                "revision_id": revision_id,
                "scope": scope,
                "sequence": sequence,
                "status": status,
                "usage": usage,
            },
        )

    @classmethod
    def harness_snapshot_activated(
        cls,
        *,
        scope: Mapping[str, object],
        revision_id: str,
        sequence: int,
        snapshot_id: str,
    ) -> JournalRecord:
        return cls(
            record_id=f"harness-activated:{revision_id}",
            kind="harness.snapshot-activated",
            payload={
                "revision_id": revision_id,
                "scope": scope,
                "sequence": sequence,
                "snapshot_id": snapshot_id,
            },
        )

    @classmethod
    def harness_effect_uncertain(
        cls,
        *,
        scope: Mapping[str, object],
        proposal_id: str,
        proposal_digest: str,
        revision_id: str,
        sequence: int,
        effect_digest: str,
    ) -> JournalRecord:
        return cls(
            record_id=f"harness-uncertain:{revision_id}",
            kind="harness.effect-uncertain",
            payload={
                "effect_digest": effect_digest,
                "proposal_digest": proposal_digest,
                "proposal_id": proposal_id,
                "revision_id": revision_id,
                "scope": scope,
                "sequence": sequence,
                "status": "uncertain",
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
        ...

    def append(self, expected_position: int, record: JournalRecord) -> JournalEntry:
        """Compare-and-append one safe record, or replay an equal record."""
        ...

    def replay(self, cursor: JournalCursor) -> tuple[JournalEntry, ...]:
        """Return the immutable suffix strictly after the cursor."""
        ...

    def accept_command(
        self, command: ControlCommand, *, expected_position: int | None = None
    ) -> JournalEntry:
        """Append one validated command record."""
        ...

    def accept_event(
        self, event: ControlEvent, *, expected_position: int | None = None
    ) -> JournalEntry:
        """Append one validated event record."""
        ...

    def accept_client_intent(
        self, intent: object, *, expected_position: int | None = None
    ) -> JournalEntry:
        """Append one body-free client intent before dispatch."""
        ...

    def accept_client_observation(
        self, observation: Mapping[str, object], *, expected_position: int | None = None
    ) -> JournalEntry:
        """Append one body-free provider observation before projection."""
        ...

    def accept_client_event(
        self, event: object, *, expected_position: int | None = None
    ) -> JournalEntry:
        """Append one body-free projected client event."""
        ...

    def accept_session_context_command(
        self,
        command: SessionContextCommand,
        *,
        expected_position: int | None = None,
    ) -> JournalEntry:
        """Append one validated session-context command record."""
        ...


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

    def accept_client_intent(
        self, intent: object, *, expected_position: int | None = None
    ) -> JournalEntry:
        position = self.position if expected_position is None else expected_position
        return self.append(position, JournalRecord.client_intent_accepted(intent))

    def accept_client_observation(
        self, observation: Mapping[str, object], *, expected_position: int | None = None
    ) -> JournalEntry:
        position = self.position if expected_position is None else expected_position
        return self.append(
            position, JournalRecord.client_observation_accepted(observation)
        )

    def accept_client_event(
        self, event: object, *, expected_position: int | None = None
    ) -> JournalEntry:
        position = self.position if expected_position is None else expected_position
        return self.append(position, JournalRecord.client_event_accepted(event))

    def accept_session_context_command(
        self,
        command: SessionContextCommand,
        *,
        expected_position: int | None = None,
    ) -> JournalEntry:
        if not isinstance(command, SessionContextCommand):
            raise JournalConflictError("journal context command is invalid")
        return self.append(
            self.position if expected_position is None else expected_position,
            JournalRecord(
                record_id=f"context-command:{command.command_id}",
                kind="context.command.accepted",
                payload={"command": command.to_mapping()},
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
            "client.intent.accepted": "intent",
            "client.observation.accepted": "observation",
            "client.event.accepted": "event",
            "context.command.accepted": "command",
            "context.operation.receipted": "receipt",
        }.get(record.kind)
        if field is None:
            return
        value = record.payload[field]
        if (
            not isinstance(value, Mapping)
            or value.get("session_id") != self._session_id
        ):
            raise JournalConflictError("journal record session identity mismatches")


class FileCanonicalJournal:
    """Descriptor-relative, hash-chained canonical JSONL journal."""

    def __init__(
        self, root: Path, session_id: str, filename: str, *, root_fd: int | None = None
    ) -> None:
        self._root = root
        self._parent = root.parent
        self._session_id = session_id
        self._filename = filename
        self._root_fd = root_fd
        self._closed = False
        self._entries: tuple[JournalEntry, ...] = ()
        self._by_record_id: dict[str, JournalEntry] = {}
        self._parent_identity: tuple[int, int] | None = None
        self._root_identity: tuple[int, int] | None = None
        self._file_identity: tuple[int, int] | None = None
        self._file_stamp: tuple[int, int, int] | None = None
        self._initialized = False

    @classmethod
    def open(
        cls, root: os.PathLike[str] | str, session_id: str
    ) -> FileCanonicalJournal:
        try:
            if (
                not isinstance(session_id, str)
                or OPAQUE_ID.fullmatch(session_id) is None
                or not isinstance(root, (str, os.PathLike))
            ):
                raise JournalConflictError("file journal construction is invalid")
            native_root = Path(root)
            if ".." in native_root.parts:
                raise JournalConflictError("file journal construction is invalid")
            native_root = Path(os.path.abspath(native_root))
            filename = f"journal-{hashlib.sha256(session_id.encode('utf-8')).hexdigest()}.jsonl"
            journal = cls(native_root, session_id, filename)
            journal._refresh(exclusive=False, create=True)
            return journal
        except JournalConflictError:
            raise
        except (OSError, TypeError, ValueError, UnicodeError):
            raise JournalConflictError("file journal cannot be opened safely") from None

    @classmethod
    def open_at(
        cls, root_fd: int, root: os.PathLike[str] | str, session_id: str
    ) -> FileCanonicalJournal:
        try:
            if (
                isinstance(root_fd, bool)
                or not isinstance(root_fd, int)
                or not isinstance(session_id, str)
                or OPAQUE_ID.fullmatch(session_id) is None
                or not isinstance(root, (str, os.PathLike))
            ):
                raise JournalConflictError("file journal construction is invalid")
            native_root = Path(os.path.abspath(Path(root)))
            if ".." in native_root.parts:
                raise JournalConflictError("file journal construction is invalid")
            owned_root_fd = os.dup(root_fd)
            try:
                _validate_private_directory_fd(owned_root_fd, require_mode=True)
                filename = (
                    "journal-"
                    f"{hashlib.sha256(session_id.encode('utf-8')).hexdigest()}.jsonl"
                )
                journal = cls(
                    native_root,
                    session_id,
                    filename,
                    root_fd=owned_root_fd,
                )
                owned_root_fd = -1
                journal._refresh(exclusive=False, create=True)
                return journal
            finally:
                if owned_root_fd >= 0:
                    os.close(owned_root_fd)
        except JournalConflictError:
            raise
        except (OSError, TypeError, ValueError, UnicodeError):
            raise JournalConflictError("file journal cannot be opened safely") from None

    @property
    def position(self) -> int:
        self._refresh(exclusive=False, create=False)
        return len(self._entries)

    def close(self) -> None:
        self._closed = True
        root_fd = self._root_fd
        self._root_fd = None
        if root_fd is not None:
            try:
                os.close(root_fd)
            except OSError:
                pass

    def append(self, expected_position: int, record: JournalRecord) -> JournalEntry:
        if not isinstance(record, JournalRecord):
            raise JournalConflictError("journal record is invalid")
        try:
            parent_fd, root_fd, file_fd = self._open_descriptors(create=False)
            try:
                fcntl.flock(file_fd, fcntl.LOCK_EX)
                self._confirm_instance_bindings(parent_fd, root_fd, file_fd)
                entries = _read_file_entries(file_fd, self._session_id)
                self._install(entries, os.fstat(file_fd))
                existing = self._by_record_id.get(record.record_id)
                if existing is not None:
                    if existing.digest != record.digest:
                        raise JournalConflictError("journal record replay conflicts")
                    os.fsync(file_fd)
                    self._confirm_instance_bindings(parent_fd, root_fd, file_fd)
                    self._file_stamp = _file_stamp(os.fstat(file_fd))
                    return existing
                if (
                    isinstance(expected_position, bool)
                    or not isinstance(expected_position, int)
                    or expected_position != len(entries)
                ):
                    raise JournalConflictError("journal append position conflicts")
                _validate_prefix(len(entries), record)
                _validate_session(self._session_id, record)
                entry = JournalEntry(
                    position=len(entries) + 1,
                    digest=record.digest,
                    record=record,
                )
                previous = entries[-1].digest if entries else None
                encoded = _encode_file_row(entry, previous)
                with os.fdopen(os.dup(file_fd), "ab", buffering=0) as stream:
                    offset = 0
                    while offset < len(encoded):
                        written = stream.write(encoded[offset:])
                        if written is None or written < 1:
                            raise OSError("journal write made no progress")
                        offset += written
                    stream.flush()
                    os.fsync(stream.fileno())
                self._confirm_instance_bindings(parent_fd, root_fd, file_fd)
                _verify_file_binding(root_fd, self._filename, file_fd)
                self._install((*entries, entry), os.fstat(file_fd))
                return self._by_record_id[record.record_id]
            finally:
                os.close(file_fd)
                os.close(root_fd)
                if parent_fd is not None:
                    os.close(parent_fd)
        except JournalConflictError:
            raise
        except (OSError, TypeError, ValueError, UnicodeError):
            raise JournalConflictError("file journal append failed safely") from None

    def replay(self, cursor: JournalCursor) -> tuple[JournalEntry, ...]:
        if not isinstance(cursor, JournalCursor):
            raise JournalConflictError("journal replay cursor conflicts")
        self._refresh(exclusive=False, create=False)
        if cursor.position > len(self._entries):
            raise JournalConflictError("journal replay cursor conflicts")
        return self._entries[cursor.position :]

    def accept_command(
        self, command: ControlCommand, *, expected_position: int | None = None
    ) -> JournalEntry:
        if not isinstance(command, ControlCommand):
            raise JournalConflictError("journal command is invalid")
        position = self.position if expected_position is None else expected_position
        return self.append(
            position,
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
        position = self.position if expected_position is None else expected_position
        return self.append(
            position,
            JournalRecord(
                record_id=f"event:{event.event_id}",
                kind="event.accepted",
                payload={"event": event.to_mapping()},
            ),
        )

    def accept_client_intent(
        self, intent: object, *, expected_position: int | None = None
    ) -> JournalEntry:
        position = self.position if expected_position is None else expected_position
        return self.append(position, JournalRecord.client_intent_accepted(intent))

    def accept_client_observation(
        self, observation: Mapping[str, object], *, expected_position: int | None = None
    ) -> JournalEntry:
        position = self.position if expected_position is None else expected_position
        return self.append(
            position, JournalRecord.client_observation_accepted(observation)
        )

    def accept_client_event(
        self, event: object, *, expected_position: int | None = None
    ) -> JournalEntry:
        position = self.position if expected_position is None else expected_position
        return self.append(position, JournalRecord.client_event_accepted(event))

    def accept_session_context_command(
        self,
        command: SessionContextCommand,
        *,
        expected_position: int | None = None,
    ) -> JournalEntry:
        if not isinstance(command, SessionContextCommand):
            raise JournalConflictError("journal context command is invalid")
        position = self.position if expected_position is None else expected_position
        return self.append(
            position,
            JournalRecord(
                record_id=f"context-command:{command.command_id}",
                kind="context.command.accepted",
                payload={"command": command.to_mapping()},
            ),
        )

    def _refresh(self, *, exclusive: bool, create: bool) -> None:
        try:
            parent_fd, root_fd, file_fd = self._open_descriptors(create=create)
            try:
                fcntl.flock(file_fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
                self._confirm_instance_bindings(parent_fd, root_fd, file_fd)
                self._install(
                    _read_file_entries(file_fd, self._session_id),
                    os.fstat(file_fd),
                )
                if create:
                    os.fsync(file_fd)
                    os.fsync(root_fd)
                    if parent_fd is not None:
                        os.fsync(parent_fd)
                    self._confirm_instance_bindings(parent_fd, root_fd, file_fd)
                    self._file_stamp = _file_stamp(os.fstat(file_fd))
            finally:
                os.close(file_fd)
                os.close(root_fd)
                if parent_fd is not None:
                    os.close(parent_fd)
        except JournalConflictError:
            raise
        except (OSError, TypeError, ValueError, UnicodeError):
            raise JournalConflictError("file journal cannot be read safely") from None

    def _open_descriptors(self, *, create: bool) -> tuple[int | None, int, int]:
        if self._closed:
            raise JournalConflictError("file journal is closed")
        if self._root_fd is not None:
            root_fd = os.dup(self._root_fd)
            try:
                _validate_private_directory_fd(root_fd, require_mode=True)
                file_fd, _ = _open_private_file(root_fd, self._filename, create=create)
                return None, root_fd, file_fd
            except BaseException:
                os.close(root_fd)
                raise
        parent_fd = _open_private_parent(self._parent)
        try:
            root_fd = _open_private_root(
                parent_fd,
                self._root.name,
                self._root,
                create=create,
            )
        except BaseException:
            os.close(parent_fd)
            raise
        try:
            file_fd, _ = _open_private_file(root_fd, self._filename, create=create)
        except BaseException:
            os.close(root_fd)
            os.close(parent_fd)
            raise
        return parent_fd, root_fd, file_fd

    def _confirm_instance_bindings(
        self, parent_fd: int | None, root_fd: int, file_fd: int
    ) -> None:
        _validate_private_directory_fd(root_fd, require_mode=True)
        if parent_fd is not None:
            _verify_parent_binding(self._parent, parent_fd)
            _verify_root_binding_at(parent_fd, self._root.name, root_fd)
            _verify_root_binding(self._root, root_fd)
        _verify_file_binding(root_fd, self._filename, file_fd)
        identities = (
            None if parent_fd is None else _identity(os.fstat(parent_fd)),
            _identity(os.fstat(root_fd)),
            _identity(os.fstat(file_fd)),
        )
        pinned = (
            self._parent_identity,
            self._root_identity,
            self._file_identity,
        )
        if not self._initialized:
            (
                self._parent_identity,
                self._root_identity,
                self._file_identity,
            ) = identities
        elif identities != pinned:
            raise JournalConflictError("file journal instance binding changed")

    def _install(
        self, entries: tuple[JournalEntry, ...], details: os.stat_result
    ) -> None:
        stamp = _file_stamp(details)
        if self._initialized:
            if (
                len(entries) < len(self._entries)
                or entries[: len(self._entries)] != self._entries
                or (entries == self._entries and stamp != self._file_stamp)
            ):
                raise JournalConflictError("file journal instance prefix changed")
            if entries == self._entries:
                return
            entries = self._entries + entries[len(self._entries) :]
        self._entries = entries
        self._by_record_id = {entry.record.record_id: entry for entry in entries}
        self._file_stamp = stamp
        self._initialized = True


def _open_private_parent(parent: Path) -> int:
    before = os.lstat(parent)
    descriptor = os.open(parent, os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC)
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(before.st_mode)
            or not stat.S_ISDIR(details.st_mode)
            or _identity(before) != _identity(details)
            or details.st_uid != os.getuid()
        ):
            raise JournalConflictError("file journal parent is unsafe")
        _verify_parent_binding(parent, descriptor)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _validate_private_directory_fd(
    descriptor: int, *, require_mode: bool
) -> os.stat_result:
    details = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or (require_mode and stat.S_IMODE(details.st_mode) != 0o700)
    ):
        raise JournalConflictError("file journal root is unsafe")
    return details


def _open_private_root(
    parent_fd: int,
    root_name: str,
    root: Path,
    *,
    create: bool,
) -> int:
    if create:
        try:
            os.mkdir(root_name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
    before = os.stat(root_name, dir_fd=parent_fd, follow_symlinks=False)
    descriptor = os.open(
        root_name,
        os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
        dir_fd=parent_fd,
    )
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(before.st_mode)
            or not stat.S_ISDIR(details.st_mode)
            or _identity(before) != _identity(details)
            or stat.S_IMODE(details.st_mode) != 0o700
            or details.st_uid != os.getuid()
        ):
            raise JournalConflictError("file journal root is unsafe")
        _verify_root_binding_at(parent_fd, root_name, descriptor)
        _verify_root_binding(root, descriptor)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_private_file(
    root_fd: int, filename: str, *, create: bool
) -> tuple[int, bool]:
    flags = os.O_RDWR | os.O_APPEND | _NOFOLLOW | _CLOEXEC
    created = False
    try:
        descriptor = os.open(filename, flags, dir_fd=root_fd)
    except FileNotFoundError:
        if not create:
            raise
        try:
            descriptor = os.open(
                filename,
                flags | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=root_fd,
            )
            created = True
        except FileExistsError:
            descriptor = os.open(filename, flags, dir_fd=root_fd)
    try:
        if created:
            os.fchmod(descriptor, 0o600)
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.getuid()
            or details.st_nlink != 1
        ):
            raise JournalConflictError("file journal artifact is unsafe")
        _verify_file_binding(root_fd, filename, descriptor)
        return descriptor, created
    except BaseException:
        os.close(descriptor)
        raise


def _read_file_entries(file_fd: int, session_id: str) -> tuple[JournalEntry, ...]:
    details_before = os.fstat(file_fd)
    if (
        not stat.S_ISREG(details_before.st_mode)
        or stat.S_IMODE(details_before.st_mode) != 0o600
        or details_before.st_uid != os.getuid()
        or details_before.st_nlink != 1
    ):
        raise JournalConflictError("file journal artifact is unsafe")
    with os.fdopen(os.dup(file_fd), "rb", buffering=0) as stream:
        stream.seek(0)
        raw = stream.read()
    details_after = os.fstat(file_fd)
    if _identity(details_before) != _identity(details_after) or _file_stamp(
        details_before
    ) != _file_stamp(details_after):
        raise JournalConflictError("file journal changed while reading")
    if raw and not raw.endswith(b"\n"):
        raise JournalConflictError("file journal is truncated")
    entries: list[JournalEntry] = []
    record_ids: set[str] = set()
    previous_digest: str | None = None
    raw_lines = raw[:-1].split(b"\n") if raw else ()
    for expected_position, raw_line in enumerate(raw_lines, start=1):
        try:
            text = raw_line.decode("utf-8", errors="strict")
            value = json.loads(text)
            if (
                not isinstance(value, dict)
                or set(value) != _FILE_ROW_FIELDS
                or json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
                != raw_line
                or value["version"] != JOURNAL_FILE_VERSION
                or value["position"] != expected_position
                or value["previous_digest"] != previous_digest
                or not isinstance(value["record"], dict)
                or set(value["record"]) != _RECORD_FIELDS
            ):
                raise JournalConflictError("file journal row is invalid")
            record_value = value["record"]
            record = JournalRecord(
                record_id=record_value["record_id"],
                kind=record_value["kind"],
                payload=record_value["payload"],
            )
            if value["record_digest"] != record.digest:
                raise JournalConflictError("file journal digest is invalid")
            if record.record_id in record_ids:
                raise JournalConflictError("file journal record identity is duplicated")
            _validate_prefix(len(entries), record)
            _validate_session(session_id, record)
            entry = JournalEntry(
                position=expected_position,
                digest=record.digest,
                record=record,
            )
        except JournalConflictError:
            raise
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
            raise JournalConflictError("file journal row is invalid") from None
        entries.append(entry)
        record_ids.add(record.record_id)
        previous_digest = entry.digest
    return tuple(entries)


def _identity(details: os.stat_result) -> tuple[int, int]:
    return details.st_dev, details.st_ino


def _file_stamp(details: os.stat_result) -> tuple[int, int, int]:
    return details.st_size, details.st_mtime_ns, details.st_ctime_ns


def _verify_parent_binding(parent: Path, parent_fd: int) -> None:
    path_details = os.lstat(parent)
    descriptor_details = os.fstat(parent_fd)
    if (
        not stat.S_ISDIR(path_details.st_mode)
        or _identity(path_details) != _identity(descriptor_details)
        or descriptor_details.st_uid != os.getuid()
    ):
        raise JournalConflictError("file journal parent binding changed")


def _verify_root_binding_at(parent_fd: int, root_name: str, root_fd: int) -> None:
    path_details = os.stat(root_name, dir_fd=parent_fd, follow_symlinks=False)
    descriptor_details = os.fstat(root_fd)
    if (
        not stat.S_ISDIR(path_details.st_mode)
        or _identity(path_details) != _identity(descriptor_details)
        or stat.S_IMODE(path_details.st_mode) != 0o700
    ):
        raise JournalConflictError("file journal root binding changed")


def _verify_root_binding(root: Path, root_fd: int) -> None:
    path_details = os.lstat(root)
    descriptor_details = os.fstat(root_fd)
    if (
        not stat.S_ISDIR(path_details.st_mode)
        or _identity(path_details) != _identity(descriptor_details)
        or stat.S_IMODE(path_details.st_mode) != 0o700
    ):
        raise JournalConflictError("file journal root binding changed")


def _verify_file_binding(root_fd: int, filename: str, file_fd: int) -> None:
    path_details = os.stat(filename, dir_fd=root_fd, follow_symlinks=False)
    descriptor_details = os.fstat(file_fd)
    if (
        not stat.S_ISREG(path_details.st_mode)
        or _identity(path_details) != _identity(descriptor_details)
        or stat.S_IMODE(path_details.st_mode) != 0o600
        or path_details.st_nlink != 1
    ):
        raise JournalConflictError("file journal artifact binding changed")


def _encode_file_row(entry: JournalEntry, previous_digest: str | None) -> bytes:
    value = {
        "version": JOURNAL_FILE_VERSION,
        "position": entry.position,
        "previous_digest": previous_digest,
        "record_digest": entry.digest,
        "record": {
            "record_id": entry.record.record_id,
            "kind": entry.record.kind,
            "payload": _json_value(entry.record.payload),
        },
    }
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )


def _validate_prefix(position: int, record: JournalRecord) -> None:
    if position == 0 and record.kind != "system.bound":
        raise JournalConflictError("journal system binding is missing")
    if position == 1 and record.kind != "authority.bound":
        raise JournalConflictError("journal authority binding is missing")
    if position >= 2 and record.kind in {"system.bound", "authority.bound"}:
        raise JournalConflictError("journal binding record is duplicated")


def _validate_session(session_id: str, record: JournalRecord) -> None:
    field = {
        "command.accepted": "command",
        "event.accepted": "event",
        "client.intent.accepted": "intent",
        "client.observation.accepted": "observation",
        "client.event.accepted": "event",
        "checkpoint.sealed": "checkpoint_event",
        "context.command.accepted": "command",
        "context.operation.receipted": "receipt",
    }.get(record.kind)
    if record.kind in {"client.export.receipted", "client.share.receipted"}:
        if record.payload.get("session_id") != session_id:
            raise JournalConflictError("journal record session identity mismatches")
        return
    if field is None:
        return
    value = record.payload[field]
    if not isinstance(value, Mapping) or value.get("session_id") != session_id:
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
    if kind == "client.intent.accepted":
        _require_fields(value, {"intent"})
        from asterion.client.protocol import validate_client_intent

        validate_client_intent(value["intent"])
        return
    if kind == "client.observation.accepted":
        _require_fields(value, {"observation"})
        _validate_client_observation(value["observation"])
        return
    if kind == "client.event.accepted":
        _require_fields(value, {"event"})
        from asterion.client.protocol import validate_client_event

        validate_client_event(value["event"])
        return
    if kind == "client.export.receipted":
        _require_fields(
            value,
            {
                "artifact_id",
                "client_id",
                "generation",
                "media_type",
                "session_id",
                "sha256",
                "size",
                "storage_ref",
                "visibility",
            },
        )
        _require_opaque_id(value["artifact_id"], "journal client export artifact")
        _require_opaque_id(value["client_id"], "journal client export client")
        _require_opaque_id(value["session_id"], "journal client export session")
        _require_safe_positive_integer(
            value["generation"], "journal client export generation"
        )
        _require_one_media_type(value["media_type"], "journal client export media type")
        _require_digest(value["sha256"], "journal client export digest")
        _require_safe_nonnegative_integer(value["size"], "journal client export size")
        _require_opaque_id(value["storage_ref"], "journal client export storage")
        if value["visibility"] not in {"private", "public"}:
            raise JournalConflictError("journal client export visibility is invalid")
        return
    if kind == "client.share.receipted":
        _require_fields(
            value,
            {
                "artifact_id",
                "client_id",
                "generation",
                "media_type",
                "session_id",
                "sha256",
                "share_id",
                "share_ref",
            },
        )
        for field in (
            "artifact_id",
            "client_id",
            "session_id",
            "share_id",
            "share_ref",
        ):
            _require_opaque_id(value[field], f"journal client share {field}")
        _require_safe_positive_integer(
            value["generation"], "journal client share generation"
        )
        _require_one_media_type(value["media_type"], "journal client share media type")
        _require_digest(value["sha256"], "journal client share digest")
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
        if set(value) == {"action_id", "receipt_ref", "usage"}:
            value = {
                **value,
                "artifact_ids": (),
                "media_types": (),
            }
        _require_fields(
            value,
            {"action_id", "artifact_ids", "media_types", "receipt_ref", "usage"},
        )
        _require_opaque_id(value["action_id"], "journal receipt action")
        _require_opaque_id(value["receipt_ref"], "journal receipt reference")
        _require_opaque_ids(value["artifact_ids"], "journal receipt artifacts")
        _require_media_types(value["media_types"], "journal receipt media types")
        _validate_usage(value["usage"])
        return
    if kind == "action.running":
        _require_fields(value, {"action_id", "proposal_digest"})
        _require_opaque_id(value["action_id"], "journal running action")
        _require_digest(value["proposal_digest"], "journal running proposal digest")
        return
    if kind == "context.command.accepted":
        _require_fields(value, {"command"})
        validate_session_context_command(value["command"])
        return
    if kind == "operation.transaction.accepted":
        from asterion.operation.protocol import OperationTransaction

        _require_fields(value, {"transaction"})
        if not isinstance(value["transaction"], Mapping):
            raise JournalConflictError("journal operation transaction is invalid")
        OperationTransaction.from_mapping(value["transaction"])
        return
    if kind == "operation.admitted":
        _require_fields(
            value,
            {
                "operation_id",
                "authority_id",
                "authority_revision",
                "transaction_digest",
                "feature_id",
                "status",
                "reason",
            },
        )
        OperationDecision(**value)  # type: ignore[arg-type]
        return
    if kind == "operation.reserved":
        _require_fields(value, {"operation_id", "transaction_digest"})
        _require_opaque_id(value["operation_id"], "journal operation identity")
        _require_digest(value["transaction_digest"], "journal operation digest")
        return
    if kind == "operation.dispatch.started":
        _require_fields(value, {"operation_id", "transaction_digest"})
        _require_opaque_id(value["operation_id"], "journal operation identity")
        _require_digest(value["transaction_digest"], "journal operation digest")
        return
    if kind == "operation.handoff.fenced":
        _require_fields(value, {"operation_id", "transaction_digest"})
        _require_opaque_id(value["operation_id"], "journal operation identity")
        _require_digest(value["transaction_digest"], "journal operation digest")
        return
    if kind in {"operation.handoff.prepared", "operation.handoff.entered"}:
        _require_fields(
            value,
            {"operation_id", "transaction_digest", "handoff_proof_digest"},
        )
        _require_opaque_id(value["operation_id"], "journal operation identity")
        _require_digest(value["transaction_digest"], "journal operation digest")
        _require_digest(value["handoff_proof_digest"], "journal handoff proof digest")
        return
    if kind == "operation.receipted":
        from asterion.operation.protocol import OperationReceipt

        _require_fields(value, {"receipt"})
        if not isinstance(value["receipt"], Mapping):
            raise JournalConflictError("journal operation receipt is invalid")
        OperationReceipt.from_mapping(value["receipt"])
        return
    if kind == "operation.reconciliation.recorded":
        _require_fields(value, {"operation_id", "attempt"})
        _require_opaque_id(value["operation_id"], "journal operation identity")
        _require_positive_integer(value["attempt"], "journal reconciliation attempt")
        return
    if kind == "context.operation.decided":
        _require_fields(
            value,
            {
                "command_id",
                "idempotency_key",
                "authority_revision",
                "operation",
                "command_digest",
                "status",
                "reason",
            },
        )
        _require_opaque_id(value["command_id"], "journal context command")
        _require_opaque_id(value["idempotency_key"], "journal context idempotency key")
        _require_positive_integer(
            value["authority_revision"], "journal context authority revision"
        )
        if value["operation"] not in SESSION_CONTEXT_OPERATIONS:
            raise JournalConflictError("journal context operation is invalid")
        _require_digest(value["command_digest"], "journal context command digest")
        if value["status"] not in {"admitted", "rejected"}:
            raise JournalConflictError("journal context decision status is invalid")
        _require_identifier(value["reason"], "journal context decision reason")
        return
    if kind == "context.operation.receipted":
        _require_fields(value, {"receipt", "usage"})
        receipt = validate_session_context_receipt(value["receipt"])
        if receipt["status"] == "uncertain":
            if value["usage"] is not None:
                raise JournalConflictError("journal context receipt usage is invalid")
        else:
            _validate_usage(value["usage"])
        return
    if kind == "checkpoint.sealed":
        _require_fields(value, {"checkpoint_event"})
        event = validate_control_event(value["checkpoint_event"])
        if event["type"] != "checkpoint.created":
            raise JournalConflictError("journal checkpoint event is invalid")
        return
    if kind == "fault.projected":
        _require_fields(value, {"fault_id", "code", "recoverable", "evidence_ref"})
        _require_opaque_id(value["fault_id"], "journal fault identity")
        _require_identifier(value["code"], "journal fault code")
        if not isinstance(value["recoverable"], bool):
            raise JournalConflictError("journal fault recovery flag is invalid")
        if value["evidence_ref"] is not None:
            _require_opaque_id(value["evidence_ref"], "journal fault evidence")
        return
    if kind == "harness.proposed":
        _require_fields(
            value,
            {
                "authority_id",
                "authority_revision",
                "baseline_snapshot_id",
                "edit_count",
                "evidence_count",
                "proposal_digest",
                "proposal_id",
                "revision_id",
                "rollback_revision_id",
                "scope",
                "sequence",
            },
        )
        _validate_harness_scope(value["scope"])
        _require_opaque_id(value["proposal_id"], "journal harness proposal")
        _require_digest(value["proposal_digest"], "journal harness proposal digest")
        _require_opaque_id(value["authority_id"], "journal harness authority")
        _require_positive_integer(
            value["authority_revision"], "journal harness authority revision"
        )
        _require_opaque_id(
            value["baseline_snapshot_id"], "journal harness baseline snapshot"
        )
        _require_opaque_id(value["revision_id"], "journal harness revision")
        _require_positive_integer(value["sequence"], "journal harness sequence")
        _require_positive_integer(value["edit_count"], "journal harness edit count")
        _require_positive_integer(
            value["evidence_count"], "journal harness evidence count"
        )
        if value["rollback_revision_id"] is not None:
            _require_opaque_id(
                value["rollback_revision_id"], "journal harness rollback revision"
            )
        return
    if kind == "harness.effect-started":
        _require_fields(
            value,
            {
                "effect_digest",
                "proposal_digest",
                "proposal_id",
                "revision_id",
                "scope",
                "sequence",
            },
        )
        _validate_harness_effect_identity(value)
        return
    if kind == "harness.effect-terminal":
        _require_fields(
            value,
            {
                "effect_digest",
                "entries",
                "proposal_digest",
                "proposal_id",
                "result_snapshot_id",
                "revision_id",
                "scope",
                "sequence",
                "status",
                "usage",
            },
        )
        _validate_harness_effect_identity(value)
        if value["status"] not in {"succeeded", "failed", "cancelled"}:
            raise JournalConflictError("journal harness terminal status is invalid")
        _require_opaque_id(
            value["result_snapshot_id"], "journal harness result snapshot"
        )
        _validate_harness_entries(value["entries"])
        _validate_harness_usage(value["usage"])
        return
    if kind == "harness.snapshot-activated":
        _require_fields(value, {"revision_id", "scope", "sequence", "snapshot_id"})
        _validate_harness_scope(value["scope"])
        _require_opaque_id(value["revision_id"], "journal harness revision")
        _require_positive_integer(value["sequence"], "journal harness sequence")
        _require_opaque_id(value["snapshot_id"], "journal harness snapshot")
        return
    if kind == "harness.effect-uncertain":
        _require_fields(
            value,
            {
                "effect_digest",
                "proposal_digest",
                "proposal_id",
                "revision_id",
                "scope",
                "sequence",
                "status",
            },
        )
        _validate_harness_effect_identity(value)
        if value["status"] != "uncertain":
            raise JournalConflictError("journal harness uncertain status is invalid")
        return
    if kind == "long-running.registered":
        _require_fields(value, {"registered_at_ms", "spec"})
        _require_nonnegative_integer(
            value["registered_at_ms"], "journal long-running registration time"
        )
        _validate_long_running_spec(value["spec"])
        return
    if kind == "long-running.intent":
        _require_fields(
            value,
            {"due_at_ms", "effect_id", "source_id", "source_kind"},
        )
        _require_nonnegative_integer(
            value["due_at_ms"], "journal long-running due time"
        )
        _require_opaque_id(value["effect_id"], "journal long-running effect")
        _require_opaque_id(value["source_id"], "journal long-running source")
        if value["source_kind"] not in {"heartbeat", "schedule"}:
            raise JournalConflictError("journal long-running source kind is invalid")
        return
    if kind == "long-running.receipted":
        _require_fields(
            value,
            {
                "due_at_ms",
                "effect_id",
                "source_id",
                "source_kind",
                "status",
            },
        )
        _require_nonnegative_integer(
            value["due_at_ms"], "journal long-running receipt time"
        )
        _require_opaque_id(value["effect_id"], "journal long-running receipt effect")
        _require_opaque_id(value["source_id"], "journal long-running receipt source")
        if value["source_kind"] not in {"heartbeat", "schedule"}:
            raise JournalConflictError("journal long-running source kind is invalid")
        if value["status"] not in {
            "succeeded",
            "failed",
            "cancelled",
            "uncertain",
        }:
            raise JournalConflictError("journal long-running receipt status is invalid")
        return
    if kind == "long-running.controller-retained":
        _require_fields(
            value,
            {"controller_id", "acquired_at_ms", "expires_at_ms"},
        )
        _require_opaque_id(value["controller_id"], "journal resident controller")
        _require_nonnegative_integer(
            value["acquired_at_ms"], "journal resident acquisition time"
        )
        _require_nonnegative_integer(
            value["expires_at_ms"], "journal resident expiry time"
        )
        if value["expires_at_ms"] <= value["acquired_at_ms"]:
            raise JournalConflictError("journal resident lease is invalid")
        return
    if kind == "long-running.controller-attached":
        _require_fields(value, {"controller_id", "attached_at_ms"})
        _require_opaque_id(value["controller_id"], "journal attached controller")
        _require_nonnegative_integer(
            value["attached_at_ms"], "journal controller attach time"
        )
        return
    if kind == "long-running.controller-evicted":
        _require_fields(value, {"controller_id", "evicted_at_ms"})
        _require_opaque_id(value["controller_id"], "journal evicted controller")
        _require_nonnegative_integer(
            value["evicted_at_ms"], "journal controller eviction time"
        )
        return
    if kind == "long-running.task-started":
        _require_fields(value, {"task_id", "started_at_ms", "expires_at_ms"})
        _require_opaque_id(value["task_id"], "journal resident task")
        _require_nonnegative_integer(
            value["started_at_ms"], "journal task start time"
        )
        _require_nonnegative_integer(
            value["expires_at_ms"], "journal task expiry time"
        )
        if value["expires_at_ms"] <= value["started_at_ms"]:
            raise JournalConflictError("journal task authority is invalid")
        return
    if kind == "long-running.closed":
        _require_fields(value, {"closed_at_ms"})
        _require_nonnegative_integer(
            value["closed_at_ms"], "journal long-running close time"
        )
        return
    raise JournalConflictError("journal record kind is invalid")


def _operation_digest(transaction: OperationTransaction) -> str:
    encoded = json.dumps(
        _json_value(transaction.to_mapping()),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_client_observation(value: object) -> None:
    _canonical_client_observation(value)


def _canonical_client_observation(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JournalConflictError("journal client observation is invalid")
    _require_fields(
        value,
        {
            "observation_id",
            "session_id",
            "generation",
            "source_sequence",
            "emitted_at",
            "kind",
            "payload",
        },
    )
    from asterion.client.protocol import ClientEvent

    event = ClientEvent(
        protocol="asterion.agent-client/v1",
        event_id=value["observation_id"],  # type: ignore[arg-type]
        session_id=value["session_id"],  # type: ignore[arg-type]
        generation=value["generation"],  # type: ignore[arg-type]
        sequence=value["source_sequence"],  # type: ignore[arg-type]
        emitted_at=value["emitted_at"],  # type: ignore[arg-type]
        type=value["kind"],  # type: ignore[arg-type]
        payload=value["payload"],  # type: ignore[arg-type]
    )
    return MappingProxyType(
        {
            "observation_id": event.event_id,
            "session_id": event.session_id,
            "generation": event.generation,
            "source_sequence": event.sequence,
            "emitted_at": event.emitted_at,
            "kind": event.type,
            "payload": event.payload,
        }
    )


def _client_artifact_receipt_values(value: object) -> Mapping[str, object]:
    try:
        values = {
            "artifact_id": getattr(value, "artifact_id"),
            "sha256": getattr(value, "sha256"),
            "media_type": getattr(value, "media_type"),
            "size": getattr(value, "size"),
            "storage_ref": getattr(value, "storage_ref"),
        }
        _require_opaque_id(values["artifact_id"], "journal client artifact")
        _require_digest(values["sha256"], "journal client artifact digest")
        if (
            not isinstance(values["media_type"], str)
            or MEDIA_TYPE.fullmatch(values["media_type"]) is None
        ):
            raise JournalConflictError("journal client artifact media type is invalid")
        _require_safe_nonnegative_integer(
            values["size"], "journal client artifact size"
        )
        _require_opaque_id(values["storage_ref"], "journal client artifact storage")
        return MappingProxyType(values)
    except (AttributeError, TypeError, ValueError):
        raise JournalConflictError(
            "journal client artifact receipt is invalid"
        ) from None


def _client_share_receipt_values(value: object) -> Mapping[str, object]:
    try:
        values = {
            "share_id": getattr(value, "share_id"),
            "artifact_id": getattr(value, "artifact_id"),
            "sha256": getattr(value, "sha256"),
            "media_type": getattr(value, "media_type"),
            "share_ref": getattr(value, "share_ref"),
        }
        _require_opaque_id(values["share_id"], "journal client share")
        _require_opaque_id(values["artifact_id"], "journal client share artifact")
        _require_digest(values["sha256"], "journal client share digest")
        if (
            not isinstance(values["media_type"], str)
            or MEDIA_TYPE.fullmatch(values["media_type"]) is None
        ):
            raise JournalConflictError("journal client share media type is invalid")
        _require_opaque_id(values["share_ref"], "journal client share reference")
        return MappingProxyType(values)
    except (AttributeError, TypeError, ValueError):
        raise JournalConflictError("journal client share receipt is invalid") from None


def _validate_harness_effect_identity(value: Mapping[str, object]) -> None:
    _validate_harness_scope(value["scope"])
    _require_opaque_id(value["proposal_id"], "journal harness proposal")
    _require_digest(value["proposal_digest"], "journal harness proposal digest")
    _require_opaque_id(value["revision_id"], "journal harness revision")
    _require_positive_integer(value["sequence"], "journal harness sequence")
    _require_digest(value["effect_digest"], "journal harness effect digest")


def _validate_harness_scope(value: object) -> None:
    if not isinstance(value, Mapping):
        raise JournalConflictError("journal harness scope is invalid")
    _require_fields(value, {"kind", "scope_id"})
    if value["kind"] in {"session", "project"}:
        _require_opaque_id(value["scope_id"], "journal harness scope")
    elif value["kind"] == "global":
        if value["scope_id"] is not None:
            raise JournalConflictError("journal harness scope is invalid")
    else:
        raise JournalConflictError("journal harness scope is invalid")


def _validate_harness_entries(value: object) -> None:
    if not isinstance(value, (list, tuple)):
        raise JournalConflictError("journal harness entries are invalid")
    entry_ids: list[str] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            raise JournalConflictError("journal harness entries are invalid")
        _require_fields(
            entry,
            {
                "body_digest",
                "entry_id",
                "grouping_path_digest",
                "kind",
                "metadata_digest",
                "title_digest",
                "version",
            },
        )
        _require_opaque_id(entry["entry_id"], "journal harness entry")
        if entry["kind"] not in {"prompt", "memory", "skill", "subagent"}:
            raise JournalConflictError("journal harness entry kind is invalid")
        for field in ("title_digest", "body_digest", "metadata_digest"):
            _require_digest(entry[field], "journal harness entry digest")
        if entry["grouping_path_digest"] is not None:
            _require_digest(
                entry["grouping_path_digest"], "journal harness grouping digest"
            )
        _require_positive_integer(entry["version"], "journal harness entry version")
        entry_ids.append(str(entry["entry_id"]))
    if entry_ids != sorted(set(entry_ids)):
        raise JournalConflictError("journal harness entries are invalid")


def _validate_harness_usage(value: object) -> None:
    if not isinstance(value, Mapping):
        raise JournalConflictError("journal harness usage is invalid")
    _require_fields(
        value,
        {
            "aggregate_tokens",
            "cost_micros",
            "model_credential_reads",
            "provider_operations",
        },
    )
    for item in value.values():
        _require_nonnegative_integer(item, "journal harness usage")


def _validate_long_running_spec(value: object) -> None:
    if not isinstance(value, Mapping):
        raise JournalConflictError("journal long-running specification is invalid")
    spec_type = value.get("spec_type")
    if spec_type == "heartbeat":
        _require_fields(
            value,
            {"interval_ms", "owner_id", "owner_kind", "source_id", "spec_type"},
        )
        _require_opaque_id(value["source_id"], "journal heartbeat identity")
        _require_positive_integer(value["interval_ms"], "journal heartbeat interval")
        if value["owner_kind"] == "user":
            if value["owner_id"] is not None:
                raise JournalConflictError("journal heartbeat owner is invalid")
        elif value["owner_kind"] == "agent":
            _require_opaque_id(value["owner_id"], "journal heartbeat owner")
        else:
            raise JournalConflictError("journal heartbeat owner is invalid")
        return
    if spec_type == "schedule":
        _require_fields(
            value,
            {
                "cron_expression",
                "due_at_ms",
                "schedule_kind",
                "source_id",
                "spec_type",
            },
        )
        _require_opaque_id(value["source_id"], "journal schedule identity")
        if value["schedule_kind"] == "once":
            _require_nonnegative_integer(
                value["due_at_ms"], "journal schedule due time"
            )
            if value["cron_expression"] is not None:
                raise JournalConflictError("journal schedule expression is invalid")
        elif value["schedule_kind"] == "cron":
            if value["due_at_ms"] is not None or not isinstance(
                value["cron_expression"], str
            ):
                raise JournalConflictError("journal schedule expression is invalid")
        else:
            raise JournalConflictError("journal schedule kind is invalid")
        return
    raise JournalConflictError("journal long-running specification is invalid")


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


def _public_usage(value: object) -> Mapping[str, object]:
    fields = (
        "controller_tokens",
        "application_tokens",
        "child_tokens",
        "aggregate_tokens",
        "cost_micros",
    )
    if isinstance(value, Mapping):
        if set(value) != set(fields):
            raise JournalConflictError("journal receipt usage is invalid")
        result = {field: value[field] for field in fields}
    else:
        try:
            result = {field: getattr(value, field) for field in fields}
        except AttributeError:
            raise JournalConflictError("journal receipt usage is invalid") from None
    _validate_usage(result)
    return result


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


def _require_opaque_ids(value: object, label: str) -> None:
    if (
        not isinstance(value, (list, tuple))
        or any(not isinstance(item, str) for item in value)
        or not is_sorted_unique_scalar_strings(list(value))
        or any(OPAQUE_ID.fullmatch(item) is None for item in value)
    ):
        raise JournalConflictError(f"{label} are invalid")


def _require_media_types(value: object, label: str) -> None:
    if (
        not isinstance(value, (list, tuple))
        or any(not isinstance(item, str) for item in value)
        or not is_sorted_unique_scalar_strings(list(value))
        or any(MEDIA_TYPE.fullmatch(item) is None for item in value)
    ):
        raise JournalConflictError(f"{label} are invalid")


def _require_positive_integer(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JournalConflictError(f"{label} is invalid")


def _require_one_media_type(value: object, label: str) -> None:
    if not isinstance(value, str) or MEDIA_TYPE.fullmatch(value) is None:
        raise JournalConflictError(f"{label} is invalid")


def _require_safe_positive_integer(value: object, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= 9_007_199_254_740_991
    ):
        raise JournalConflictError(f"{label} is invalid")


def _require_safe_nonnegative_integer(value: object, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= 9_007_199_254_740_991
    ):
        raise JournalConflictError(f"{label} is invalid")


def _require_nonnegative_integer(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
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
