from __future__ import annotations

import hashlib
import json
import os
import queue
import stat
import tempfile
import threading
import traceback
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Callable, NoReturn, cast
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
    NativeRootIdentity,
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


def bound_record_with_authority_revision(revision: int) -> NativeRecord:
    return session_bound_record(
        provider_id="native",
        provider_version="0.1.0",
        system_id="research.system",
        system_version="1.0.0",
        session_id=SESSION_ID,
        generation=1,
        checkpoint_version="1.0.0",
        authority_id="authority-1",
        authority_revision=revision,
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
    def assert_redacted_store_error(self, error: BaseException) -> None:
        self.assertIs(type(error), NativeStoreError)
        self.assertEqual(str(error), "native session store is unavailable")
        self.assertNotIn("SENTINEL_SECRET", str(error))
        self.assertNotIn("SENTINEL_SECRET", repr(error))
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)

    def assert_traceback_chain_redacted(
        self,
        error: BaseException,
        *sentinels: str,
    ) -> None:
        formatted = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        for sentinel in sentinels:
            self.assertNotIn(sentinel, formatted)
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)

    def test_file_session_accepts_exact_expected_root_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            root_stat = root.stat(follow_symlinks=False)
            session = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
                expected_root_identity=NativeRootIdentity(
                    root_stat.st_dev,
                    root_stat.st_ino,
                ),
            )
            try:
                self.assertTrue(session_child(root).is_dir())
            finally:
                session.close()

    def test_file_session_rejects_expected_root_identity_mismatch_before_children(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "root"
            other = parent / "other"
            root.mkdir(mode=0o700)
            other.mkdir(mode=0o700)
            root.chmod(0o700)
            other.chmod(0o700)
            other_stat = other.stat(follow_symlinks=False)

            with self.assertRaises(NativeStoreError) as captured:
                NativeSessionDirectory.open(
                    root,
                    SESSION_ID,
                    max_total_private_bytes=1_000_000,
                    expected_root_identity=NativeRootIdentity(
                        other_stat.st_dev,
                        other_stat.st_ino,
                    ),
                )

            self.assert_redacted_store_error(captured.exception)
            self.assertFalse(session_child(root).exists())
            session = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            session.close()

    def test_file_session_rejects_hostile_expected_root_identity_shape(
        self,
    ) -> None:
        class HostileTuple(tuple[object, ...]):
            effects = 0

            def __iter__(self) -> NoReturn:
                type(self).effects += 1
                raise AssertionError("SENTINEL_SECRET")

            def __getattribute__(self, name: str) -> object:
                if name in {"st_dev", "st_ino", "dev", "ino"}:
                    type(self).effects += 1
                    raise AssertionError("SENTINEL_SECRET")
                return super().__getattribute__(name)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)

            for label, expected in (
                ("tuple-subclass", HostileTuple((1, 2))),
                ("bool-dev", NativeRootIdentity.__new__(NativeRootIdentity)),
            ):
                with self.subTest(label=label):
                    if label == "bool-dev":
                        object.__setattr__(expected, "dev", True)
                        object.__setattr__(expected, "ino", 1)
                    with self.assertRaises(NativeStoreError) as captured:
                        NativeSessionDirectory.open(
                            root,
                            SESSION_ID,
                            max_total_private_bytes=1_000_000,
                            expected_root_identity=cast(NativeRootIdentity, expected),
                        )
                    self.assert_redacted_store_error(captured.exception)
                    self.assertFalse(session_child(root).exists())

            self.assertEqual(HostileTuple.effects, 0)

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

    def test_session_directory_counts_capsule_receipt_finals_and_temps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            session.close()
            capsules = session_child(root) / "capsules"
            body = capsules / f"{'a' * 64}.capsule"
            receipt = capsules / f"{'a' * 64}.capsule-receipt"
            temp = capsules / f".capsule-receipt-{'b' * 32}.tmp"
            body.write_bytes(b"body")
            receipt.write_bytes(b"receipt")
            temp.write_bytes(b"temp")
            body.chmod(0o600)
            receipt.chmod(0o600)
            temp.chmod(0o600)

            with self.assertRaises(NativeStoreError) as raised:
                NativeSessionDirectory.open(
                    root,
                    SESSION_ID,
                    max_total_private_bytes=len(b"bodyreceipttemp") - 1,
                )
            self.assert_redacted_store_error(raised.exception)

            reopened = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=len(b"bodyreceipttemp"),
            )
            self.addCleanup(reopened.close)
            self.assertEqual(reopened.budget.used_bytes, len(b"bodyreceipttemp"))
            reopened.close()

            unknown = capsules / "unknown.capsule-receipt"
            unknown.write_bytes(b"x")
            unknown.chmod(0o600)
            with self.assertRaises(NativeStoreError) as raised:
                NativeSessionDirectory.open(
                    root,
                    SESSION_ID,
                    max_total_private_bytes=1_000_000,
                )
            self.assert_redacted_store_error(raised.exception)

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

    def test_file_store_rejects_hardlinked_private_regular_files(self) -> None:
        for label, builder in hardlink_cases():
            with self.subTest(label=label):
                with self.assertRaises(NativeStoreError) as raised:
                    builder()
                self.assert_redacted_store_error(raised.exception)

    def test_file_store_rejects_hardlinked_publication_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            original_write_all = store_module._write_all
            token = "c" * 32
            temporary = records / f".record-00000000000000000001-{token}.tmp"
            outside = session_child(root) / "publication-hardlink"

            def hardlink_then_write(descriptor: int, data: bytes) -> None:
                os.link(temporary, outside)
                original_write_all(descriptor, data)

            with (
                patch.object(store_module.secrets, "token_hex", return_value=token),
                patch.object(store_module, "_write_all", hardlink_then_write),
                self.assertRaises(NativeStoreError) as raised,
            ):
                store.append(0, bound_record())

            self.assert_redacted_store_error(raised.exception)
            self.assertFalse(temporary.exists())
            self.assertTrue(outside.exists())

    def test_file_store_rejects_oversized_records_before_reading_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            entry = NativeEntry(1, None, bound_record())
            payload = canonical_entry_bytes(entry) + (b"x" * 1024)
            write_entry(records, entry, payload)
            session.close()
            reopened = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            self.addCleanup(reopened.close)
            original_read = os.read
            read_bytes = 0

            def counting_read(descriptor: int, length: int) -> bytes:
                nonlocal read_bytes
                chunk = original_read(descriptor, length)
                read_bytes += len(chunk)
                return chunk

            with (
                patch.object(store_module.os, "read", counting_read),
                self.assertRaises(NativeStoreError) as raised,
            ):
                FileNativeSessionStore(
                    reopened,
                    max_record_bytes=len(canonical_entry_bytes(entry)) - 1,
                )

            self.assert_redacted_store_error(raised.exception)
            self.assertEqual(read_bytes, 0)

    def test_file_store_rejects_record_growth_after_eof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            entry = NativeEntry(1, None, bound_record())
            record_path = records / final_name(entry)
            write_entry(records, entry)
            session.close()
            reopened = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            self.addCleanup(reopened.close)
            original_read = os.read
            appended = False

            def grow_after_eof(descriptor: int, length: int) -> bytes:
                nonlocal appended
                chunk = original_read(descriptor, length)
                if chunk == b"" and not appended:
                    appended = True
                    with record_path.open("ab") as handle:
                        handle.write(b" ")
                return chunk

            with (
                patch.object(store_module.os, "read", grow_after_eof),
                self.assertRaises(NativeStoreError) as raised,
            ):
                FileNativeSessionStore(
                    reopened,
                    max_record_bytes=len(canonical_entry_bytes(entry)) + 10,
                )

            self.assert_redacted_store_error(raised.exception)

    def test_memory_and_file_stores_reject_hostile_record_subclasses_redacted(self) -> None:
        owner = MemoryNativeStorageOwner(maximum_bytes=1_000_000)
        memory = MemoryNativeSessionStore(owner, max_record_bytes=65_536)
        self.addCleanup(owner.close)
        self.addCleanup(memory.close)

        with self.assertRaises(NativeStoreError) as memory_error:
            memory.append(0, hostile_record())
        self.assert_redacted_store_error(memory_error.exception)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, _records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)

            with self.assertRaises(NativeStoreError) as file_error:
                store.append(0, hostile_record())
            self.assert_redacted_store_error(file_error.exception)

    def test_two_file_borrowers_equal_append_publish_once_without_double_charge(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            first = FileNativeSessionStore(session, max_record_bytes=65_536)
            second = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(first.close)
            self.addCleanup(second.close)
            rename_barrier = threading.Barrier(2)
            original_rename = os.rename

            def racing_rename(
                src: str,
                dst: str,
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                rename_barrier.wait(timeout=5)
                original_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

            with patch.object(store_module.os, "rename", racing_rename):
                results = run_two_appends(
                    (first, 0, bound_record()),
                    (second, 0, bound_record()),
                )

            entries = assert_two_successes(self, results)
            self.assertEqual(entries[0], entries[1])
            final_files = list(records.glob("*.record"))
            self.assertEqual(final_files, [records / final_name(entries[0])])
            self.assertEqual(final_files[0].stat().st_nlink, 1)
            self.assertEqual(
                session.budget.used_bytes,
                len(canonical_entry_bytes(entries[0])),
            )

    def test_two_file_borrowers_conflicting_append_has_one_fixed_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            bootstrap = FileNativeSessionStore(session, max_record_bytes=65_536)
            bootstrap.append(0, bound_record())
            first = FileNativeSessionStore(session, max_record_bytes=65_536)
            second = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(bootstrap.close)
            self.addCleanup(first.close)
            self.addCleanup(second.close)
            rename_barrier = threading.Barrier(2)
            original_rename = os.rename

            def racing_rename(
                src: str,
                dst: str,
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                rename_barrier.wait(timeout=5)
                original_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

            with patch.object(store_module.os, "rename", racing_rename):
                results = run_two_appends(
                    (first, 1, authority_record()),
                    (second, 1, authority_record(2)),
                )

            entries, errors = split_results(results)
            self.assertEqual(len(entries), 1)
            self.assertEqual(len(errors), 1)
            self.assert_redacted_store_error(errors[0])
            self.assertEqual(len(list(records.glob("*.record"))), 2)

    def test_file_borrower_stale_position_fails_after_owner_serialized_refresh(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, _records = prepared_file_session(root)
            first = FileNativeSessionStore(session, max_record_bytes=65_536)
            second = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(first.close)
            self.addCleanup(second.close)

            committed = first.append(0, bound_record())
            with self.assertRaises(NativeStoreError) as raised:
                second.append(0, bound_record_with_authority_revision(2))

            self.assert_redacted_store_error(raised.exception)
            self.assertEqual(first.replay(), (committed,))
            self.assertEqual(second.replay(), (committed,))

    def test_file_publish_never_overwrites_existing_final_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            entry = NativeEntry(1, None, bound_record())
            preexisting = records / final_name(entry)
            original_write_all = store_module._write_all

            def create_final_then_write(descriptor: int, data: bytes) -> None:
                preexisting.write_bytes(b"SENTINEL_SECRET")
                preexisting.chmod(0o600)
                original_write_all(descriptor, data)

            with (
                patch.object(store_module, "_write_all", create_final_then_write),
                self.assertRaises(NativeStoreError) as raised,
            ):
                store.append(0, bound_record())

            self.assert_redacted_store_error(raised.exception)
            self.assertEqual(preexisting.read_bytes(), b"SENTINEL_SECRET")
            self.assertEqual(preexisting.stat().st_nlink, 1)
            self.assertEqual(list(records.glob(".record-*.tmp")), [])
            self.assertEqual(session.budget.used_bytes, 0)

    def test_memory_borrowers_share_owner_serialized_journal_and_budget(self) -> None:
        owner = MemoryNativeStorageOwner(maximum_bytes=1_000_000)
        first = MemoryNativeSessionStore(owner, max_record_bytes=65_536)
        second = MemoryNativeSessionStore(owner, max_record_bytes=65_536)
        self.addCleanup(owner.close)
        self.addCleanup(first.close)
        self.addCleanup(second.close)

        entry = first.append(0, bound_record())
        self.assertEqual(second.append(1, bound_record()), entry)
        self.assertEqual(second.replay(), (entry,))
        self.assertEqual(owner.budget.used_bytes, len(canonical_entry_bytes(entry)))
        with self.assertRaises(NativeStoreError) as raised:
            second.append(1, bound_record_with_authority_revision(2))
        self.assert_redacted_store_error(raised.exception)

    def test_file_close_waits_for_append_and_cannot_redirect_to_reused_fd(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            token = "1" * 32
            expected = NativeEntry(1, None, bound_record())
            attacker = session_child(root) / "attacker"
            attacker.mkdir(mode=0o700)
            attacker_temp = attacker / f".record-00000000000000000001-{token}.tmp"
            attacker_temp.write_bytes(canonical_entry_bytes(expected))
            attacker_temp.chmod(0o600)
            entered = threading.Event()
            release = threading.Event()
            original_write_all = store_module._write_all

            def blocked_write(descriptor: int, data: bytes) -> None:
                entered.set()
                self.assertTrue(release.wait(timeout=5))
                original_write_all(descriptor, data)

            with (
                patch.object(store_module.secrets, "token_hex", return_value=token),
                patch.object(store_module, "_write_all", blocked_write),
            ):
                append_results = run_threaded_call(
                    lambda: store.append(0, bound_record())
                )
                self.assertTrue(entered.wait(timeout=5))
                close_results = run_threaded_call(store.close)
                attacker_fd = -1
                try:
                    close_results.thread.join(timeout=0.05)
                    self.assertTrue(close_results.thread.is_alive())
                    attacker_fd = os.open(str(attacker), os.O_RDONLY | os.O_DIRECTORY)
                finally:
                    release.set()
                    append_results.thread.join(timeout=5)
                    close_results.thread.join(timeout=5)
                    if attacker_fd >= 0:
                        os.close(attacker_fd)

            self.assertFalse(append_results.thread.is_alive())
            self.assertFalse(close_results.thread.is_alive())
            self.assertEqual(append_results.value_or_raise(), expected)
            close_results.value_or_raise()
            self.assertEqual(list(attacker.iterdir()), [attacker_temp])
            self.assertEqual(list(records.glob("*.record")), [records / final_name(expected)])
            with self.assertRaises(NativeStoreError) as raised:
                store.replay()
            self.assert_redacted_store_error(raised.exception)

    def test_file_close_waits_for_replay_then_post_close_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, _records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            entry = store.append(0, bound_record())
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            entered = threading.Event()
            release = threading.Event()
            original_read_child = store_module._read_child_file

            def blocked_read(
                parent_fd: int,
                name: str,
                mode: int,
                max_bytes: int,
            ) -> bytes:
                entered.set()
                self.assertTrue(release.wait(timeout=5))
                return original_read_child(parent_fd, name, mode, max_bytes)

            with patch.object(store_module, "_read_child_file", blocked_read):
                replay_results = run_threaded_call(store.replay)
                self.assertTrue(entered.wait(timeout=5))
                close_results = run_threaded_call(store.close)
                try:
                    close_results.thread.join(timeout=0.05)
                    self.assertTrue(close_results.thread.is_alive())
                finally:
                    release.set()
                    replay_results.thread.join(timeout=5)
                    close_results.thread.join(timeout=5)

            self.assertEqual(replay_results.value_or_raise(), (entry,))
            close_results.value_or_raise()
            with self.assertRaises(NativeStoreError) as raised:
                store.position
            self.assert_redacted_store_error(raised.exception)

    def test_memory_close_waits_for_append_then_post_close_fails(self) -> None:
        owner = MemoryNativeStorageOwner(maximum_bytes=1_000_000)
        store = MemoryNativeSessionStore(owner, max_record_bytes=65_536)
        self.addCleanup(owner.close)
        self.addCleanup(store.close)
        expected = NativeEntry(1, None, bound_record())
        entered = threading.Event()
        release = threading.Event()
        original_validate = store_module._validate_entries

        def blocked_validate(entries: tuple[NativeEntry, ...]) -> None:
            if entries == (expected,):
                entered.set()
                self.assertTrue(release.wait(timeout=5))
            original_validate(entries)

        with patch.object(store_module, "_validate_entries", blocked_validate):
            append_results = run_threaded_call(lambda: store.append(0, bound_record()))
            self.assertTrue(entered.wait(timeout=5))
            close_results = run_threaded_call(store.close)
            try:
                close_results.thread.join(timeout=0.05)
                self.assertTrue(close_results.thread.is_alive())
            finally:
                release.set()
                append_results.thread.join(timeout=5)
                close_results.thread.join(timeout=5)

        self.assertEqual(append_results.value_or_raise(), expected)
        close_results.value_or_raise()
        with self.assertRaises(NativeStoreError) as raised:
            store.replay()
        self.assert_redacted_store_error(raised.exception)

    def test_failed_publication_retains_reservation_when_temp_alias_survives(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            expected = NativeEntry(1, None, bound_record())
            encoded = canonical_entry_bytes(expected)
            token = "2" * 32
            temporary = records / f".record-00000000000000000001-{token}.tmp"
            alias = session_child(root) / "retained-temp-alias"

            def alias_then_fail(_descriptor: int, _data: bytes) -> None:
                os.link(temporary, alias)
                raise OSError("SENTINEL_SECRET")

            with (
                patch.object(store_module.secrets, "token_hex", return_value=token),
                patch.object(store_module, "_write_all", alias_then_fail),
                self.assertRaises(NativeStoreError) as raised,
            ):
                store.append(0, bound_record())

            self.assert_redacted_store_error(raised.exception)
            self.assertFalse(temporary.exists())
            self.assertTrue(alias.exists())
            self.assertEqual(session.budget.used_bytes, len(encoded))

    def test_failed_publication_releases_only_after_temp_inode_is_gone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            token = "3" * 32
            temporary = records / f".record-00000000000000000001-{token}.tmp"
            retained = records / f".record-00000000000000000000-{'4' * 32}.tmp"
            retained.write_bytes(b"foreign")
            retained.chmod(0o600)
            observed_unlinked_fd_nlinks: list[int] = []
            original_fstat = os.fstat

            def fail_write(_descriptor: int, _data: bytes) -> None:
                raise OSError("SENTINEL_SECRET")

            def recording_fstat(descriptor: int) -> os.stat_result:
                result = original_fstat(descriptor)
                if result.st_nlink == 0:
                    observed_unlinked_fd_nlinks.append(result.st_nlink)
                return result

            with (
                patch.object(store_module.secrets, "token_hex", return_value=token),
                patch.object(store_module, "_write_all", fail_write),
                patch.object(store_module.os, "fstat", recording_fstat),
                self.assertRaises(NativeStoreError) as raised,
            ):
                store.append(0, bound_record())

            self.assert_redacted_store_error(raised.exception)
            self.assertIn(0, observed_unlinked_fd_nlinks)
            self.assertFalse(temporary.exists())
            self.assertTrue(retained.exists())
            self.assertEqual(session.budget.used_bytes, 0)

    def test_failed_publication_retains_reservation_when_cleanup_proof_fails(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            expected = NativeEntry(1, None, bound_record())
            encoded = canonical_entry_bytes(expected)
            token = "5" * 32
            temporary = records / f".record-00000000000000000001-{token}.tmp"
            original_fstat = os.fstat
            original_unlink = os.unlink
            cleanup_started = False

            def fail_write(_descriptor: int, _data: bytes) -> None:
                raise OSError("SENTINEL_SECRET")

            def mark_cleanup_unlink(name: str, *, dir_fd: int | None = None) -> None:
                nonlocal cleanup_started
                original_unlink(name, dir_fd=dir_fd)
                cleanup_started = True

            def fail_cleanup_fstat(descriptor: int) -> os.stat_result:
                if cleanup_started:
                    raise OSError("SENTINEL_SECRET")
                return original_fstat(descriptor)

            with (
                patch.object(store_module.secrets, "token_hex", return_value=token),
                patch.object(store_module, "_write_all", fail_write),
                patch.object(store_module.os, "unlink", mark_cleanup_unlink),
                patch.object(store_module.os, "fstat", fail_cleanup_fstat),
                self.assertRaises(NativeStoreError) as raised,
            ):
                store.append(0, bound_record())

            self.assert_redacted_store_error(raised.exception)
            self.assertFalse(temporary.exists())
            self.assertEqual(session.budget.used_bytes, len(encoded))

    def test_failed_publication_does_not_delete_replaced_temp_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            expected = NativeEntry(1, None, bound_record())
            encoded = canonical_entry_bytes(expected)
            token = "7" * 32
            temporary = records / f".record-00000000000000000001-{token}.tmp"
            replacement = b"foreign replacement"

            def replace_name_then_fail(_descriptor: int, _data: bytes) -> None:
                os.unlink(temporary)
                temporary.write_bytes(replacement)
                temporary.chmod(0o600)
                raise OSError("SENTINEL_SECRET")

            with (
                patch.object(store_module.secrets, "token_hex", return_value=token),
                patch.object(store_module, "_write_all", replace_name_then_fail),
                self.assertRaises(NativeStoreError) as raised,
            ):
                store.append(0, bound_record())

            self.assert_redacted_store_error(raised.exception)
            self.assertEqual(temporary.read_bytes(), replacement)
            self.assertEqual(session.budget.used_bytes, len(encoded))

    def test_keyboard_interrupt_cleanup_proves_removed_temp_before_propagating(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            token = "6" * 32
            temporary = records / f".record-00000000000000000001-{token}.tmp"
            observed_unlinked_fd_nlinks: list[int] = []
            original_fstat = os.fstat

            def interrupt_write(_descriptor: int, _data: bytes) -> None:
                raise KeyboardInterrupt

            def recording_fstat(descriptor: int) -> os.stat_result:
                result = original_fstat(descriptor)
                if result.st_nlink == 0:
                    observed_unlinked_fd_nlinks.append(result.st_nlink)
                return result

            with (
                patch.object(store_module.secrets, "token_hex", return_value=token),
                patch.object(store_module, "_write_all", interrupt_write),
                patch.object(store_module.os, "fstat", recording_fstat),
                self.assertRaises(KeyboardInterrupt),
            ):
                store.append(0, bound_record())

            self.assertIn(0, observed_unlinked_fd_nlinks)
            self.assertFalse(temporary.exists())
            self.assertEqual(session.budget.used_bytes, 0)

    def test_publication_release_failure_redacts_sensitive_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            expected = NativeEntry(1, None, bound_record())
            encoded = canonical_entry_bytes(expected)
            token = "8" * 32
            temporary = records / f".record-00000000000000000001-{token}.tmp"

            def fail_write(_descriptor: int, _data: bytes) -> None:
                raise OSError("SENTINEL_SECRET_RELEASE_ORIGINAL")

            def fail_release(_size: int) -> None:
                raise NativeStoreError

            with (
                patch.object(store_module.secrets, "token_hex", return_value=token),
                patch.object(store_module, "_write_all", fail_write),
                patch.object(session.budget, "release", fail_release),
                self.assertRaises(NativeStoreError) as raised,
            ):
                store.append(0, bound_record())

            self.assert_redacted_store_error(raised.exception)
            self.assert_traceback_chain_redacted(
                raised.exception,
                "SENTINEL_SECRET_RELEASE_ORIGINAL",
            )
            self.assertFalse(temporary.exists())
            self.assertEqual(session.budget.used_bytes, len(encoded))

    def test_cleanup_failure_redacts_sensitive_publication_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            expected = NativeEntry(1, None, bound_record())
            encoded = canonical_entry_bytes(expected)
            token = "9" * 32
            temporary = records / f".record-00000000000000000001-{token}.tmp"

            def fail_write(_descriptor: int, _data: bytes) -> None:
                raise OSError("SENTINEL_SECRET_CLEANUP_ORIGINAL")

            def fail_cleanup_sync(_descriptor: int) -> None:
                raise OSError("SENTINEL_SECRET_CLEANUP_FAILURE")

            with (
                patch.object(store_module.secrets, "token_hex", return_value=token),
                patch.object(store_module, "_write_all", fail_write),
                patch.object(store_module, "_fsync_directory", fail_cleanup_sync),
                patch.object(store_module, "_fsync_directory_quietly", fail_cleanup_sync),
                self.assertRaises(NativeStoreError) as raised,
            ):
                store.append(0, bound_record())

            self.assert_redacted_store_error(raised.exception)
            self.assert_traceback_chain_redacted(
                raised.exception,
                "SENTINEL_SECRET_CLEANUP_ORIGINAL",
                "SENTINEL_SECRET_CLEANUP_FAILURE",
            )
            self.assertFalse(temporary.exists())
            self.assertEqual(session.budget.used_bytes, len(encoded))

    def test_native_publication_error_release_failure_stays_context_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            expected = NativeEntry(1, None, bound_record())
            encoded = canonical_entry_bytes(expected)
            token = "a" * 32
            temporary = records / f".record-00000000000000000001-{token}.tmp"

            def fail_write(_descriptor: int, _data: bytes) -> None:
                raise NativeStoreError

            def fail_release(_size: int) -> None:
                raise NativeStoreError

            with (
                patch.object(store_module.secrets, "token_hex", return_value=token),
                patch.object(store_module, "_write_all", fail_write),
                patch.object(session.budget, "release", fail_release),
                self.assertRaises(NativeStoreError) as raised,
            ):
                store.append(0, bound_record())

            self.assert_redacted_store_error(raised.exception)
            self.assert_traceback_chain_redacted(raised.exception)
            self.assertFalse(temporary.exists())
            self.assertEqual(session.budget.used_bytes, len(encoded))

    def test_process_control_publication_error_survives_release_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            expected = NativeEntry(1, None, bound_record())
            encoded = canonical_entry_bytes(expected)
            token = "b" * 32
            temporary = records / f".record-00000000000000000001-{token}.tmp"

            def interrupt_write(_descriptor: int, _data: bytes) -> None:
                raise KeyboardInterrupt

            def fail_release(_size: int) -> None:
                raise NativeStoreError

            with (
                patch.object(store_module.secrets, "token_hex", return_value=token),
                patch.object(store_module, "_write_all", interrupt_write),
                patch.object(session.budget, "release", fail_release),
                self.assertRaises(KeyboardInterrupt) as raised,
            ):
                store.append(0, bound_record())

            self.assertIs(type(raised.exception), KeyboardInterrupt)
            self.assertFalse(temporary.exists())
            self.assertEqual(session.budget.used_bytes, len(encoded))


CorruptCase = Callable[[], None]
EntryMutator = Callable[[Path, Path, NativeEntry, NativeEntry], None]
AppendRequest = tuple[FileNativeSessionStore, int, NativeRecord]
AppendResult = tuple[str, NativeEntry | BaseException]


class ThreadedCallResult:
    def __init__(self, call: Callable[[], object]) -> None:
        self._results: queue.Queue[object] = queue.Queue()
        self.thread = threading.Thread(target=self._run, args=(call,))
        self.thread.start()

    def value_or_raise(self) -> object:
        result = self._results.get_nowait()
        if isinstance(result, BaseException):
            raise result
        return result

    def _run(self, call: Callable[[], object]) -> None:
        try:
            self._results.put(call())
        except BaseException as error:
            self._results.put(error)


def run_threaded_call(call: Callable[[], object]) -> ThreadedCallResult:
    return ThreadedCallResult(call)


def run_two_appends(left: AppendRequest, right: AppendRequest) -> list[AppendResult]:
    results: queue.Queue[AppendResult] = queue.Queue()

    def append(request: AppendRequest) -> None:
        store, expected_position, record = request
        try:
            results.put(("ok", store.append(expected_position, record)))
        except BaseException as error:
            results.put(("error", error))

    threads = (
        threading.Thread(target=append, args=(left,)),
        threading.Thread(target=append, args=(right,)),
    )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    if any(thread.is_alive() for thread in threads):
        raise AssertionError("concurrent append did not finish")
    return [results.get_nowait(), results.get_nowait()]


def split_results(results: list[AppendResult]) -> tuple[list[NativeEntry], list[BaseException]]:
    entries: list[NativeEntry] = []
    errors: list[BaseException] = []
    for status, value in results:
        if status == "ok":
            entries.append(cast(NativeEntry, value))
        else:
            errors.append(cast(BaseException, value))
    return entries, errors


def assert_two_successes(
    case: unittest.TestCase,
    results: list[AppendResult],
) -> list[NativeEntry]:
    entries, errors = split_results(results)
    case.assertEqual(errors, [])
    case.assertEqual(len(entries), 2)
    return entries


class HostileNativeRecord(NativeRecord):
    def __getattribute__(self, name: str) -> object:
        armed = False
        try:
            armed = bool(object.__getattribute__(self, "_armed"))
        except AttributeError:
            pass
        if armed and name in {"record_id", "kind", "payload", "digest"}:
            raise RuntimeError("SENTINEL_SECRET")
        return super().__getattribute__(name)


def hostile_record() -> NativeRecord:
    record = HostileNativeRecord(
        "hostile-record",
        "authority.synced",
        {
            "authority_revision": 1,
            "budget": {
                "controller_tokens": 100,
                "application_tokens": 0,
                "child_tokens": 0,
                "aggregate_tokens": 100,
                "cost_micros": 10_000,
                "deadline_ms": 60_000,
            },
        },
    )
    object.__setattr__(record, "_armed", True)
    return record


def hardlink_cases() -> list[tuple[str, CorruptCase]]:
    cases: list[tuple[str, CorruptCase]] = []

    def add(label: str, builder: CorruptCase) -> None:
        cases.append((label, builder))

    def hardlinked_final_record() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            entry = store.append(0, bound_record())
            store.close()
            session.close()
            os.link(records / final_name(entry), session_child(root) / "record-hardlink")
            reopened = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            try:
                FileNativeSessionStore(reopened, max_record_bytes=65_536)
            finally:
                reopened.close()

    add("final-record", hardlinked_final_record)

    def hardlinked_record_temp() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            session.close()
            temp = records / f".record-00000000000000000000-{'d' * 32}.tmp"
            temp.write_bytes(b"temporary")
            temp.chmod(0o600)
            os.link(temp, session_child(root) / "record-temp-hardlink")
            NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )

    add("record-temp", hardlinked_record_temp)

    def hardlinked_capsule_file() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, _records = prepared_file_session(root)
            session.close()
            capsules = session_child(root) / "capsules"
            capsule = capsules / f"{'e' * 64}.capsule"
            capsule.write_bytes(b"capsule")
            capsule.chmod(0o600)
            os.link(capsule, session_child(root) / "capsule-hardlink")
            NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )

    add("capsule-file", hardlinked_capsule_file)

    def hardlinked_capsule_temp() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, _records = prepared_file_session(root)
            session.close()
            capsules = session_child(root) / "capsules"
            capsule = capsules / f".capsule-{'f' * 32}.tmp"
            capsule.write_bytes(b"capsule")
            capsule.chmod(0o600)
            os.link(capsule, session_child(root) / "capsule-temp-hardlink")
            NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )

    add("capsule-temp", hardlinked_capsule_temp)

    def hardlinked_lock() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, _records = prepared_file_session(root)
            session.close()
            lock = session_child(root) / "lock"
            os.link(lock, session_child(root) / "lock-hardlink")
            NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )

    add("lock", hardlinked_lock)
    return cases


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
