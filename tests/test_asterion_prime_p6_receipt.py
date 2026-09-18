"""Tests for P6 sealed receipt (Phase 9, Task 6)."""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from asterion.applications.prime.p6.receipt import (
    P6NativeReceipt,
    P6ReceiptError,
    build,
    seal_p6_native_receipt,
)


def _digest(payload: str) -> str:
    """Deterministic placeholder for one digest input."""

    import hashlib

    return hashlib.sha256(b"p6:" + payload.encode()).hexdigest()


def _baseline() -> str:
    return _digest("baseline")


def _candidate() -> str:
    return _digest("candidate")


def _task_a() -> str:
    return _digest("task-a-evidence")


def _task_b_preserved() -> str:
    return _digest("task-b-preserved")


def _task_b_rolled_back() -> str:
    return _digest("task-b-rolled-back")


class TestP6Receipt(unittest.TestCase):
    def test_p6_receipt_is_frozen_dataclass(self) -> None:
        # Field-shape proof: the 9 spec fields + failure_digest at the
        # end of the dataclass field order (failure_digest is the 10th
        # field, added beyond the 9-field spec shape).
        receipt = build(
            root_run_id="root-1",
            baseline_snapshot_digest=_baseline(),
            candidate_revision_digest=_candidate(),
            task_a_evidence_digest=_task_a(),
            task_b_result_digest=_task_b_preserved(),
            terminal_outcome="preserved",
            global_activation_approved=False,
            rollback_invocation_count=0,
            receipt_sha256="a" * 64,
            failure_digest=None,
        )
        # The 10-field shape: 9 spec fields + failure_digest (10th).
        dataclass_fields = receipt.__dataclass_fields__
        spec_fields = (
            "root_run_id",
            "baseline_snapshot_digest",
            "candidate_revision_digest",
            "task_a_evidence_digest",
            "task_b_result_digest",
            "terminal_outcome",
            "global_activation_approved",
            "rollback_invocation_count",
            "receipt_sha256",
        )
        for name in spec_fields:
            self.assertIn(name, dataclass_fields)
        # failure_digest is the 10th field, declared after the 9 spec
        # fields. Asserted positionally via dataclass_fields order.
        self.assertIn("failure_digest", dataclass_fields)
        dataclass_field_names = tuple(dataclass_fields.keys())
        self.assertEqual(dataclass_field_names[-1], "failure_digest")
        self.assertEqual(len(dataclass_field_names), 10)
        # Mutating any field raises FrozenInstanceError.
        with self.assertRaises(FrozenInstanceError):
            receipt.root_run_id = "root-2"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            receipt.terminal_outcome = "rolled-back"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            receipt.failure_digest = "b" * 64  # type: ignore[misc]

    def test_p6_seal_computes_canonical_form_sha256(self) -> None:
        # Two seal() calls with identical inputs produce the same
        # receipt_sha256. The digest is canonical-JSON SHA-256.
        kwargs = dict(
            root_run_id="root-1",
            baseline_snapshot_digest=_baseline(),
            candidate_revision_digest=_candidate(),
            task_a_evidence_digest=_task_a(),
            task_b_result_digest=_task_b_preserved(),
            terminal_outcome="preserved",
            global_activation_approved=False,
            rollback_invocation_count=0,
            failure_digest=None,
        )
        receipt_a = build(
            **kwargs,
            receipt_sha256="0" * 64,  # bogus; seal will recompute.
        )
        receipt_b = build(
            **kwargs,
            receipt_sha256="f" * 64,  # different bogus value.
        )
        sealed_a = seal_p6_native_receipt(receipt_a)
        sealed_b = seal_p6_native_receipt(receipt_b)
        # Same digest regardless of bogus pre-existing receipt_sha256.
        self.assertEqual(sealed_a.receipt_sha256, sealed_b.receipt_sha256)
        # Deterministic 64-hex SHA-256.
        self.assertEqual(len(sealed_a.receipt_sha256), 64)
        self.assertTrue(
            all(c in "0123456789abcdef" for c in sealed_a.receipt_sha256)
        )

    def test_p6_seal_rejects_invalid_terminal_outcome(self) -> None:
        # The public 2-element enum is closed. ``global-rejected`` is
        # the oracle's internal verdict (3-element enum) — it MUST
        # NOT appear on the receipt. Spec L376–L380: ``global-rejected``
        # folds into ``terminal_outcome="rolled-back"`` +
        # ``global_activation_approved=False``.
        #
        # Construct the receipt bypassing __post_init__ (via
        # object.__new__) so the test reaches seal_p6_native_receipt's
        # defense-in-depth terminal_outcome validation. __post_init__
        # already rejects this input on the normal construction path;
        # seal()'s check is the receipt boundary's last line.
        receipt = P6NativeReceipt.__new__(P6NativeReceipt)
        object.__setattr__(
            receipt, "root_run_id", "root-1"
        )
        object.__setattr__(
            receipt, "baseline_snapshot_digest", _baseline()
        )
        object.__setattr__(
            receipt, "candidate_revision_digest", _candidate()
        )
        object.__setattr__(
            receipt, "task_a_evidence_digest", _task_a()
        )
        object.__setattr__(
            receipt,
            "task_b_result_digest",
            _task_b_rolled_back(),
        )
        object.__setattr__(
            receipt,
            "terminal_outcome",
            "global-rejected",  # type: ignore[arg-type]
        )
        object.__setattr__(
            receipt, "global_activation_approved", False
        )
        object.__setattr__(
            receipt, "rollback_invocation_count", 0
        )
        object.__setattr__(receipt, "receipt_sha256", "0" * 64)
        object.__setattr__(receipt, "failure_digest", None)
        with self.assertRaises(P6ReceiptError):
            seal_p6_native_receipt(receipt)

    def test_p6_seal_accepts_preserved_and_rolled_back_terminal_outcomes(
        self,
    ) -> None:
        # Both halves of the closed 2-element enum round-trip cleanly.
        for outcome, rb_count, task_b in (
            ("preserved", 0, _task_b_preserved()),
            ("rolled-back", 1, _task_b_rolled_back()),
        ):
            with self.subTest(outcome=outcome):
                receipt = build(
                    root_run_id="root-1",
                    baseline_snapshot_digest=_baseline(),
                    candidate_revision_digest=_candidate(),
                    task_a_evidence_digest=_task_a(),
                    task_b_result_digest=task_b,
                    terminal_outcome=outcome,  # type: ignore[arg-type]
                    global_activation_approved=False,
                    rollback_invocation_count=rb_count,
                    receipt_sha256="0" * 64,
                    failure_digest=None,
                )
                sealed = seal_p6_native_receipt(receipt)
                self.assertEqual(sealed.terminal_outcome, outcome)
                self.assertEqual(
                    sealed.rollback_invocation_count, rb_count
                )
                self.assertEqual(len(sealed.receipt_sha256), 64)

    def test_p6_receipt_preserves_global_activation_approved_flag(
        self,
    ) -> None:
        # The ``global_activation_approved`` flag is preserved through
        # seal(). False = project-scope (the default); True ONLY for
        # global-scope with operator authorization (spec L267).
        for approved in (False, True):
            with self.subTest(global_activation_approved=approved):
                receipt = build(
                    root_run_id="root-1",
                    baseline_snapshot_digest=_baseline(),
                    candidate_revision_digest=_candidate(),
                    task_a_evidence_digest=_task_a(),
                    task_b_result_digest=_task_b_preserved(),
                    terminal_outcome="preserved",
                    global_activation_approved=approved,
                    rollback_invocation_count=0,
                    receipt_sha256="0" * 64,
                    failure_digest=None,
                )
                sealed = seal_p6_native_receipt(receipt)
                self.assertEqual(
                    sealed.global_activation_approved, approved
                )
                # The flag is preserved (not silently normalized).
                self.assertIs(
                    sealed.global_activation_approved, approved
                )

    def test_p6_receipt_failure_digest_field_is_optional(self) -> None:
        # failure_digest accepts None and is preserved through seal().
        receipt_none = build(
            root_run_id="root-1",
            baseline_snapshot_digest=_baseline(),
            candidate_revision_digest=_candidate(),
            task_a_evidence_digest=_task_a(),
            task_b_result_digest=_task_b_preserved(),
            terminal_outcome="preserved",
            global_activation_approved=False,
            rollback_invocation_count=0,
            receipt_sha256="0" * 64,
            failure_digest=None,
        )
        sealed_none = seal_p6_native_receipt(receipt_none)
        self.assertIsNone(sealed_none.failure_digest)

        # failure_digest also accepts a 64-hex SHA-256 (the wrapper's
        # _error_digest(exc) output on an error path).
        digest = "0" * 64
        receipt_set = build(
            root_run_id="root-1",
            baseline_snapshot_digest=_baseline(),
            candidate_revision_digest=_candidate(),
            task_a_evidence_digest=_task_a(),
            task_b_result_digest=_task_b_rolled_back(),
            terminal_outcome="rolled-back",
            global_activation_approved=False,
            rollback_invocation_count=1,
            receipt_sha256="0" * 64,
            failure_digest=digest,
        )
        sealed_set = seal_p6_native_receipt(receipt_set)
        self.assertEqual(sealed_set.failure_digest, digest)

        # The failure_digest is part of the digest payload — changing
        # it changes the receipt_sha256.
        receipt_no_digest = build(
            root_run_id="root-1",
            baseline_snapshot_digest=_baseline(),
            candidate_revision_digest=_candidate(),
            task_a_evidence_digest=_task_a(),
            task_b_result_digest=_task_b_rolled_back(),
            terminal_outcome="rolled-back",
            global_activation_approved=False,
            rollback_invocation_count=1,
            receipt_sha256="0" * 64,
            failure_digest=None,
        )
        sealed_no_digest = seal_p6_native_receipt(receipt_no_digest)
        self.assertNotEqual(
            sealed_set.receipt_sha256, sealed_no_digest.receipt_sha256
        )

    def test_p6_receipt_sha256_excludes_receipt_sha256_field(self) -> None:
        # Test 7: two receipts that differ ONLY in receipt_sha256 (with
        # all other 9 fields plus failure_digest identical) produce the
        # SAME receipt_sha256 after re-sealing. The digest is over the
        # OTHER fields, never over itself.
        kwargs = dict(
            root_run_id="root-1",
            baseline_snapshot_digest=_baseline(),
            candidate_revision_digest=_candidate(),
            task_a_evidence_digest=_task_a(),
            task_b_result_digest=_task_b_preserved(),
            terminal_outcome="preserved",
            global_activation_approved=False,
            rollback_invocation_count=0,
            failure_digest=None,
        )
        receipt_a = build(**kwargs, receipt_sha256="0" * 64)
        receipt_b = build(**kwargs, receipt_sha256="f" * 64)
        sealed_a = seal_p6_native_receipt(receipt_a)
        sealed_b = seal_p6_native_receipt(receipt_b)
        # Identical digests — the bogus pre-existing receipt_sha256
        # values did NOT influence the recomputed digest.
        self.assertEqual(sealed_a.receipt_sha256, sealed_b.receipt_sha256)
        # And the recomputed digest is NOT a function of itself.
        self.assertNotEqual(sealed_a.receipt_sha256, "0" * 64)
        self.assertNotEqual(sealed_a.receipt_sha256, "f" * 64)


if __name__ == "__main__":
    unittest.main()
