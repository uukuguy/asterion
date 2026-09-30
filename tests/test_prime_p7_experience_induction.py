"""Tests for bounded action-effect extraction and immutable simulation state."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from asterion.applications.prime.p7.broker import ArcAction
from asterion.applications.prime.p7.experience_induction import (
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


if __name__ == "__main__":
    unittest.main()
