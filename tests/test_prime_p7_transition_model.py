import unittest
from dataclasses import replace

from asterion.applications.prime.p7.broker import ArcAction
from asterion.applications.prime.p7.score import digest
from asterion.applications.prime.p7.verified_history import ArcHistoryRecord, ArcPredictionError
from asterion.applications.prime.p7.world_model import WorldModelSnapshot


def history():
    first = ArcHistoryRecord.initial(
        game_id="game", seed=1, run_id="run", frame=((0,),), levels_completed=0,
        state="NOT_FINISHED", after_state_sha256=digest("s0"),
    )
    second = ArcHistoryRecord.following(
        first, action=ArcAction("ACTION1"), before_state_sha256=first.after_state_sha256,
        after_state_sha256=digest("s1"), frame=((1,),), levels_completed=0,
        state="NOT_FINISHED",
    )
    return first, second


class TransitionModelTests(unittest.TestCase):
    def setUp(self):
        self.records = history()
        self.world = WorldModelSnapshot("game", 1, 2, {}, {}, {}, 0, 0)

    def test_contiguous_history_builds_model_and_retrodicts(self):
        from asterion.applications.prime.p7.transition_model import TransitionModel, retrodict
        model = TransitionModel.from_history(self.records, world=self.world)
        report = retrodict(model, self.records)
        self.assertTrue(report.ok)
        self.assertEqual(len(model.expectations()), 1)

    def test_gap_and_wrong_before_hash_are_rejected(self):
        from asterion.applications.prime.p7.transition_model import TransitionModel, retrodict
        with self.assertRaises(ArcPredictionError):
            TransitionModel.from_history((self.records[0], replace(self.records[1], sequence=3)), world=self.world)
        report = retrodict(TransitionModel.from_history(self.records, world=self.world),
                           (self.records[0], replace(self.records[1], before_frame_sha256=digest("wrong"))))
        self.assertFalse(report.ok)
        self.assertTrue(all(item.startswith(("sequence:", "before_", "action:", "level:", "state:", "expectation:")) for item in report.failures))

    def test_model_rule_mismatch_is_reported(self):
        from asterion.applications.prime.p7.transition_model import TransitionModel, TransitionRule, retrodict
        model = TransitionModel((TransitionRule(
            action="ACTION1", data=(), prior_state_sha256=self.records[0].after_state_sha256,
            after_state_sha256=digest("wrong-state"), prior_level=0, prior_state="NOT_FINISHED",
            prior_frame_sha256=self.records[0].after_frame_sha256,
            after_frame_sha256=digest("wrong"), changed_cells=(), levels_completed=0,
            state="NOT_FINISHED",
        ),))
        report = retrodict(model, self.records)
        self.assertFalse(report.ok)
        self.assertIn("expectation:frame", report.failures)

    def test_after_state_hash_tampering_is_rejected(self):
        from asterion.applications.prime.p7.transition_model import TransitionModel, retrodict
        model = TransitionModel.from_history(self.records, world=self.world)
        tampered = replace(self.records[1], after_state_sha256=digest("tampered"))
        report = retrodict(model, (self.records[0], tampered))
        self.assertFalse(report.ok)
        self.assertIn("expectation:state_hash", report.failures)

    def test_malformed_rule_is_rejected_at_construction(self):
        from asterion.applications.prime.p7.transition_model import TransitionModel, TransitionRule
        with self.assertRaises(ArcPredictionError):
            TransitionModel((TransitionRule(
                action="ACTION1", data=(("bad", "value"),),
                prior_state_sha256=self.records[0].after_state_sha256,
                after_state_sha256=self.records[1].after_state_sha256,
                prior_level=0, prior_state="NOT_FINISHED",
                prior_frame_sha256=self.records[0].after_frame_sha256,
                after_frame_sha256=self.records[1].after_frame_sha256,
                changed_cells=((64, 0, 0, 1),), levels_completed=0, state="NOT_FINISHED",
            ),))

    def test_state_and_level_mismatch_are_reported(self):
        from asterion.applications.prime.p7.transition_model import TransitionModel, retrodict
        model = TransitionModel.from_history(self.records, world=self.world)
        changed = replace(self.records[1], levels_completed=1, state="GAME_OVER")
        report = retrodict(model, (self.records[0], changed))
        self.assertFalse(report.ok)
        self.assertIn("level:mismatch", report.failures)
        self.assertIn("state:mismatch", report.failures)

    def test_rejected_model_has_no_expectations_and_observation_has_no_public_frame(self):
        from asterion.applications.prime.p7.transition_model import TransitionModel
        with self.assertRaises(ArcPredictionError):
            TransitionModel.from_history((self.records[0], replace(self.records[1], sequence=2)), world=self.world)
        observation = __import__("asterion.applications.prime.p7.verified_history", fromlist=["transition_observation"]).transition_observation(self.records[1])
        observation["frame"] = ((9,),)
        self.assertEqual(self.records[1].frame, ((1,),))
        self.assertNotIn("frame", self.records[1].public_view())


if __name__ == "__main__":
    unittest.main()
