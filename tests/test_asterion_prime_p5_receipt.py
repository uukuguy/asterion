"""Tests for P5 sealed receipt (Phase 8, Task 6)."""

from __future__ import annotations

import unittest

from asterion.applications.prime.p5.receipt import (
    P5NativeReceipt,
    P5ReceiptError,
    build,
    media_type,
    seal,
)


def _digest(payload: str) -> str:
    """Deterministic placeholder for one workspace-digest input."""

    import hashlib

    return hashlib.sha256(b"workspace:" + payload.encode()).hexdigest()


class TestP5Receipt(unittest.TestCase):
    def test_seal_receipt_is_digest_stable(self) -> None:
        joined = _digest("propose-1")

        first = seal(
            root_run_id="root-1",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=2,
            repair_step_count=1,
            failed_verify_count=1,
            terminal_reason="success",
            joined_workspace_digest=joined,
        )
        self.assertIsInstance(first, P5NativeReceipt)
        first_digest = first.sha256()

        # Re-sealing with identical inputs is idempotent (same digest).
        again = seal(
            root_run_id="root-1",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=2,
            repair_step_count=1,
            failed_verify_count=1,
            terminal_reason="success",
            joined_workspace_digest=joined,
        )
        self.assertEqual(again.sha256(), first_digest)
        # receipt_sha256 is the digest of the OTHER fields; sha256()
        # digests the whole dataclass. They will differ — see
        # test_build_accepts_caller_supplied_digest.
        self.assertEqual(first.receipt_sha256, again.receipt_sha256)
        self.assertEqual(len(first.receipt_sha256), 64)

        # Any field change -> different digest.
        with self.subTest("root_run_id change"):
            other = seal(
                root_run_id="root-2",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=2,
                repair_step_count=1,
                failed_verify_count=1,
                terminal_reason="success",
                joined_workspace_digest=joined,
            )
            self.assertNotEqual(other.sha256(), first_digest)
        with self.subTest("verify_step_count change"):
            other = seal(
                root_run_id="root-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=3,
                repair_step_count=1,
                failed_verify_count=1,
                terminal_reason="success",
                joined_workspace_digest=joined,
            )
            self.assertNotEqual(other.sha256(), first_digest)
        with self.subTest("joined_workspace_digest change"):
            other = seal(
                root_run_id="root-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=2,
                repair_step_count=1,
                failed_verify_count=1,
                terminal_reason="success",
                joined_workspace_digest=_digest("propose-2"),
            )
            self.assertNotEqual(other.sha256(), first_digest)

    def test_seal_receipt_with_no_progress_round_trips(self) -> None:
        # terminal_reason = "no-progress" is a valid receipt; the digest
        # includes the terminal_reason code (changing it changes the SHA).
        joined = _digest("propose-1")
        receipt = seal(
            root_run_id="root-noprogress",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=2,
            repair_step_count=0,
            failed_verify_count=1,
            terminal_reason="no-progress",
            joined_workspace_digest=joined,
        )
        self.assertIsInstance(receipt, P5NativeReceipt)
        self.assertEqual(receipt.terminal_reason, "no-progress")
        self.assertEqual(receipt.repair_step_count, 0)
        self.assertEqual(len(receipt.receipt_sha256), 64)
        first_digest = receipt.sha256()

        # Same inputs -> same digest.
        again = seal(
            root_run_id="root-noprogress",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=2,
            repair_step_count=0,
            failed_verify_count=1,
            terminal_reason="no-progress",
            joined_workspace_digest=joined,
        )
        self.assertEqual(again.sha256(), first_digest)

        # Changing terminal_reason changes the digest.
        other = seal(
            root_run_id="root-noprogress",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=2,
            repair_step_count=0,
            failed_verify_count=1,
            terminal_reason="iteration-cap-exceeded",
            joined_workspace_digest=joined,
        )
        self.assertNotEqual(other.sha256(), first_digest)

    def test_seal_receipt_with_iteration_cap_round_trips(self) -> None:
        # terminal_reason = "iteration-cap-exceeded" is a valid receipt;
        # same digest-stability assertion as the other terminal reasons.
        joined = _digest("iter-cap")
        receipt = seal(
            root_run_id="root-iter-cap",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=3,
            repair_step_count=2,
            failed_verify_count=3,
            terminal_reason="iteration-cap-exceeded",
            joined_workspace_digest=joined,
        )
        self.assertIsInstance(receipt, P5NativeReceipt)
        self.assertEqual(receipt.terminal_reason, "iteration-cap-exceeded")
        first_digest = receipt.sha256()

        again = seal(
            root_run_id="root-iter-cap",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=3,
            repair_step_count=2,
            failed_verify_count=3,
            terminal_reason="iteration-cap-exceeded",
            joined_workspace_digest=joined,
        )
        self.assertEqual(again.sha256(), first_digest)

        # Changing any other field changes the digest.
        other = seal(
            root_run_id="root-iter-cap",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=3,
            repair_step_count=2,
            failed_verify_count=3,
            terminal_reason="success",
            joined_workspace_digest=joined,
        )
        self.assertNotEqual(other.sha256(), first_digest)

    def test_seal_receipt_with_cancelled_round_trips(self) -> None:
        # terminal_reason = "cancelled" is a valid receipt; same
        # digest-stability assertion as the other terminal reasons.
        joined = _digest("cancelled")
        receipt = seal(
            root_run_id="root-cancelled",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=1,
            repair_step_count=0,
            failed_verify_count=1,
            terminal_reason="cancelled",
            joined_workspace_digest=joined,
        )
        self.assertIsInstance(receipt, P5NativeReceipt)
        self.assertEqual(receipt.terminal_reason, "cancelled")
        first_digest = receipt.sha256()

        again = seal(
            root_run_id="root-cancelled",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=1,
            repair_step_count=0,
            failed_verify_count=1,
            terminal_reason="cancelled",
            joined_workspace_digest=joined,
        )
        self.assertEqual(again.sha256(), first_digest)

        other = seal(
            root_run_id="root-cancelled",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=1,
            repair_step_count=0,
            failed_verify_count=1,
            terminal_reason="success",
            joined_workspace_digest=joined,
        )
        self.assertNotEqual(other.sha256(), first_digest)

    def test_build_accepts_caller_supplied_digest(self) -> None:
        # build() is a test-only constructor that does NOT recompute the
        # digest — caller supplies it. Mirrors P3's pattern.
        receipt = build(
            root_run_id="root-build",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=2,
            repair_step_count=1,
            failed_verify_count=1,
            terminal_reason="success",
            joined_workspace_digest=_digest("propose-1"),
            receipt_sha256="c" * 64,
        )
        self.assertEqual(receipt.receipt_sha256, "c" * 64)
        # sha256() computes over the dataclass asdict, including
        # receipt_sha256 itself, so it WILL differ from the caller value.
        self.assertNotEqual(receipt.sha256(), receipt.receipt_sha256)

    def test_media_type_returns_closed_p5_string(self) -> None:
        self.assertEqual(
            media_type(),
            "application/vnd.asterion.prime.p5-native-receipt+json",
        )
        # The closed media type is also reachable via the class.
        self.assertEqual(
            P5NativeReceipt.media_type(),
            "application/vnd.asterion.prime.p5-native-receipt+json",
        )

    def test_seal_receipt_rejects_invalid_inputs(self) -> None:
        joined = _digest("x")
        # propose_step_count must be >= 1.
        with self.assertRaises(P5ReceiptError):
            seal(
                root_run_id="root-1",
                root_generation=1,
                propose_step_count=0,
                verify_step_count=1,
                repair_step_count=0,
                failed_verify_count=1,
                terminal_reason="success",
                joined_workspace_digest=joined,
            )
        # terminal_reason not in the closed 5-element enum.
        with self.assertRaises(P5ReceiptError):
            seal(
                root_run_id="root-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=1,
                repair_step_count=0,
                failed_verify_count=1,
                terminal_reason="still-running",  # type: ignore[arg-type]
                joined_workspace_digest=joined,
            )
        # A repair cannot exist without a failed verify.
        with self.assertRaises(P5ReceiptError):
            seal(
                root_run_id="root-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=1,
                repair_step_count=1,
                failed_verify_count=0,
                terminal_reason="success",
                joined_workspace_digest=joined,
            )
        # repair_step_count must be >= 0.
        with self.assertRaises(P5ReceiptError):
            seal(
                root_run_id="root-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=1,
                repair_step_count=-1,
                failed_verify_count=1,
                terminal_reason="success",
                joined_workspace_digest=joined,
            )
        # Empty root_run_id rejected.
        with self.assertRaises(P5ReceiptError):
            seal(
                root_run_id="",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=1,
                repair_step_count=0,
                failed_verify_count=1,
                terminal_reason="success",
                joined_workspace_digest=joined,
            )


if __name__ == "__main__":
    unittest.main()
