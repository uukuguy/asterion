"""Private continuation capsule stores for the native controller."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import weakref
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NoReturn, Protocol, cast

from asterion.control.protocol import OPAQUE_ID
from asterion.control.providers.native.model import (
    MAX_SAFE_JSON_INTEGER,
    NativeCapsuleMetadata,
)
from asterion.control.providers.native.store import (
    MemoryNativeStorageOwner,
    NativeSessionDirectory,
    NativeStorageOwner,
    NativeStoreError,
    _CLOEXEC,
    _close_fd_quietly,
    _fsync_directory,
    _nofollow,
    _read_child_file,
    _remove_unpublished_temp,
    _same_trusted_file,
    _validate_child_file,
    _validate_fd,
    _write_all,
)


NATIVE_CONTROL_PLANE_ID = "native"
NATIVE_CONTROL_PLANE_VERSION = "0.1.0"
NATIVE_CHECKPOINT_VERSION = "1.0.0"
_CAPSULE_DOMAIN = b"asterion.native-capsule/v1\x00"
_CAPSULE_FILE = re.compile(r"^[0-9a-f]{64}\.capsule$")
_CAPSULE_RECEIPT_FILE = re.compile(r"^[0-9a-f]{64}\.capsule-receipt$")
_CAPSULE_MODE = 0o600
_MAX_RECEIPT_BYTES = 4096


class _PublishFailed(Exception):
    def __init__(self, cleanup_proven: bool) -> None:
        super().__init__()
        self.cleanup_proven = cleanup_proven


class NativeCapsuleStore(Protocol):
    def seal(
        self,
        *,
        capsule_id: str,
        payload: bytes,
        covered_position: int,
        covered_sequence: int,
    ) -> NativeCapsuleMetadata:
        raise NotImplementedError

    def verify(self, metadata: NativeCapsuleMetadata) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class _MemoryCapsule:
    metadata: NativeCapsuleMetadata
    payload: bytes
    receipt: bytes


@dataclass
class _MemoryCapsuleState:
    capsules: dict[str, _MemoryCapsule]


_MEMORY_STATES: weakref.WeakKeyDictionary[
    MemoryNativeStorageOwner, _MemoryCapsuleState
] = weakref.WeakKeyDictionary()
_MEMORY_STATES_LOCK = threading.Lock()


class MemoryNativeCapsuleStore:
    def __init__(
        self,
        owner: NativeStorageOwner,
        *,
        max_capsule_bytes: int,
    ) -> None:
        _require_capsule_limit(max_capsule_bytes)
        if type(owner) is not MemoryNativeStorageOwner:
            raise NativeStoreError
        self._owner = cast(MemoryNativeStorageOwner, owner)
        self._max_capsule_bytes = max_capsule_bytes
        self._closed = False
        with self._owner.operation():
            self._owner.require_open()
            _memory_state(self._owner)

    def seal(
        self,
        *,
        capsule_id: str,
        payload: bytes,
        covered_position: int,
        covered_sequence: int,
    ) -> NativeCapsuleMetadata:
        with self._owner.operation():
            try:
                self._require_usable()
                capsule = _build_capsule(
                    capsule_id=capsule_id,
                    payload=payload,
                    covered_position=covered_position,
                    covered_sequence=covered_sequence,
                    max_capsule_bytes=self._max_capsule_bytes,
                )
                state = _memory_state(self._owner)
                existing = state.capsules.get(capsule.metadata.storage_ref)
                if existing is not None:
                    _require_same_capsule(existing, capsule)
                    return existing.metadata
                self._owner.budget.reserve(len(capsule.payload) + len(capsule.receipt))
                state.capsules[capsule.metadata.storage_ref] = capsule
                return capsule.metadata
            except NativeStoreError:
                raise
            except Exception:
                _raise_capsule_error()

    def verify(self, metadata: NativeCapsuleMetadata) -> None:
        _require_metadata(metadata)
        with self._owner.operation():
            try:
                self._require_usable()
                existing = _memory_state(self._owner).capsules.get(metadata.storage_ref)
                if existing is None:
                    raise NativeStoreError
                _require_metadata_matches_payload(metadata, existing.payload)
                if existing.metadata != metadata:
                    raise NativeStoreError
            except NativeStoreError:
                raise
            except Exception:
                _raise_capsule_error()

    def close(self) -> None:
        with self._owner.operation():
            self._closed = True

    def _require_usable(self) -> None:
        if self._closed:
            raise NativeStoreError
        self._owner.require_open()


class FileNativeCapsuleStore:
    def __init__(
        self,
        session_directory: NativeSessionDirectory,
        *,
        max_capsule_bytes: int,
    ) -> None:
        if type(session_directory) is not NativeSessionDirectory:
            raise NativeStoreError
        _require_capsule_limit(max_capsule_bytes)
        self._owner = session_directory
        self._max_capsule_bytes = max_capsule_bytes
        self._capsules_fd = -1
        self._metadata_by_ref: dict[str, NativeCapsuleMetadata] = {}
        self._closed = False
        try:
            with self._owner.operation():
                self._require_usable()
                self._capsules_fd = session_directory.duplicate_capsules_fd()
        except NativeStoreError:
            descriptor = self._capsules_fd
            self._capsules_fd = -1
            self._closed = True
            _close_fd_quietly(descriptor)
            raise
        except Exception:
            descriptor = self._capsules_fd
            self._capsules_fd = -1
            self._closed = True
            _close_fd_quietly(descriptor)
            _raise_capsule_error()

    def seal(
        self,
        *,
        capsule_id: str,
        payload: bytes,
        covered_position: int,
        covered_sequence: int,
    ) -> NativeCapsuleMetadata:
        with self._owner.operation():
            try:
                self._require_usable()
                capsule = _build_capsule(
                    capsule_id=capsule_id,
                    payload=payload,
                    covered_position=covered_position,
                    covered_sequence=covered_sequence,
                    max_capsule_bytes=self._max_capsule_bytes,
                )
                name = _capsule_name(capsule.metadata.storage_ref)
                receipt_name = _receipt_name(capsule.metadata.storage_ref)
                existing = _read_existing_pair(
                    self._capsules_fd,
                    name,
                    receipt_name,
                    self._max_capsule_bytes,
                )
                if existing is not None:
                    existing_payload, existing_metadata = existing
                    if existing_payload != capsule.payload:
                        raise NativeStoreError
                    if existing_metadata != capsule.metadata:
                        raise NativeStoreError
                    previous = self._metadata_by_ref.get(capsule.metadata.storage_ref)
                    if previous is not None and previous != capsule.metadata:
                        raise NativeStoreError
                    self._metadata_by_ref[capsule.metadata.storage_ref] = (
                        capsule.metadata
                    )
                    return capsule.metadata
                temporary = f".capsule-{secrets.token_hex(16)}.tmp"
                receipt_temporary = f".capsule-receipt-{secrets.token_hex(16)}.tmp"
                self._owner.budget.reserve(len(capsule.payload) + len(capsule.receipt))
                try:
                    self._publish_pair(
                        temporary,
                        name,
                        capsule.payload,
                        receipt_temporary,
                        receipt_name,
                        capsule.receipt,
                    )
                except NativeStoreError:
                    raise
                except Exception:
                    _raise_capsule_error()
                self._metadata_by_ref[capsule.metadata.storage_ref] = capsule.metadata
                return capsule.metadata
            except NativeStoreError:
                raise
            except Exception:
                _raise_capsule_error()

    def verify(self, metadata: NativeCapsuleMetadata) -> None:
        _require_metadata(metadata)
        with self._owner.operation():
            try:
                self._require_usable()
                pair = _read_existing_pair(
                    self._capsules_fd,
                    _capsule_name(metadata.storage_ref),
                    _receipt_name(metadata.storage_ref),
                    self._max_capsule_bytes,
                )
                if pair is None:
                    raise NativeStoreError
                payload, persisted = pair
                previous = self._metadata_by_ref.get(metadata.storage_ref)
                if previous is not None and previous != metadata:
                    raise NativeStoreError
                if persisted != metadata:
                    raise NativeStoreError
                _require_metadata_matches_payload(metadata, payload)
                self._metadata_by_ref[metadata.storage_ref] = metadata
            except NativeStoreError:
                raise
            except Exception:
                _raise_capsule_error()

    def close(self) -> None:
        with self._owner.operation():
            if self._closed:
                return
            descriptor = self._capsules_fd
            self._capsules_fd = -1
            self._closed = True
            _close_fd_quietly(descriptor)

    def _publish_pair(
        self,
        body_temporary: str,
        body_name: str,
        body: bytes,
        receipt_temporary: str,
        receipt_name: str,
        receipt: bytes,
    ) -> None:
        published = False
        try:
            self._publish_one(body_temporary, body_name, body)
            published = True
            self._publish_one(receipt_temporary, receipt_name, receipt)
        except _PublishFailed as error:
            if published:
                _raise_capsule_error()
            if error.cleanup_proven:
                try:
                    self._owner.budget.release(len(body) + len(receipt))
                except Exception:
                    pass
            _raise_capsule_error()
        except BaseException as error:
            if published:
                if isinstance(error, Exception):
                    _raise_capsule_error()
                error.__cause__ = None
                error.__context__ = None
                raise
            if isinstance(error, Exception):
                _raise_capsule_error()
            error.__cause__ = None
            error.__context__ = None
            raise

    def _publish_one(self, temporary: str, final_name: str, payload: bytes) -> None:
        descriptor = -1
        temp_created = False
        final_linked = False
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _CLOEXEC | _nofollow(),
                _CAPSULE_MODE,
                dir_fd=self._capsules_fd,
            )
            temp_created = True
            os.fchmod(descriptor, _CAPSULE_MODE)
            _validate_fd(descriptor, _CAPSULE_MODE, regular=True)
            _write_all(descriptor, payload)
            os.fsync(descriptor)
            temp_stat = _validate_fd(descriptor, _CAPSULE_MODE, regular=True)
            if temp_stat.st_size != len(payload):
                raise NativeStoreError
            os.link(
                temporary,
                final_name,
                src_dir_fd=self._capsules_fd,
                dst_dir_fd=self._capsules_fd,
                follow_symlinks=False,
            )
            final_linked = True
            _fsync_directory(self._capsules_fd)
            os.unlink(temporary, dir_fd=self._capsules_fd)
            _fsync_directory(self._capsules_fd)
            temp_stat = _validate_fd(descriptor, _CAPSULE_MODE, regular=True)
            final_stat = _validate_child_file(
                self._capsules_fd,
                final_name,
                _CAPSULE_MODE,
            )
            if not _same_trusted_file(temp_stat, final_stat):
                raise NativeStoreError
        except BaseException as error:
            should_release = False
            if not final_linked:
                try:
                    should_release = _remove_unpublished_temp(
                        self._capsules_fd,
                        temporary,
                        temp_fd=descriptor,
                        temp_created=temp_created,
                    )
                except Exception:
                    should_release = False
            _close_fd_quietly(descriptor)
            if isinstance(error, Exception):
                raise _PublishFailed(should_release) from None
            error.__cause__ = None
            error.__context__ = None
            raise
        _close_fd_quietly(descriptor)

    def _require_usable(self) -> None:
        if self._closed:
            raise NativeStoreError
        self._owner.require_open()


def _memory_state(owner: MemoryNativeStorageOwner) -> _MemoryCapsuleState:
    with _MEMORY_STATES_LOCK:
        state = _MEMORY_STATES.get(owner)
        if state is None:
            state = _MemoryCapsuleState({})
            _MEMORY_STATES[owner] = state
        return state


def _build_capsule(
    *,
    capsule_id: str,
    payload: bytes,
    covered_position: int,
    covered_sequence: int,
    max_capsule_bytes: int,
) -> _MemoryCapsule:
    _require_capsule_id(capsule_id)
    _require_payload(payload, max_capsule_bytes)
    _require_position(covered_position)
    _require_position(covered_sequence)
    metadata = NativeCapsuleMetadata(
        capsule_id=capsule_id,
        capsule_digest=hashlib.sha256(payload).hexdigest(),
        control_plane_id=NATIVE_CONTROL_PLANE_ID,
        control_plane_version=NATIVE_CONTROL_PLANE_VERSION,
        checkpoint_version=NATIVE_CHECKPOINT_VERSION,
        covered_position=covered_position,
        covered_sequence=covered_sequence,
        storage_ref=_storage_ref(capsule_id),
    )
    return _MemoryCapsule(metadata, payload, _encode_receipt(metadata))


def _require_same_capsule(
    existing: _MemoryCapsule,
    candidate: _MemoryCapsule,
) -> None:
    if existing.payload != candidate.payload or existing.metadata != candidate.metadata:
        raise NativeStoreError


def _read_existing_pair(
    parent_fd: int,
    body_name: str,
    receipt_name: str,
    max_body_bytes: int,
) -> tuple[bytes, NativeCapsuleMetadata] | None:
    body_exists = _child_exists(parent_fd, body_name)
    receipt_exists = _child_exists(parent_fd, receipt_name)
    if not body_exists and not receipt_exists:
        return None
    if not body_exists or not receipt_exists:
        raise NativeStoreError
    body = _read_child_file(parent_fd, body_name, _CAPSULE_MODE, max_body_bytes)
    receipt = _read_child_file(
        parent_fd,
        receipt_name,
        _CAPSULE_MODE,
        _MAX_RECEIPT_BYTES,
    )
    metadata = _decode_receipt(receipt, receipt_name)
    _require_metadata_matches_payload(metadata, body)
    if body_name != _capsule_name(metadata.storage_ref):
        raise NativeStoreError
    return body, metadata


def _child_exists(parent_fd: int, name: str) -> bool:
    try:
        _validate_child_file(parent_fd, name, _CAPSULE_MODE)
    except NativeStoreError:
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError:
            _raise_capsule_error()
        raise
    return True


def _require_metadata(metadata: NativeCapsuleMetadata) -> None:
    if type(metadata) is not NativeCapsuleMetadata:
        raise NativeStoreError
    if (
        metadata.control_plane_id != NATIVE_CONTROL_PLANE_ID
        or metadata.control_plane_version != NATIVE_CONTROL_PLANE_VERSION
        or metadata.checkpoint_version != NATIVE_CHECKPOINT_VERSION
        or metadata.storage_ref != _storage_ref(metadata.capsule_id)
    ):
        raise NativeStoreError
    _capsule_name(metadata.storage_ref)
    _receipt_name(metadata.storage_ref)


def _require_metadata_matches_payload(
    metadata: NativeCapsuleMetadata,
    payload: bytes,
) -> None:
    _require_metadata(metadata)
    _require_payload(payload, MAX_SAFE_JSON_INTEGER)
    if hashlib.sha256(payload).hexdigest() != metadata.capsule_digest:
        raise NativeStoreError


def _capsule_name(storage_ref: str) -> str:
    name = f"{storage_ref}.capsule"
    if _CAPSULE_FILE.fullmatch(name) is None:
        raise NativeStoreError
    return name


def _receipt_name(storage_ref: str) -> str:
    name = f"{storage_ref}.capsule-receipt"
    if _CAPSULE_RECEIPT_FILE.fullmatch(name) is None:
        raise NativeStoreError
    return name


def _encode_receipt(metadata: NativeCapsuleMetadata) -> bytes:
    _require_metadata(metadata)
    return _canonical_json(_receipt_document(metadata))


def _decode_receipt(raw: bytes, filename: str) -> NativeCapsuleMetadata:
    if raw.endswith((b"\n", b"\r")):
        raise NativeStoreError
    try:
        text = raw.decode("utf-8")
        document = json.loads(text, object_pairs_hook=_object_without_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _raise_capsule_error()
    _assert_json_tree_safe(document)
    if _canonical_json(document) != raw:
        raise NativeStoreError
    if not isinstance(document, dict) or set(document) != {
        "capsule_id",
        "capsule_digest",
        "control_plane_id",
        "control_plane_version",
        "checkpoint_version",
        "covered_position",
        "covered_sequence",
        "storage_ref",
    }:
        raise NativeStoreError
    try:
        metadata = NativeCapsuleMetadata(
            capsule_id=str(document["capsule_id"]),
            capsule_digest=str(document["capsule_digest"]),
            control_plane_id=str(document["control_plane_id"]),
            control_plane_version=str(document["control_plane_version"]),
            checkpoint_version=str(document["checkpoint_version"]),
            covered_position=_positive_integer(document["covered_position"]),
            covered_sequence=_positive_integer(document["covered_sequence"]),
            storage_ref=str(document["storage_ref"]),
        )
    except (TypeError, ValueError):
        _raise_capsule_error()
    _require_metadata(metadata)
    if filename != _receipt_name(metadata.storage_ref):
        raise NativeStoreError
    return metadata


def _receipt_document(metadata: NativeCapsuleMetadata) -> dict[str, object]:
    return {
        "capsule_id": metadata.capsule_id,
        "capsule_digest": metadata.capsule_digest,
        "control_plane_id": metadata.control_plane_id,
        "control_plane_version": metadata.control_plane_version,
        "checkpoint_version": metadata.checkpoint_version,
        "covered_position": metadata.covered_position,
        "covered_sequence": metadata.covered_sequence,
        "storage_ref": metadata.storage_ref,
    }


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
        _raise_capsule_error()


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


def _positive_integer(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_SAFE_JSON_INTEGER
    ):
        raise NativeStoreError
    return value


def _storage_ref(capsule_id: str) -> str:
    _require_capsule_id(capsule_id)
    return hashlib.sha256(_CAPSULE_DOMAIN + capsule_id.encode("utf-8")).hexdigest()


def _require_capsule_limit(value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_SAFE_JSON_INTEGER
    ):
        raise NativeStoreError


def _require_capsule_id(value: str) -> None:
    if not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None:
        raise NativeStoreError


def _require_payload(value: bytes, maximum: int) -> None:
    if (
        type(value) is not bytes
        or len(value) < 1
        or len(value) > maximum
        or len(value) > MAX_SAFE_JSON_INTEGER
    ):
        raise NativeStoreError


def _require_position(value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_SAFE_JSON_INTEGER
    ):
        raise NativeStoreError


def _raise_capsule_error() -> NoReturn:
    try:
        raise NativeStoreError from None
    except NativeStoreError as error:
        error.__context__ = None
        raise
