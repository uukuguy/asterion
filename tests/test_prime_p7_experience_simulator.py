from __future__ import annotations

import unittest
from dataclasses import replace

from asterion.applications.prime.p7.broker import ArcAction
from asterion.applications.prime.p7.experience_induction import (
    ExperienceInducer,
    SimState,
    extract_action_effect,
)
from asterion.applications.prime.p7.mechanism_model import (
    MechanismRule,
    MechanismSpec,
    compile_effect_hypothesis,
    simulate_step,
    validate_mechanism,
)
from asterion.applications.prime.p7.model_search import search_model
from asterion.applications.prime.p7.score import digest
from asterion.applications.prime.p7.verified_history import ArcHistoryRecord


def effect_for(value: int):
    first = ArcHistoryRecord.initial(
        game_id="game", seed=1, run_id="run", frame=((0,),),
        levels_completed=0, state="NOT_FINISHED", after_state_sha256=digest("s0"),
    )
    second = ArcHistoryRecord.following(
        first, action=ArcAction("ACTION1"),
        before_state_sha256=first.after_state_sha256,
        after_state_sha256=digest(("s", value)), frame=((value,),),
        levels_completed=0, state="NOT_FINISHED",
    )
    return extract_action_effect(first, second)


class ExperienceSimulatorTests(unittest.TestCase):
    def test_candidate_compiles_and_simulates_a_cell_edit(self) -> None:
        inducer = ExperienceInducer(win_levels=1)
        effect = effect_for(7)
        inducer.observe(effect)
        inducer.observe(replace(effect, sequence=2))
        spec = compile_effect_hypothesis(inducer.candidates()[0])
        self.assertIsNotNone(spec)
        state = SimState.from_observation(
            frame=((0,),), level=0, state="NOT_FINISHED", available_actions=["ACTION1"],
        )
        prediction = simulate_step(spec, state, ArcAction("ACTION1"))
        self.assertEqual(prediction.status, "predicted")
        self.assertEqual(prediction.next_state.frame, ((7,),))
        self.assertEqual(prediction.changed_cells, ((0, 0, 0, 7),))
        self.assertTrue(prediction.rule_ids)

    def test_unknown_hidden_entity_state_does_not_get_fabricated(self) -> None:
        spec = MechanismSpec(
            "game", 1, 1,
            (MechanismRule(
                "ACTION1",
                guards=(
                    {"op": "entity_attr_equals", "args": {"entity": "door", "attr": "open", "value": True}},
                ),
                effects=({"op": "set_state", "args": {"value": "WIN"}},),
            ),),
        )
        state = SimState.from_observation(
            frame=((0,),), level=0, state="NOT_FINISHED", available_actions=["ACTION1"],
            unknown_fields=["door.open"],
        )
        prediction = simulate_step(spec, state, "ACTION1")
        self.assertEqual(prediction.status, "unknown")
        self.assertEqual(prediction.reason, "unknown-hidden-state")

    def test_ambiguous_rules_are_conflict(self) -> None:
        spec = MechanismSpec(
            "game", 1, 1,
            (
                MechanismRule("ACTION1", effects=({"op": "set_cell", "args": {"x": 0, "y": 0, "value": 1}},)),
                MechanismRule("ACTION1", effects=({"op": "set_cell", "args": {"x": 0, "y": 0, "value": 2}},)),
            ),
        )
        state = SimState.from_observation(
            frame=((0,),), level=0, state="NOT_FINISHED", available_actions=["ACTION1"],
        )
        prediction = simulate_step(spec, state, "ACTION1")
        self.assertEqual(prediction.status, "conflict")
        self.assertIsNone(prediction.next_state)

    def test_search_rejects_certificate_from_a_stale_current_prefix(self) -> None:
        first = ArcHistoryRecord.initial(
            game_id="game", seed=1, run_id="run", frame=((0,),),
            levels_completed=0, state="NOT_FINISHED", after_state_sha256=digest("s0"),
        )
        second = ArcHistoryRecord.following(
            first, action=ArcAction("ACTION1"),
            before_state_sha256=first.after_state_sha256,
            after_state_sha256=digest("s1"), frame=((1,),),
            levels_completed=0, state="NOT_FINISHED",
        )
        spec = MechanismSpec(
            "game", 1, 1,
            (MechanismRule("ACTION1", effects=({"op": "set_cell", "args": {"x": 0, "y": 0, "value": 1}},)),),
        )
        certificate = validate_mechanism(spec, (first, second))
        self.assertIsNotNone(certificate)
        result = search_model(
            spec, frame=((0,),), level=0, state="NOT_FINISHED",
            actions=("ACTION1",), target_level=1, certificate=certificate,
        )
        self.assertEqual(result.status, "model-unavailable")
        self.assertEqual(result.reason, "stale-certificate")

    def test_translation_candidate_compiles_and_reuses_new_position(self) -> None:
        inducer = ExperienceInducer()
        for sequence, start_x in ((1, 1), (2, 5)):
            before_rows = [[0 for _ in range(12)] for _ in range(6)]
            after_rows = [[0 for _ in range(12)] for _ in range(6)]
            for x in range(start_x, start_x + 2):
                before_rows[2][x] = 7
            for x in range(start_x + 1, start_x + 3):
                after_rows[2][x] = 7
            first = ArcHistoryRecord.initial(
                game_id="game", seed=1, run_id="run", frame=tuple(tuple(row) for row in before_rows),
                levels_completed=0, state="NOT_FINISHED", after_state_sha256=digest(("s0", sequence)),
            )
            second = ArcHistoryRecord.following(
                first, action=ArcAction("ACTION1"),
                before_state_sha256=first.after_state_sha256,
                after_state_sha256=digest(("s1", sequence)),
                frame=tuple(tuple(row) for row in after_rows),
                levels_completed=0, state="NOT_FINISHED",
            )
            effect = extract_action_effect(first, second)
            if sequence == 2:
                effect = replace(effect, sequence=2)
            inducer.observe(effect)
        spec = compile_effect_hypothesis(inducer.candidates()[0])
        self.assertIsNotNone(spec)
        state = SimState.from_observation(
            frame=tuple(tuple(7 if 5 <= x <= 6 and y == 2 else 0 for x in range(12)) for y in range(6)),
            level=0, state="NOT_FINISHED", available_actions=["ACTION1"],
        )
        prediction = simulate_step(spec, state, "ACTION1")
        self.assertEqual(prediction.status, "predicted")
        self.assertEqual(prediction.next_state.frame[2][5:8], (0, 7, 7))

    def test_large_translation_prediction_keeps_bounded_sample_and_omitted_count(self) -> None:
        spec = MechanismSpec(
            "game", 1, 1,
            (MechanismRule(
                "ACTION1",
                effects=({"op": "translate_components", "args": {
                    "pattern": [[0, 0, 7], [1, 0, 7]],
                    "clear": 0, "dx": 2, "dy": 0, "count": 32,
                }},),
            ),),
        )
        frame = tuple(tuple(7 if 2 <= x < 4 and y % 2 == 0 else 0 for x in range(64)) for y in range(64))
        state = SimState.from_observation(
            frame=frame, level=0, state="NOT_FINISHED", available_actions=["ACTION1"],
        )
        prediction = simulate_step(spec, state, "ACTION1")
        self.assertEqual(prediction.status, "predicted")
        self.assertEqual(len(prediction.changed_cells), 80)
        self.assertGreater(prediction.changed_cells_omitted, 0)


if __name__ == "__main__":
    unittest.main()
