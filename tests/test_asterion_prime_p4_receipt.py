"""Tests for P4 sealed receipt (Phase 6, Task 7)."""

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
from asterion.applications.prime.p4.oracle import P4Oracle
from asterion.applications.prime.p4.receipt import (
    P4_RECEIPT_MEDIA_TYPE,
    P4NativeReceipt,
    P4ReceiptError,
    build_native_receipt,
)


_WORKER_A = hashlib.sha256(b"worker-a").hexdigest()
_WORKER_B = hashlib.sha256(b"worker-b").hexdigest()


def _identity(
    root: Path,
    *,
    generation: int = 2,
    worker_identity_sha256: str = _WORKER_B,
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


def _seeded_pair(
    root: Path,
) -> tuple[PrimeCheckpoint, PrimeBackendIdentity]:
    """Open store at gen=1, seal one checkpoint, then continue at gen=2."""

    gen1 = _identity(root, generation=1, worker_identity_sha256=_WORKER_A)
    with FilePrimeSessionStore(root, gen1) as store:
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
    gen2 = _identity(root, generation=2, worker_identity_sha256=_WORKER_B)
    return checkpoint, gen2


class TestP4Receipt(unittest.TestCase):
    def test_seal_receipt_is_digest_stable(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            prior, gen2 = _seeded_pair(root)
            oracle = P4Oracle(prior, gen2)
            commit_result = hashlib.sha256(b"commit").hexdigest()
            recover_result = hashlib.sha256(b"recover").hexdigest()
            oracle_receipt = oracle.verify(
                commit_result_sha256=commit_result,
                recover_result_sha256=recover_result,
                recovered_prior_checkpoint_sha256=prior.digest,
            )
            new_checkpoint_sha = hashlib.sha256(b"new-checkpoint").hexdigest()
            cleanup_sha = hashlib.sha256(b"cleanup").hexdigest()

            receipt = build_native_receipt(
                prior_checkpoint_sha256=prior.digest,
                new_checkpoint_sha256=new_checkpoint_sha,
                continuation_id=gen2.continuation_id,
                prior_generation=prior.generation,
                new_generation=gen2.generation,
                oracle=oracle_receipt,
                cleanup_receipt_sha256=cleanup_sha,
                bytes_returned=42,
            )

            self.assertIsInstance(receipt, P4NativeReceipt)
            first_digest = receipt.sha256()

            # Re-sealing with identical inputs is idempotent (same digest).
            receipt_again = build_native_receipt(
                prior_checkpoint_sha256=prior.digest,
                new_checkpoint_sha256=new_checkpoint_sha,
                continuation_id=gen2.continuation_id,
                prior_generation=prior.generation,
                new_generation=gen2.generation,
                oracle=oracle_receipt,
                cleanup_receipt_sha256=cleanup_sha,
                bytes_returned=42,
            )
            self.assertEqual(receipt_again.sha256(), first_digest)

            # Any field change -> different digest.
            receipt_other = build_native_receipt(
                prior_checkpoint_sha256=prior.digest,
                new_checkpoint_sha256=new_checkpoint_sha,
                continuation_id=gen2.continuation_id,
                prior_generation=prior.generation,
                new_generation=gen2.generation,
                oracle=oracle_receipt,
                cleanup_receipt_sha256=cleanup_sha,
                bytes_returned=43,
            )
            self.assertNotEqual(receipt_other.sha256(), first_digest)

    def test_receipt_rejects_unverified_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            prior, gen2 = _seeded_pair(root)
            oracle = P4Oracle(prior, gen2)
            failed = oracle.check(
                commit_result_sha256=hashlib.sha256(b"a").hexdigest(),
                recover_result_sha256=hashlib.sha256(b"a").hexdigest(),
                recovered_prior_checkpoint_sha256=prior.digest,
            )
            self.assertFalse(failed.succeeded)
            with self.assertRaises(P4ReceiptError):
                build_native_receipt(
                    prior_checkpoint_sha256=prior.digest,
                    new_checkpoint_sha256=hashlib.sha256(b"n").hexdigest(),
                    continuation_id=gen2.continuation_id,
                    prior_generation=prior.generation,
                    new_generation=gen2.generation,
                    oracle=failed,
                    cleanup_receipt_sha256=hashlib.sha256(b"cl").hexdigest(),
                    bytes_returned=0,
                )

    def test_receipt_rejects_mismatched_generations(self) -> None:
        with self.assertRaises(Exception):
            P4NativeReceipt(
                application="prime.long-session-continuity@1.0.0",
                runtime="asterion.prime",
                prior_checkpoint_sha256=hashlib.sha256(b"p").hexdigest(),
                new_checkpoint_sha256=hashlib.sha256(b"n").hexdigest(),
                continuation_id="c",
                prior_generation=2,
                new_generation=2,  # must be prior + 1
                oracle_receipt_sha256=hashlib.sha256(b"o").hexdigest(),
                cleanup_receipt_sha256=hashlib.sha256(b"cl").hexdigest(),
                bytes_returned=0,
                final_status="verified",
            )

    def test_receipt_media_type(self) -> None:
        self.assertEqual(
            P4_RECEIPT_MEDIA_TYPE,
            "application/vnd.asterion.prime.p4-native-receipt+json",
        )


if __name__ == "__main__":
    unittest.main()