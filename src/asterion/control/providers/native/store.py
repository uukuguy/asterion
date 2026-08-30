"""Storage owners and descriptor-relative journals for the native controller."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import NoReturn, Protocol, cast

from asterion.control.protocol import OPAQUE_ID
from asterion.control.providers.native.model import (
    MAX_SAFE_JSON_INTEGER,
    NATIVE_JOURNAL_VERSION,
    NativeEntry,
    NativeRecord,
    _json_value,
)
from asterion.control.providers.native.state import (
    NativeStateError,
    reduce_native_entries,
)


_ERROR = "native session store is unavailable"
_NOFOLLOW = getattr(os, "O_NOFOLLOW", None)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_RECORD_FILE = re.compile(r"^(?P<position>[0-9]{20})-(?P<digest>[0-9a-f]{64})\.record$")
_RECORD_TEMP = re.compile(r"^\.record-[0-9]{20}-[0-9a-f]{32}\.tmp$")
_CAPSULE_TEMP = re.compile(r"^\.capsule-[0-9a-f]{32}\.tmp$")
_CAPSULE_FILE = re.compile(r"^[0-9a-f]{64}\.capsule$")


class NativeStoreError(RuntimeError):
    """Raised when native storage cannot be trusted or used."""

    def __init__(self) -> None:
        super().__init__(_ERROR)


def _raise_store_error() -> NoReturn:
    try:
        raise NativeStoreError from None
    except NativeStoreError as error:
        error.__context__ = None
        raise


class NativeStorageBudget:
    """Shared byte budget for private native session storage."""

    def __init__(self, maximum_bytes: int, *, used_bytes: int = 0) -> None:
        if (
            isinstance(maximum_bytes, bool)
            or not isinstance(maximum_bytes, int)
            or maximum_bytes < 0
            or maximum_bytes > MAX_SAFE_JSON_INTEGER
        ):
            raise NativeStoreError
        if (
            isinstance(used_bytes, bool)
            or not isinstance(used_bytes, int)
            or used_bytes < 0
            or used_bytes > maximum_bytes
        ):
            raise NativeStoreError
        self._maximum_bytes = maximum_bytes
        self._used_bytes = used_bytes
        self._lock = threading.Lock()

    @property
    def maximum_bytes(self) -> int:
        return self._maximum_bytes

    @property
    def used_bytes(self) -> int:
        with self._lock:
            return self._used_bytes

    def reserve(self, size: int) -> None:
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or size > MAX_SAFE_JSON_INTEGER
        ):
            raise NativeStoreError
        with self._lock:
            if self._used_bytes + size > self._maximum_bytes:
                raise NativeStoreError
            self._used_bytes += size

    def release(self, size: int) -> None:
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or size > MAX_SAFE_JSON_INTEGER
        ):
            raise NativeStoreError
        with self._lock:
            if size > self._used_bytes:
                raise NativeStoreError
            self._used_bytes = max(0, self._used_bytes - size)


class NativeStorageOwner(Protocol):
    @property
    def budget(self) -> NativeStorageBudget:
        raise NotImplementedError

    def require_open(self) -> None:
        raise NotImplementedError

    def operation(self) -> AbstractContextManager[None]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class NativeSessionStore(Protocol):
    @property
    def position(self) -> int:
        raise NotImplementedError

    def append(self, expected_position: int, record: NativeRecord) -> NativeEntry:
        raise NotImplementedError

    def replay(self, position: int = 0) -> tuple[NativeEntry, ...]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class MemoryNativeStorageOwner:
    """In-memory owner with the same close and budget semantics as file storage."""

    def __init__(self, *, maximum_bytes: int) -> None:
        self._budget = NativeStorageBudget(maximum_bytes)
        self._operation_lock = threading.RLock()
        self._entries: list[NativeEntry] = []
        self._by_record_id: dict[str, NativeEntry] = {}
        self._closed = False

    @property
    def budget(self) -> NativeStorageBudget:
        self.require_open()
        return self._budget

    def require_open(self) -> None:
        if self._closed:
            raise NativeStoreError

    @contextmanager
    def operation(self) -> Iterator[None]:
        with self._operation_lock:
            yield

    def close(self) -> None:
        with self._operation_lock:
            self._closed = True


class MemoryNativeSessionStore:
    def __init__(
        self,
        owner: NativeStorageOwner,
        *,
        max_record_bytes: int,
    ) -> None:
        _require_record_limit(max_record_bytes)
        if type(owner) is not MemoryNativeStorageOwner:
            raise NativeStoreError
        self._owner = cast(MemoryNativeStorageOwner, owner)
        self._max_record_bytes = max_record_bytes
        self._closed = False
        with self._owner.operation():
            self._owner.require_open()

    @property
    def position(self) -> int:
        with self._owner.operation():
            self._require_usable()
            return len(self._owner._entries)

    def append(self, expected_position: int, record: NativeRecord) -> NativeEntry:
        with self._owner.operation():
            self._require_usable()
            _require_position_boundary(expected_position)
            if type(record) is not NativeRecord:
                raise NativeStoreError
            current = len(self._owner._entries)
            existing = self._owner._by_record_id.get(record.record_id)
            if existing is not None:
                if (
                    not _expected_position_matches_idempotent_append(
                        expected_position,
                        current,
                        existing,
                    )
                    or existing.record.digest != record.digest
                ):
                    raise NativeStoreError
                _require_encoded_size(_encode_entry(existing), self._max_record_bytes)
                _validate_entries(tuple(self._owner._entries))
                return existing
            if expected_position != current:
                raise NativeStoreError
            previous_digest = (
                self._owner._entries[-1].digest if self._owner._entries else None
            )
            entry = NativeEntry(current + 1, previous_digest, record)
            encoded = _encode_entry(entry)
            _require_encoded_size(encoded, self._max_record_bytes)
            _validate_entries((*self._owner._entries, entry))
            self._owner.budget.reserve(len(encoded))
            self._owner._entries.append(entry)
            self._owner._by_record_id[record.record_id] = entry
            return entry

    def replay(self, position: int = 0) -> tuple[NativeEntry, ...]:
        with self._owner.operation():
            self._require_usable()
            _require_replay_position(position, len(self._owner._entries))
            entries = tuple(self._owner._entries)
            _validate_entries(entries)
            return entries[position:]

    def close(self) -> None:
        self._closed = True

    def _require_usable(self) -> None:
        if self._closed:
            raise NativeStoreError
        self._owner.require_open()


class NativeSessionDirectory:
    """Owns pinned descriptors, the lifetime lock, and one shared byte budget."""

    def __init__(
        self,
        *,
        root_fd: int,
        session_fd: int,
        records_fd: int,
        capsules_fd: int,
        lock_fd: int,
        budget: NativeStorageBudget,
    ) -> None:
        self._root_fd = root_fd
        self._session_fd = session_fd
        self._records_fd = records_fd
        self._capsules_fd = capsules_fd
        self._lock_fd = lock_fd
        self._budget = budget
        self._operation_lock = threading.RLock()
        self._closed = False

    @classmethod
    def open(
        cls,
        private_root: Path,
        session_id: str,
        max_total_private_bytes: int,
    ) -> NativeSessionDirectory:
        _require_platform()
        _require_session_id(session_id)
        root_fd = session_fd = records_fd = capsules_fd = lock_fd = -1
        try:
            root_fd = _open_root(private_root)
            _validate_directory_fd(root_fd, 0o700)
            session_name = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
            session_fd = _open_or_create_child_directory(root_fd, session_name)
            records_fd = _open_or_create_child_directory(session_fd, "records")
            capsules_fd = _open_or_create_child_directory(session_fd, "capsules")
            lock_fd = _open_lock(session_fd)
            used = _existing_storage_bytes(records_fd, "records")
            used += _existing_storage_bytes(capsules_fd, "capsules")
            budget = NativeStorageBudget(
                max_total_private_bytes,
                used_bytes=used,
            )
            return cls(
                root_fd=root_fd,
                session_fd=session_fd,
                records_fd=records_fd,
                capsules_fd=capsules_fd,
                lock_fd=lock_fd,
                budget=budget,
            )
        except NativeStoreError:
            for descriptor in (lock_fd, capsules_fd, records_fd, session_fd, root_fd):
                _close_fd_quietly(descriptor)
            raise
        except Exception:
            for descriptor in (lock_fd, capsules_fd, records_fd, session_fd, root_fd):
                _close_fd_quietly(descriptor)
            _raise_store_error()

    @property
    def budget(self) -> NativeStorageBudget:
        self.require_open()
        return self._budget

    def require_open(self) -> None:
        if self._closed:
            raise NativeStoreError

    @contextmanager
    def operation(self) -> Iterator[None]:
        with self._operation_lock:
            yield

    def duplicate_records_fd(self) -> int:
        self.require_open()
        try:
            return os.dup(self._records_fd)
        except OSError:
            _raise_store_error()

    def duplicate_capsules_fd(self) -> int:
        self.require_open()
        try:
            return os.dup(self._capsules_fd)
        except OSError:
            _raise_store_error()

    def close(self) -> None:
        with self._operation_lock:
            if self._closed:
                return
            self._closed = True
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            for descriptor in (
                self._lock_fd,
                self._capsules_fd,
                self._records_fd,
                self._session_fd,
                self._root_fd,
            ):
                _close_fd_quietly(descriptor)


class FileNativeSessionStore:
    def __init__(
        self,
        session_directory: NativeSessionDirectory,
        *,
        max_record_bytes: int,
    ) -> None:
        _require_record_limit(max_record_bytes)
        self._owner = session_directory
        self._max_record_bytes = max_record_bytes
        self._records_fd = -1
        self._closed = False
        try:
            with self._owner.operation():
                self._require_usable()
                self._records_fd = session_directory.duplicate_records_fd()
                self._entries = self._load_entries()
                self._by_record_id = _index_by_record_id(self._entries)
        except NativeStoreError:
            self.close()
            raise
        except Exception:
            self.close()
            _raise_store_error()

    @property
    def position(self) -> int:
        with self._owner.operation():
            self._require_usable()
            self._refresh()
            return len(self._entries)

    def append(self, expected_position: int, record: NativeRecord) -> NativeEntry:
        with self._owner.operation():
            self._require_usable()
            _require_position_boundary(expected_position)
            if type(record) is not NativeRecord:
                raise NativeStoreError
            self._refresh()
            current = len(self._entries)
            existing = self._by_record_id.get(record.record_id)
            if existing is not None:
                if (
                    not _expected_position_matches_idempotent_append(
                        expected_position,
                        current,
                        existing,
                    )
                    or existing.record.digest != record.digest
                ):
                    raise NativeStoreError
                _require_encoded_size(_encode_entry(existing), self._max_record_bytes)
                _validate_entries(self._entries)
                return existing
            if expected_position != current:
                raise NativeStoreError

            previous_digest = self._entries[-1].digest if self._entries else None
            entry = NativeEntry(current + 1, previous_digest, record)
            encoded = _encode_entry(entry)
            _require_encoded_size(encoded, self._max_record_bytes)
            _validate_entries((*self._entries, entry))
            final_name = _final_name(entry)
            temporary = f".record-{entry.position:020d}-{secrets.token_hex(16)}.tmp"
            self._owner.budget.reserve(len(encoded))
            try:
                self._publish_entry(temporary, final_name, encoded)
            except NativeStoreError:
                raise
            except Exception:
                _raise_store_error()

            self._refresh()
            final_entry = self._by_record_id.get(record.record_id)
            if final_entry != entry:
                raise NativeStoreError
            return entry

    def replay(self, position: int = 0) -> tuple[NativeEntry, ...]:
        with self._owner.operation():
            self._require_usable()
            self._refresh()
            _require_replay_position(position, len(self._entries))
            return self._entries[position:]

    def _publish_entry(self, temporary: str, final_name: str, encoded: bytes) -> None:
        descriptor = -1
        temp_created = False
        final_linked = False
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _CLOEXEC | _nofollow(),
                0o600,
                dir_fd=self._records_fd,
            )
            temp_created = True
            os.fchmod(descriptor, 0o600)
            _validate_fd(descriptor, 0o600, regular=True)
            _write_all(descriptor, encoded)
            os.fsync(descriptor)
            temp_stat = _validate_fd(descriptor, 0o600, regular=True)
            if temp_stat.st_size != len(encoded):
                raise NativeStoreError
            os.close(descriptor)
            descriptor = -1
            os.link(
                temporary,
                final_name,
                src_dir_fd=self._records_fd,
                dst_dir_fd=self._records_fd,
                follow_symlinks=False,
            )
            final_linked = True
            _fsync_directory(self._records_fd)
            os.unlink(temporary, dir_fd=self._records_fd)
            _fsync_directory(self._records_fd)
            final_stat = _validate_child_file(self._records_fd, final_name, 0o600)
            if not _same_trusted_file(temp_stat, final_stat):
                raise NativeStoreError
        except NativeStoreError:
            if descriptor >= 0:
                _close_fd_quietly(descriptor)
            if not final_linked and _remove_unpublished_temp(
                self._records_fd,
                temporary,
                temp_created=temp_created,
            ):
                self._owner.budget.release(len(encoded))
            raise
        except Exception:
            if descriptor >= 0:
                _close_fd_quietly(descriptor)
            if not final_linked and _remove_unpublished_temp(
                self._records_fd,
                temporary,
                temp_created=temp_created,
            ):
                self._owner.budget.release(len(encoded))
            _raise_store_error()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _close_fd_quietly(self._records_fd)

    def _refresh(self) -> None:
        self._entries = self._load_entries()
        self._by_record_id = _index_by_record_id(self._entries)

    def _load_entries(self) -> tuple[NativeEntry, ...]:
        self._require_usable()
        entries: list[NativeEntry] = []
        try:
            names = sorted(os.listdir(self._records_fd))
        except OSError:
            _raise_store_error()
        for name in names:
            if _RECORD_TEMP.fullmatch(name):
                _validate_child_file(self._records_fd, name, 0o600)
                continue
            match = _RECORD_FILE.fullmatch(name)
            if match is None:
                raise NativeStoreError
            raw = _read_child_file(
                self._records_fd,
                name,
                0o600,
                self._max_record_bytes,
            )
            entry = _decode_entry(raw, name)
            entries.append(entry)
        result = tuple(entries)
        _validate_entries(result)
        return result

    def _require_usable(self) -> None:
        if self._closed:
            raise NativeStoreError
        self._owner.require_open()


def _require_platform() -> None:
    if not isinstance(_NOFOLLOW, int):
        raise NativeStoreError


def _nofollow() -> int:
    nofollow = _NOFOLLOW
    if not isinstance(nofollow, int):
        raise NativeStoreError
    return nofollow


def _current_uid() -> int:
    return os.geteuid()


def _require_session_id(session_id: str) -> None:
    if not isinstance(session_id, str) or OPAQUE_ID.fullmatch(session_id) is None:
        raise NativeStoreError


def _require_record_limit(value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_SAFE_JSON_INTEGER
    ):
        raise NativeStoreError


def _require_position_boundary(value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > MAX_SAFE_JSON_INTEGER
    ):
        raise NativeStoreError


def _require_replay_position(value: int, current: int) -> None:
    _require_position_boundary(value)
    if value > current:
        raise NativeStoreError


def _expected_position_matches_idempotent_append(
    expected_position: int,
    current_position: int,
    existing: NativeEntry,
) -> bool:
    return expected_position == current_position or (
        existing.position == current_position
        and expected_position == existing.position - 1
    )


def _require_encoded_size(encoded: bytes, maximum: int) -> None:
    if len(encoded) > maximum:
        raise NativeStoreError


def _open_root(path: Path) -> int:
    try:
        return os.open(
            str(path),
            os.O_RDONLY | _DIRECTORY | _CLOEXEC | _nofollow(),
        )
    except OSError:
        _raise_store_error()


def _open_or_create_child_directory(parent_fd: int, name: str) -> int:
    created = False
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        created = True
        _fsync_directory(parent_fd)
    except FileExistsError:
        pass
    except OSError:
        _raise_store_error()
    try:
        child_fd = os.open(
            name,
            os.O_RDONLY | _DIRECTORY | _CLOEXEC | _nofollow(),
            dir_fd=parent_fd,
        )
    except OSError:
        _raise_store_error()
    try:
        if created:
            os.fchmod(child_fd, 0o700)
            _fsync_directory(child_fd)
        _validate_directory_fd(child_fd, 0o700)
        return child_fd
    except NativeStoreError:
        _close_fd_quietly(child_fd)
        raise
    except Exception:
        _close_fd_quietly(child_fd)
        _raise_store_error()


def _open_lock(session_fd: int) -> int:
    try:
        descriptor = os.open(
            "lock",
            os.O_RDWR | os.O_CREAT | _CLOEXEC | _nofollow(),
            0o600,
            dir_fd=session_fd,
        )
    except OSError:
        _raise_store_error()
    try:
        os.fchmod(descriptor, 0o600)
        _validate_fd(descriptor, 0o600, regular=True)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _fsync_directory(session_fd)
        return descriptor
    except OSError as exc:
        _close_fd_quietly(descriptor)
        if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
            _raise_store_error()
        _raise_store_error()
    except NativeStoreError:
        _close_fd_quietly(descriptor)
        raise
    except Exception:
        _close_fd_quietly(descriptor)
        _raise_store_error()


def _validate_directory_fd(descriptor: int, mode: int) -> None:
    _validate_fd(descriptor, mode, directory=True)


def _validate_fd(
    descriptor: int,
    mode: int,
    *,
    directory: bool = False,
    regular: bool = False,
) -> os.stat_result:
    try:
        result = os.fstat(descriptor)
    except OSError:
        _raise_store_error()
    _validate_stat(result, mode, directory=directory, regular=regular)
    return result


def _validate_child_file(parent_fd: int, name: str, mode: int) -> os.stat_result:
    try:
        result = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        _raise_store_error()
    _validate_stat(result, mode, regular=True)
    return result


def _validate_stat(
    result: os.stat_result,
    mode: int,
    *,
    directory: bool = False,
    regular: bool = False,
) -> None:
    if result.st_uid != _current_uid():
        raise NativeStoreError
    if stat.S_IMODE(result.st_mode) != mode:
        raise NativeStoreError
    if directory and not stat.S_ISDIR(result.st_mode):
        raise NativeStoreError
    if regular and not stat.S_ISREG(result.st_mode):
        raise NativeStoreError
    if regular and result.st_nlink != 1:
        raise NativeStoreError


def _existing_storage_bytes(descriptor: int, child: str) -> int:
    try:
        names = os.listdir(descriptor)
    except OSError:
        _raise_store_error()
    total = 0
    for name in names:
        if child == "records":
            exact = _RECORD_FILE.fullmatch(name) or _RECORD_TEMP.fullmatch(name)
        else:
            exact = _CAPSULE_FILE.fullmatch(name) or _CAPSULE_TEMP.fullmatch(name)
        if exact is None:
            raise NativeStoreError
        result = _validate_child_file(descriptor, name, 0o600)
        if (
            result.st_size > MAX_SAFE_JSON_INTEGER
            or total + result.st_size > MAX_SAFE_JSON_INTEGER
        ):
            raise NativeStoreError
        total += result.st_size
    return total


def _read_child_file(parent_fd: int, name: str, mode: int, max_bytes: int) -> bytes:
    before = _validate_child_file(parent_fd, name, mode)
    if before.st_size > max_bytes:
        raise NativeStoreError
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | _CLOEXEC | _nofollow(),
            dir_fd=parent_fd,
        )
    except OSError:
        _raise_store_error()
    try:
        after = _validate_fd(descriptor, mode, regular=True)
        if not _same_trusted_file(before, after):
            raise NativeStoreError
        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = max_bytes + 1 - total
            if remaining <= 0:
                raise NativeStoreError
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                final = _validate_fd(descriptor, mode, regular=True)
                if not _same_trusted_file(before, final) or total != final.st_size:
                    raise NativeStoreError
                return b"".join(chunks)
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise NativeStoreError
    except NativeStoreError:
        raise
    except Exception:
        _raise_store_error()
    finally:
        _close_fd_quietly(descriptor)


def _same_trusted_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and left.st_mode == right.st_mode
        and left.st_uid == right.st_uid
        and left.st_nlink == right.st_nlink
        and left.st_size == right.st_size
    )


def _index_by_record_id(entries: tuple[NativeEntry, ...]) -> dict[str, NativeEntry]:
    indexed: dict[str, NativeEntry] = {}
    for entry in entries:
        existing = indexed.get(entry.record.record_id)
        if existing is not None and existing.record.digest != entry.record.digest:
            raise NativeStoreError
        indexed.setdefault(entry.record.record_id, entry)
    return indexed


def _validate_entries(entries: tuple[NativeEntry, ...]) -> None:
    try:
        reduce_native_entries(entries)
    except (NativeStateError, TypeError, ValueError):
        _raise_store_error()


def _encode_entry(entry: NativeEntry) -> bytes:
    document: dict[str, object] = {
        "format": NATIVE_JOURNAL_VERSION,
        "position": entry.position,
        "previous_digest": entry.previous_digest,
        "record": {
            "record_id": entry.record.record_id,
            "kind": entry.record.kind,
            "payload": _json_value(entry.record.payload),
        },
        "entry_digest": entry.digest,
    }
    return _canonical_json(document)


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        _raise_store_error()


def _decode_entry(raw: bytes, filename: str) -> NativeEntry:
    if raw.endswith((b"\n", b"\r")):
        raise NativeStoreError
    try:
        text = raw.decode("utf-8")
        document = json.loads(text, object_pairs_hook=_object_without_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _raise_store_error()
    _assert_json_tree_safe(document)
    if _canonical_json(document) != raw:
        raise NativeStoreError
    if not isinstance(document, dict) or set(document) != {
        "entry_digest",
        "format",
        "position",
        "previous_digest",
        "record",
    }:
        raise NativeStoreError
    if document["format"] != NATIVE_JOURNAL_VERSION:
        raise NativeStoreError
    record_mapping = document["record"]
    if not isinstance(record_mapping, dict) or set(record_mapping) != {
        "kind",
        "payload",
        "record_id",
    }:
        raise NativeStoreError
    try:
        record = NativeRecord(
            str(record_mapping["record_id"]),
            str(record_mapping["kind"]),
            _mapping(record_mapping["payload"]),
        )
        entry = NativeEntry(
            _integer(document["position"]),
            _optional_digest(document["previous_digest"]),
            record,
        )
    except (TypeError, ValueError):
        _raise_store_error()
    if document["entry_digest"] != entry.digest:
        raise NativeStoreError
    if filename != _final_name(entry):
        raise NativeStoreError
    return entry


def _object_without_duplicates(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _assert_json_tree_safe(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise NativeStoreError
            _assert_json_tree_safe(item)
        return
    if isinstance(value, list):
        for item in value:
            _assert_json_tree_safe(item)
        return
    if isinstance(value, float):
        raise NativeStoreError
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > MAX_SAFE_JSON_INTEGER:
            raise NativeStoreError
        return
    if value is None or isinstance(value, (str, bool)):
        return
    raise NativeStoreError


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise NativeStoreError
    return value


def _integer(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_SAFE_JSON_INTEGER
    ):
        raise NativeStoreError
    return value


def _optional_digest(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise NativeStoreError
    return value


def _final_name(entry: NativeEntry) -> str:
    return f"{entry.position:020d}-{entry.digest}.record"


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    written = 0
    while written < len(data):
        count = os.write(descriptor, view[written:])
        if count <= 0:
            raise OSError("write failed")
        written += count


def _fsync_directory(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if exc.errno != errno.EINVAL:
            raise


def _fsync_directory_quietly(descriptor: int) -> None:
    try:
        _fsync_directory(descriptor)
    except OSError:
        pass


def _unlink_child_quietly(parent_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=parent_fd)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _remove_unpublished_temp(
    parent_fd: int,
    name: str,
    *,
    temp_created: bool,
) -> bool:
    if not temp_created:
        return True
    try:
        os.unlink(name, dir_fd=parent_fd)
        _fsync_directory(parent_fd)
        return True
    except FileNotFoundError:
        _fsync_directory_quietly(parent_fd)
        return True
    except OSError:
        _fsync_directory_quietly(parent_fd)
        return False


def _close_fd_quietly(descriptor: int) -> None:
    if descriptor < 0:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass
