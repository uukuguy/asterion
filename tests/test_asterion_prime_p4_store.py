"""Tests for FilePrimeSessionStore.open_continued (Phase 6, Task 1)."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from asterion.agents.prime.state import (
    PrimeBackendIdentity,
    PrimeCheckpoint,
)
from asterion.agents.prime.store import (
    FilePrimeSessionStore,
    PrimeStoreError,
    private_root_identity,
)


_DIGEST = hashlib.sha256(b"test").hexdigest()
_WORKER_A = hashlib.sha256(b"worker-a").hexdigest()
_WORKER_B = hashlib.sha256(b"worker-b").hexdigest()


def _identity(
    root: Path,
    *,
    generation: int = 1,
    worker_identity_sha256: str = _WORKER_A,
    continuation_id: str = "continuation-1",
    session_id: str = "session-1",
    private_root_identity_override: str | None = None,
) -> PrimeBackendIdentity:
    values: dict[str, object] = {
        "session_id": session_id,
        "generation": generation,
        "provider_id": "prime-applications",
        "application_id": "prime.long-session-continuity",
        "application_version": "1.0.0",
        "runtime_id": "asterion.prime",
        "pi_command_sha256": _DIGEST,
        "extension_binding_fingerprint": hashlib.sha256(b"extension").hexdigest(),
        "worker_identity_sha256": worker_identity_sha256,
        "continuation_id": continuation_id,
        "private_root_identity": (
            private_root_identity_override
            if private_root_identity_override is not None
            else private_root_identity(root)
        ),
        "ceilings_sha256": hashlib.sha256(b"ceilings").hexdigest(),
    }
    return PrimeBackendIdentity(**values)  # type: ignore[arg-type]


def _checkpoint(
    identity: PrimeBackendIdentity,
    transcript: bytes,
    usage: Mapping[str, object],
    *,
    checkpoint_id: str = "checkpoint-1",
    cursor: int = 1,
    summary: bytes | None = None,
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
        outstanding_effect=None,
        prior_checkpoint_sha256=prior,
    )


def _seed_committed_checkpoint(
    root: Path, worker_sha: str = _WORKER_A
) -> tuple[PrimeBackendIdentity, PrimeCheckpoint]:
    """Open a store at gen=1, append one event, seal one checkpoint, close."""

    identity = _identity(root, worker_identity_sha256=worker_sha)
    with FilePrimeSessionStore(root, identity) as store:
        store.append(
            "event-1", "public.event", {"cursor": 1}, expected_position=0
        )
        checkpoint = _checkpoint(identity, b"transcript-a", {"input_tokens": 0})
        store.write_checkpoint(
            checkpoint,
            expected_position=1,
            transcript=b"transcript-a",
            summary=None,
            usage={"input_tokens": 0},
        )
    return identity, checkpoint


class TestFilePrimeSessionStoreOpenContinued(unittest.TestCase):
    def test_open_continued_bumps_generation_and_binds_existing_root(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            prior_identity, _ = _seed_committed_checkpoint(root)
            continued = _identity(
                root, generation=2, worker_identity_sha256=_WORKER_A
            )

            store = FilePrimeSessionStore.open_continued(root, continued)

            try:
                self.assertEqual(store.identity, continued)
                self.assertEqual(store.highest_sealed_generation, 1)
                self.assertEqual(store.continued_from, prior_identity)
                recovered = store.recover_checkpoint()
                self.assertIsNotNone(recovered)
                assert recovered is not None
                self.assertEqual(recovered.checkpoint.generation, 1)
            finally:
                store.close()

    def test_open_continued_rejects_same_generation(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            _seed_committed_checkpoint(root)
            same_generation = _identity(root, generation=1)

            with self.assertRaises(PrimeStoreError):
                FilePrimeSessionStore.open_continued(root, same_generation)

    def test_open_continued_rejects_unrelated_field_drift(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            _seed_committed_checkpoint(root)
            drift_session = _identity(
                root, generation=2, session_id="session-OTHER"
            )

            with self.assertRaises(PrimeStoreError):
                FilePrimeSessionStore.open_continued(root, drift_session)

            drift_continuation = _identity(
                root, generation=2, continuation_id="continuation-OTHER"
            )
            with self.assertRaises(PrimeStoreError):
                FilePrimeSessionStore.open_continued(root, drift_continuation)

            drift_application = _identity(
                root,
                generation=2,
            )
            drift_application_obj = PrimeBackendIdentity(
                **{
                    **{
                        field: getattr(drift_application, field)
                        for field in (
                            "session_id",
                            "generation",
                            "provider_id",
                            "runtime_id",
                            "pi_command_sha256",
                            "extension_binding_fingerprint",
                            "worker_identity_sha256",
                            "continuation_id",
                            "private_root_identity",
                            "ceilings_sha256",
                        )
                    },
                    "application_id": "prime.recursive-workflow",
                    "application_version": "1.0.0",
                }
            )
            with self.assertRaises(PrimeStoreError):
                FilePrimeSessionStore.open_continued(root, drift_application_obj)

    def test_open_continued_allows_worker_swap_when_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            prior_identity, _ = _seed_committed_checkpoint(root, worker_sha=_WORKER_A)
            continued = _identity(
                root, generation=2, worker_identity_sha256=_WORKER_B
            )

            store = FilePrimeSessionStore.open_continued(root, continued)

            try:
                self.assertEqual(store.identity.worker_identity_sha256, _WORKER_B)
                self.assertEqual(store.continued_from, prior_identity)
                self.assertIsNotNone(store.continued_from)
                assert store.continued_from is not None
                self.assertEqual(
                    store.continued_from.worker_identity_sha256, _WORKER_A
                )
                self.assertEqual(store.highest_sealed_generation, 1)

                # A new checkpoint sealed by the new worker at the new generation
                # is accepted; replay at the prior generation is rejected.
                store.append(
                    "event-2",
                    "public.event",
                    {"cursor": 2},
                    expected_position=2,
                )
                prior_recovered = store.recover_checkpoint()
                self.assertIsNotNone(prior_recovered)
                assert prior_recovered is not None
                new_checkpoint = PrimeCheckpoint(
                    checkpoint_id="checkpoint-2",
                    generation=2,
                    public_event_cursor=2,
                    private_transcript_sha256=hashlib.sha256(b"transcript-b").hexdigest(),
                    summary_sha256=None,
                    covered_leaf_id=None,
                    worker_identity_sha256=_WORKER_B,
                    continuation_id=continued.continuation_id,
                    usage_sha256=hashlib.sha256(b"{}").hexdigest(),
                    outstanding_effect=None,
                    prior_checkpoint_sha256=prior_recovered.checkpoint.digest,
                )
                record = store.write_checkpoint(
                    new_checkpoint,
                    expected_position=3,
                    transcript=b"transcript-b",
                    summary=None,
                    usage={},
                )
                self.assertEqual(record.record_id, "checkpoint:checkpoint-2")
                self.assertEqual(store.highest_sealed_generation, 2)

                # Replaying at the prior generation is the exact violation the
                # continuation invariant must catch.
                replay_checkpoint = PrimeCheckpoint(
                    checkpoint_id="checkpoint-replay",
                    generation=1,
                    public_event_cursor=2,
                    private_transcript_sha256=hashlib.sha256(b"transcript-x").hexdigest(),
                    summary_sha256=None,
                    covered_leaf_id=None,
                    worker_identity_sha256=_WORKER_A,
                    continuation_id=continued.continuation_id,
                    usage_sha256=hashlib.sha256(b"{}").hexdigest(),
                    outstanding_effect=None,
                    prior_checkpoint_sha256=None,
                )
                with self.assertRaises(PrimeStoreError):
                    store.write_checkpoint(
                        replay_checkpoint,
                        expected_position=4,
                        transcript=b"transcript-x",
                        summary=None,
                        usage={},
                    )
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()