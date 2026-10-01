"""Tests for bounded action-effect extraction and immutable simulation state."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import unittest

from asterion.applications.prime.p7.broker import ArcAction
from asterion.applications.prime.p7.experience_induction import (
    EffectHypothesis,
    ExperienceInducer,
    ProbePlan,
    SimState,
    extract_action_effect,
)
from asterion.applications.prime.p7.score import digest
from asterion.applications.prime.p7.verified_history import ArcHistoryRecord


def records(*, action: ArcAction, before: tuple[tuple[int, ...], ...], after: tuple[tuple[int, ...], ...],
            level: int = 0, state: str = "NOT_FINISHED", levels: int = 0) -> tuple[ArcHistoryRecord, ArcHistoryRecord]:
    first = ArcHistoryRecord.initial(
        game_id="game", seed=1, run_id="run", frame=before,
        levels_completed=0, state="NOT_FINISHED", after_state_sha256=digest("s0"),
    )
    second = ArcHistoryRecord.following(
        first, action=action, before_state_sha256=first.after_state_sha256,
        after_state_sha256=digest((state, levels)), frame=after,
        levels_completed=levels, state=state,
    )
    return first, second


class ExperienceInductionTests(unittest.TestCase):
    def test_extracts_normalized_click_effect_and_connected_components(self) -> None:
        first, second = records(
            action=ArcAction("ACTION6", (("x", 2), ("y", 1))),
            before=((0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0)),
            after=((0, 0, 0, 0), (0, 7, 7, 0), (0, 0, 0, 0)),
        )
        effect = extract_action_effect(first, second)
        self.assertEqual(effect.action, "ACTION6")
        self.assertEqual(effect.data, (("x", 2), ("y", 1)))
        self.assertEqual(effect.outcome, "changed")
        self.assertEqual(effect.changed_cell_count, 2)
        self.assertEqual(len(effect.components), 1)
        self.assertEqual(effect.components[0].bounds, (1, 1, 2, 1))
        self.assertEqual(effect.components[0].old_values, (0, 0))
        self.assertEqual(effect.components[0].new_values, (7, 7))

    def test_keyboard_and_no_effect_are_distinguished(self) -> None:
        first, second = records(
            action=ArcAction("ACTION1"), before=((4, 4),), after=((4, 4),),
        )
        effect = extract_action_effect(first, second)
        self.assertEqual(effect.outcome, "no-effect")
        self.assertEqual(effect.changed_cell_count, 0)
        self.assertEqual(effect.components, ())

    def test_level_transition_and_terminal_outcome_are_explicit(self) -> None:
        first, second = records(
            action=ArcAction("ACTION2"), before=((1,),), after=((2,),),
            level=1, levels=1, state="WIN",
        )
        effect = extract_action_effect(first, second)
        self.assertEqual(effect.outcome, "level-transition")
        self.assertEqual(effect.levels_completed, 1)
        self.assertEqual(effect.state, "WIN")
        candidate = ExperienceInducer(win_levels=2)
        candidate.observe(effect)
        self.assertEqual(candidate.candidates()[0].status, "hypothesis")

    def test_extract_rejects_non_adjacent_or_mismatched_identity(self) -> None:
        first, second = records(
            action=ArcAction("ACTION1"), before=((0,),), after=((1,),),
        )
        from dataclasses import replace
        with self.assertRaises(ValueError):
            extract_action_effect(first, replace(second, sequence=2))
        with self.assertRaises(ValueError):
            extract_action_effect(first, replace(second, game_id="other"))

    def test_sim_state_is_immutable_and_normalizes_observation(self) -> None:
        frame = [[1, 2], [3, 4]]
        entities = {"player": {"x": 1, "y": 0}}
        state = SimState.from_observation(
            frame=frame, level=0, state="NOT_FINISHED",
            available_actions=["ACTION1", "ACTION6"], entities=entities,
        )
        frame[0][0] = 9
        entities["player"]["x"] = 8
        self.assertEqual(state.frame, ((1, 2), (3, 4)))
        self.assertEqual(state.entities, (("player", (("x", 1), ("y", 0))),))
        self.assertEqual(state.available_actions, ("ACTION1", "ACTION6"))
        with self.assertRaises(FrozenInstanceError):
            state.level = 1  # type: ignore[misc]

    def test_sim_state_rejects_invalid_or_duplicate_actions(self) -> None:
        for actions in (["ACTION1", "ACTION1"], ["UNKNOWN"], [], ["RESET"]):
            with self.subTest(actions=actions):
                with self.assertRaises(ValueError):
                    SimState.from_observation(
                        frame=((0,),), level=0, state="NOT_FINISHED",
                        available_actions=actions,
                    )

    def test_repeated_effects_form_one_hypothesis_with_bounded_evidence(self) -> None:
        inducer = ExperienceInducer(max_effects=4)
        before = ((0, 0), (0, 0))
        for value in (7, 7):
            first, second = records(
                action=ArcAction("ACTION1"), before=before,
                after=((value, 0), (0, 0)),
            )
            effect = extract_action_effect(first, second)
            inducer.observe(effect if value == 7 and not inducer.effects() else replace(effect, sequence=2))
        candidates = inducer.candidates()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].support_count, 2)
        self.assertEqual(candidates[0].status, "hypothesis")
        self.assertEqual(candidates[0].evidence_sequences, (1, 2))

    def test_candidate_exposes_insufficient_support_reason(self) -> None:
        inducer = ExperienceInducer()
        first, second = records(
            action=ArcAction("ACTION1"), before=((0,),), after=((7,),),
        )
        inducer.observe(extract_action_effect(first, second))

        candidate = inducer.candidates()[0]

        self.assertEqual(candidate.refusal_reason, "insufficient-support")
        self.assertIn("insufficient-support", candidate.refusal_reasons)

    def test_candidate_exposes_ambiguous_motion_reason(self) -> None:
        inducer = ExperienceInducer()
        first, second = records(
            action=ArcAction("ACTION1"), before=((7, 8),), after=((8, 7),),
        )
        effect = extract_action_effect(first, second)
        inducer.observe(effect)
        inducer.observe(replace(effect, sequence=2))

        candidate = inducer.candidates()[0]

        self.assertIn("ambiguous-motion", candidate.refusal_reasons)

    def test_repeated_no_effect_stays_a_boundary_and_is_not_probeable(self) -> None:
        inducer = ExperienceInducer()
        first, second = records(action=ArcAction("ACTION1"), before=((4,),), after=((4,),))
        effect = extract_action_effect(first, second)
        inducer.observe(effect)
        inducer.observe(replace(effect, sequence=2))
        self.assertEqual(inducer.candidates()[0].status, "boundary")
        current = SimState.from_observation(
            frame=((4,),), level=0, state="NOT_FINISHED", available_actions=["ACTION1"],
        )
        self.assertEqual(ExperienceInducer.probe_plan(current, inducer.candidates()).status, "no-discriminating-probe")

    def test_candidate_exposes_partial_delta_reason(self) -> None:
        inducer = ExperienceInducer()
        first, second = records(
            action=ArcAction("ACTION1"), before=((0, 0),), after=((7, 7),),
        )
        effect = extract_action_effect(first, second)
        effect = replace(effect, changed_cells_omitted=1)
        inducer.observe(effect)
        inducer.observe(replace(effect, sequence=2))

        candidate = inducer.candidates()[0]

        self.assertIn("partial-delta", candidate.refusal_reasons)

    def test_candidate_exposes_context_conflict_reason(self) -> None:
        inducer = ExperienceInducer()
        first, second = records(
            action=ArcAction("ACTION1"), before=((0,),), after=((7,),),
        )
        inducer.observe(extract_action_effect(first, second))
        first, second = records(
            action=ArcAction("ACTION1"), before=((0,),), after=((8,),),
        )
        inducer.observe(extract_action_effect(first, second))

        self.assertTrue(all(
            "context-conflict" in item.refusal_reasons
            for item in inducer.candidates()
        ))

    def test_candidate_exposes_unsupported_residual_reason(self) -> None:
        inducer = ExperienceInducer()
        first, second = records(
            action=ArcAction("ACTION1"), before=((7, 0, 0),), after=((0, 7, 8),),
        )
        effect = extract_action_effect(first, second)
        self.assertIsNone(effect.motion_reason)
        effect = replace(effect, motion_reason="unsupported-residual")
        inducer.observe(effect)
        inducer.observe(replace(effect, sequence=2))

        self.assertIn("unsupported-residual", inducer.candidates()[0].refusal_reasons)

    def test_candidate_accepts_retrodiction_mismatch_diagnostic(self) -> None:
        candidate = EffectHypothesis(
            key="retrodiction", game_id="game", seed=1, level=0,
            action_family="keyboard", action="ACTION1", data=(),
            signature="cell-edit", status="hypothesis",
            evidence_sequences=(1, 2), conflict_sequences=(),
            diagnostic_reasons=("retrodiction-mismatch",),
        )

        self.assertEqual(candidate.refusal_reason, "retrodiction-mismatch")

    def test_boundary_observation_does_not_contradict_consistent_motion(self) -> None:
        inducer = ExperienceInducer()
        first, second = records(
            action=ArcAction("ACTION1"),
            before=((7, 0, 0),),
            after=((0, 7, 0),),
        )
        motion = extract_action_effect(first, second)
        inducer.observe(motion)
        inducer.observe(replace(motion, sequence=2))

        boundary_first, boundary_second = records(
            action=ArcAction("ACTION1"),
            before=((7, 0, 0),),
            after=((7, 0, 0),),
        )
        boundary = extract_action_effect(boundary_first, boundary_second)
        inducer.observe(replace(boundary, sequence=3))

        candidates = inducer.candidates()
        motion_candidate = next(item for item in candidates if item.signature.startswith("('translation'"))
        boundary_candidate = next(item for item in candidates if item.signature.startswith("('no-effect'"))
        self.assertEqual(motion_candidate.status, "hypothesis")
        self.assertEqual(motion_candidate.support_count, 2)
        self.assertEqual(boundary_candidate.status, "boundary")

    def test_contradictory_delta_retires_prior_candidate(self) -> None:
        inducer = ExperienceInducer()
        first, second = records(
            action=ArcAction("ACTION1"), before=((0, 0),), after=((7, 0),),
        )
        inducer.observe(extract_action_effect(first, second))
        first, second = records(
            action=ArcAction("ACTION1"), before=((0, 0),), after=((8, 0),),
        )
        inducer.observe(extract_action_effect(first, second))
        candidates = inducer.candidates()
        self.assertEqual(len(candidates), 2)
        self.assertEqual({item.status for item in candidates}, {"contradicted"})
        self.assertTrue(all(item.conflict_sequences == (1,) for item in candidates))

    def test_distinct_keyboard_actions_do_not_contradict_each_other(self) -> None:
        inducer = ExperienceInducer()
        for action, value, sequence in (("ACTION1", 7, 1), ("ACTION2", 8, 2)):
            first, second = records(
                action=ArcAction(action), before=((0, 0),), after=((value, 0),),
            )
            effect = replace(extract_action_effect(first, second), sequence=sequence)
            inducer.observe(effect)
        candidates = inducer.candidates()
        self.assertEqual(len(candidates), 2)
        self.assertEqual({item.status for item in candidates}, {"hypothesis"})

    def test_identical_effects_from_distinct_keyboard_actions_stay_distinct(self) -> None:
        inducer = ExperienceInducer()
        for action, sequence in (("ACTION1", 1), ("ACTION2", 2)):
            first, second = records(
                action=ArcAction(action), before=((0, 0),), after=((7, 0),),
            )
            effect = replace(extract_action_effect(first, second), sequence=sequence)
            inducer.observe(effect)
        candidates = inducer.candidates()
        self.assertEqual(len(candidates), 2)
        self.assertEqual({item.action for item in candidates}, {"ACTION1", "ACTION2"})

    def test_probe_plan_ranks_information_and_rejects_stale_click(self) -> None:
        current = SimState.from_observation(
            frame=((0, 0), (0, 0)), level=0, state="NOT_FINISHED",
            available_actions=["ACTION1", "ACTION6"],
        )
        keyboard = EffectHypothesis(
            key="keyboard", game_id="game", seed=1, level=0,
            action_family="keyboard", action="ACTION1", data=(),
            signature="cell-edit", status="hypothesis",
            evidence_sequences=(1, 2), conflict_sequences=(),
        )
        stale_click = EffectHypothesis(
            key="stale-click", game_id="game", seed=1, level=0,
            action_family="click", action="ACTION6", data=(("x", 9), ("y", 9)),
            signature="cell-edit", status="hypothesis",
            evidence_sequences=(3, 4), conflict_sequences=(),
        )
        plan = ExperienceInducer.probe_plan(current, (keyboard, stale_click))
        self.assertIsInstance(plan, ProbePlan)
        self.assertEqual(plan.status, "ready")
        self.assertEqual(plan.action, "ACTION1")
        self.assertIn("stale-click", plan.rejected_candidates)

    def test_probe_plan_allows_consistent_candidate_in_a_new_state(self) -> None:
        current = SimState.from_observation(
            frame=((0, 0),), level=0, state="NOT_FINISHED",
            available_actions=["ACTION1"],
        )
        candidate = EffectHypothesis(
            key="move", game_id="game", seed=1, level=0,
            action_family="keyboard", action="ACTION1", data=(),
            signature="translate", status="hypothesis",
            evidence_sequences=(1, 2), conflict_sequences=(),
        )
        plan = ExperienceInducer.probe_plan(
            current, (candidate,), tried_actions=(("ACTION1", ()),),
        )
        self.assertEqual(plan.status, "ready")
        self.assertEqual(plan.action, "ACTION1")

    def test_large_frame_uses_private_full_delta_for_components(self) -> None:
        before = tuple(tuple(0 for _ in range(12)) for _ in range(12))
        after_rows = [list(row) for row in before]
        for y in range(4, 12):
            for x in range(4, 12):
                after_rows[y][x] = 7
        first, second = records(
            action=ArcAction("ACTION1"), before=before,
            after=tuple(tuple(row) for row in after_rows),
        )
        effect = extract_action_effect(first, second)
        self.assertEqual(effect.changed_cell_count, 64)
        self.assertEqual(effect.changed_cells_omitted, 0)
        self.assertEqual(len(effect.components), 1)

    def test_translation_at_different_positions_forms_one_hypothesis(self) -> None:
        inducer = ExperienceInducer()
        for sequence, start_x in ((1, 1), (2, 5)):
            before_rows = [[0 for _ in range(12)] for _ in range(6)]
            after_rows = [[0 for _ in range(12)] for _ in range(6)]
            for x in range(start_x, start_x + 2):
                before_rows[2][x] = 7
            for x in range(start_x + 1, start_x + 3):
                after_rows[2][x] = 7
            first, second = records(
                action=ArcAction("ACTION1"),
                before=tuple(tuple(row) for row in before_rows),
                after=tuple(tuple(row) for row in after_rows),
            )
            effect = extract_action_effect(first, second)
            if sequence == 2:
                effect = replace(effect, sequence=2)
            inducer.observe(effect)
        candidates = inducer.candidates()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].status, "hypothesis")
        self.assertEqual(candidates[0].support_count, 2)
        self.assertTrue(candidates[0].template is not None)
        self.assertTrue(candidates[0].template.motions)

    def test_extracts_motion_when_independent_boundary_delta_is_present(self) -> None:
        before = (
            (0, 0, 0, 0, 0, 0),
            (0, 7, 7, 0, 0, 0),
            (0, 0, 0, 0, 0, 0),
            (14, 14, 14, 14, 14, 14),
        )
        after = (
            (0, 0, 0, 0, 0, 0),
            (0, 0, 7, 7, 0, 0),
            (0, 0, 0, 0, 0, 0),
            (0, 0, 14, 14, 14, 14),
        )
        first, second = records(action=ArcAction("ACTION1"), before=before, after=after)
        effect = extract_action_effect(first, second)
        self.assertFalse(effect.motion_complete)
        self.assertEqual(len(effect.motions), 1)
        self.assertEqual((effect.motions[0].dx, effect.motions[0].dy), (1, 0))

    def test_small_boundary_decoration_does_not_hide_complete_motion(self) -> None:
        before = (
            (0, 0, 0, 0, 0, 0, 0, 0),
            (0, 7, 7, 0, 0, 0, 0, 0),
            (0, 0, 0, 0, 0, 0, 0, 0),
            (14, 14, 14, 14, 14, 14, 14, 14),
        )
        after = (
            (0, 0, 0, 0, 0, 0, 0, 0),
            (0, 0, 7, 7, 0, 0, 0, 0),
            (0, 0, 0, 0, 0, 0, 0, 0),
            (14, 14, 14, 0, 14, 14, 14, 14),
        )
        first, second = records(action=ArcAction("ACTION1"), before=before, after=after)
        effect = extract_action_effect(first, second)
        self.assertTrue(effect.motion_complete)
        self.assertEqual((effect.motions[0].dx, effect.motions[0].dy), (1, 0))

    def test_motion_direction_uses_geometry_instead_of_color_order(self) -> None:
        for object_color, background_color in ((9, 12), (12, 9)):
            before = tuple(
                tuple(object_color if x in (2, 3) and y in (1, 2) else background_color for x in range(8))
                for y in range(4)
            )
            after = tuple(
                tuple(object_color if x in (3, 4) and y in (1, 2) else background_color for x in range(8))
                for y in range(4)
            )
            first, second = records(action=ArcAction("ACTION1"), before=before, after=after)
            effect = extract_action_effect(first, second)
            with self.subTest(object_color=object_color, background_color=background_color):
                self.assertEqual(len(effect.motions), 1)
                self.assertEqual(effect.motions[0].source_value, object_color)
                self.assertEqual(effect.motions[0].clear_value, background_color)
                self.assertEqual((effect.motions[0].dx, effect.motions[0].dy), (1, 0))

    def test_color_block_swap_is_ambiguous_and_stays_unmodeled(self) -> None:
        first, second = records(
            action=ArcAction("ACTION1"),
            before=((9, 9, 12, 12),),
            after=((12, 12, 9, 9),),
        )
        effect = extract_action_effect(first, second)
        self.assertEqual(effect.motions, ())
        self.assertFalse(effect.motion_complete)

    def test_component_merge_is_not_reduced_to_a_partial_motion(self) -> None:
        first, second = records(
            action=ArcAction("ACTION1"),
            before=((0, 7, 7, 0, 7, 7, 0),),
            after=((0, 0, 7, 7, 7, 7, 0),),
        )
        effect = extract_action_effect(first, second)
        self.assertEqual(effect.motions, ())
        self.assertFalse(effect.motion_complete)

    def test_component_split_is_not_reduced_to_background_fragments(self) -> None:
        first, second = records(
            action=ArcAction("ACTION1"),
            before=((0, 7, 7, 7, 0),),
            after=((7, 7, 0, 7, 7),),
        )
        effect = extract_action_effect(first, second)
        self.assertEqual(effect.motions, ())
        self.assertFalse(effect.motion_complete)


if __name__ == "__main__":
    unittest.main()
