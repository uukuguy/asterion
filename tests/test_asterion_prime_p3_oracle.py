"""Tests for P3 oracle (Phase 7, Task 5)."""

from __future__ import annotations

import hashlib
import unittest

from asterion.applications.prime.p3.oracle import (
    P3Oracle,
    P3OracleError,
    P3OracleReceipt,
)


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


_JOINED_SHA = _digest(b"joined-result")
_CHILD_SHA = _digest(b"child-result")


class TestP3Oracle(unittest.TestCase):
    def test_oracle_passes_when_child_admitted_and_joined(self) -> None:
        oracle = P3Oracle()
        receipt = oracle.check(
            root_run_id="root-1",
            root_generation=1,
            child_run_id="child-1",
            child_generation=2,
            child_result_sha256=_CHILD_SHA,
            joined_result_sha256=_JOINED_SHA,
            depth_reached=2,
            refusal_reason=None,
        )

        self.assertIsInstance(receipt, P3OracleReceipt)
        self.assertTrue(receipt.verified)
        self.assertEqual(receipt.verdict, "pass")
        self.assertIsNone(receipt.reason_code)
        self.assertIsNone(receipt.reason_detail)
        # checked_at is a non-empty ISO 8601 UTC string ending in 'Z'.
        self.assertTrue(receipt.checked_at)
        self.assertTrue(receipt.checked_at.endswith("Z"))

    def test_oracle_rejects_when_child_result_missing(self) -> None:
        oracle = P3Oracle()
        # depth=2 with child_run_id=None ⇒ child-not-joined.
        with self.assertRaises(P3OracleError):
            oracle.check(
                root_run_id="root-1",
                root_generation=1,
                child_run_id=None,
                child_generation=None,
                child_result_sha256=None,
                joined_result_sha256=_JOINED_SHA,
                depth_reached=2,
                refusal_reason=None,
            )

    def test_oracle_rejects_when_depth_exceeded(self) -> None:
        oracle = P3Oracle()
        with self.assertRaises(P3OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                root_generation=1,
                child_run_id=None,
                child_generation=None,
                child_result_sha256=None,
                joined_result_sha256=_JOINED_SHA,
                depth_reached=1,
                refusal_reason="depth-exceeded",
            )
        self.assertIn("depth-exceeded", str(ctx.exception))

    def test_oracle_rejects_when_concurrency_exceeded(self) -> None:
        oracle = P3Oracle()
        with self.assertRaises(P3OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                root_generation=1,
                child_run_id=None,
                child_generation=None,
                child_result_sha256=None,
                joined_result_sha256=_JOINED_SHA,
                depth_reached=1,
                refusal_reason="concurrency-exceeded",
            )
        self.assertIn("concurrency-exceeded", str(ctx.exception))

    def test_oracle_rejects_when_budget_exceeded(self) -> None:
        oracle = P3Oracle()
        with self.assertRaises(P3OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                root_generation=1,
                child_run_id=None,
                child_generation=None,
                child_result_sha256=None,
                joined_result_sha256=_JOINED_SHA,
                depth_reached=1,
                refusal_reason="budget-exceeded",
            )
        self.assertIn("budget-exceeded", str(ctx.exception))

    def test_oracle_rejects_when_cancelled(self) -> None:
        oracle = P3Oracle()
        with self.assertRaises(P3OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                root_generation=1,
                child_run_id=None,
                child_generation=None,
                child_result_sha256=None,
                joined_result_sha256=_JOINED_SHA,
                depth_reached=1,
                refusal_reason="cancelled",
            )
        self.assertIn("cancelled", str(ctx.exception))

    def test_oracle_rejects_when_session_backend_rejected(self) -> None:
        oracle = P3Oracle()
        with self.assertRaises(P3OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                root_generation=1,
                child_run_id=None,
                child_generation=None,
                child_result_sha256=None,
                joined_result_sha256=_JOINED_SHA,
                depth_reached=1,
                refusal_reason="session-backend-rejected",
            )
        self.assertIn("session-backend-rejected", str(ctx.exception))

    def test_oracle_accepts_root_alone_when_depth_one(self) -> None:
        oracle = P3Oracle()
        receipt = oracle.check(
            root_run_id="root-alone",
            root_generation=1,
            child_run_id=None,
            child_generation=None,
            child_result_sha256=None,
            joined_result_sha256=_JOINED_SHA,
            depth_reached=1,
            refusal_reason=None,
        )

        self.assertIsInstance(receipt, P3OracleReceipt)
        self.assertTrue(receipt.verified)
        self.assertEqual(receipt.verdict, "pass")
        self.assertIsNone(receipt.reason_code)
        self.assertIsNone(receipt.reason_detail)


if __name__ == "__main__":
    unittest.main()
