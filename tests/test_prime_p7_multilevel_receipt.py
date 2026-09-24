"""P7 target-level receipts retain a cumulative, bounded local score."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest


class _TwoLevelEngine:
    game_id = "ls20-9607627b"
    seed = 0

    def __init__(self) -> None:
        self.calls = 0
        self.levels_completed = 0

    def observe(self) -> dict[str, object]:
        return {
            "available_actions": ["ACTION1"],
            "frame": [[[self.calls]]],
            "levels_completed": self.levels_completed,
            "state": "NOT_FINISHED",
            "win_levels": 7,
        }

    def step(self, action: str) -> dict[str, object]:
        del action
        self.calls += 1
        if self.calls in (2, 5):
            self.levels_completed += 1
        return self.observe()


class TestP7MultilevelReceipt(unittest.TestCase):
    def test_full_game_receipt_requires_terminal_win(self) -> None:
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt, P7PrivateTraceReceiptError
        from tests.test_prime_p7_native_broker import _FullGameEngine

        game = P7GameSelection("ls20-9607627b", 0, 7)
        for state in ("WIN", "NOT_FINISHED"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                broker = ArcBroker(engine=_FullGameEngine(final_state=state), game=game)
                for _ in range(7):
                    broker.act(("ACTION1",))
                trace = P7PrivateTraceReceipt(broker, PrimeTraceRecorder(Path(directory)))
                try:
                    if state == "WIN":
                        expected = trace.expected_receipt_sha256(run_id="p7-full")
                        receipt = trace.get_receipt(run_id="p7-full", receipt_sha256=expected)
                        self.assertEqual(receipt.completed_level_count, 7)
                        self.assertEqual(receipt.partial_game_score, "100.000000")
                    else:
                        with self.assertRaises(P7PrivateTraceReceiptError):
                            trace.expected_receipt_sha256(run_id="p7-full")
                finally:
                    trace.close()

    def test_failed_attempt_and_reset_count_toward_completed_level(self) -> None:
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt
        from asterion.applications.prime.p7.score import partial_game_score
        from tests.test_prime_p7_native_broker import _ResetEngine

        game = P7GameSelection("ls20-9607627b", 0, target_level=2)
        broker = ArcBroker(engine=_ResetEngine(), game=game)
        broker.act(("ACTION1",))
        broker.act(("ACTION1",))
        broker.act(("RESET",))
        broker.act(("ACTION1",))
        with tempfile.TemporaryDirectory() as directory:
            trace = P7PrivateTraceReceipt(broker, PrimeTraceRecorder(Path(directory)))
            expected = trace.expected_receipt_sha256(run_id="p7-reset")
            receipt = trace.get_receipt(run_id="p7-reset", receipt_sha256=expected)

        self.assertEqual(receipt.primitive_action_count, 4)
        self.assertEqual(receipt.partial_game_score, partial_game_score((1, 3), game))

    def test_target_two_receipt_scores_each_completed_level_from_journal(self) -> None:
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt

        game = P7GameSelection("ls20-9607627b", 0, target_level=2)
        broker = ArcBroker(engine=_TwoLevelEngine(), game=game)
        broker.act(("ACTION1",) * 3)
        broker.act(("ACTION1",) * 3)
        with tempfile.TemporaryDirectory() as directory:
            trace = P7PrivateTraceReceipt(
                broker, PrimeTraceRecorder(Path(directory))
            )
            expected = trace.expected_receipt_sha256(run_id="p7-two-level")
            receipt = trace.get_receipt(
                run_id="p7-two-level", receipt_sha256=expected
            )

        self.assertEqual(receipt.completed_level_count, 2)
        self.assertEqual(receipt.primitive_action_count, 5)
        self.assertEqual(receipt.partial_game_score, "10.714286")

    def test_score_caps_completed_levels_at_their_weighted_completion_share(self) -> None:
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.score import partial_game_score

        self.assertEqual(
            partial_game_score((2, 3), P7GameSelection("ls20-9607627b", 0, 2)),
            "10.714286",
        )

    def test_public_receipt_accepts_bounded_multilevel_completion(self) -> None:
        from asterion.capabilities.prime_arc_agi_3_solver.host import (
            PrimeArcAgi3SolveReceipt,
            PrimeArcAgi3SolveReceiptError,
            validate_prime_arc_agi_3_solve_receipt,
        )

        receipt = PrimeArcAgi3SolveReceipt.create(
            run_id="p7-two-level",
            completed_level_count=2,
            primitive_action_count=5,
            partial_game_score="10.714286",
        )
        validate_prime_arc_agi_3_solve_receipt(receipt)
        with self.assertRaises(PrimeArcAgi3SolveReceiptError):
            PrimeArcAgi3SolveReceipt.create(
                run_id="p7-ten-levels",
                completed_level_count=10,
                primitive_action_count=5,
                partial_game_score="100.000000",
            )
