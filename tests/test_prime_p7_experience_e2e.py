from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.playbook import load_playbook, save_playbook


class _LearningEngine:
    game_id = "ls20-9607627b"
    seed = 0
    win_levels = 7

    def __init__(self) -> None:
        self.calls: list[str] = []

    def observe(self) -> dict[str, object]:
        return {
            "available_actions": ["ACTION1", "ACTION2"],
            "frame": [[[len(self.calls), 0]]],
            "levels_completed": 0,
            "state": "NOT_FINISHED",
            "win_levels": 7,
        }

    def step(self, action: str) -> dict[str, object]:
        self.calls.append(action)
        return self.observe()


class ExperienceEndToEndTests(unittest.TestCase):
    def test_learning_evidence_survives_playbook_reload_without_planner_authority(self) -> None:
        engine = _LearningEngine()
        broker = ArcBroker(engine=engine)
        broker.bind_history("learning-run")
        broker.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"cell": {"x": 0, "y": 0, "value": 1}},
        }])
        self.assertEqual(len(broker.action_effects()), 1)
        self.assertEqual(broker.simulator_status()["confirmed_model"], False)
        self.assertEqual(engine.calls, ["ACTION1"])
        snapshot = broker.export_playbook(successful=False)
        self.assertEqual(len(snapshot.effect_summaries), 1)
        self.assertEqual(len(snapshot.candidate_summaries), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_playbook(root, snapshot)
            loaded = load_playbook(root, snapshot.key)
            self.assertIsNotNone(loaded)
            engine2 = _LearningEngine()
            fresh = ArcBroker(engine=engine2)
            fresh.bind_history("new-run")
            fresh.load_playbook(loaded)
            persisted = fresh.mechanism_candidates()
            self.assertEqual(len(persisted), 1)
            self.assertEqual(persisted[0]["status"], "stale")
            self.assertEqual(fresh.simulator_status()["confirmed_model"], False)
            self.assertEqual(engine2.calls, [])


if __name__ == "__main__":
    unittest.main()
