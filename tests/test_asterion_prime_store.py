from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.agents.prime.state import (
    PrimeBackendIdentity,
    PrimeBackendSnapshot,
    PrimeCheckpoint,
    PrimeStateError,
)
from asterion.agents.prime.store import (
    FilePrimeSessionStore,
    PrimeStoreError,
    private_root_identity,
)


_DIGEST = hashlib.sha256(b"test").hexdigest()


def _identity(root: Path, **updates: object) -> PrimeBackendIdentity:
    values: dict[str, object] = {
        "session_id": "session-1",
        "generation": 1,
        "provider_id": "prime-applications",
        "application_id": "prime.ipython-coding",
        "application_version": "1.0.0",
        "runtime_id": "asterion.prime",
        "pi_command_sha256": _DIGEST,
        "extension_binding_fingerprint": hashlib.sha256(b"extension").hexdigest(),
        "worker_identity_sha256": hashlib.sha256(b"worker").hexdigest(),
        "continuation_id": "continuation-1",
        "private_root_identity": private_root_identity(root),
        "ceilings_sha256": hashlib.sha256(b"ceilings").hexdigest(),
    }
    values.update(updates)
    return PrimeBackendIdentity(**values)  # type: ignore[arg-type]


def _checkpoint(
    identity: PrimeBackendIdentity,
    transcript: bytes,
    usage: Mapping[str, object],
    *,
    checkpoint_id: str = "checkpoint-1",
    cursor: int = 1,
    summary: bytes | None = None,
    outstanding_effect: str | None = None,
    prior: str | None = None,
) -> PrimeCheckpoint:
    return PrimeCheckpoint(
        checkpoint_id=checkpoint_id,
        generation=identity.generation,
        public_event_cursor=cursor,
        private_transcript_sha256=hashlib.sha256(transcript).hexdigest(),
        summary_sha256=(
            None if summary is None else hashlib.sha256(summary).hexdigest()
        ),
        covered_leaf_id=None if summary is None else "leaf-1",
        worker_identity_sha256=identity.worker_identity_sha256,
        continuation_id=identity.continuation_id,
        usage_sha256=hashlib.sha256(
            json.dumps(usage, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        outstanding_effect=outstanding_effect,
        prior_checkpoint_sha256=prior,
    )


class TestPrimeState(unittest.TestCase):
    def test_identity_snapshot_and_checkpoint_are_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            identity = _identity(root)
            snapshot = PrimeBackendSnapshot(
                identity=identity,
                cursor=0,
                phase="created",
                outstanding_effect=None,
                authority_revision=1,
            )
            checkpoint = _checkpoint(identity, b"[]", {}, cursor=0)

            with self.assertRaises(FrozenInstanceError):
                identity.generation = 2  # type: ignore[misc]
            with self.assertRaises(FrozenInstanceError):
                snapshot.cursor = 1  # type: ignore[misc]
            with self.assertRaises(FrozenInstanceError):
                checkpoint.checkpoint_id = "changed"  # type: ignore[misc]

    def test_state_rejects_invalid_identity_and_phase(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            with self.assertRaises(PrimeStateError):
                _identity(root, runtime_id="other")
            identity = _identity(root)
            with self.assertRaises(PrimeStateError):
                PrimeBackendSnapshot(identity, 0, "running", None, 1)  # type: ignore[arg-type]


class TestFilePrimeSessionStore(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "private"
        self.root.mkdir(mode=0o700)
        self.identity = _identity(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_empty_owned_root_is_initialized_without_advancing_position(self) -> None:
        store = FilePrimeSessionStore(self.root, self.identity)
        self.addCleanup(store.close)

        self.assertEqual(store.position, 0)
        self.assertEqual(store.records(), ())
        self.assertEqual(oct(self.root.stat().st_mode & 0o777), "0o700")
        self.assertNotIn(str(self.root), repr(store))

    def test_root_identity_uses_descriptor_identity_and_rejects_links(self) -> None:
        expected = hashlib.sha256(
            json.dumps(
                {"dev": self.root.stat().st_dev, "ino": self.root.stat().st_ino},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        self.assertEqual(private_root_identity(self.root), expected)

        linked = self.root.parent / "linked"
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(PrimeStoreError, "unavailable") as caught:
            private_root_identity(linked)
        self.assertNotIn(str(self.root), str(caught.exception))

    def test_reopen_requires_exact_identity_and_one_live_writer(self) -> None:
        store = FilePrimeSessionStore(self.root, self.identity)
        with self.assertRaises(PrimeStoreError):
            FilePrimeSessionStore(self.root, self.identity)
        store.close()

        different = _identity(self.root, continuation_id="continuation-2")
        with self.assertRaises(PrimeStoreError):
            FilePrimeSessionStore(self.root, different)

    def test_live_store_rejects_replaced_lifetime_lock(self) -> None:
        store = FilePrimeSessionStore(self.root, self.identity)
        self.addCleanup(store.close)
        replacement = self.root / "replacement"
        replacement.write_bytes(b"")
        os.chmod(replacement, 0o600)
        replacement.replace(self.root / ".writer.lock")

        with self.assertRaises(PrimeStoreError):
            _ = store.position

    def test_live_trust_rejects_root_and_identity_drift(self) -> None:
        for case in ("root-mode", "identity-content"):
            with self.subTest(case=case):
                root = self.root.parent / case
                root.mkdir(mode=0o700)
                identity = _identity(root)
                store = FilePrimeSessionStore(root, identity)
                identity_file: Path | None = None
                original: bytes | None = None
                try:
                    if case == "root-mode":
                        os.chmod(root, 0o755)
                    else:
                        identity_file = root / "identity.json"
                        original = identity_file.read_bytes()
                        tampered = original.replace(b"session-1", b"session-2")
                        self.assertEqual(len(tampered), len(original))
                        identity_file.write_bytes(tampered)
                    with self.assertRaises(PrimeStoreError):
                        if case == "root-mode":
                            _ = store.identity
                        else:
                            _ = store.position
                    if case == "root-mode":
                        os.chmod(root, 0o700)
                    else:
                        assert identity_file is not None and original is not None
                        identity_file.write_bytes(original)
                    with self.assertRaises(PrimeStoreError):
                        store.records()
                finally:
                    os.chmod(root, 0o700)
                    store.close()

    def test_append_is_canonical_immutable_and_idempotent(self) -> None:
        store = FilePrimeSessionStore(self.root, self.identity)
        self.addCleanup(store.close)
        payload = {"cursor": 1, "event": {"type": "safe", "values": [1, True]}}
        first = store.append("event-1", "public.event", payload, expected_position=0)
        payload["cursor"] = 99

        self.assertEqual(first.position, 1)
        self.assertEqual(first.payload["cursor"], 1)
        self.assertEqual(store.position, 1)
        self.assertTrue(store.has_record("event-1"))
        self.assertIs(
            store.append(
                "event-1",
                "public.event",
                {"cursor": 1, "event": {"type": "safe", "values": [1, True]}},
                expected_position=1,
            ),
            first,
        )
        with self.assertRaises(TypeError):
            first.payload["cursor"] = 2  # type: ignore[index]
        line = (self.root / "records.jsonl").read_bytes().removesuffix(b"\n")
        self.assertEqual(
            json.dumps(
                json.loads(line),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
            line,
        )

    def test_append_rejects_position_divergence_and_cursor_gaps(self) -> None:
        store = FilePrimeSessionStore(self.root, self.identity)
        self.addCleanup(store.close)
        with self.assertRaises(PrimeStoreError):
            store.append("record-1", "effect.started", {}, expected_position=1)
        with self.assertRaises(PrimeStoreError):
            store.append("event-2", "public.event", {"cursor": 2}, expected_position=0)
        self.assertEqual(store.position, 0)

    def test_duplicate_record_id_rejects_a_different_digest(self) -> None:
        store = FilePrimeSessionStore(self.root, self.identity)
        self.addCleanup(store.close)
        store.append("record-1", "effect.started", {"value": 1}, expected_position=0)
        with self.assertRaises(PrimeStoreError):
            store.append(
                "record-1", "effect.started", {"value": 2}, expected_position=1
            )

    def test_record_and_total_byte_caps_fail_closed(self) -> None:
        store = FilePrimeSessionStore(
            self.root,
            self.identity,
            max_bytes=700,
            max_record_bytes=180,
        )
        self.addCleanup(store.close)
        with self.assertRaises(PrimeStoreError):
            store.append(
                "large-record",
                "effect.committed",
                {"private": "x" * 500},
                expected_position=0,
            )
        self.assertEqual(store.position, 0)

    def test_fsync_failure_never_acknowledges_or_advances_memory(self) -> None:
        store = FilePrimeSessionStore(self.root, self.identity)
        self.addCleanup(store.close)
        with patch("asterion.agents.prime.store.os.fsync", side_effect=OSError):
            with self.assertRaises(PrimeStoreError):
                store.append("record-1", "effect.started", {}, expected_position=0)
        with self.assertRaises(PrimeStoreError):
            _ = store.position

    def test_reopen_rejects_trailing_or_noncanonical_records(self) -> None:
        store = FilePrimeSessionStore(self.root, self.identity)
        store.append("record-1", "effect.started", {}, expected_position=0)
        store.close()
        journal = self.root / "records.jsonl"
        journal.write_bytes(journal.read_bytes().removesuffix(b"\n"))
        with self.assertRaises(PrimeStoreError):
            FilePrimeSessionStore(self.root, self.identity)

    def test_live_store_rejects_same_prefix_rewritten_in_place(self) -> None:
        store = FilePrimeSessionStore(self.root, self.identity)
        self.addCleanup(store.close)
        store.append("record-1", "effect.started", {}, expected_position=0)
        journal = self.root / "records.jsonl"
        original = journal.read_bytes()
        journal.write_bytes(original)

        with self.assertRaises(PrimeStoreError):
            store.records()

    def test_checkpoint_round_trip_binds_every_recovery_input(self) -> None:
        transcript = b'[{"private":"sentinel prompt"}]'
        summary = b"sentinel summary"
        usage = {
            "model_callbacks": 2,
            "tool_callbacks": 1,
            "input_tokens": 20,
            "output_tokens": 5,
            "cost_micros": 100,
        }
        store = FilePrimeSessionStore(self.root, self.identity)
        store.append("event-1", "public.event", {"cursor": 1}, expected_position=0)
        checkpoint = _checkpoint(
            self.identity,
            transcript,
            usage,
            summary=summary,
            outstanding_effect="tool-1",
        )
        sealed = store.write_checkpoint(
            checkpoint,
            expected_position=1,
            transcript=transcript,
            summary=summary,
            usage=usage,
        )
        self.assertEqual(sealed.kind, "checkpoint.sealed")
        self.assertNotIn("sentinel", repr(sealed))
        store.close()

        recovered_store = FilePrimeSessionStore(self.root, self.identity)
        self.addCleanup(recovered_store.close)
        recovered = recovered_store.recover_checkpoint()
        self.assertIsNotNone(recovered)
        assert recovered is not None
        self.assertEqual(recovered.checkpoint, checkpoint)
        self.assertEqual(recovered.transcript, transcript)
        self.assertEqual(recovered.summary, summary)
        self.assertEqual(dict(recovered.usage), usage)
        self.assertNotIn("sentinel", repr(recovered))

    def test_checkpoint_requires_exact_identity_cursor_digests_and_chain(self) -> None:
        transcript = b"[]"
        usage: dict[str, object] = {}
        store = FilePrimeSessionStore(self.root, self.identity)
        self.addCleanup(store.close)
        with self.assertRaises(PrimeStoreError):
            store.write_checkpoint(
                _checkpoint(self.identity, transcript, usage),
                expected_position=0,
                transcript=transcript,
                summary=None,
                usage=usage,
            )

    def test_exact_checkpoint_duplicate_is_idempotent(self) -> None:
        transcript = b"[]"
        usage: dict[str, object] = {}
        store = FilePrimeSessionStore(self.root, self.identity)
        self.addCleanup(store.close)
        store.append("event-1", "public.event", {"cursor": 1}, expected_position=0)
        checkpoint = _checkpoint(self.identity, transcript, usage)
        first = store.write_checkpoint(
            checkpoint,
            expected_position=1,
            transcript=transcript,
            summary=None,
            usage=usage,
        )

        self.assertIs(
            store.write_checkpoint(
                checkpoint,
                expected_position=2,
                transcript=transcript,
                summary=None,
                usage=usage,
            ),
            first,
        )
        self.assertEqual(store.position, 2)
        store.append("event-1", "public.event", {"cursor": 1}, expected_position=0)
        first = _checkpoint(self.identity, transcript, usage)
        store.write_checkpoint(
            first,
            expected_position=1,
            transcript=transcript,
            summary=None,
            usage=usage,
        )
        with self.assertRaises(PrimeStoreError):
            store.write_checkpoint(
                _checkpoint(
                    self.identity,
                    transcript,
                    usage,
                    checkpoint_id="checkpoint-2",
                    prior=_DIGEST,
                ),
                expected_position=2,
                transcript=transcript,
                summary=None,
                usage=usage,
            )

    def test_checkpoint_blob_tamper_is_rejected_on_recovery(self) -> None:
        transcript = b"private transcript"
        usage: dict[str, object] = {}
        store = FilePrimeSessionStore(self.root, self.identity)
        store.append("event-1", "public.event", {"cursor": 1}, expected_position=0)
        store.write_checkpoint(
            _checkpoint(self.identity, transcript, usage),
            expected_position=1,
            transcript=transcript,
            summary=None,
            usage=usage,
        )
        store.close()
        transcript_file = next(self.root.glob("transcript-*.blob"))
        transcript_file.write_bytes(b"tampered")

        with self.assertRaises(PrimeStoreError):
            FilePrimeSessionStore(self.root, self.identity)

    def test_artifact_symlink_is_rejected(self) -> None:
        target = self.root / "target"
        target.write_bytes(b"")
        os.chmod(target, 0o600)
        (self.root / "records.jsonl").symlink_to(target)
        with self.assertRaises(PrimeStoreError):
            FilePrimeSessionStore(self.root, self.identity)

    def test_public_reads_redact_missing_artifacts_and_os_errors(self) -> None:
        cases = (
            "missing-records",
            "missing-identity",
            "missing-blob",
            "read-eacces",
            "stat-eacces",
        )
        for case in cases:
            with self.subTest(case=case):
                root = self.root.parent / case
                root.mkdir(mode=0o700)
                identity = _identity(root)
                store = FilePrimeSessionStore(root, identity)
                secret = f"PRIVATE-{case}-{root}"
                try:
                    action = store.records
                    context = patch(
                        "asterion.agents.prime.store.os.getuid",
                        return_value=os.getuid(),
                    )
                    if case == "missing-records":
                        (root / "records.jsonl").unlink()

                        def action() -> object:
                            return store.position

                    elif case == "missing-identity":
                        (root / "identity.json").unlink()
                    elif case == "missing-blob":
                        transcript = b"private"
                        usage: dict[str, object] = {}
                        store.append(
                            "event-1",
                            "public.event",
                            {"cursor": 1},
                            expected_position=0,
                        )
                        store.write_checkpoint(
                            _checkpoint(identity, transcript, usage),
                            expected_position=1,
                            transcript=transcript,
                            summary=None,
                            usage=usage,
                        )
                        next(root.glob("transcript-*.blob")).unlink()
                        action = store.recover_checkpoint
                    elif case == "read-eacces":
                        journal = root / "records.jsonl"
                        details = journal.stat()
                        os.utime(
                            journal,
                            ns=(details.st_atime_ns, details.st_mtime_ns + 1),
                        )
                        context = patch(
                            "asterion.agents.prime.store._read_fd",
                            side_effect=OSError(secret),
                        )
                    else:
                        context = patch(
                            "asterion.agents.prime.store.os.stat",
                            side_effect=OSError(secret),
                        )

                        def action() -> object:
                            return store.has_record("record-1")

                    with context, self.assertRaises(PrimeStoreError) as caught:
                        action()
                    rendered = repr(caught.exception)
                    self.assertEqual(
                        str(caught.exception), "Prime session store is unavailable"
                    )
                    self.assertNotIn(secret, rendered)
                    self.assertIsNone(caught.exception.__context__)
                finally:
                    store.close()


if __name__ == "__main__":
    unittest.main()
