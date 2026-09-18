"""Tests for P3 sealed receipt (Phase 7, Task 6)."""

from __future__ import annotations

import unittest

from asterion.applications.prime.p3.receipt import (
    P3NativeReceipt,
    build,
    seal,
)


def _root_result_sha(root_run_id: str) -> str:
    """A deterministic placeholder for the root run's own result digest."""

    import hashlib

    return hashlib.sha256(
        b"root-result:" + root_run_id.encode()
    ).hexdigest()


def _child_result_sha(child_run_id: str) -> str:
    """A deterministic placeholder for the child run's sealed result digest."""

    import hashlib

    return hashlib.sha256(
        b"child-result:" + child_run_id.encode()
    ).hexdigest()


def _joined_sha(
    *,
    root_run_id: str,
    child_run_id: str | None,
    depth_reached: int,
) -> str:
    """Mirror of P3 spec: deterministic SHA of
    (root_result_sha || child_result_sha || depth_reached) as canonical
    JSON bytes."""

    import hashlib
    import json

    root_sha = _root_result_sha(root_run_id)
    child_sha = (
        _child_result_sha(child_run_id)
        if child_run_id is not None
        else None
    )
    payload = {
        "child_result_sha256": child_sha,
        "depth_reached": depth_reached,
        "root_result_sha256": root_sha,
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


class TestP3Receipt(unittest.TestCase):
    def test_seal_receipt_is_digest_stable(self) -> None:
        root_run_id = "root-1"
        child_run_id = "child-1"
        joined = _joined_sha(
            root_run_id=root_run_id,
            child_run_id=child_run_id,
            depth_reached=2,
        )

        receipt = seal(
            root_run_id=root_run_id,
            root_generation=1,
            child_run_id=child_run_id,
            child_generation=2,
            child_result_sha256=_child_result_sha(child_run_id),
            joined_result_sha256=joined,
            depth_reached=2,
            refusal_reason=None,
        )
        self.assertIsInstance(receipt, P3NativeReceipt)
        first_digest = receipt.sha256()

        # Re-sealing with identical inputs is idempotent (same digest).
        receipt_again = seal(
            root_run_id=root_run_id,
            root_generation=1,
            child_run_id=child_run_id,
            child_generation=2,
            child_result_sha256=_child_result_sha(child_run_id),
            joined_result_sha256=joined,
            depth_reached=2,
            refusal_reason=None,
        )
        self.assertEqual(receipt_again.sha256(), first_digest)

        # Any field change -> different digest. Vary joined_result_sha256
        # because it is invariant under the consistency check.
        receipt_other = seal(
            root_run_id=root_run_id,
            root_generation=1,
            child_run_id=child_run_id,
            child_generation=2,
            child_result_sha256=_child_result_sha(child_run_id),
            joined_result_sha256="0" * 64,
            depth_reached=2,
            refusal_reason=None,
        )
        self.assertNotEqual(receipt_other.sha256(), first_digest)

    def test_seal_receipt_with_null_child_round_trips(self) -> None:
        root_run_id = "root-alone"
        joined = _joined_sha(
            root_run_id=root_run_id,
            child_run_id=None,
            depth_reached=1,
        )

        receipt = seal(
            root_run_id=root_run_id,
            root_generation=1,
            child_run_id=None,
            child_generation=None,
            child_result_sha256=None,
            joined_result_sha256=joined,
            depth_reached=1,
            refusal_reason=None,
        )
        self.assertIsInstance(receipt, P3NativeReceipt)
        self.assertIsNone(receipt.child_run_id)
        self.assertIsNone(receipt.child_generation)
        self.assertIsNone(receipt.child_result_sha256)
        self.assertIsNone(receipt.refusal_reason)
        self.assertEqual(receipt.depth_reached, 1)
        self.assertEqual(receipt.root_run_id, root_run_id)
        self.assertEqual(receipt.joined_result_sha256, joined)
        self.assertEqual(receipt.joined_result_sha256, joined)
        self.assertEqual(len(receipt.receipt_sha256), 64)

    def test_seal_receipt_with_refusal_reason(self) -> None:
        root_run_id = "root-refused"
        joined = _joined_sha(
            root_run_id=root_run_id,
            child_run_id=None,
            depth_reached=1,
        )

        receipt = seal(
            root_run_id=root_run_id,
            root_generation=1,
            child_run_id=None,
            child_generation=None,
            child_result_sha256=None,
            joined_result_sha256=joined,
            depth_reached=1,
            refusal_reason="depth-exceeded",
        )
        self.assertIsInstance(receipt, P3NativeReceipt)
        self.assertEqual(receipt.refusal_reason, "depth-exceeded")
        # No child on a refusal.
        self.assertIsNone(receipt.child_run_id)
        self.assertIsNone(receipt.child_generation)
        self.assertIsNone(receipt.child_result_sha256)

        # The digest must change when the refusal reason changes.
        receipt_other_reason = seal(
            root_run_id=root_run_id,
            root_generation=1,
            child_run_id=None,
            child_generation=None,
            child_result_sha256=None,
            joined_result_sha256=joined,
            depth_reached=1,
            refusal_reason="budget-exceeded",
        )
        self.assertNotEqual(
            receipt_other_reason.sha256(), receipt.sha256()
        )

        # And the digest must change when a refusal is present vs absent.
        receipt_no_refusal = seal(
            root_run_id=root_run_id,
            root_generation=1,
            child_run_id=None,
            child_generation=None,
            child_result_sha256=None,
            joined_result_sha256=joined,
            depth_reached=1,
            refusal_reason=None,
        )
        self.assertNotEqual(receipt_no_refusal.sha256(), receipt.sha256())

    def test_build_accepts_caller_supplied_digest(self) -> None:
        # build() is a test-only constructor that does NOT recompute the
        # digest — caller supplies it. Mirrors P4's pattern.
        receipt = build(
            root_run_id="root-build",
            root_generation=1,
            child_run_id="child-build",
            child_generation=2,
            child_result_sha256="a" * 64,
            joined_result_sha256="b" * 64,
            depth_reached=2,
            refusal_reason=None,
            receipt_sha256="c" * 64,
        )
        self.assertEqual(receipt.receipt_sha256, "c" * 64)
        # sha256() computes over the dataclass asdict, including
        # receipt_sha256 itself, so it WILL differ from the caller value.
        self.assertNotEqual(receipt.sha256(), receipt.receipt_sha256)


if __name__ == "__main__":
    unittest.main()