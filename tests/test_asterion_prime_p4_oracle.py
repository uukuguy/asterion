"""Tests for P4 oracle (Phase 6, Task 6)."""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from asterion.agents.prime.state import (
    PrimeBackendIdentity,
    PrimeCheckpoint,
)
from asterion.agents.prime.store import (
    FilePrimeSessionStore,
    private_root_identity,
)
from asterion.applications.prime.p4.oracle import (
    P4Oracle,
    P4OracleError,
    P4OracleReceipt,
)


_WORKER_A = hashlib.sha256(b"worker-a").hexdigest()
_WORKER_B = hashlib.sha256(b"worker-b").hexdigest()


def _identity(
    root: Path,
    *,
    generation: int = 1,
    worker_identity_sha256: str = _WORKER_A,
    continuation_id: str = "continuation-1",
) -> PrimeBackendIdentity:
    values: dict[str, object] = {
        "session_id": "session-1",
        "generation": generation,
        "provider_id": "prime-applications",
        "application_id": "prime.long-session-continuity",
        "application_version": "1.0.0",
        "runtime_id": "asterion.prime",
        "pi_command_sha256": hashlib.sha256(b"pi").hexdigest(),
        "extension_binding_fingerprint": hashlib.sha256(b"extension").hexdigest(),
        "worker_identity_sha256": worker_identity_sha256,
        "continuation_id": continuation_id,
        "private_root_identity": private_root_identity(root),
        "ceilings_sha256": hashlib.sha256(b"ceilings").hexdigest(),
    }
    return PrimeBackendIdentity(**values)  # type: ignore[arg-type]


def _seeded_checkpoint(root: Path) -> PrimeCheckpoint:
    """Open a store at gen=1, append one event, seal one checkpoint, close."""

    identity = _identity(root)
    with FilePrimeSessionStore(root, identity) as store:
        store.append(
            "event-1", "public.event", {"cursor": 1}, expected_position=0
        )
        checkpoint = PrimeCheckpoint(
            checkpoint_id="checkpoint-1",
            generation=1,
            public_event_cursor=1,
            private_transcript_sha256=hashlib.sha256(b"transcript-a").hexdigest(),
            summary_sha256=None,
            covered_leaf_id=None,
            worker_identity_sha256=_WORKER_A,
            continuation_id="continuation-1",
            usage_sha256=hashlib.sha256(b"{}").hexdigest(),
            outstanding_effect=None,
            prior_checkpoint_sha256=None,
        )
        store.write_checkpoint(
            checkpoint,
            expected_position=1,
            transcript=b"transcript-a",
            summary=None,
            usage={},
        )
    return checkpoint


class TestP4Oracle(unittest.TestCase):
    def test_oracle_passes_when_generation_increments_and_result_differs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            prior = _seeded_checkpoint(root)
            next_identity = _identity(
                root, generation=2, worker_identity_sha256=_WORKER_B
            )
            oracle = P4Oracle(prior, next_identity)

            receipt = oracle.verify(
                commit_result_sha256=hashlib.sha256(b"commit").hexdigest(),
                recover_result_sha256=hashlib.sha256(b"recover").hexdigest(),
                recovered_prior_checkpoint_sha256=prior.digest,
            )

            self.assertIsInstance(receipt, P4OracleReceipt)
            self.assertTrue(receipt.succeeded)
            self.assertIsNone(receipt.reason_code)
            self.assertEqual(receipt.prior_generation, 1)
            self.assertEqual(receipt.next_generation, 2)
            self.assertEqual(receipt.continuation_id, "continuation-1")
            self.assertEqual(receipt.prior_checkpoint_sha256, prior.digest)

    def test_oracle_rejects_replay_when_result_digest_matches_commit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            prior = _seeded_checkpoint(root)
            next_identity = _identity(
                root, generation=2, worker_identity_sha256=_WORKER_B
            )
            oracle = P4Oracle(prior, next_identity)
            same_result = hashlib.sha256(b"same").hexdigest()

            receipt = oracle.check(
                commit_result_sha256=same_result,
                recover_result_sha256=same_result,
                recovered_prior_checkpoint_sha256=prior.digest,
            )

            self.assertFalse(receipt.succeeded)
            self.assertEqual(receipt.reason_code, "replayed-committed-effect")
            # `verify` raises on the same inputs.
            with self.assertRaises(P4OracleError):
                oracle.verify(
                    commit_result_sha256=same_result,
                    recover_result_sha256=same_result,
                    recovered_prior_checkpoint_sha256=prior.digest,
                )

    def test_oracle_rejects_when_generation_does_not_increment(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            prior = _seeded_checkpoint(root)
            next_identity = _identity(
                root, generation=3, worker_identity_sha256=_WORKER_B
            )
            oracle = P4Oracle(prior, next_identity)

            receipt = oracle.check(
                commit_result_sha256=hashlib.sha256(b"commit").hexdigest(),
                recover_result_sha256=hashlib.sha256(b"recover").hexdigest(),
                recovered_prior_checkpoint_sha256=prior.digest,
            )

            self.assertFalse(receipt.succeeded)
            self.assertEqual(receipt.reason_code, "generation-not-monotonic")

    def test_oracle_rejects_broken_continuity_chain(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            prior = _seeded_checkpoint(root)
            next_identity = _identity(
                root, generation=2, worker_identity_sha256=_WORKER_B
            )
            oracle = P4Oracle(prior, next_identity)

            receipt = oracle.check(
                commit_result_sha256=hashlib.sha256(b"commit").hexdigest(),
                recover_result_sha256=hashlib.sha256(b"recover").hexdigest(),
                recovered_prior_checkpoint_sha256=(
                    hashlib.sha256(b"WRONG-PRIOR").hexdigest()
                ),
            )

            self.assertFalse(receipt.succeeded)
            self.assertEqual(receipt.reason_code, "continuity-chain-broken")

    def test_oracle_rejects_mismatched_continuation_id(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            prior = _seeded_checkpoint(root)
            next_identity = _identity(
                root,
                generation=2,
                worker_identity_sha256=_WORKER_B,
                continuation_id="continuation-OTHER",
            )
            oracle = P4Oracle(prior, next_identity)

            receipt = oracle.check(
                commit_result_sha256=hashlib.sha256(b"commit").hexdigest(),
                recover_result_sha256=hashlib.sha256(b"recover").hexdigest(),
                recovered_prior_checkpoint_sha256=prior.digest,
            )

            self.assertFalse(receipt.succeeded)
            self.assertEqual(receipt.reason_code, "continuity-chain-broken")

    def test_oracle_constructor_rejects_wrong_types(self) -> None:
        with self.assertRaises(P4OracleError):
            P4Oracle("not-a-checkpoint", "not-an-identity")  # type: ignore[arg-type]

    def test_oracle_receipt_rejects_invalid_digests(self) -> None:
        with self.assertRaises(P4OracleError):
            P4OracleReceipt(
                prior_checkpoint_sha256="not-a-digest",
                next_generation=2,
                prior_generation=1,
                commit_result_sha256=hashlib.sha256(b"c").hexdigest(),
                recover_result_sha256=hashlib.sha256(b"r").hexdigest(),
                continuation_id="c",
                succeeded=True,
                reason_code=None,
            )


if __name__ == "__main__":
    unittest.main()