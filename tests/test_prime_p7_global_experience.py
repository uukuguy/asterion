from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.game_mechanics import GameMechanicsStore


class _TranslationEngine:
    game_id = "ls20-9607627b"
    seed = 0
    win_levels = 7

    def __init__(self) -> None:
        self.offset = 0

    def observe(self) -> dict[str, object]:
        row = [0, 0, 0, 0, 0, 0]
        row[self.offset] = 7
        return {
            "available_actions": ["ACTION1"],
            "frame": [[row]],
            "levels_completed": 0,
            "state": "NOT_FINISHED",
            "win_levels": self.win_levels,
        }

    def step(self, action: str) -> dict[str, object]:
        if action != "ACTION1":
            raise AssertionError(action)
        self.offset += 1
        return self.observe()


class GlobalExperienceIntegrationTests(unittest.TestCase):
    def test_broker_persists_game_memory_and_exposes_safe_simulation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = _TranslationEngine()
            store = GameMechanicsStore(root, engine.game_id, engine.seed, engine.win_levels)
            broker = ArcBroker(engine=engine, game_mechanics_store=store)
            broker.bind_history("global-memory-run")
            for expected_x in (1, 2):
                result = broker.act_checked([{
                    "action": {"name": "ACTION1", "data": {}},
                    "expect": {"cell": {"x": expected_x, "y": 0, "value": 7}},
                }])
                self.assertIn(result["stop_reason"], {"matched", "completed"})

            projection = broker.game_mechanics_projection()
            self.assertEqual(projection["execution_authority"], "none")
            self.assertTrue(projection["mechanisms"])
            self.assertTrue(any(item["status"] == "confirmed" for item in projection["mechanisms"]))
            restored = GameMechanicsStore.load(root, engine.game_id, engine.seed, engine.win_levels)
            self.assertTrue(restored.records())

            observation = broker.observation_state()
            self.assertEqual(observation.input_kind, "keyboard")
            counterfactual = broker.counterfactual_search(max_nodes=8, max_depth=2)
            self.assertEqual(counterfactual["execution_authority"], "none")
            self.assertEqual(counterfactual["executed_actions"], [])


if __name__ == "__main__":
    unittest.main()
