from __future__ import annotations

import tempfile
import json
import unittest
from pathlib import Path

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.operator import _P7BrokerClient
from asterion.applications.prime.p7.ipython_host import p7_client_facade
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
            "win_levels": 7,
        }

    def step(self, action: str) -> dict[str, object]:
        if action != "ACTION1":
            raise AssertionError(action)
        self.offset += 1
        return self.observe()


class ExperienceEndToEndTests(unittest.TestCase):
    def test_observation_surfaces_compiled_learning_hint_without_route_authority(self) -> None:
        broker = ArcBroker(engine=_TranslationEngine())
        broker.bind_history("learning-run")
        for expected_x in (1, 2):
            broker.act_checked([{
                "action": {"name": "ACTION1", "data": {}},
                "expect": {"cell": {"x": expected_x, "y": 0, "value": 7}},
            }])
        hint = broker.learning_hint()
        self.assertEqual(hint["recommendation"], "inspect_candidate_and_probe")
        self.assertEqual(hint["execution_authority"], "none")
        self.assertTrue(hint["compiled_candidates"])
        self.assertLessEqual(len(json.dumps(hint).encode()), 1024)
        self.assertNotIn("plan", hint["compiled_candidates"][0])

        status = _P7BrokerClient(broker, None).status()
        self.assertEqual(status["learning_hint"]["recommendation"], "inspect_candidate_and_probe")
        # The bridge may truncate a large frame response.  The bounded hint
        # must therefore precede the frame-bearing fields in the wire mapping.
        observed = _P7BrokerClient(broker, None).observe()
        self.assertEqual(next(iter(observed)), "learning_hint")
        candidates = broker.mechanism_candidates()
        bundle = next(item for item in candidates if item["key"] == "experience.induced.bundle")
        self.assertEqual(candidates[0]["key"], "experience.induced.bundle")
        self.assertEqual(bundle["source"], "induced-bundle")
        self.assertNotIn("plan", bundle["compiled_mechanism"])

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

    def test_ipython_facade_exposes_induction_queries(self) -> None:
        broker = ArcBroker(engine=_TranslationEngine())
        broker.bind_history("learning-run")
        facade = p7_client_facade(_P7BrokerClient(broker, None))
        self.assertIsInstance(facade.action_effects(), list)
        self.assertIsInstance(facade.mechanism_candidates(), list)
        self.assertIsInstance(facade.probe_plan(), dict)
        self.assertIsInstance(facade.simulator_status(), dict)


if __name__ == "__main__":
    unittest.main()
