from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from asterion.applications.prime.p7.cognition_session import CognitionSession
from asterion.applications.prime.p7.semantic_cognition import SemanticCognitionStore


class CognitionAssessmentTests(unittest.TestCase):
    def test_snapshot_reports_whether_more_validation_is_needed_and_possible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SemanticCognitionStore(Path(directory), "validation-game", 0, 2, level=0)
            session = CognitionSession(store, session_id="validation", max_actions_per_episode=1, max_resets=0)
            initial = session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            self.assertTrue(initial["session"]["validation"]["needed"])
            self.assertTrue(initial["session"]["validation"]["possible"])
            session.propose({"claims": [{
                "id": "probe", "kind": "control", "subject": "ACTION1", "claim": "ACTION1 changes the scene.",
                "reason": "It is available.", "falsifier": "The scene is unchanged.", "next_test": "Apply it.",
            }]})
            session.select_experiment({
                "claim_ids": ["probe"], "question": "Does it change?", "information_gain": "control",
                "action": {"name": "ACTION1"}, "expected": {"frame_changed": True},
            })
            session.record_action({"frame": [[2]], "levels_completed": 0, "state": "NOT_FINISHED"}, action={"name": "ACTION1"})
            session.analyze({"results": [{"claim_id": "probe", "status": "undetermined", "explanation": "The effect is not yet identified."}]})
            exhausted = session.snapshot(emit_event=False)["session"]["validation"]
            self.assertTrue(exhausted["needed"])
            self.assertFalse(exhausted["possible"])

    def test_claim_assessments_update_multiple_hypotheses_from_one_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SemanticCognitionStore(Path(directory), "assessment-game", 0, 2, level=0)
            session = CognitionSession(store, session_id="assessments")
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            session.propose({"claims": [
                {"id": "bar-moves", "kind": "control", "subject": "color-9", "claim": "The bar moves.", "reason": "It changed.", "falsifier": "It stays fixed.", "next_test": "Move it."},
                {"id": "space-passable", "kind": "object_role", "subject": "color-12", "claim": "Color 12 is passable space.", "reason": "The bar crossed it.", "falsifier": "The bar collides.", "next_test": "Move through it."},
            ]})
            session.select_experiment({
                "claim_ids": ["bar-moves", "space-passable"],
                "question": "Did the bar move through color 12?",
                "information_gain": "Tests movement and passability together.",
                "action": {"name": "ACTION1"},
                "expected": {"cell": {"x": 1, "y": 0, "value": 9}},
            })
            session.record_action({"frame": [[9, 12]], "levels_completed": 0, "state": "NOT_FINISHED"}, action={"name": "ACTION1"})
            snapshot = session.analyze({
                "claim_assessments": [
                    {"id": "bar-moves", "assessment": "supported", "reason": "The bar moved."},
                    {"id": "space-passable", "assessment": "supported", "reason": "The bar occupied the former color-12 cell."},
                ],
            })
            claims = {item["id"]: item for values in snapshot["report"]["claims"].values() if isinstance(values, list) for item in values}
            self.assertEqual(claims["bar-moves"]["status"], "certain")
            self.assertEqual(claims["space-passable"]["status"], "certain")


if __name__ == "__main__":
    unittest.main()
