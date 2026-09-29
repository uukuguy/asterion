import unittest
from pathlib import Path
import tempfile

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.mechanics_prior import build_mechanics_prior
from asterion.applications.prime.p7.operator import _P7BrokerClient
from asterion.applications.prime.p7.broker import ArcStatus


class MechanicsPriorTests(unittest.TestCase):
    def test_client_pages_bounded_history_and_redacts_identity_and_frames(self):
        class Broker:
            game = type("Game", (), {"target_level": 3})()

            def __init__(self):
                self.calls = []

            def status(self):
                return ArcStatus(300, 2, 100, "active")

            def history(self, start, limit):
                self.calls.append((start, limit))
                return [
                    {
                        "sequence": index,
                        "action": "ACTION1",
                        "data": {},
                        "changed_cell_count": 0,
                        "changed_cells": [],
                        "levels_completed": index // 32,
                        "state": "NOT_FINISHED",
                        "run_id": "private",
                        "frame": [["secret"]],
                    }
                    for index in range(start, min(start + limit, 300))
                ]

            journal = ()

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            broker = Broker()
            result = _P7BrokerClient(broker, recorder).mechanics_prior()
            recorder.close()
        self.assertLessEqual(len(broker.calls), 8)
        self.assertTrue(all(limit == 32 for _, limit in broker.calls))
        self.assertTrue(result["available"])
        rendered = repr(result)
        self.assertNotIn("private", rendered)
        self.assertNotIn("secret", rendered)

    def test_client_history_failure_returns_scalar_safe_status(self):
        class Broker:
            game = type("Game", (), {"target_level": 3})()
            journal = ()

            def status(self):
                return ArcStatus(4, 1, 20, "active")

            def history(self, start, limit):
                raise RuntimeError("private broker detail")

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            result = _P7BrokerClient(Broker(), recorder).mechanics_prior()
            recorder.close()
        self.assertEqual(result["reason"], "history-unavailable")
        self.assertEqual(result["levels_completed"], 1)
        self.assertNotIn("private", repr(result))

    def test_summarizes_levels_coordinates_advances_and_confidence(self):
        records = [
            {"sequence": 1, "action": "ACTION1", "data": {}, "changed_cell_count": 0,
             "changed_cells": [], "levels_completed": 0, "state": "NOT_FINISHED"},
            {"sequence": 2, "action": "ACTION6", "data": {"x": 2, "y": 4}, "changed_cell_count": 1,
             "changed_cells": [(2, 4, 1, 3)], "levels_completed": 0, "state": "NOT_FINISHED"},
            {"sequence": 3, "action": "ACTION6", "data": {"x": 8, "y": 1}, "changed_cell_count": 2,
             "changed_cells": [(8, 1, 1, 3)], "levels_completed": 1, "state": "NOT_FINISHED"},
            {"sequence": 4, "action": "ACTION2", "data": {}, "changed_cell_count": 0,
             "changed_cells": [], "levels_completed": 2, "state": "WIN"},
        ]
        result = build_mechanics_prior(records, current_level=2)
        self.assertEqual(result["prefix_actions"], 4)
        self.assertEqual(result["highest_verified_level"], 2)
        self.assertEqual(result["current_level"], 2)
        self.assertEqual(result["levels"][0]["action_counts"], {"ACTION1": 1, "ACTION6": 1})
        self.assertEqual(result["levels"][0]["action6_coordinate_range"],
                         {"min_x": 2, "max_x": 2, "min_y": 4, "max_y": 4})
        self.assertEqual(result["level_advances"], [
            {"from_level": 0, "to_level": 1, "sequence": 3},
            {"from_level": 1, "to_level": 2, "sequence": 4},
        ])
        rules = {row["action"]: row for row in result["candidate_rules"]}
        self.assertEqual(rules["ACTION1"]["confidence"], "observed")
        self.assertEqual(rules["ACTION6"]["confidence"], "repeated")
        self.assertEqual(rules["ACTION2"]["confidence"], "observed")

    def test_mixed_effects_and_redaction_do_not_mutate_input(self):
        records = [
            {"sequence": 1, "action": "ACTION3", "data": {}, "changed_cell_count": 1,
             "changed_cells": [[0, 0]], "levels_completed": 0, "state": "NOT_FINISHED",
             "secret": "do-not-copy", "frame": {"pixels": [1]}},
            {"sequence": 2, "action": "ACTION3", "data": {}, "changed_cell_count": 0,
             "changed_cells": [], "levels_completed": 1, "state": "NOT_FINISHED"},
        ]
        before = repr(records)
        result = build_mechanics_prior(records, current_level=1)
        self.assertEqual(repr(records), before)
        rule = result["candidate_rules"][0]
        self.assertEqual(rule["confidence"], "mixed")
        rendered = repr(result)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("pixels", rendered)

    def test_empty_and_malformed_rows_are_safe(self):
        result = build_mechanics_prior([{}, {"action": "RESET"}, {"action": "ACTION1"}], current_level=3)
        self.assertEqual(result["prefix_actions"], 0)
        self.assertFalse(result["available"])
        self.assertEqual(result["current_level"], 3)


if __name__ == "__main__":
    unittest.main()
