"""Public-safe contract tests for the independent P7 solver package."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from asterion.capabilities.prime_arc_agi_3_solver.host import (
    PrimeArcAgi3SolveReceipt,
    PrimeArcAgi3SolveReceiptError,
    canonical_solve_receipt_sha256,
    validate_prime_arc_agi_3_solve_receipt,
)


class TestPrimeArcAgi3SolveReceipt(unittest.TestCase):
    def test_create_seals_the_exact_canonical_unsigned_receipt(self) -> None:
        unsigned = {
            "run_id": "prime-p7-solve-route",
            "scope": "p7-solving",
            "promotion": "unpromoted",
            "completed_level_count": 1,
            "primitive_action_count": 22,
            "partial_game_score": "3.571429",
        }

        receipt = PrimeArcAgi3SolveReceipt.create(
            run_id=unsigned["run_id"],
            completed_level_count=unsigned["completed_level_count"],
            primitive_action_count=unsigned["primitive_action_count"],
            partial_game_score=unsigned["partial_game_score"],
        )

        self.assertEqual(receipt.scope, "p7-solving")
        self.assertEqual(receipt.promotion, "unpromoted")
        self.assertEqual(receipt.receipt_sha256, canonical_solve_receipt_sha256(unsigned))
        with self.assertRaises(FrozenInstanceError):
            receipt.primitive_action_count = 23  # type: ignore[misc]

    def test_rejects_malformed_or_tampered_receipts_at_retrieval_boundary(self) -> None:
        receipt = PrimeArcAgi3SolveReceipt.create(
            run_id="prime-p7-solve-route",
            completed_level_count=1,
            primitive_action_count=22,
            partial_game_score="3.571429",
        )
        for changes in (
            {"receipt_sha256": "sha256:" + "0" * 64},
            {"primitive_action_count": 23},
            {"partial_game_score": "not-a-score"},
            {"partial_game_score": "100.000001"},
            {"completed_level_count": 0},
        ):
            with self.subTest(changes=changes):
                forged = object.__new__(PrimeArcAgi3SolveReceipt)
                for name, value in vars(receipt).items():
                    object.__setattr__(forged, name, changes.get(name, value))
                with self.assertRaises(PrimeArcAgi3SolveReceiptError):
                    validate_prime_arc_agi_3_solve_receipt(forged)

    def test_rejects_extra_fields_and_noncanonical_scores(self) -> None:
        cases = (
            {"partial_game_score": "3.57142"},
            {"partial_game_score": "03.571429"},
            {"partial_game_score": "3.5714290"},
            {"primitive_action_count": -1},
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(PrimeArcAgi3SolveReceiptError):
                PrimeArcAgi3SolveReceipt.create(
                    run_id="prime-p7-solve-route",
                    completed_level_count=1,
                    primitive_action_count=values.get("primitive_action_count", 22),
                    partial_game_score=values.get("partial_game_score", "3.571429"),
                )
        receipt = PrimeArcAgi3SolveReceipt.create(
            run_id="prime-p7-solve-route",
            completed_level_count=1,
            primitive_action_count=22,
            partial_game_score="3.571429",
        )
        object.__setattr__(receipt, "private_answer", "SENTINEL")
        with self.assertRaises(PrimeArcAgi3SolveReceiptError):
            validate_prime_arc_agi_3_solve_receipt(receipt)


if __name__ == "__main__":
    unittest.main()
