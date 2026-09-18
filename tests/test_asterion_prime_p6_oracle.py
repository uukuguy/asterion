"""Tests for P6 oracle (Phase 9, Task 5)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import hashlib
import json
import unittest

from asterion.applications.prime.p6.host import (
    P6AdmittedProposal,
    P6HoldoutResult,
    P6PromotionAction,
)
from asterion.applications.prime.p6.oracle import (
    CandidateStoreVerdict,
    P6Oracle,
    P6OracleError,
    P6OracleReceipt,
)


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _iso(ts: datetime) -> str:
    return ts.replace(microsecond=0).isoformat()


def _admission(
    *,
    proposal_id: str = "prop-1",
    proposal_digest: str | None = "d" * 64,
    revision_id: str = "rev-1",
    when: datetime | None = None,
) -> P6AdmittedProposal:
    if proposal_digest is None:
        proposal_digest = ""
    return P6AdmittedProposal(
        proposal_id=proposal_id,
        proposal_digest=proposal_digest,
        revision_id=revision_id,
        admission_timestamp=when
        or datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc),
    )


def _holdout(
    *,
    task_b_result_sha256: str = "c" * 64,
    non_regressing: bool = True,
    when: datetime | None = None,
) -> P6HoldoutResult:
    return P6HoldoutResult(
        task_b_result_sha256=task_b_result_sha256,
        non_regressing=non_regressing,
        evaluation_timestamp=when
        or datetime(2026, 9, 19, 12, 1, 0, tzinfo=timezone.utc),
    )


def _promotion(
    *,
    promotion_id: str = "prom-1",
    promotion_digest: str | None = "e" * 64,
    target_revision_id: str = "rev-1",
    when: datetime | None = None,
) -> P6PromotionAction:
    if promotion_digest is None:
        promotion_digest = ""
    return P6PromotionAction(
        promotion_id=promotion_id,
        promotion_digest=promotion_digest,
        target_revision_id=target_revision_id,
        promotion_timestamp=when
        or datetime(2026, 9, 19, 12, 2, 0, tzinfo=timezone.utc),
    )


class TestP6Oracle(unittest.TestCase):
    def test_p6_oracle_check_preserved_path_returns_preserved_verdict(self) -> None:
        oracle = P6Oracle()
        receipt = oracle.check(
            root_run_id="root-1",
            admitted_proposal=_admission(),
            holdout_result=_holdout(),
            promotion_action=_promotion(),
            rollback_invocation_count=0,
            global_activation_approved=False,
            signal=None,
        )

        self.assertIsInstance(receipt, P6OracleReceipt)
        self.assertEqual(receipt.verdict, "preserved")
        self.assertEqual(receipt.root_run_id, "root-1")
        self.assertEqual(receipt.rollback_invocation_count, 0)
        self.assertFalse(receipt.global_activation_approved)
        self.assertIsNotNone(receipt.candidate_admission_digest)
        self.assertIsNotNone(receipt.holdout_result_digest)
        self.assertIsNotNone(receipt.promotion_action_digest)
        self.assertTrue(receipt.receipt_sha256)
        self.assertEqual(len(receipt.receipt_sha256), 64)

    def test_p6_oracle_check_rolled_back_path_returns_rolled_back_verdict(self) -> None:
        oracle = P6Oracle()
        receipt = oracle.check(
            root_run_id="root-1",
            admitted_proposal=_admission(),
            holdout_result=_holdout(non_regressing=False),
            promotion_action=None,
            rollback_invocation_count=1,
            global_activation_approved=False,
            signal=None,
        )

        self.assertIsInstance(receipt, P6OracleReceipt)
        self.assertEqual(receipt.verdict, "rolled-back")
        self.assertEqual(receipt.rollback_invocation_count, 1)
        self.assertIsNone(receipt.promotion_action_digest)
        self.assertIsNotNone(receipt.candidate_admission_digest)
        self.assertIsNotNone(receipt.holdout_result_digest)
        self.assertTrue(receipt.receipt_sha256)

    def test_p6_oracle_check_global_rejected_path_returns_global_rejected_verdict(
        self,
    ) -> None:
        oracle = P6Oracle()
        receipt = oracle.check(
            root_run_id="root-1",
            admitted_proposal=None,
            holdout_result=None,
            promotion_action=None,
            rollback_invocation_count=0,
            global_activation_approved=False,
            signal=None,
        )

        self.assertIsInstance(receipt, P6OracleReceipt)
        self.assertEqual(receipt.verdict, "global-rejected")
        self.assertEqual(receipt.rollback_invocation_count, 0)
        self.assertFalse(receipt.global_activation_approved)
        self.assertIsNone(receipt.candidate_admission_digest)
        self.assertIsNone(receipt.holdout_result_digest)
        self.assertIsNone(receipt.promotion_action_digest)
        self.assertTrue(receipt.receipt_sha256)

    def test_p6_oracle_rejects_missing_admitted_proposal_for_preserved_path(
        self,
    ) -> None:
        oracle = P6Oracle()
        with self.assertRaises(P6OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                admitted_proposal=None,
                holdout_result=_holdout(),
                promotion_action=_promotion(),
                rollback_invocation_count=0,
                global_activation_approved=False,
                signal=None,
            )
        # Invariant 1 (candidate admitted) violated.
        self.assertIn("admitted_proposal", str(ctx.exception))

    def test_p6_oracle_rejects_missing_holdout_result_for_preserved_path(
        self,
    ) -> None:
        oracle = P6Oracle()
        with self.assertRaises(P6OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                admitted_proposal=_admission(),
                holdout_result=None,
                promotion_action=_promotion(),
                rollback_invocation_count=0,
                global_activation_approved=False,
                signal=None,
            )
        # Invariant 2 (holdout evaluated) violated.
        self.assertIn("holdout_result", str(ctx.exception))

    def test_p6_oracle_rejects_promotion_action_for_rolled_back_path(self) -> None:
        oracle = P6Oracle()
        with self.assertRaises(P6OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                admitted_proposal=_admission(),
                holdout_result=_holdout(non_regressing=False),
                promotion_action=_promotion(),
                rollback_invocation_count=1,
                global_activation_approved=False,
                signal=None,
            )
        # Invariant 3: rolled-back path forbids promotion_action.
        self.assertIn("rolled-back path forbids promotion_action", str(ctx.exception))

    def test_p6_oracle_rejects_global_activation_approved_true_with_no_admission(
        self,
    ) -> None:
        oracle = P6Oracle()
        with self.assertRaises(P6OracleError) as ctx:
            oracle.check(
                root_run_id="root-1",
                admitted_proposal=None,
                holdout_result=None,
                promotion_action=None,
                rollback_invocation_count=0,
                global_activation_approved=True,
                signal=None,
            )
        # Inconsistent state: global_activation_approved=True without
        # any admitted proposal.
        self.assertIn(
            "global_activation_approved requires admitted_proposal",
            str(ctx.exception),
        )

    def test_p6_oracle_accepts_empty_optional_digest_for_global_rejected_path(
        self,
    ) -> None:
        """P5 Task 5 lesson: type-only _validate_str allows None to reach
        the invariant verdict rather than being over-rejected."""
        oracle = P6Oracle()
        # All inputs are None — the ``global-rejected`` path carries
        # None for every digest field by design. The verdict must
        # still resolve to "global-rejected" cleanly.
        receipt = oracle.check(
            root_run_id="root-1",
            admitted_proposal=None,
            holdout_result=None,
            promotion_action=None,
            rollback_invocation_count=0,
            global_activation_approved=False,
            signal=None,
        )
        self.assertEqual(receipt.verdict, "global-rejected")
        self.assertIsNone(receipt.candidate_admission_digest)
        self.assertIsNone(receipt.holdout_result_digest)
        self.assertIsNone(receipt.promotion_action_digest)

        # Cross-check the canonical-form SHA on the None-bearing
        # inputs: the receipt_sha256 must equal the SHA-256 of
        # canonical-form JSON of the 7 other fields with None
        # serialized as JSON null.
        expected_sha = hashlib.sha256(
            json.dumps(
                {
                    "root_run_id": "root-1",
                    "verdict": "global-rejected",
                    "candidate_admission_digest": None,
                    "holdout_result_digest": None,
                    "promotion_action_digest": None,
                    "rollback_invocation_count": 0,
                    "global_activation_approved": False,
                },
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        self.assertEqual(receipt.receipt_sha256, expected_sha)

    def test_p6_oracle_receipt_is_frozen(self) -> None:
        oracle = P6Oracle()
        receipt = oracle.check(
            root_run_id="root-1",
            admitted_proposal=_admission(),
            holdout_result=_holdout(),
            promotion_action=_promotion(),
            rollback_invocation_count=0,
            global_activation_approved=False,
            signal=None,
        )

        # P6OracleReceipt is a frozen dataclass — mutation must raise.
        with self.assertRaises(FrozenInstanceError):
            receipt.verdict = "rolled-back"  # type: ignore[misc]

        # Same for the digests and counters.
        with self.assertRaises(FrozenInstanceError):
            receipt.rollback_invocation_count = 1  # type: ignore[misc]

    def test_p6_oracle_receipt_sha256_is_canonical_form(self) -> None:
        """Two oracle.check() calls with identical inputs must produce
        identical receipt_sha256 values — the SHA is the canonical-form
        digest of the 7 other fields, deterministic across re-checks."""
        oracle = P6Oracle()
        inputs = dict(
            root_run_id="root-deterministic",
            admitted_proposal=_admission(),
            holdout_result=_holdout(),
            promotion_action=_promotion(),
            rollback_invocation_count=0,
            global_activation_approved=False,
            signal=None,
        )

        receipt_1 = oracle.check(**inputs)
        receipt_2 = oracle.check(**inputs)

        self.assertEqual(receipt_1.receipt_sha256, receipt_2.receipt_sha256)
        self.assertEqual(
            receipt_1.candidate_admission_digest,
            receipt_2.candidate_admission_digest,
        )
        self.assertEqual(
            receipt_1.holdout_result_digest,
            receipt_2.holdout_result_digest,
        )
        self.assertEqual(
            receipt_1.promotion_action_digest,
            receipt_2.promotion_action_digest,
        )
        # Sanity-check: receipt_sha256 is a 64-hex SHA-256 string.
        self.assertEqual(len(receipt_1.receipt_sha256), 64)
        self.assertTrue(
            all(c in "0123456789abcdef" for c in receipt_1.receipt_sha256)
        )

    def test_p6_oracle_verdict_is_closed_three_element_literal(self) -> None:
        """Type-level assertion: CandidateStoreVerdict is the closed
        3-element Literal ``"preserved" | "rolled-back" |
        "global-rejected"``."""
        # The Literal[...] type alias must exist with the exact closed
        # set of three strings. The closed-set guard inside
        # ``P6OracleReceipt.__post_init__`` rejects any value outside
        # the three; this test pins that surface.
        self.assertEqual(
            CandidateStoreVerdict.__args__,  # type: ignore[attr-defined]
            ("preserved", "rolled-back", "global-rejected"),
        )

        # Round-trip: every accepted verdict passes the receipt guard.
        for verdict in ("preserved", "rolled-back", "global-rejected"):
            oracle = P6Oracle()
            if verdict == "preserved":
                receipt = oracle.check(
                    root_run_id="root-1",
                    admitted_proposal=_admission(),
                    holdout_result=_holdout(),
                    promotion_action=_promotion(),
                    rollback_invocation_count=0,
                    global_activation_approved=False,
                    signal=None,
                )
            elif verdict == "rolled-back":
                receipt = oracle.check(
                    root_run_id="root-1",
                    admitted_proposal=_admission(),
                    holdout_result=_holdout(non_regressing=False),
                    promotion_action=None,
                    rollback_invocation_count=1,
                    global_activation_approved=False,
                    signal=None,
                )
            else:  # global-rejected
                receipt = oracle.check(
                    root_run_id="root-1",
                    admitted_proposal=None,
                    holdout_result=None,
                    promotion_action=None,
                    rollback_invocation_count=0,
                    global_activation_approved=False,
                    signal=None,
                )
            self.assertEqual(receipt.verdict, verdict)


if __name__ == "__main__":
    unittest.main()