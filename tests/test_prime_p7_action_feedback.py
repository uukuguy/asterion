"""Bounded, game-neutral action-effect feedback for checked P7 plans."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest


class TestP7ActionFeedback(unittest.TestCase):
    def test_checked_result_contains_bounded_changed_frame_feedback(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from tests.test_prime_p7_native_broker import _HistoryEngine

        broker = ArcBroker(engine=_HistoryEngine())
        broker.bind_history("run-feedback")
        result = broker.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"cell": {"x": 0, "y": 0, "value": 1}},
        }])

        feedback = result["feedback"][0]
        history = broker.history(1, 1)[0]
        self.assertEqual(feedback, {
            "changed_cell_count": 1,
            "changed_cells": [[0, 0, 0, 1]],
            "changed_cells_omitted": 0,
            "before_frame_sha256": history["before_frame_sha256"],
            "after_frame_sha256": history["after_frame_sha256"],
            "levels_completed": 0,
            "state": "NOT_FINISHED",
            "no_effect": False,
            "stop_reason": "matched",
        })
        self.assertNotIn("frame", feedback)

    def test_checked_result_marks_no_effect_feedback_and_preserves_count(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from tests.test_prime_p7_native_broker import _SettledNoEffectEngine

        broker = ArcBroker(engine=_SettledNoEffectEngine())
        broker.bind_history("run-no-effect-feedback")
        result = broker.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"cell": {"x": 0, "y": 0, "value": 7}},
        }])

        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["feedback"][0]["changed_cell_count"], 0)
        self.assertEqual(result["feedback"][0]["changed_cells"], [])
        self.assertTrue(result["feedback"][0]["no_effect"])
        self.assertEqual(result["feedback"][0]["stop_reason"], "observation-no-change")

    def test_operator_forwards_feedback_without_frame(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from tests.test_prime_p7_native_broker import _HistoryEngine

        with tempfile.TemporaryDirectory() as directory:
            broker = ArcBroker(engine=_HistoryEngine())
            broker.bind_history("run-client-feedback")
            recorder = PrimeTraceRecorder(Path(directory))
            try:
                result = _P7BrokerClient(broker, recorder).act_checked([{
                    "action": {"name": "ACTION1", "data": {}},
                    "expect": {"cell": {"x": 0, "y": 0, "value": 1}},
                }])
            finally:
                recorder.close()

        self.assertEqual(result["feedback"][0]["changed_cells"], [[0, 0, 0, 1]])
        self.assertNotIn("frame", result["feedback"][0])
