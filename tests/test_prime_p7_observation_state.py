from __future__ import annotations

import json
import math
import unittest

from asterion.applications.prime.p7.observation_state import (
    EntityObservation,
    ObservationState,
    RelationObservation,
)


class TestP7ObservationState(unittest.TestCase):
    def test_from_observation_freezes_metadata_and_is_json_safe_and_hashable(self) -> None:
        source = {
            "available_actions": ["ACTION1", "ACTION6"],
            "frame": [[[1, 0], [0, 2]]],
            "levels_completed": 1,
            "state": "NOT_FINISHED",
            "win_levels": 3,
            "hud": {"score": 10, "label": "stage-1"},
            "timers": {"turn": 7.5},
            "resources": {"keys": 1},
            "entities": [{"id": "player", "kind": "avatar", "x": 0, "y": 1}],
            "relations": [{"source": "player", "relation": "near", "target": "exit"}],
            "events": [{"kind": "spawn", "entity": "player", "sequence": 0}],
        }

        observed = ObservationState.from_observation(source)
        source["hud"]["score"] = 999
        source["frame"][0][0][0] = 9

        self.assertEqual(observed.frame, (((1, 0), (0, 2)),))
        self.assertEqual(observed.hud["score"], 10)
        self.assertEqual(observed.input_kind, "keyboard_click")
        self.assertEqual(observed.entities[0].entity_id, "player")
        self.assertEqual(observed.relations[0].target, "exit")
        self.assertEqual(observed.events[0].kind, "spawn")
        with self.assertRaises(TypeError):
            observed.hud["score"] = 11  # type: ignore[index]
        with self.assertRaises(TypeError):
            observed.entities[0].attributes["x"] = 2  # type: ignore[index]

        projection = observed.to_projection()
        self.assertEqual(json.loads(json.dumps(projection)), projection)
        self.assertEqual(observed, ObservationState.from_projection(projection))
        self.assertEqual(hash(observed), hash(ObservationState.from_projection(projection)))
        self.assertTrue(observed.digest.startswith("sha256:"))

    def test_entities_relations_and_events_have_stable_order_and_typed_records(self) -> None:
        state = ObservationState.from_projection(
            {
                "frame": [[0, 0], [0, 1]],
                "available_actions": ["ACTION2"],
                "entities": {
                    "goal": {"kind": "target", "color": 3},
                    "player": {"kind": "avatar", "x": 1},
                },
                "relations": [
                    {"source": "player", "relation": "touching", "target": "goal", "confidence": 0.8}
                ],
                "events": [
                    {"kind": "move", "entity": "player", "sequence": 2},
                    {"kind": "spawn", "entity": "goal", "sequence": 1},
                ],
            }
        )

        self.assertEqual(tuple(entity.entity_id for entity in state.entities), ("goal", "player"))
        self.assertIsInstance(state.entities[0], EntityObservation)
        self.assertIsInstance(state.relations[0], RelationObservation)
        self.assertEqual(tuple(event.sequence for event in state.events), (1, 2))
        self.assertEqual(state.to_projection()["entities"][0]["id"], "goal")
        self.assertEqual(state.to_projection()["events"][0]["sequence"], 1)

    def test_from_observation_accepts_native_arc_observation_objects(self) -> None:
        from asterion.applications.prime.p7.broker import ArcObservation

        native = ArcObservation(
            available_actions=("ACTION1",),
            frame=(((0,),),),
            levels_completed=0,
            state="NOT_FINISHED",
            win_levels=2,
        )

        state = ObservationState.from_observation(native)

        self.assertEqual(state.frame, (((0,),),))
        self.assertEqual(state.available_actions, ("ACTION1",))
        self.assertEqual(state.win_levels, 2)

    def test_projection_accepts_nested_observation_and_preserves_optional_fields(self) -> None:
        state = ObservationState.from_projection(
            {
                "observation": {
                    "frame": [[7]],
                    "available_actions": [],
                    "levels_completed": 0,
                    "state": "WIN",
                    "win_levels": 1,
                },
                "hud": {"status": "done"},
                "timers": {"elapsed": 1},
            }
        )

        self.assertEqual(state.frame, ((7,),))
        self.assertEqual(state.state, "WIN")
        self.assertEqual(state.input_kind, "unknown")
        self.assertEqual(state.hud["status"], "done")
        self.assertEqual(state.timers["elapsed"], 1)

    def test_invalid_values_and_bounds_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ObservationState.from_projection({"frame": [[math.nan]]})
        with self.assertRaises(ValueError):
            ObservationState.from_projection({"frame": [[0]], "input_kind": "mouse"})
        with self.assertRaises(ValueError):
            ObservationState.from_projection(
                {"frame": [[0]], "entities": [{"id": "same"}, {"id": "same"}]}
            )
        with self.assertRaises(ValueError):
            ObservationState.from_projection(
                {"frame": [[0]], "events": [{"kind": "x", "payload": object()}]}
            )
        with self.assertRaises(ValueError):
            EntityObservation("player", attributes={"id": "shadow"})
        with self.assertRaises(ValueError):
            RelationObservation("player", "near", "goal", attributes={"source": "shadow"})


if __name__ == "__main__":
    unittest.main()
