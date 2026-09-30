from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from asterion.applications.prime.p7.cognition import (
    GameCognitionStore,
    classify_input_kind,
)


class TestP7Cognition(unittest.TestCase):
    def test_classifies_input_kind_from_available_actions(self) -> None:
        self.assertEqual(classify_input_kind(("ACTION1",)), "keyboard")
        self.assertEqual(classify_input_kind(("ACTION6",)), "click")
        self.assertEqual(classify_input_kind(("ACTION1", "ACTION6")), "keyboard_click")
        self.assertEqual(classify_input_kind(()), "unknown")

    def test_persists_type_cognition_and_game_experience(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = GameCognitionStore(root)
            store.observe(
                game_id="ls20-9607627b",
                seed=0,
                win_levels=7,
                available_actions=("ACTION1", "ACTION6"),
                levels_completed=0,
                primitive_actions=0,
            )
            store.record_experience(
                game_id="ls20-9607627b",
                seed=0,
                win_levels=7,
                levels_completed=1,
                primitive_actions=4,
                model_digest="sha256:" + "a" * 64,
            )

            restored = GameCognitionStore(root)
            projection = restored.projection(
                game_id="ls20-9607627b", seed=0, win_levels=7
            )

        self.assertEqual(projection["input_kind"], "keyboard_click")
        self.assertEqual(projection["type_profile"]["games_seen"], 1)
        self.assertEqual(projection["game_experience"]["levels_completed"], 1)
        self.assertEqual(projection["game_experience"]["primitive_actions"], 4)

    def test_type_profile_is_prior_only_and_does_not_expose_routes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = GameCognitionStore(Path(directory))
            store.observe(
                game_id="game-a", seed=0, win_levels=1,
                available_actions=("ACTION6",), levels_completed=0,
                primitive_actions=0,
            )
            projection = store.projection(game_id="game-b", seed=0, win_levels=1)

        self.assertEqual(projection["input_kind"], "click")
        self.assertEqual(projection["type_profile"]["authority"], "prior-only")
        self.assertNotIn("route", projection["type_profile"])

    def test_broker_updates_experience_without_gating_exploration(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker

        class Engine:
            game_id = "ls20-9607627b"
            seed = 0

            def __init__(self) -> None:
                self.calls = 0

            def observe(self) -> dict[str, object]:
                return {
                    "available_actions": ["ACTION1"],
                    "frame": [[[self.calls]]],
                    "levels_completed": 0,
                    "state": "NOT_FINISHED",
                    "win_levels": 7,
                }

            def step(self, action: str) -> dict[str, object]:
                self.calls += 1
                return self.observe()

        with tempfile.TemporaryDirectory() as directory:
            engine = Engine()
            store = GameCognitionStore(Path(directory))
            broker = ArcBroker(engine=engine, cognition_store=store)
            broker.bind_history("cognition-run")
            broker.act(("ACTION1",))
            projection = GameCognitionStore(Path(directory)).projection(
                game_id=engine.game_id, seed=engine.seed, win_levels=7
            )

        self.assertEqual(projection["game_experience"]["primitive_actions"], 1)
        self.assertEqual(projection["game_experience"]["current_primitive_actions"], 1)
        self.assertEqual(projection["input_kind"], "keyboard")

    def test_projection_separates_best_and_current_action_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = GameCognitionStore(Path(directory))
            for actions in (0, 6, 3):
                store.observe(
                    game_id="sp80-589a99af",
                    seed=0,
                    win_levels=6,
                    available_actions=("ACTION1", "ACTION6"),
                    levels_completed=0,
                    primitive_actions=actions,
                )
            projection = store.projection(
                game_id="sp80-589a99af", seed=0, win_levels=6
            )

        self.assertEqual(projection["game_experience"]["primitive_actions"], 3)
        self.assertEqual(projection["game_experience"]["current_primitive_actions"], 3)


if __name__ == "__main__":
    unittest.main()
