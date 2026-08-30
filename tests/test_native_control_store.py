from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Callable, cast
from unittest.mock import patch

from asterion.control.authority import RemainingBudget
from asterion.control.providers.native import store as store_module
from asterion.control.providers.native.model import (
    MAX_SAFE_JSON_INTEGER,
    NATIVE_JOURNAL_VERSION,
    NativeEntry,
    NativeRecord,
    _json_value,
)
from asterion.control.providers.native.state import (
    authority_synced_record,
    session_bound_record,
)
from asterion.control.providers.native.store import (
    FileNativeSessionStore,
    MemoryNativeSessionStore,
    MemoryNativeStorageOwner,
    NativeSessionDirectory,
    NativeStoreError,
)


SESSION_ID = "session-1"


def bound_record(record_id_suffix: str = "") -> NativeRecord:
    if record_id_suffix == "":
        return session_bound_record(
            provider_id="native",
            provider_version="0.1.0",
            system_id="research.system",
            system_version="1.0.0",
            session_id=SESSION_ID,
            generation=1,
            checkpoint_version="1.0.0",
            authority_id="authority-1",
            authority_revision=1,
        )
    return NativeRecord(
        f"bound-{record_id_suffix}",
        "session.bound",
        {
            "provider_id": "native",
            "provider_version": "0.1.0",
            "system_id": "research.system",
            "system_version": "1.0.0",
            "session_id": SESSION_ID,
            "generation": 1,
            "checkpoint_version": "1.0.0",
            "authority_id": "authority-1",
            "authority_revision": 1,
        },
    )


def authority_record(revision: int = 1) -> NativeRecord:
    return authority_synced_record(
        revision,
        RemainingBudget(
            controller_tokens=100,
            application_tokens=0,
            child_tokens=0,
            aggregate_tokens=100,
            cost_micros=10_000,
            deadline_ms=60_000,
        ),
    )


def conflicting_authority_record() -> NativeRecord:
    return NativeRecord(
        authority_record().record_id,
        "authority.synced",
        {
            "authority_revision": 2,
            "budget": {
                "controller_tokens": 90,
                "application_tokens": 0,
                "child_tokens": 0,
                "aggregate_tokens": 90,
                "cost_micros": 9_000,
                "deadline_ms": 60_000,
            },
        },
    )


def entry_document(entry: NativeEntry) -> dict[str, object]:
    document: dict[str, object] = {
        "format": NATIVE_JOURNAL_VERSION,
        "position": entry.position,
        "previous_digest": entry.previous_digest,
        "record": {
            "record_id": entry.record.record_id,
            "kind": entry.record.kind,
            "payload": _json_value(entry.record.payload),
        },
    }
    document["entry_digest"] = entry.digest
    return document


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_entry_bytes(entry: NativeEntry) -> bytes:
    return canonical_bytes(entry_document(entry))


def final_name(entry: NativeEntry) -> str:
    return f"{entry.position:020d}-{entry.digest}.record"


def session_child(root: Path) -> Path:
    return root / hashlib.sha256(SESSION_ID.encode("utf-8")).hexdigest()


def write_entry(records: Path, entry: NativeEntry, data: bytes | None = None) -> None:
    path = records / final_name(entry)
    path.write_bytes(canonical_entry_bytes(entry) if data is None else data)
    path.chmod(0o600)


def prepared_file_session(root: Path) -> tuple[NativeSessionDirectory, Path]:
    root.chmod(0o700)
    session = NativeSessionDirectory.open(
        root,
        SESSION_ID,
        max_total_private_bytes=1_000_000,
    )
    return session, session_child(root) / "records"


class TestNativeControlStore(unittest.TestCase):
    def test_memory_store_deduplicates_conflicts_and_replays_slices(self) -> None:
        owner = MemoryNativeStorageOwner(maximum_bytes=1_000_000)
        store = MemoryNativeSessionStore(owner, max_record_bytes=65_536)
        self.addCleanup(owner.close)
        self.addCleanup(store.close)

        first = store.append(0, bound_record())
        second = store.append(1, authority_record())

        self.assertEqual(store.position, 2)
        self.assertEqual(store.replay(0), (first, second))
        self.assertEqual(store.replay(1), (second,))
        self.assertEqual(store.append(store.position, authority_record()), second)
        self.assertEqual(store.position, 2)

        with self.assertRaisesRegex(NativeStoreError, "native session store is unavailable"):
            store.append(0, authority_record())
        with self.assertRaisesRegex(NativeStoreError, "native session store is unavailable"):
            store.append(store.position, conflicting_authority_record())

    def test_memory_store_enforces_limits_and_close_semantics(self) -> None:
        owner = MemoryNativeStorageOwner(maximum_bytes=350)
        store = MemoryNativeSessionStore(owner, max_record_bytes=160)
        self.addCleanup(owner.close)
        self.addCleanup(store.close)

        with self.assertRaisesRegex(NativeStoreError, "native session store is unavailable"):
            store.append(0, bound_record())

        owner = MemoryNativeStorageOwner(maximum_bytes=1_000_000)
        store = MemoryNativeSessionStore(owner, max_record_bytes=65_536)
        store.close()
        with self.assertRaisesRegex(NativeStoreError, "native session store is unavailable"):
            store.replay()
        with self.assertRaisesRegex(NativeStoreError, "native session store is unavailable"):
            MemoryNativeSessionStore(owner, max_record_bytes=0)
        owner.close()
        with self.assertRaisesRegex(NativeStoreError, "native session store is unavailable"):
            MemoryNativeSessionStore(owner, max_record_bytes=65_536)

    def test_file_store_reopens_exact_committed_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, _records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            entry = store.append(0, bound_record())
            store.close()
            session.close()

            reopened_session = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            reopened = FileNativeSessionStore(
                reopened_session,
                max_record_bytes=65_536,
            )
            self.addCleanup(reopened_session.close)
            self.addCleanup(reopened.close)

            self.assertEqual(reopened.replay(0), (entry,))

    def test_file_store_deduplicates_conflicts_stale_positions_and_slices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, _records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)

            first = store.append(0, bound_record())
            second = store.append(1, authority_record())

            self.assertEqual(store.position, 2)
            self.assertEqual(store.replay(1), (second,))
            self.assertEqual(store.append(store.position, authority_record()), second)
            with self.assertRaisesRegex(NativeStoreError, "native session store is unavailable"):
                store.append(0, authority_record())
            with self.assertRaisesRegex(NativeStoreError, "native session store is unavailable"):
                store.append(store.position, conflicting_authority_record())
            self.assertEqual(store.replay(0), (first, second))

    def test_file_store_lock_permissions_pin_replacement_and_close(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)

            with self.assertRaisesRegex(NativeStoreError, "native session store is unavailable"):
                NativeSessionDirectory.open(
                    root,
                    SESSION_ID,
                    max_total_private_bytes=1_000_000,
                )

            session_dir = session_child(root)
            self.assertEqual(stat.S_IMODE(session_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(records.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((session_dir / "lock").stat().st_mode), 0o600)

            replaced_records = session_dir / "records.replaced"
            records.rename(replaced_records)
            (session_dir / "records").mkdir(mode=0o700)
            entry = store.append(0, bound_record())

            self.assertTrue((replaced_records / final_name(entry)).is_file())
            self.assertFalse((session_dir / "records" / final_name(entry)).exists())
            self.assertEqual(
                stat.S_IMODE((replaced_records / final_name(entry)).stat().st_mode),
                0o600,
            )

            store.close()
            with self.assertRaisesRegex(NativeStoreError, "native session store is unavailable"):
                store.position
            session.close()
            with self.assertRaisesRegex(NativeStoreError, "native session store is unavailable"):
                FileNativeSessionStore(session, max_record_bytes=65_536)

    def test_file_store_rejects_security_and_chain_failures_redacted(self) -> None:
        for label, corrupt in corruption_cases():
            with self.subTest(label=label), self.assertRaisesRegex(
                NativeStoreError,
                "native session store is unavailable",
            ) as raised:
                corrupt()
            self.assertNotIn("SENTINEL_SECRET", repr(raised.exception))

    def test_file_store_counts_committed_and_temporary_bytes_without_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            entry = store.append(0, bound_record())
            store.close()
            session.close()

            retained = records / f".record-00000000000000000001-{'a' * 32}.tmp"
            retained.write_bytes(b"x" * 50)
            retained.chmod(0o600)
            reopened = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=len(canonical_entry_bytes(entry)) + 50,
            )
            constrained = FileNativeSessionStore(reopened, max_record_bytes=65_536)
            self.addCleanup(reopened.close)
            self.addCleanup(constrained.close)

            with self.assertRaisesRegex(NativeStoreError, "native session store is unavailable"):
                constrained.append(constrained.position, authority_record())
            self.assertTrue(retained.exists())
            self.assertEqual(constrained.replay(), (entry,))

    def test_file_store_releases_failed_reservation_and_removes_only_own_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)

            retained = records / f".record-00000000000000000000-{'b' * 32}.tmp"
            retained.write_bytes(b"retained")
            retained.chmod(0o600)

            def fail_write(_descriptor: int, _data: bytes) -> None:
                raise OSError("SENTINEL_SECRET")

            with patch.object(store_module, "_write_all", fail_write):
                with self.assertRaisesRegex(
                    NativeStoreError,
                    "native session store is unavailable",
                ) as raised:
                    store.append(0, bound_record())

            self.assertNotIn("SENTINEL_SECRET", repr(raised.exception))
            self.assertEqual(list(records.glob(".record-*.tmp")), [retained])
            self.assertEqual(store.append(0, bound_record()).position, 1)


CorruptCase = Callable[[], None]
EntryMutator = Callable[[Path, Path, NativeEntry, NativeEntry], None]


def corruption_cases() -> list[tuple[str, CorruptCase]]:
    cases: list[tuple[str, CorruptCase]] = []

    def add(label: str, builder: CorruptCase) -> None:
        cases.append((label, builder))

    def root_mode() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o755)
            NativeSessionDirectory.open(root, SESSION_ID, max_total_private_bytes=1_000)

    add("root-mode", root_mode)

    def root_symlink() -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            target.mkdir(mode=0o700)
            link = Path(directory) / "link"
            link.symlink_to(target, target_is_directory=True)
            NativeSessionDirectory.open(link, SESSION_ID, max_total_private_bytes=1_000)

    add("root-symlink", root_symlink)

    def session_symlink() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            (root / "target").mkdir(mode=0o700)
            session_child(root).symlink_to("target", target_is_directory=True)
            NativeSessionDirectory.open(root, SESSION_ID, max_total_private_bytes=1_000)

    add("session-symlink", session_symlink)

    def child_symlink() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, _records = prepared_file_session(root)
            session.close()
            session_dir = session_child(root)
            os.rmdir(session_dir / "records")
            (session_dir / "records").symlink_to("capsules", target_is_directory=True)
            NativeSessionDirectory.open(root, SESSION_ID, max_total_private_bytes=1_000)

    add("child-symlink", child_symlink)

    def child_type() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            session_dir = session_child(root)
            session_dir.mkdir(mode=0o700)
            (session_dir / "records").write_text("not a directory")
            (session_dir / "records").chmod(0o700)
            NativeSessionDirectory.open(root, SESSION_ID, max_total_private_bytes=1_000)

    add("child-type", child_type)

    def child_mode() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, _records = prepared_file_session(root)
            session.close()
            (session_child(root) / "records").chmod(0o755)
            NativeSessionDirectory.open(root, SESSION_ID, max_total_private_bytes=1_000)

    add("child-mode", child_mode)

    def owner_mismatch() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            with patch.object(store_module, "_current_uid", return_value=os.geteuid() + 1):
                NativeSessionDirectory.open(
                    root,
                    SESSION_ID,
                    max_total_private_bytes=1_000,
                )

    add("owner-mismatch", owner_mismatch)

    def unsupported_nofollow() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            with patch.object(store_module, "_NOFOLLOW", "invalid"):
                NativeSessionDirectory.open(
                    root,
                    SESSION_ID,
                    max_total_private_bytes=1_000,
                )

    add("unsupported-nofollow", unsupported_nofollow)

    def two_entries(mutator: EntryMutator) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            first = NativeEntry(1, None, bound_record())
            second = NativeEntry(2, first.digest, authority_record())
            write_entry(records, first)
            write_entry(records, second)
            session.close()
            mutator(root, records, first, second)
            reopened = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            try:
                FileNativeSessionStore(reopened, max_record_bytes=65_536)
            finally:
                reopened.close()

    def missing(_root: Path, records: Path, first: NativeEntry, second: NativeEntry) -> None:
        (records / final_name(first)).unlink()

    add("missing", lambda: two_entries(missing))

    def reordered(
        _root: Path,
        records: Path,
        first: NativeEntry,
        _second: NativeEntry,
    ) -> None:
        moved = NativeEntry(2, None, first.record)
        (records / final_name(first)).rename(records / final_name(moved))

    add("reordered", lambda: two_entries(reordered))

    def forked(_root: Path, records: Path, first: NativeEntry, _second: NativeEntry) -> None:
        fork = NativeEntry(2, first.digest, bound_record("fork"))
        write_entry(records, fork)

    add("forked", lambda: two_entries(forked))

    def digest_corruption(
        _root: Path,
        records: Path,
        _first: NativeEntry,
        second: NativeEntry,
    ) -> None:
        document = entry_document(second)
        record = dict(cast(Mapping[str, object], document["record"]))
        payload = dict(cast(Mapping[str, object], record["payload"]))
        payload["authority_revision"] = 2
        record["payload"] = payload
        document["record"] = record
        write_entry(records, second, canonical_bytes(document))

    add("digest-corruption", lambda: two_entries(digest_corruption))

    def invalid_json(label: str, data: bytes) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            entry = NativeEntry(1, None, bound_record())
            write_entry(records, entry, data)
            session.close()
            reopened = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            try:
                FileNativeSessionStore(reopened, max_record_bytes=65_536)
            finally:
                reopened.close()

    entry = NativeEntry(1, None, bound_record())
    document = entry_document(entry)
    duplicate_keys = (
        b'{"entry_digest":"'
        + entry.digest.encode()
        + b'","entry_digest":"'
        + entry.digest.encode()
        + b'","format":"'
        + NATIVE_JOURNAL_VERSION.encode()
        + b'","position":1,"previous_digest":null,"record":{"kind":"session.bound",'
        + b'"payload":{},"record_id":"SENTINEL_SECRET"}}'
    )
    add("duplicate-json-keys", lambda: invalid_json("duplicate", duplicate_keys))
    add("trailing-newline", lambda: invalid_json("trailing", canonical_bytes(document) + b"\n"))
    noncanonical = json.dumps(document, sort_keys=False, indent=2).encode("utf-8")
    add("noncanonical", lambda: invalid_json("noncanonical", noncanonical))
    unsafe = dict(document)
    unsafe["position"] = MAX_SAFE_JSON_INTEGER + 1
    add("unsafe-int", lambda: invalid_json("unsafe-int", canonical_bytes(unsafe)))
    unknown = dict(document)
    unknown["SENTINEL_SECRET"] = "leak"
    add("unknown-field", lambda: invalid_json("unknown", canonical_bytes(unknown)))

    def filename_mismatch() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            write_entry(records, entry)
            wrong = records / f"{entry.position:020d}-{'0' * 64}.record"
            (records / final_name(entry)).rename(wrong)
            session.close()
            reopened = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            try:
                FileNativeSessionStore(reopened, max_record_bytes=65_536)
            finally:
                reopened.close()

    add("filename-mismatch", filename_mismatch)

    def record_mode() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            write_entry(records, entry)
            (records / final_name(entry)).chmod(0o644)
            session.close()
            reopened = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            try:
                FileNativeSessionStore(reopened, max_record_bytes=65_536)
            finally:
                reopened.close()

    add("record-mode", record_mode)

    def oversized() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, _records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=12)
            try:
                store.append(0, bound_record())
            finally:
                store.close()
                session.close()

    add("oversized", oversized)

    return cases
