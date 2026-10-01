from __future__ import annotations

import unittest
from dataclasses import replace

from asterion.applications.prime.p7.broker import ArcAction
from asterion.applications.prime.p7.experience_induction import (
    ExperienceInducer,
    SimState,
    extract_action_effect,
)
from asterion.applications.prime.p7.hypothesis_simulator import (
    CounterfactualSearchResult,
    Subgoal,
    search_counterfactual,
)
from asterion.applications.prime.p7.mechanism_model import MechanismRule, MechanismSpec
from asterion.applications.prime.p7.score import digest
from asterion.applications.prime.p7.transition_model import TransitionRule
from asterion.applications.prime.p7.verified_history import ArcHistoryRecord


def _state(*, value: int = 0, level: int = 0) -> SimState:
    return SimState.from_observation(
        frame=((value,),),
        level=level,
        state="NOT_FINISHED",
        available_actions=["ACTION1"],
    )


def _spec(value: int) -> MechanismSpec:
    return MechanismSpec(
        "game", 1, 1,
        (MechanismRule(
            "ACTION1",
            effects=({"op": "set_cell", "args": {"x": 0, "y": 0, "value": value}},),
        ),),
    )


class HypothesisSimulatorTests(unittest.TestCase):
    def test_confirmed_model_branches_without_dispatch_and_reports_subgoal(self) -> None:
        result = search_counterfactual(
            _state(),
            (_spec(7),),
            actions=("ACTION1",),
            subgoals=(Subgoal("paint", cells=((0, 0, 7),)),),
        )

        self.assertIsInstance(result, CounterfactualSearchResult)
        self.assertEqual(result.status, "found")
        self.assertEqual(result.branches[0].evidence_grade, "confirmed")
        self.assertEqual(result.branches[0].state.frame, ((7,),))
        self.assertEqual(result.branches[0].subgoals[0].status, "complete")
        self.assertEqual(result.branches[0].path[0].action["name"], "ACTION1")
        self.assertEqual(result.executed_actions, ())

    def test_hypothesis_is_advisory_and_simulated_with_hypothesis_grade(self) -> None:
        first = ArcHistoryRecord.initial(
            game_id="game", seed=1, run_id="run", frame=((0,),),
            levels_completed=0, state="NOT_FINISHED", after_state_sha256=digest("s0"),
        )
        second = ArcHistoryRecord.following(
            first, action=ArcAction("ACTION1"),
            before_state_sha256=first.after_state_sha256,
            after_state_sha256=digest("s1"), frame=((7,),),
            levels_completed=0, state="NOT_FINISHED",
        )
        effect = extract_action_effect(first, second)
        inducer = ExperienceInducer(win_levels=1)
        inducer.observe(effect)
        inducer.observe(replace(effect, sequence=2, before_state_sha256=digest("s2"), after_state_sha256=digest("s3")))

        result = search_counterfactual(
            _state(),
            (inducer.candidates()[0],),
            actions=("ACTION1",),
            subgoals=(Subgoal("paint", cells=((0, 0, 7),)),),
        )

        self.assertEqual(result.status, "found")
        self.assertEqual(result.branches[0].evidence_grade, "hypothesis")
        self.assertEqual(result.branches[0].subgoals[0].status, "complete")

    def test_divergent_candidates_are_retained_as_conflict_branches(self) -> None:
        result = search_counterfactual(
            _state(),
            (_spec(1), _spec(2)),
            actions=("ACTION1",),
            subgoals=(Subgoal("paint", cells=((0, 0, 1),)),),
        )

        self.assertEqual(result.status, "found")
        self.assertTrue(result.conflicts)
        self.assertTrue(any("candidate-divergence" in item for item in result.conflicts))
        self.assertTrue(any(branch.conflicts for branch in result.branches))
        self.assertEqual(len(result.branches), 2)

    def test_history_only_transition_rule_is_not_executed_or_fabricated(self) -> None:
        rule = TransitionRule(
            action="ACTION1", data=(),
            prior_state_sha256=digest("before"), after_state_sha256=digest("after"),
            prior_level=0, prior_state="NOT_FINISHED",
            prior_frame_sha256=digest("frame-before"), after_frame_sha256=digest("frame-after"),
            changed_cells=(), levels_completed=0, state="NOT_FINISHED",
        )
        result = search_counterfactual(_state(), (rule,), actions=("ACTION1",))

        self.assertEqual(result.status, "no-plan")
        self.assertIn("history-only-transition", result.conflicts)
        self.assertEqual(result.executed_actions, ())
        self.assertEqual(result.branches, ())

    def test_budget_exhaustion_preserves_progress_and_projection(self) -> None:
        result = search_counterfactual(
            _state(),
            (_spec(7),),
            actions=("ACTION1",),
            subgoals=(Subgoal("paint", cells=((0, 0, 9),)),),
            max_nodes=1,
            max_depth=2,
        )

        self.assertEqual(result.status, "budget-exhausted")
        self.assertTrue(result.progress)
        projection = result.projection()
        self.assertEqual(projection["status"], "budget-exhausted")
        self.assertIn("evidence_grade", projection["branches"][0])
        self.assertIn("subgoals", projection["branches"][0])

    def test_default_goal_at_final_level_waits_for_win_state(self) -> None:
        result = search_counterfactual(
            _state(level=1),
            (_spec(7),),
            actions=("ACTION1",),
            max_depth=1,
        )

        self.assertNotEqual(result.status, "found")
        self.assertEqual(result.branches[0].subgoals[0].name, "win-state")
        self.assertEqual(result.branches[0].subgoals[0].status, "unchanged")


if __name__ == "__main__":
    unittest.main()
