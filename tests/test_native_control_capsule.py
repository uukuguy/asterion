from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import threading
import traceback
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from asterion.control.providers.native import capsule as capsule_module
from asterion.control.providers.native.model import NativeCapsuleMetadata
from asterion.control.providers.native.store import (
    FileNativeSessionStore,
    MemoryNativeStorageOwner,
    NativeSessionDirectory,
    NativeStoreError,
)

from tests.test_native_control_store import (
    bound_record,
    canonical_entry_bytes,
    prepared_file_session,
    session_child,
)


SESSION_ID = "session-1"
PROVIDER_ID = "native"
PROVIDER_VERSION = "0.1.0"
CHECKPOINT_VERSION = "1.0.0"
CAPSULE_DOMAIN = b"asterion.native-capsule/v1\x00"


def storage_ref(capsule_id: str) -> str:
    return hashlib.sha256(CAPSULE_DOMAIN + capsule_id.encode("utf-8")).hexdigest()


def capsule_path(root: Path, capsule_id: str) -> Path:
    return session_child(root) / "capsules" / f"{storage_ref(capsule_id)}.capsule"


def payload_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def metadata(
    capsule_id: str = "capsule-1",
    payload: bytes = b"SENTINEL_PRIVATE_CAPSULE",
    *,
    covered_position: int = 7,
    covered_sequence: int = 4,
) -> NativeCapsuleMetadata:
    return NativeCapsuleMetadata(
        capsule_id=capsule_id,
        capsule_digest=payload_digest(payload),
        control_plane_id=PROVIDER_ID,
        control_plane_version=PROVIDER_VERSION,
        checkpoint_version=CHECKPOINT_VERSION,
        covered_position=covered_position,
        covered_sequence=covered_sequence,
        storage_ref=storage_ref(capsule_id),
    )


class HostileBytes(bytes):
    pass


class TestNativeControlCapsule(unittest.TestCase):
    def assert_redacted_store_error(self, error: BaseException) -> None:
        self.assertIs(type(error), NativeStoreError)
        self.assertEqual(str(error), "native session store is unavailable")
        self.assertNotIn("SENTINEL", str(error))
        self.assertNotIn("SENTINEL", repr(error))
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

    def test_capsule_seal_is_idempotent_private_and_body_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            store = capsule_module.FileNativeCapsuleStore(
                session,
                max_capsule_bytes=65_536,
            )
            self.addCleanup(session.close)
            self.addCleanup(store.close)

            first = store.seal(
                capsule_id="capsule-1",
                payload=b"SENTINEL_PRIVATE_CAPSULE",
                covered_position=7,
                covered_sequence=4,
            )
            second = store.seal(
                capsule_id="capsule-1",
                payload=b"SENTINEL_PRIVATE_CAPSULE",
                covered_position=7,
                covered_sequence=4,
            )

            self.assertEqual(first, metadata())
            self.assertEqual(first, second)
            self.assertEqual(session.budget.used_bytes, len(b"SENTINEL_PRIVATE_CAPSULE"))
            self.assertNotIn("SENTINEL_PRIVATE_CAPSULE", repr(first))
            self.assertNotIn("storage_ref", repr(first))
            self.assertFalse(Path(first.storage_ref).is_absolute())
            self.assertEqual(first.storage_ref, storage_ref("capsule-1"))
            self.assertEqual(capsule_path(root, "capsule-1").read_bytes(), b"SENTINEL_PRIVATE_CAPSULE")
            self.assertEqual(
                stat.S_IMODE(capsule_path(root, "capsule-1").stat().st_mode),
                0o600,
            )

    def test_memory_capsules_share_owner_budget_and_conflict_rules(self) -> None:
        owner = MemoryNativeStorageOwner(maximum_bytes=64)
        first = capsule_module.MemoryNativeCapsuleStore(owner, max_capsule_bytes=32)
        second = capsule_module.MemoryNativeCapsuleStore(owner, max_capsule_bytes=32)
        self.addCleanup(owner.close)
        self.addCleanup(first.close)
        self.addCleanup(second.close)

        sealed = first.seal(
            capsule_id="capsule-1",
            payload=b"capsule-body",
            covered_position=2,
            covered_sequence=1,
        )

        self.assertEqual(
            second.seal(
                capsule_id="capsule-1",
                payload=b"capsule-body",
                covered_position=2,
                covered_sequence=1,
            ),
            sealed,
        )
        self.assertEqual(owner.budget.used_bytes, len(b"capsule-body"))
        for kwargs in (
            {"payload": b"changed", "covered_position": 2, "covered_sequence": 1},
            {"payload": b"capsule-body", "covered_position": 3, "covered_sequence": 1},
            {"payload": b"capsule-body", "covered_position": 2, "covered_sequence": 2},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(NativeStoreError) as raised:
                second.seal(capsule_id="capsule-1", **kwargs)
            self.assert_redacted_store_error(raised.exception)

    def test_capsule_payload_must_be_exact_nonempty_bounded_bytes(self) -> None:
        owner = MemoryNativeStorageOwner(maximum_bytes=1_000_000)
        store = capsule_module.MemoryNativeCapsuleStore(owner, max_capsule_bytes=3)
        self.addCleanup(owner.close)
        self.addCleanup(store.close)

        for payload in (b"", b"1234", bytearray(b"abc"), memoryview(b"abc"), HostileBytes(b"abc")):
            with self.subTest(payload_type=type(payload).__name__), self.assertRaises(NativeStoreError) as raised:
                store.seal(
                    capsule_id="capsule-1",
                    payload=payload,  # type: ignore[arg-type]
                    covered_position=1,
                    covered_sequence=1,
                )
            self.assert_redacted_store_error(raised.exception)

        self.assertEqual(
            store.seal(
                capsule_id="capsule-1",
                payload=b"abc",
                covered_position=1,
                covered_sequence=1,
            ),
            metadata("capsule-1", b"abc", covered_position=1, covered_sequence=1),
        )

    def test_file_capsule_reopen_uses_direct_ref_and_rejects_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            store = capsule_module.FileNativeCapsuleStore(
                session,
                max_capsule_bytes=65_536,
            )
            original = store.seal(
                capsule_id="capsule-1",
                payload=b"SENTINEL_PRIVATE_CAPSULE",
                covered_position=1,
                covered_sequence=1,
            )
            store.close()
            session.close()

            reopened_session = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            reopened = capsule_module.FileNativeCapsuleStore(
                reopened_session,
                max_capsule_bytes=65_536,
            )
            self.addCleanup(reopened_session.close)
            self.addCleanup(reopened.close)
            with patch.object(capsule_module.os, "listdir", side_effect=AssertionError("scan")):
                reopened.verify(original)
                self.assertEqual(
                    reopened.seal(
                        capsule_id="capsule-1",
                        payload=b"SENTINEL_PRIVATE_CAPSULE",
                        covered_position=1,
                        covered_sequence=1,
                    ),
                    original,
                )

            reopened.close()
            reopened_session.close()
            capsule_path(root, "capsule-1").write_bytes(b"SENTINEL_CORRUPTED")
            capsule_path(root, "capsule-1").chmod(0o600)
            corrupted_session = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            corrupted = capsule_module.FileNativeCapsuleStore(
                corrupted_session,
                max_capsule_bytes=65_536,
            )
            self.addCleanup(corrupted_session.close)
            self.addCleanup(corrupted.close)
            with self.assertRaises(NativeStoreError) as raised:
                corrupted.verify(original)
            self.assert_redacted_store_error(raised.exception)

    def test_file_capsule_rejects_symlink_wrong_mode_hardlink_growth_and_identity_drift(self) -> None:
        for label, mutate in file_corruption_cases():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                session = NativeSessionDirectory.open(
                    root,
                    SESSION_ID,
                    max_total_private_bytes=1_000_000,
                )
                store = capsule_module.FileNativeCapsuleStore(
                    session,
                    max_capsule_bytes=65_536,
                )
                sealed = store.seal(
                    capsule_id="capsule-1",
                    payload=b"SENTINEL_PRIVATE_CAPSULE",
                    covered_position=1,
                    covered_sequence=1,
                )
                store.close()
                session.close()
                patcher = mutate(root)
                try:
                    try:
                        reopened_session = NativeSessionDirectory.open(
                            root,
                            SESSION_ID,
                            max_total_private_bytes=1_000_000,
                        )
                    except NativeStoreError as error:
                        self.assert_redacted_store_error(error)
                        continue
                    reopened = capsule_module.FileNativeCapsuleStore(
                        reopened_session,
                        max_capsule_bytes=65_536,
                    )
                    self.addCleanup(reopened_session.close)
                    self.addCleanup(reopened.close)
                    with self.assertRaises(NativeStoreError) as raised:
                        reopened.verify(sealed)
                    self.assert_redacted_store_error(raised.exception)
                finally:
                    if patcher is not None:
                        patcher.stop()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            store = capsule_module.FileNativeCapsuleStore(
                session,
                max_capsule_bytes=65_536,
            )
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            sealed = store.seal(
                capsule_id="capsule-1",
                payload=b"capsule-body",
                covered_position=1,
                covered_sequence=1,
            )
            for drifted in (
                replace(sealed, capsule_id="capsule-2"),
                replace(sealed, capsule_digest="b" * 64),
                replace(sealed, control_plane_id="other"),
                replace(sealed, control_plane_version="0.2.0"),
                replace(sealed, checkpoint_version="2.0.0"),
                replace(sealed, covered_position=2),
                replace(sealed, covered_sequence=2),
                replace(sealed, storage_ref=storage_ref("capsule-2")),
            ):
                with self.subTest(drifted=drifted), self.assertRaises(NativeStoreError) as raised:
                    store.verify(drifted)
                self.assert_redacted_store_error(raised.exception)

    def test_file_capsule_counts_record_and_capsule_bytes_in_one_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, records = prepared_file_session(root)
            journal = FileNativeSessionStore(session, max_record_bytes=65_536)
            capsule_store = capsule_module.FileNativeCapsuleStore(
                session,
                max_capsule_bytes=65_536,
            )
            self.addCleanup(session.close)
            self.addCleanup(journal.close)
            self.addCleanup(capsule_store.close)
            entry = journal.append(0, bound_record())
            payload = b"capsule-body"
            sealed = capsule_store.seal(
                capsule_id="capsule-1",
                payload=payload,
                covered_position=entry.position,
                covered_sequence=1,
            )

            self.assertEqual(
                session.budget.used_bytes,
                len(canonical_entry_bytes(entry)) + len(payload),
            )
            self.assertEqual(journal.append(journal.position, bound_record()), entry)
            self.assertEqual(
                capsule_store.seal(
                    capsule_id="capsule-1",
                    payload=payload,
                    covered_position=entry.position,
                    covered_sequence=1,
                ),
                sealed,
            )
            self.assertEqual(
                session.budget.used_bytes,
                len(canonical_entry_bytes(entry)) + len(payload),
            )
            session.close()

            retained = records / f".record-00000000000000000002-{'a' * 32}.tmp"
            retained.write_bytes(b"x" * 13)
            retained.chmod(0o600)
            constrained = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=len(canonical_entry_bytes(entry)) + len(payload) + 13,
            )
            constrained_capsules = capsule_module.FileNativeCapsuleStore(
                constrained,
                max_capsule_bytes=65_536,
            )
            self.addCleanup(constrained.close)
            self.addCleanup(constrained_capsules.close)
            with self.assertRaises(NativeStoreError) as raised:
                constrained_capsules.seal(
                    capsule_id="capsule-2",
                    payload=b"y",
                    covered_position=1,
                    covered_sequence=1,
                )
            self.assert_redacted_store_error(raised.exception)

    def test_file_publication_is_no_overwrite_serialized_and_release_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            store = capsule_module.FileNativeCapsuleStore(
                session,
                max_capsule_bytes=65_536,
            )
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            preexisting = capsule_path(root, "capsule-1")
            original_write_all = capsule_module._write_all

            def create_final_then_write(descriptor: int, data: bytes) -> None:
                preexisting.write_bytes(b"SENTINEL_FOREIGN")
                preexisting.chmod(0o600)
                original_write_all(descriptor, data)

            with (
                patch.object(capsule_module, "_write_all", create_final_then_write),
                self.assertRaises(NativeStoreError) as raised,
            ):
                store.seal(
                    capsule_id="capsule-1",
                    payload=b"SENTINEL_PRIVATE_CAPSULE",
                    covered_position=1,
                    covered_sequence=1,
                )
            self.assert_redacted_store_error(raised.exception)
            self.assertEqual(preexisting.read_bytes(), b"SENTINEL_FOREIGN")
            self.assertEqual(session.budget.used_bytes, 0)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = NativeSessionDirectory.open(
                root,
                SESSION_ID,
                max_total_private_bytes=1_000_000,
            )
            store = capsule_module.FileNativeCapsuleStore(
                session,
                max_capsule_bytes=65_536,
            )
            self.addCleanup(session.close)
            self.addCleanup(store.close)
            token = "1" * 32
            temp = session_child(root) / "capsules" / f".capsule-{token}.tmp"
            alias = session_child(root) / "retained-capsule-temp-alias"

            def alias_then_fail(_descriptor: int, _data: bytes) -> None:
                os.link(temp, alias)
                raise OSError("SENTINEL_WRITE_FAILURE")

            with (
                patch.object(capsule_module.secrets, "token_hex", return_value=token),
                patch.object(capsule_module, "_write_all", alias_then_fail),
                self.assertRaises(NativeStoreError) as raised,
            ):
                store.seal(
                    capsule_id="capsule-1",
                    payload=b"SENTINEL_PRIVATE_CAPSULE",
                    covered_position=1,
                    covered_sequence=1,
                )
            self.assert_redacted_store_error(raised.exception)
            self.assertFalse(temp.exists())
            self.assertTrue(alias.exists())
            self.assertEqual(session.budget.used_bytes, len(b"SENTINEL_PRIVATE_CAPSULE"))

        owner = MemoryNativeStorageOwner(maximum_bytes=1_000_000)
        store = capsule_module.MemoryNativeCapsuleStore(owner, max_capsule_bytes=65_536)
        self.addCleanup(owner.close)
        self.addCleanup(store.close)
        entered = threading.Event()
        release = threading.Event()
        original_digest = capsule_module.hashlib.sha256

        def blocked_sha256(data: bytes = b""):
            if data == b"SENTINEL_PRIVATE_CAPSULE":
                entered.set()
                self.assertTrue(release.wait(timeout=5))
            return original_digest(data)

        with patch.object(capsule_module.hashlib, "sha256", blocked_sha256):
            seal_results = run_threaded_call(
                lambda: store.seal(
                    capsule_id="capsule-1",
                    payload=b"SENTINEL_PRIVATE_CAPSULE",
                    covered_position=1,
                    covered_sequence=1,
                )
            )
            self.assertTrue(entered.wait(timeout=5))
            close_results = run_threaded_call(store.close)
            try:
                close_results.thread.join(timeout=0.05)
                self.assertTrue(close_results.thread.is_alive())
            finally:
                release.set()
                seal_results.thread.join(timeout=5)
                close_results.thread.join(timeout=5)

        self.assertEqual(seal_results.value_or_raise(), metadata(covered_position=1, covered_sequence=1))
        close_results.value_or_raise()
        with self.assertRaises(NativeStoreError) as raised:
            store.verify(metadata(covered_position=1, covered_sequence=1))
        self.assert_redacted_store_error(raised.exception)

    def test_verify_accepts_exact_metadata_only_and_failures_are_redacted(self) -> None:
        owner = MemoryNativeStorageOwner(maximum_bytes=1_000_000)
        store = capsule_module.MemoryNativeCapsuleStore(owner, max_capsule_bytes=65_536)
        self.addCleanup(owner.close)
        self.addCleanup(store.close)
        sealed = store.seal(
            capsule_id="capsule-1",
            payload=b"SENTINEL_PRIVATE_CAPSULE",
            covered_position=1,
            covered_sequence=1,
        )
        store.verify(sealed)

        for candidate in (
            sealed.__dict__,
            replace(sealed, storage_ref="private.path"),
        ):
            with self.subTest(candidate=type(candidate).__name__), self.assertRaises(NativeStoreError) as raised:
                store.verify(candidate)  # type: ignore[arg-type]
            self.assert_redacted_store_error(raised.exception)

        def hostile_digest(_data: bytes = b""):
            raise RuntimeError("SENTINEL_HASH_FAILURE")

        with (
            patch.object(capsule_module.hashlib, "sha256", hostile_digest),
            self.assertRaises(NativeStoreError) as raised,
        ):
            store.seal(
                capsule_id="capsule-2",
                payload=b"SENTINEL_PRIVATE_CAPSULE",
                covered_position=1,
                covered_sequence=1,
            )
        self.assert_redacted_store_error(raised.exception)
        self.assert_traceback_chain_redacted(raised.exception, "SENTINEL_HASH_FAILURE")
        store.close()
        store.close()
        owner.close()
        owner.close()
        with self.assertRaises(NativeStoreError) as raised:
            store.seal(
                capsule_id="capsule-3",
                payload=b"private",
                covered_position=1,
                covered_sequence=1,
            )
        self.assert_redacted_store_error(raised.exception)


def file_corruption_cases():
    def symlink(root: Path):
        path = capsule_path(root, "capsule-1")
        path.unlink()
        os.symlink("SENTINEL_TARGET", path)
        return None

    def wrong_mode(root: Path):
        capsule_path(root, "capsule-1").chmod(0o644)
        return None

    def hardlink(root: Path):
        os.link(capsule_path(root, "capsule-1"), session_child(root) / "capsule-hardlink")
        return None

    def replacement(root: Path):
        path = capsule_path(root, "capsule-1")
        path.unlink()
        path.write_bytes(b"SENTINEL_REPLACED")
        path.chmod(0o600)
        return None

    def growth_after_eof(root: Path):
        original_read = capsule_module.os.read
        appended = False

        def grow(descriptor: int, length: int) -> bytes:
            nonlocal appended
            chunk = original_read(descriptor, length)
            if chunk == b"" and not appended:
                appended = True
                with capsule_path(root, "capsule-1").open("ab") as handle:
                    handle.write(b" ")
            return chunk

        patcher = patch.object(capsule_module.os, "read", grow)
        patcher.start()
        return patcher

    return (
        ("symlink", symlink),
        ("wrong-mode", wrong_mode),
        ("hardlink", hardlink),
        ("replacement", replacement),
        ("growth-after-eof", growth_after_eof),
    )


class ThreadedResult:
    def __init__(self, thread: threading.Thread) -> None:
        self.thread = thread
        self.value: object = None
        self.error: BaseException | None = None

    def value_or_raise(self) -> object:
        if self.error is not None:
            raise self.error
        return self.value


def run_threaded_call(call):
    result = ThreadedResult(threading.Thread(target=lambda: None))

    def target() -> None:
        try:
            result.value = call()
        except BaseException as error:
            result.error = error

    result.thread = threading.Thread(target=target)
    result.thread.start()
    return result


if __name__ == "__main__":
    unittest.main()
