"""Canonical private storage for one live Asterion Prime backend generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
from types import MappingProxyType
from typing import NoReturn

from .state import PrimeBackendIdentity, PrimeCheckpoint, PrimeStateError


_ERROR = "Prime session store is unavailable"
_VERSION = "asterion.prime-session-store/v1"
_IDENTITY_VERSION = "asterion.prime-session-identity/v1"
_MAX_INTEGER = (1 << 53) - 1
_DEFAULT_MAX_BYTES = 16 * 1024 * 1024
_DEFAULT_MAX_RECORD_BYTES = 1024 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_KIND = re.compile(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_BLOB_NAME = re.compile(
    r"(?:transcript|summary)-[0-9a-f]{64}\.blob|usage-[0-9a-f]{64}\.json"
)
_ROW_FIELDS = frozenset(
    {"version", "position", "previous_digest", "record_digest", "record"}
)
_RECORD_FIELDS = frozenset({"record_id", "kind", "payload"})
_CHECKPOINT_FIELDS = frozenset(
    {"checkpoint", "checkpoint_sha256", "summary_blob", "transcript_blob", "usage_blob"}
)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class PrimeStoreError(RuntimeError):
    """Body-free failure raised whenever durable state cannot be trusted."""

    def __init__(self) -> None:
        super().__init__(_ERROR)


def _fail() -> NoReturn:
    try:
        raise PrimeStoreError from None
    except PrimeStoreError as error:
        error.__context__ = None
        raise


@dataclass(frozen=True, slots=True, repr=False)
class PrimeStoreRecord:
    """One immutable logical record in the canonical private journal."""

    position: int
    record_id: str
    kind: str
    payload: Mapping[str, object]
    digest: str

    def __post_init__(self) -> None:
        if (
            type(self.position) is not int
            or not 1 <= self.position <= _MAX_INTEGER
            or type(self.record_id) is not str
            or _ID.fullmatch(self.record_id) is None
            or type(self.kind) is not str
            or _KIND.fullmatch(self.kind) is None
            or not isinstance(self.payload, Mapping)
        ):
            _fail()
        frozen = _freeze_mapping(self.payload)
        expected = _record_digest(self.record_id, self.kind, frozen)
        if self.digest != expected:
            _fail()
        object.__setattr__(self, "payload", frozen)

    def __repr__(self) -> str:
        return (
            "PrimeStoreRecord("
            f"position={self.position!r}, kind={self.kind!r}, digest={self.digest!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class PrimeRecoveredCheckpoint:
    """Exact private material validated against a durable checkpoint."""

    checkpoint: PrimeCheckpoint
    transcript: bytes
    summary: bytes | None
    usage: Mapping[str, object]

    def __post_init__(self) -> None:
        if (
            type(self.checkpoint) is not PrimeCheckpoint
            or type(self.transcript) is not bytes
            or (self.summary is not None and type(self.summary) is not bytes)
            or not isinstance(self.usage, Mapping)
        ):
            _fail()
        object.__setattr__(self, "usage", _freeze_mapping(self.usage))

    def __repr__(self) -> str:
        return (
            "PrimeRecoveredCheckpoint("
            f"checkpoint_digest={self.checkpoint.digest!r}, "
            f"transcript_bytes={len(self.transcript)!r}, "
            f"summary_bytes={None if self.summary is None else len(self.summary)!r})"
        )


def private_root_identity(root: os.PathLike[str] | str) -> str:
    """Return a path-free digest of an owned private directory's dev/inode."""

    descriptor = -1
    try:
        path = _root_path(root)
        descriptor = _open_root(path)
        details = os.fstat(descriptor)
        return _sha256(_canonical_bytes({"dev": details.st_dev, "ino": details.st_ino}))
    except PrimeStoreError:
        raise
    except (OSError, TypeError, ValueError, UnicodeError):
        _fail()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


# The shorter spelling is the backend-facing API.  Keep the prefixed spelling
# available for callers that prefer an unambiguous imported helper.
prime_private_root_identity = private_root_identity


class FilePrimeSessionStore:
    """One-writer, descriptor-bound, append-only private session store."""

    def __init__(
        self,
        root: os.PathLike[str] | str,
        identity: PrimeBackendIdentity,
        *,
        max_bytes: int = _DEFAULT_MAX_BYTES,
        max_record_bytes: int = _DEFAULT_MAX_RECORD_BYTES,
    ) -> None:
        self._root = Path(".")
        self._identity = identity
        self._max_bytes = max_bytes
        self._max_record_bytes = max_record_bytes
        self._root_fd = -1
        self._lock_fd = -1
        self._identity_fd = -1
        self._record_fd = -1
        self._root_identity: tuple[int, int] | None = None
        self._lock_identity: tuple[int, int] | None = None
        self._identity_identity: tuple[int, int] | None = None
        self._record_identity: tuple[int, int] | None = None
        self._record_stamp: tuple[int, int, int] | None = None
        self._identity_document = b""
        self._identity_document_sha256 = ""
        self._records: tuple[PrimeStoreRecord, ...] = ()
        self._by_id: dict[str, PrimeStoreRecord] = {}
        self._mutex = threading.RLock()
        self._closed = False
        self._poisoned = False
        self._continued_from: PrimeBackendIdentity | None = None
        self._highest_sealed_generation: int = 0
        try:
            if type(identity) is not PrimeBackendIdentity:
                _fail()
            _limit(max_bytes)
            _limit(max_record_bytes)
            if max_record_bytes > max_bytes:
                _fail()
            self._root = _root_path(root)
            self._identity_document = _identity_document(identity)
            self._identity_document_sha256 = _sha256(self._identity_document)
            self._root_fd = _open_root(self._root)
            root_details = os.fstat(self._root_fd)
            self._root_identity = _file_identity(root_details)
            if private_root_identity(self._root) != identity.private_root_identity:
                _fail()
            self._lock_fd, lock_created = _open_regular(
                self._root_fd, ".writer.lock", create=True, append=False
            )
            self._lock_identity = _file_identity(os.fstat(self._lock_fd))
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno in {errno.EACCES, errno.EAGAIN}:
                    _fail()
                raise
            self._identity_fd, identity_created = _open_regular(
                self._root_fd, "identity.json", create=True, append=False
            )
            self._identity_identity = _file_identity(os.fstat(self._identity_fd))
            self._initialize_identity(self._identity_fd, identity_created)
            self._record_fd, record_created = _open_regular(
                self._root_fd, "records.jsonl", create=True, append=True
            )
            self._record_identity = _file_identity(os.fstat(self._record_fd))
            self._load_records()
            self._validate_root_artifacts()
            self._compute_highest_sealed_generation()
            self._validate_checkpoints()
            if lock_created or identity_created or record_created:
                os.fsync(self._root_fd)
            self._confirm_bindings()
        except PrimeStoreError:
            self._close_descriptors()
            raise
        except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
            self._close_descriptors()
            _fail()

    @classmethod
    def open_continued(
        cls,
        prior_root: os.PathLike[str] | str,
        next_identity: PrimeBackendIdentity,
        *,
        max_bytes: int = _DEFAULT_MAX_BYTES,
        max_record_bytes: int = _DEFAULT_MAX_RECORD_BYTES,
    ) -> FilePrimeSessionStore:
        """Bind a NEW identity against an existing private_root.

        Sole entry point that widens the same-identity fail-closed rule. Rules:

        * The prior ``identity.json`` must exist and parse as a
          :class:`PrimeBackendIdentity`.
        * ``next_identity.private_root_identity`` MUST equal the on-disk
          private root's dev/ino digest.
        * ``next_identity.generation`` MUST equal ``prior.generation + 1``.
        * ``next_identity.continuation_id`` MUST equal ``prior.continuation_id``.
        * Every other identity field MUST equal the prior identity's value,
          EXCEPT ``worker_identity_sha256`` (a different host may host the
          continuing process; the swap is recorded via
          :attr:`continued_from` and asserted on the next write).

        The on-disk ``identity.json`` is rewritten with ``next_identity``.
        Historical records (including prior-generation checkpoints) are
        preserved and re-validated against a relaxed per-generation chain.
        The new store's ``write_checkpoint`` then refuses to seal any
        generation at or below the prior highest sealed generation —
        the durable "no committed effect replayed" guarantee.
        """

        store = cls.__new__(cls)
        store._root = Path(".")
        store._identity = next_identity
        store._max_bytes = max_bytes
        store._max_record_bytes = max_record_bytes
        store._root_fd = -1
        store._lock_fd = -1
        store._identity_fd = -1
        store._record_fd = -1
        store._root_identity = None
        store._lock_identity = None
        store._identity_identity = None
        store._record_identity = None
        store._record_stamp = None
        store._identity_document = b""
        store._identity_document_sha256 = ""
        store._records = ()
        store._by_id = {}
        store._mutex = threading.RLock()
        store._closed = False
        store._poisoned = False
        store._continued_from = None
        store._highest_sealed_generation = 0
        try:
            if type(next_identity) is not PrimeBackendIdentity:
                _fail()
            _limit(max_bytes)
            _limit(max_record_bytes)
            if max_record_bytes > max_bytes:
                _fail()
            store._root = _root_path(prior_root)
            prior_identity = _read_prior_identity(store._root)
            _enforce_continuation_rules(prior_identity, next_identity)
            store._continued_from = prior_identity
            store._identity_document = _identity_document(next_identity)
            store._identity_document_sha256 = _sha256(store._identity_document)
            store._root_fd = _open_root(store._root)
            root_details = os.fstat(store._root_fd)
            store._root_identity = _file_identity(root_details)
            if private_root_identity(store._root) != next_identity.private_root_identity:
                _fail()
            store._lock_fd, _ = _open_regular(
                store._root_fd, ".writer.lock", create=True, append=False
            )
            store._lock_identity = _file_identity(os.fstat(store._lock_fd))
            try:
                fcntl.flock(store._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno in {errno.EACCES, errno.EAGAIN}:
                    _fail()
                raise
            store._identity_fd, _ = _open_regular(
                store._root_fd, "identity.json", create=True, append=False
            )
            store._identity_identity = _file_identity(os.fstat(store._identity_fd))
            _rewrite_identity_document(store._identity_fd, store._identity_document)
            store._record_fd, _ = _open_regular(
                store._root_fd, "records.jsonl", create=True, append=True
            )
            store._record_identity = _file_identity(os.fstat(store._record_fd))
            store._load_records()
            store._validate_root_artifacts()
            store._compute_highest_sealed_generation()
            store._validate_checkpoints()
            os.fsync(store._root_fd)
            store._confirm_bindings()
        except PrimeStoreError:
            store._close_descriptors()
            raise
        except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
            store._close_descriptors()
            _fail()
        return store

    @property
    def position(self) -> int:
        with self._mutex:
            self._refresh_for_read()
            return len(self._records)

    @property
    def identity(self) -> PrimeBackendIdentity:
        """Return the exact immutable identity bound to this store."""

        with self._mutex:
            self._refresh_for_read()
            return self._identity

    def records(self) -> tuple[PrimeStoreRecord, ...]:
        with self._mutex:
            self._refresh_for_read()
            return self._records

    @property
    def continued_from(self) -> PrimeBackendIdentity | None:
        """Return the prior identity this store was continued from, if any.

        ``None`` for an initial open; the prior :class:`PrimeBackendIdentity`
        when this store was opened via :meth:`open_continued`. The prior
        worker ``worker_identity_sha256`` may differ from the current one; that
        swap is intentional and recorded here.
        """

        with self._mutex:
            return self._continued_from

    @property
    def highest_sealed_generation(self) -> int:
        """Return the highest generation that has at least one sealed checkpoint."""

        with self._mutex:
            self._refresh_for_read()
            return self._highest_sealed_generation

    def has_record(self, record_id: str) -> bool:
        with self._mutex:
            self._refresh_for_read()
            if type(record_id) is not str or _ID.fullmatch(record_id) is None:
                _fail()
            return record_id in self._by_id

    def append(
        self,
        record_id: str,
        kind: str,
        payload: Mapping[str, object],
        *,
        expected_position: int,
    ) -> PrimeStoreRecord:
        with self._mutex:
            try:
                self._refresh()
                return self._append_locked(
                    record_id, kind, payload, expected_position=expected_position
                )
            except PrimeStoreError:
                raise
            except (OSError, TypeError, ValueError, UnicodeError):
                self._poisoned = True
                _fail()

    def write_checkpoint(
        self,
        checkpoint: PrimeCheckpoint,
        *,
        expected_position: int,
        transcript: bytes,
        summary: bytes | None,
        usage: Mapping[str, object],
    ) -> PrimeStoreRecord:
        with self._mutex:
            try:
                self._refresh()
                if type(checkpoint) is not PrimeCheckpoint:
                    _fail()
                if type(transcript) is not bytes or (
                    summary is not None and type(summary) is not bytes
                ):
                    _fail()
                usage_bytes = _canonical_bytes(usage)
                if (
                    checkpoint.generation != self._identity.generation
                    or checkpoint.worker_identity_sha256
                    != self._identity.worker_identity_sha256
                    or checkpoint.continuation_id != self._identity.continuation_id
                    or checkpoint.private_transcript_sha256 != _sha256(transcript)
                    or checkpoint.summary_sha256
                    != (None if summary is None else _sha256(summary))
                    or checkpoint.usage_sha256 != _sha256(usage_bytes)
                    or checkpoint.public_event_cursor != self._public_cursor()
                ):
                    _fail()
                transcript_name = (
                    f"transcript-{checkpoint.private_transcript_sha256}.blob"
                )
                summary_name = (
                    None
                    if checkpoint.summary_sha256 is None
                    else f"summary-{checkpoint.summary_sha256}.blob"
                )
                usage_name = f"usage-{checkpoint.usage_sha256}.json"
                payload: dict[str, object] = {
                    "checkpoint": checkpoint.to_mapping(),
                    "checkpoint_sha256": checkpoint.digest,
                    "summary_blob": summary_name,
                    "transcript_blob": transcript_name,
                    "usage_blob": usage_name,
                }
                record_id = f"checkpoint:{checkpoint.checkpoint_id}"
                candidate = _new_record(
                    len(self._records) + 1, record_id, "checkpoint.sealed", payload
                )
                existing = self._by_id.get(record_id)
                if existing is not None:
                    if existing.digest != candidate.digest:
                        _fail()
                    self._recover_record(existing)
                    return existing
                checkpoints = self._checkpoint_records()
                prior = (
                    None
                    if not checkpoints
                    else PrimeCheckpoint.from_mapping(
                        checkpoints[-1].payload["checkpoint"]
                    ).digest
                )
                if checkpoint.prior_checkpoint_sha256 != prior:
                    _fail()
                encoded = _encode_row(
                    candidate, self._records[-1].digest if self._records else None
                )
                _encoded_record_limit(encoded, self._max_record_bytes)
                additions: list[tuple[str, bytes]] = [
                    (transcript_name, transcript),
                    (usage_name, usage_bytes),
                ]
                if summary_name is not None and summary is not None:
                    additions.append((summary_name, summary))
                new_blob_bytes = sum(
                    len(body)
                    for name, body in additions
                    if not _artifact_exists(self._root_fd, name)
                )
                if self._used_bytes() + new_blob_bytes + len(encoded) > self._max_bytes:
                    _fail()
                _expected_position(expected_position, len(self._records))
                for name, body in additions:
                    self._write_blob(name, body)
                record = self._append_encoded(candidate, encoded)
                if checkpoint.generation > self._highest_sealed_generation:
                    self._highest_sealed_generation = checkpoint.generation
                return record
            except PrimeStoreError:
                raise
            except (OSError, TypeError, ValueError, UnicodeError, PrimeStateError):
                self._poisoned = True
                _fail()

    def recover_checkpoint(self) -> PrimeRecoveredCheckpoint | None:
        with self._mutex:
            try:
                self._refresh_for_read()
                checkpoints = self._checkpoint_records()
                if not checkpoints:
                    return None
                return self._recover_record(checkpoints[-1])
            except PrimeStoreError:
                self._poisoned = True
                raise
            except (
                OSError,
                TypeError,
                ValueError,
                UnicodeError,
                json.JSONDecodeError,
                PrimeStateError,
            ):
                self._poisoned = True
                _fail()

    def close(self) -> None:
        with self._mutex:
            if self._closed:
                return
            self._closed = True
            self._close_descriptors()

    def __enter__(self) -> FilePrimeSessionStore:
        self._require_usable()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            "FilePrimeSessionStore("
            f"identity_digest={self._identity.digest!r}, "
            f"position={len(self._records)!r}, closed={self._closed!r})"
        )

    def _initialize_identity(self, descriptor: int, created: bool) -> None:
        expected = self._identity_document
        raw = _read_fd(descriptor)
        if created:
            if raw:
                _fail()
            _write_all(descriptor, expected, offset=0)
            os.ftruncate(descriptor, len(expected))
            os.fsync(descriptor)
        elif raw != expected:
            _fail()

    def _load_records(self) -> None:
        raw = _read_fd(self._record_fd)
        if len(raw) > self._max_bytes or (raw and not raw.endswith(b"\n")):
            _fail()
        records: list[PrimeStoreRecord] = []
        seen: set[str] = set()
        previous: str | None = None
        cursor = 0
        for position, line in enumerate(raw[:-1].split(b"\n") if raw else (), 1):
            if len(line) + 1 > self._max_record_bytes:
                _fail()
            try:
                value = json.loads(line.decode("utf-8", errors="strict"))
            except (UnicodeError, ValueError, json.JSONDecodeError):
                _fail()
            if (
                type(value) is not dict
                or set(value) != _ROW_FIELDS
                or _canonical_bytes(value) != line
                or value["version"] != _VERSION
                or value["position"] != position
                or value["previous_digest"] != previous
                or type(value["record"]) is not dict
                or set(value["record"]) != _RECORD_FIELDS
            ):
                _fail()
            item = value["record"]
            record = _new_record(
                position, item["record_id"], item["kind"], item["payload"]
            )
            if value["record_digest"] != record.digest or record.record_id in seen:
                _fail()
            if record.kind == "public.event":
                cursor += 1
                if record.payload.get("cursor") != cursor:
                    _fail()
            records.append(record)
            seen.add(record.record_id)
            previous = record.digest
        self._records = tuple(records)
        self._by_id = {record.record_id: record for record in records}
        self._record_stamp = _file_stamp(os.fstat(self._record_fd))

    def _append_locked(
        self,
        record_id: str,
        kind: str,
        payload: Mapping[str, object],
        *,
        expected_position: int,
    ) -> PrimeStoreRecord:
        candidate = _new_record(len(self._records) + 1, record_id, kind, payload)
        existing = self._by_id.get(candidate.record_id)
        if existing is not None:
            if existing.digest != candidate.digest:
                _fail()
            return existing
        _expected_position(expected_position, len(self._records))
        if (
            kind == "public.event"
            and candidate.payload.get("cursor") != self._public_cursor() + 1
        ):
            _fail()
        encoded = _encode_row(
            candidate, self._records[-1].digest if self._records else None
        )
        _encoded_record_limit(encoded, self._max_record_bytes)
        if self._used_bytes() + len(encoded) > self._max_bytes:
            _fail()
        return self._append_encoded(candidate, encoded)

    def _append_encoded(
        self, candidate: PrimeStoreRecord, encoded: bytes
    ) -> PrimeStoreRecord:
        try:
            _write_all(self._record_fd, encoded, append=True)
            os.fsync(self._record_fd)
            self._confirm_bindings()
        except BaseException:
            self._poisoned = True
            _fail()
        self._records = (*self._records, candidate)
        self._by_id = {**self._by_id, candidate.record_id: candidate}
        self._record_stamp = _file_stamp(os.fstat(self._record_fd))
        return candidate

    def _write_blob(self, name: str, body: bytes) -> None:
        descriptor = -1
        try:
            if _artifact_exists(self._root_fd, name):
                descriptor, _ = _open_regular(
                    self._root_fd, name, create=False, append=False
                )
                if _read_fd(descriptor) != body:
                    _fail()
                return
            descriptor, created = _open_regular(
                self._root_fd, name, create=True, append=False
            )
            if not created or _read_fd(descriptor):
                _fail()
            _write_all(descriptor, body, offset=0)
            os.ftruncate(descriptor, len(body))
            os.fsync(descriptor)
            os.fsync(self._root_fd)
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _recover_record(self, record: PrimeStoreRecord) -> PrimeRecoveredCheckpoint:
        if (
            record.kind != "checkpoint.sealed"
            or set(record.payload) != _CHECKPOINT_FIELDS
        ):
            _fail()
        try:
            checkpoint = PrimeCheckpoint.from_mapping(record.payload["checkpoint"])
        except PrimeStateError:
            _fail()
        if record.payload["checkpoint_sha256"] != checkpoint.digest:
            _fail()
        transcript_name = record.payload["transcript_blob"]
        summary_name = record.payload["summary_blob"]
        usage_name = record.payload["usage_blob"]
        if (
            transcript_name != f"transcript-{checkpoint.private_transcript_sha256}.blob"
            or usage_name != f"usage-{checkpoint.usage_sha256}.json"
            or summary_name
            != (
                None
                if checkpoint.summary_sha256 is None
                else f"summary-{checkpoint.summary_sha256}.blob"
            )
        ):
            _fail()
        transcript = self._read_blob(
            transcript_name, checkpoint.private_transcript_sha256
        )
        summary = (
            None
            if summary_name is None
            else self._read_blob(summary_name, checkpoint.summary_sha256)
        )
        usage_raw = self._read_blob(usage_name, checkpoint.usage_sha256)
        try:
            usage = json.loads(usage_raw.decode("utf-8", errors="strict"))
        except (UnicodeError, ValueError, json.JSONDecodeError):
            _fail()
        if type(usage) is not dict or _canonical_bytes(usage) != usage_raw:
            _fail()
        return PrimeRecoveredCheckpoint(checkpoint, transcript, summary, usage)

    def _read_blob(self, name: object, digest: object) -> bytes:
        if (
            type(name) is not str
            or _BLOB_NAME.fullmatch(name) is None
            or type(digest) is not str
            or _DIGEST.fullmatch(digest) is None
        ):
            _fail()
        descriptor = -1
        try:
            descriptor, _ = _open_regular(
                self._root_fd, name, create=False, append=False
            )
            raw = _read_fd(descriptor)
            if _sha256(raw) != digest:
                _fail()
            return raw
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _checkpoint_records(self) -> tuple[PrimeStoreRecord, ...]:
        return tuple(
            record for record in self._records if record.kind == "checkpoint.sealed"
        )

    def _validate_checkpoints(self) -> None:
        prior: str | None = None
        cursor = 0
        for record in self._records:
            if record.kind == "public.event":
                cursor += 1
            if record.kind != "checkpoint.sealed":
                continue
            recovered = self._recover_record(record)
            checkpoint = recovered.checkpoint
            if (
                checkpoint.generation > self._identity.generation
                or checkpoint.continuation_id != self._identity.continuation_id
                or checkpoint.public_event_cursor != cursor
                or checkpoint.prior_checkpoint_sha256 != prior
            ):
                _fail()
            if checkpoint.generation == self._identity.generation:
                if checkpoint.worker_identity_sha256 != self._identity.worker_identity_sha256:
                    _fail()
            prior = checkpoint.digest

    def _compute_highest_sealed_generation(self) -> None:
        highest = 0
        for record in self._records:
            if record.kind != "checkpoint.sealed":
                continue
            try:
                checkpoint = PrimeCheckpoint.from_mapping(record.payload["checkpoint"])
            except PrimeStateError:
                _fail()
            if checkpoint.generation > highest:
                highest = checkpoint.generation
        self._highest_sealed_generation = highest

    def _public_cursor(self) -> int:
        return sum(record.kind == "public.event" for record in self._records)

    def _used_bytes(self) -> int:
        total = 0
        for name in os.listdir(self._root_fd):
            if name == "records.jsonl" or _BLOB_NAME.fullmatch(name) is not None:
                details = os.stat(name, dir_fd=self._root_fd, follow_symlinks=False)
                if not stat.S_ISREG(details.st_mode):
                    _fail()
                total += details.st_size
        if total > self._max_bytes:
            _fail()
        return total

    def _validate_root_artifacts(self) -> None:
        allowed = {".writer.lock", "identity.json", "records.jsonl"}
        for name in os.listdir(self._root_fd):
            if name not in allowed and _BLOB_NAME.fullmatch(name) is None:
                _fail()
            details = os.stat(name, dir_fd=self._root_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_uid != os.getuid()
                or stat.S_IMODE(details.st_mode) != 0o600
                or details.st_nlink != 1
            ):
                _fail()
        self._used_bytes()

    def _refresh(self) -> None:
        self._require_usable()
        try:
            self._confirm_bindings()
            details = os.fstat(self._record_fd)
            stamp = _file_stamp(details)
            if stamp != self._record_stamp:
                old = self._records
                old_stamp = self._record_stamp
                self._load_records()
                if (
                    len(self._records) < len(old)
                    or self._records[: len(old)] != old
                    or (self._records == old and self._record_stamp != old_stamp)
                ):
                    _fail()
            self._validate_root_artifacts()
            self._validate_checkpoints()
        except PrimeStoreError:
            self._poisoned = True
            raise

    def _refresh_for_read(self) -> None:
        try:
            self._refresh()
        except PrimeStoreError:
            raise
        except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
            self._poisoned = True
            _fail()

    def _require_usable(self) -> None:
        if self._closed or self._poisoned:
            _fail()

    def _confirm_bindings(self) -> None:
        self._require_usable()
        root = os.fstat(self._root_fd)
        lock = os.fstat(self._lock_fd)
        identity = os.fstat(self._identity_fd)
        record = os.fstat(self._record_fd)
        if (
            not stat.S_ISDIR(root.st_mode)
            or root.st_uid != os.getuid()
            or stat.S_IMODE(root.st_mode) != 0o700
            or _file_identity(root) != self._root_identity
            or _file_identity(lock) != self._lock_identity
            or _file_identity(identity) != self._identity_identity
            or _file_identity(record) != self._record_identity
        ):
            _fail()
        path_details = os.lstat(self._root)
        if (
            not stat.S_ISDIR(path_details.st_mode)
            or _file_identity(path_details) != self._root_identity
            or path_details.st_uid != os.getuid()
            or stat.S_IMODE(path_details.st_mode) != 0o700
        ):
            _fail()
        _verify_regular_binding(self._root_fd, "records.jsonl", self._record_fd)
        _verify_regular_binding(self._root_fd, ".writer.lock", self._lock_fd)
        _verify_regular_binding(self._root_fd, "identity.json", self._identity_fd)
        identity_document = _read_fd(self._identity_fd)
        if (
            _sha256(identity_document) != self._identity_document_sha256
            or identity_document != self._identity_document
        ):
            _fail()

    def _close_descriptors(self) -> None:
        for descriptor in (
            self._record_fd,
            self._identity_fd,
            self._lock_fd,
            self._root_fd,
        ):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        self._record_fd = self._identity_fd = self._lock_fd = self._root_fd = -1


def _root_path(root: os.PathLike[str] | str) -> Path:
    if not isinstance(root, (str, os.PathLike)):
        _fail()
    path = Path(root)
    if ".." in path.parts:
        _fail()
    return Path(os.path.abspath(path))


def _open_root(path: Path) -> int:
    before = os.lstat(path)
    descriptor = os.open(path, os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC)
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(before.st_mode)
            or not stat.S_ISDIR(details.st_mode)
            or _file_identity(before) != _file_identity(details)
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o700
        ):
            _fail()
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_regular(
    root_fd: int, name: str, *, create: bool, append: bool
) -> tuple[int, bool]:
    flags = os.O_RDWR | _NOFOLLOW | _CLOEXEC | (os.O_APPEND if append else 0)
    created = False
    try:
        descriptor = os.open(name, flags, dir_fd=root_fd)
    except FileNotFoundError:
        if not create:
            raise
        try:
            descriptor = os.open(
                name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root_fd
            )
            created = True
        except FileExistsError:
            descriptor = os.open(name, flags, dir_fd=root_fd)
    try:
        if created:
            os.fchmod(descriptor, 0o600)
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_nlink != 1
        ):
            _fail()
        _verify_regular_binding(root_fd, name, descriptor)
        return descriptor, created
    except BaseException:
        os.close(descriptor)
        raise


def _verify_regular_binding(root_fd: int, name: str, descriptor: int) -> None:
    path_details = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    descriptor_details = os.fstat(descriptor)
    if (
        not stat.S_ISREG(path_details.st_mode)
        or _file_identity(path_details) != _file_identity(descriptor_details)
        or path_details.st_uid != os.getuid()
        or stat.S_IMODE(path_details.st_mode) != 0o600
        or path_details.st_nlink != 1
    ):
        _fail()


def _new_record(
    position: int, record_id: object, kind: object, payload: object
) -> PrimeStoreRecord:
    if (
        type(record_id) is not str
        or _ID.fullmatch(record_id) is None
        or type(kind) is not str
        or _KIND.fullmatch(kind) is None
        or not isinstance(payload, Mapping)
    ):
        _fail()
    frozen = _freeze_mapping(payload)
    return PrimeStoreRecord(
        position, record_id, kind, frozen, _record_digest(record_id, kind, frozen)
    )


def _record_digest(record_id: str, kind: str, payload: Mapping[str, object]) -> str:
    return _sha256(
        _canonical_bytes({"record_id": record_id, "kind": kind, "payload": payload})
    )


def _encode_row(record: PrimeStoreRecord, previous: str | None) -> bytes:
    return (
        _canonical_bytes(
            {
                "version": _VERSION,
                "position": record.position,
                "previous_digest": previous,
                "record_digest": record.digest,
                "record": {
                    "record_id": record.record_id,
                    "kind": record.kind,
                    "payload": record.payload,
                },
            }
        )
        + b"\n"
    )


def _canonical_bytes(value: object) -> bytes:
    plain = _json_value(value)
    return json.dumps(
        plain, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _identity_document(identity: PrimeBackendIdentity) -> bytes:
    return (
        _canonical_bytes(
            {"version": _IDENTITY_VERSION, "identity": identity.to_mapping()}
        )
        + b"\n"
    )


def _read_prior_identity(root: Path) -> PrimeBackendIdentity:
    descriptor = -1
    try:
        descriptor = os.open(
            "identity.json",
            os.O_RDONLY | _NOFOLLOW | _CLOEXEC,
            dir_fd=_open_root(root),
        )
        raw = _read_fd(descriptor)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        _fail()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, ValueError, json.JSONDecodeError):
        _fail()
    if (
        type(value) is not dict
        or set(value) != {"version", "identity"}
        or value.get("version") != _IDENTITY_VERSION
        or not isinstance(value.get("identity"), Mapping)
    ):
        _fail()
    try:
        return PrimeBackendIdentity.from_mapping(value["identity"])
    except PrimeStateError:
        _fail()
    except (TypeError, ValueError):
        _fail()


def _enforce_continuation_rules(
    prior: PrimeBackendIdentity, next_identity: PrimeBackendIdentity
) -> None:
    if next_identity.generation != prior.generation + 1:
        _fail()
    if next_identity.continuation_id != prior.continuation_id:
        _fail()
    if next_identity.session_id != prior.session_id:
        _fail()
    if next_identity.provider_id != prior.provider_id:
        _fail()
    if next_identity.application_id != prior.application_id:
        _fail()
    if next_identity.application_version != prior.application_version:
        _fail()
    if next_identity.runtime_id != prior.runtime_id:
        _fail()
    if next_identity.pi_command_sha256 != prior.pi_command_sha256:
        _fail()
    if next_identity.extension_binding_fingerprint != prior.extension_binding_fingerprint:
        _fail()
    if next_identity.private_root_identity != prior.private_root_identity:
        _fail()
    if next_identity.ceilings_sha256 != prior.ceilings_sha256:
        _fail()


def _rewrite_identity_document(descriptor: int, document: bytes) -> None:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        _write_all(descriptor, document, offset=0)
        os.ftruncate(descriptor, len(document))
        os.fsync(descriptor)
    except (OSError, ValueError):
        _fail()


def _json_value(value: object, depth: int = 0) -> object:
    if depth > 64:
        _fail()
    if value is None or type(value) in {bool, str}:
        if type(value) is str:
            try:
                value.encode("utf-8")
            except UnicodeError:
                _fail()
        return value
    if type(value) is int:
        if not -_MAX_INTEGER <= value <= _MAX_INTEGER:
            _fail()
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, child in value.items():
            if type(key) is not str or key in result:
                _fail()
            result[key] = _json_value(child, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_value(child, depth + 1) for child in value]
    _fail()


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    plain = _json_value(value)
    assert isinstance(plain, dict)
    return MappingProxyType({key: _freeze(child) for key, child in plain.items()})


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _read_fd(descriptor: int) -> bytes:
    with os.fdopen(os.dup(descriptor), "rb", buffering=0) as stream:
        stream.seek(0)
        return stream.read()


def _write_all(
    descriptor: int,
    body: bytes,
    *,
    append: bool = False,
    offset: int | None = None,
) -> None:
    if offset is not None:
        os.lseek(descriptor, offset, os.SEEK_SET)
    elif append:
        os.lseek(descriptor, 0, os.SEEK_END)
    written = 0
    while written < len(body):
        count = os.write(descriptor, body[written:])
        if count < 1:
            raise OSError
        written += count


def _artifact_exists(root_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_identity(details: os.stat_result) -> tuple[int, int]:
    return details.st_dev, details.st_ino


def _file_stamp(details: os.stat_result) -> tuple[int, int, int]:
    return details.st_size, details.st_mtime_ns, details.st_ctime_ns


def _expected_position(value: object, current: int) -> None:
    if type(value) is not int or value != current:
        _fail()


def _limit(value: object) -> None:
    if type(value) is not int or not 1 <= value <= _MAX_INTEGER:
        _fail()


def _encoded_record_limit(encoded: bytes, maximum: int) -> None:
    if len(encoded) > maximum:
        _fail()


__all__ = [
    "FilePrimeSessionStore",
    "PrimeRecoveredCheckpoint",
    "PrimeStoreError",
    "PrimeStoreRecord",
    "prime_private_root_identity",
    "private_root_identity",
]
