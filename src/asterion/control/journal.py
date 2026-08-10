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
from typing import Protocol

import fcntl

from asterion.control.host import ControlCommand, ControlEvent
from asterion.control.protocol import (
    IDENTIFIER,
    MEDIA_TYPE,
    OPAQUE_ID,
    SEMANTIC_VERSION,
    validate_control_command,
    validate_control_event,
)
from asterion.protocol_ordering import is_sorted_unique_scalar_strings


JOURNAL_RECORD_KINDS = frozenset(
    {
        "system.bound",
        "authority.bound",
        "authority.revised",
        "command.accepted",
        "event.accepted",
        "action.decided",
        "action.running",
        "action.receipted",
        "checkpoint.sealed",
        "fault.projected",
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
    def checkpoint_sealed(cls, *, checkpoint_event: ControlEvent) -> JournalRecord:
        if not isinstance(checkpoint_event, ControlEvent):
            raise JournalConflictError("journal checkpoint event is invalid")
        checkpoint_id = checkpoint_event.payload.get("checkpoint_id")
        return cls(
            record_id=f"checkpoint:{checkpoint_id}",
            kind="checkpoint.sealed",
            payload={"checkpoint_event": checkpoint_event.to_mapping()},
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
        "checkpoint.sealed": "checkpoint_event",
    }.get(record.kind)
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
