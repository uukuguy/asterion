"""Tests for the P4 host Protocol + frozen dataclasses (Phase 6, Task 5)."""

from __future__ import annotations

import hashlib
import unittest

from asterion.applications.prime.p4.host import (
    P4CommitCall,
    P4CommitReceipt,
    P4Finalization,
    P4RecoveredSession,
    P4RuntimeHost,
    P4RuntimeHostError,
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class TestP4HostProtocol(unittest.TestCase):
    def test_protocol_shape_matches_p2_runtime_host(self) -> None:
        members = {
            name
            for name in dir(P4RuntimeHost)
            if not name.startswith("_")
        }
        # Same five-method shape as P2RuntimeHost, scoped to continuity:
        self.assertIn("validate_runtime_services", members)
        self.assertIn("commit_checkpoint", members)
        self.assertIn("wait_recovery", members)
        self.assertIn("report_recovery_stopped", members)
        self.assertIn("wait_finalization", members)

    def test_commit_call_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(ValueError):
            P4CommitCall(call_id="", prior_checkpoint_sha256=None, continuation_id="c", generation=1)
        with self.assertRaises(ValueError):
            P4CommitCall(
                call_id="ok",
                prior_checkpoint_sha256="not-a-digest",
                continuation_id="c",
                generation=1,
            )
        with self.assertRaises(ValueError):
            P4CommitCall(
                call_id="ok",
                prior_checkpoint_sha256=None,
                continuation_id="",
                generation=1,
            )
        with self.assertRaises(ValueError):
            P4CommitCall(
                call_id="ok",
                prior_checkpoint_sha256=None,
                continuation_id="c",
                generation=0,
            )

    def test_commit_receipt_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(ValueError):
            P4CommitReceipt(
                call_id="ok",
                checkpoint_sha256="not-a-digest",
                result_sha256=_sha(b"r"),
                generation=1,
                bytes_returned=0,
            )
        with self.assertRaises(ValueError):
            P4CommitReceipt(
                call_id="ok",
                checkpoint_sha256=_sha(b"c"),
                result_sha256="not-a-digest",
                generation=1,
                bytes_returned=0,
            )
        with self.assertRaises(ValueError):
            P4CommitReceipt(
                call_id="ok",
                checkpoint_sha256=_sha(b"c"),
                result_sha256=_sha(b"r"),
                generation=0,
                bytes_returned=0,
            )
        with self.assertRaises(ValueError):
            P4CommitReceipt(
                call_id="ok",
                checkpoint_sha256=_sha(b"c"),
                result_sha256=_sha(b"r"),
                generation=1,
                bytes_returned=-1,
            )

    def test_recovered_session_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(ValueError):
            P4RecoveredSession(
                prior_checkpoint_sha256="not-a-digest",
                prior_generation=1,
                recovered_payload_sha256=_sha(b"p"),
                bytes_returned=0,
            )
        with self.assertRaises(ValueError):
            P4RecoveredSession(
                prior_checkpoint_sha256=_sha(b"c"),
                prior_generation=0,
                recovered_payload_sha256=_sha(b"p"),
                bytes_returned=0,
            )
        with self.assertRaises(ValueError):
            P4RecoveredSession(
                prior_checkpoint_sha256=_sha(b"c"),
                prior_generation=1,
                recovered_payload_sha256="not-a-digest",
                bytes_returned=0,
            )
        with self.assertRaises(ValueError):
            P4RecoveredSession(
                prior_checkpoint_sha256=_sha(b"c"),
                prior_generation=1,
                recovered_payload_sha256=_sha(b"p"),
                bytes_returned=-1,
            )

    def test_finalization_completed_requires_receipt(self) -> None:
        with self.assertRaises(ValueError):
            P4Finalization(classification="completed", receipt_sha256=None)
        with self.assertRaises(ValueError):
            P4Finalization(
                classification="completed",
                receipt_sha256="not-a-digest",
            )

    def test_finalization_non_completed_rejects_receipt(self) -> None:
        for classification in ("cancelled", "budget-limited", "recovery-required"):
            with self.subTest(classification=classification):
                with self.assertRaises(ValueError):
                    P4Finalization(
                        classification=classification,  # type: ignore[arg-type]
                        receipt_sha256=_sha(b"r"),
                    )

    def test_finalization_accepts_canonical_shapes(self) -> None:
        for classification in (
            "completed",
            "cancelled",
            "budget-limited",
            "recovery-required",
        ):
            with self.subTest(classification=classification):
                receipt = (
                    _sha(b"r") if classification == "completed" else None
                )
                finalization = P4Finalization(
                    classification=classification,  # type: ignore[arg-type]
                    receipt_sha256=receipt,
                )
                self.assertEqual(finalization.classification, classification)

    def test_runtime_host_error_classification(self) -> None:
        with self.assertRaises(ValueError):
            P4RuntimeHostError(classification="completed")  # type: ignore[arg-type]
        for classification in ("budget-limited", "recovery-required"):
            with self.subTest(classification=classification):
                error = P4RuntimeHostError(classification=classification)  # type: ignore[arg-type]
                self.assertEqual(error.classification, classification)


if __name__ == "__main__":
    unittest.main()