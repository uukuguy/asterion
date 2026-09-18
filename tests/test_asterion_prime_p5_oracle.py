"""Tests for P5 oracle (Phase 8, Task 5)."""

from __future__ import annotations

import hashlib
import unittest

from asterion.applications.prime.p5.oracle import (
    P5Oracle,
    P5OracleError,
    P5OracleReceipt,
)


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


_JOINED_DIGEST = _digest(b"joined-workspace")


class TestP5Oracle(unittest.TestCase):
    def test_oracle_passes_when_success_path_with_one_repair(self) -> None:
        oracle = P5Oracle()
        receipt = oracle.check(
            root_run_id="root-1",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=2,
            repair_step_count=1,
            failed_verify_count=1,
            terminal_reason="success",
            joined_workspace_digest=_JOINED_DIGEST,
        )

        self.assertIsInstance(receipt, P5OracleReceipt)
        self.assertTrue(receipt.verified)
        self.assertEqual(receipt.verdict, "pass")
        self.assertIsNone(receipt.reason_code)
        self.assertIsNone(receipt.reason_detail)
        # checked_at is a non-empty ISO 8601 UTC string ending in 'Z'.
        self.assertTrue(receipt.checked_at)
        self.assertTrue(receipt.checked_at.endswith("Z"))

    def test_oracle_rejects_when_propose_step_count_zero(self) -> None:
        oracle = P5Oracle()
        with self.assertRaises(P5OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                root_generation=1,
                propose_step_count=0,
                verify_step_count=1,
                repair_step_count=0,
                failed_verify_count=0,
                terminal_reason="success",
                joined_workspace_digest=_JOINED_DIGEST,
            )
        self.assertIn("propose-not-admitted", str(ctx.exception))

    def test_oracle_rejects_when_no_failure_and_no_progress(self) -> None:
        oracle = P5Oracle()
        # failed_verify_count=0 AND repair_step_count=0 with success path is
        # only valid when verify_step_count >= 1 (single-propose success path
        # is handled in the dedicated test below). Here verify_step_count=0
        # to exercise the "no failure, no repair, no verify" rejection.
        with self.assertRaises(P5OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=0,
                repair_step_count=0,
                failed_verify_count=0,
                terminal_reason="success",
                joined_workspace_digest=_JOINED_DIGEST,
            )
        self.assertIn("verify-not-run", str(ctx.exception))

    def test_oracle_rejects_when_iteration_cap_exceeded(self) -> None:
        oracle = P5Oracle()
        with self.assertRaises(P5OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                root_generation=1,
                propose_step_count=5,
                verify_step_count=5,
                repair_step_count=2,
                failed_verify_count=2,
                terminal_reason="iteration-cap-exceeded",
                joined_workspace_digest=_JOINED_DIGEST,
            )
        self.assertIn("iteration-cap-exceeded", str(ctx.exception))

    def test_oracle_rejects_when_duration_cap_exceeded(self) -> None:
        oracle = P5Oracle()
        with self.assertRaises(P5OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                root_generation=1,
                propose_step_count=5,
                verify_step_count=5,
                repair_step_count=2,
                failed_verify_count=2,
                terminal_reason="duration-cap-exceeded",
                joined_workspace_digest=_JOINED_DIGEST,
            )
        self.assertIn("duration-cap-exceeded", str(ctx.exception))

    def test_oracle_rejects_when_no_progress(self) -> None:
        oracle = P5Oracle()
        with self.assertRaises(P5OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=1,
                repair_step_count=0,
                failed_verify_count=0,
                terminal_reason="no-progress",
                joined_workspace_digest=_JOINED_DIGEST,
            )
        self.assertIn("no-progress", str(ctx.exception))

    def test_oracle_rejects_when_cancelled(self) -> None:
        oracle = P5Oracle()
        with self.assertRaises(P5OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=1,
                repair_step_count=0,
                failed_verify_count=0,
                terminal_reason="cancelled",
                joined_workspace_digest=_JOINED_DIGEST,
            )
        self.assertIn("cancelled", str(ctx.exception))

    def test_oracle_rejects_when_joined_workspace_digest_empty(self) -> None:
        oracle = P5Oracle()
        with self.assertRaises(P5OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=1,
                repair_step_count=0,
                failed_verify_count=0,
                terminal_reason="success",
                joined_workspace_digest="",
            )
        self.assertIn("empty-workspace-digest", str(ctx.exception))

    def test_oracle_accepts_root_alone_when_no_repair_yet_success(self) -> None:
        oracle = P5Oracle()
        # Single-propose success path: verify_step_count=1, repair_step_count=0,
        # failed_verify_count=0, joined_workspace_digest non-empty.
        receipt = oracle.check(
            root_run_id="root-alone",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=1,
            repair_step_count=0,
            failed_verify_count=0,
            terminal_reason="success",
            joined_workspace_digest=_JOINED_DIGEST,
        )

        self.assertIsInstance(receipt, P5OracleReceipt)
        self.assertTrue(receipt.verified)
        self.assertEqual(receipt.verdict, "pass")
        self.assertIsNone(receipt.reason_code)
        self.assertIsNone(receipt.reason_detail)

    def test_oracle_constructor_rejects_wrong_types(self) -> None:
        oracle = P5Oracle()
        # propose_step_count must be an int, not a string.
        with self.assertRaises(P5OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                root_generation=1,
                propose_step_count="1",  # type: ignore[arg-type]
                verify_step_count=1,
                repair_step_count=0,
                failed_verify_count=0,
                terminal_reason="success",
                joined_workspace_digest=_JOINED_DIGEST,
            )
        self.assertIn("propose_step_count", str(ctx.exception))

    def test_oracle_rejects_when_terminal_reason_unknown(self) -> None:
        oracle = P5Oracle()
        with self.assertRaises(P5OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=1,
                repair_step_count=0,
                failed_verify_count=0,
                terminal_reason="garbage",
                joined_workspace_digest=_JOINED_DIGEST,
            )
        self.assertIn("unknown-terminal-reason", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
