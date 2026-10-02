from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from asterion.applications.prime.p7.cognition_session import CognitionSession, CognitionSessionError
from asterion.applications.prime.p7.semantic_cognition import SemanticCognitionStore


class CognitionSessionTests(unittest.TestCase):
    def _store(self, root: Path) -> SemanticCognitionStore:
        return SemanticCognitionStore(root, "synthetic-game", 0, 2, level=0)

    def _claim(self, session: CognitionSession) -> None:
        session.propose({"claims": [{
            "id": "control-right", "kind": "control", "subject": "ACTION2",
            "claim": "ACTION2 moves the player right.", "reason": "The player is isolated.",
            "falsifier": "Another direction is observed.", "next_test": "Apply ACTION2 once.",
        }]})

    def test_experiment_evidence_and_reset_preserve_semantic_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = CognitionSession(self._store(Path(directory)), session_id="s1", max_actions_per_episode=4)
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            self._claim(session)
            session.select_experiment({
                "claim_ids": ["control-right"], "question": "Does ACTION2 move right?",
                "information_gain": "Separates movement from no-effect.", "action": {"name": "ACTION2"}, "expected": {"frame_changed": True},
            })
            session.record_action({"frame": [[2]], "levels_completed": 0, "state": "NOT_FINISHED"}, action={"name": "ACTION2"})
            session.analyze({"results": [{"claim_id": "control-right", "status": "certain", "explanation": "The isolated object moved."}]})
            session.select_experiment({
                "claim_ids": ["control-right"], "question": "Does the effect repeat?",
                "information_gain": "Tests repeatability.", "action": {"name": "ACTION2"}, "expected": {"frame_changed": True},
            })
            before = session.snapshot()
            control_right = next(item for item in before["report"]["control"] if item["id"] == "control-right")
            self.assertEqual(control_right["status"], "certain")
            session.reset_episode()
            after = session.snapshot()
            control_right = next(item for item in after["report"]["control"] if item["id"] == "control-right")
            self.assertEqual(control_right["status"], "certain")
            self.assertEqual(after["session"]["episode_actions"], 0)
            self.assertEqual(after["session"]["state"], "OBSERVE")
            self.assertIn("cognition.episode.reset", [event["type"] for event in session.events])

    def test_stale_or_unbound_actions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = CognitionSession(self._store(Path(directory)), session_id="s2")
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            with self.assertRaises(CognitionSessionError):
                session.record_action({"frame": [[2]], "levels_completed": 0, "state": "NOT_FINISHED"}, action={"name": "ACTION1"})
            with self.assertRaises(CognitionSessionError):
                session.ready_for_solve()

    def test_first_episode_bootstraps_unknown_game_picture_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            session = CognitionSession(store, session_id="bootstrap")
            first = session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            claims = first["report"]["claims"]["undetermined"]
            self.assertEqual(
                {claim["id"] for claim in claims},
                {"bootstrap-frame-semantics", "bootstrap-discrete-actions", "bootstrap-success-condition"},
            )
            self.assertEqual({claim["status"] for claim in claims}, {"undetermined"})
            self.assertGreaterEqual(max(claim["confidence"] for claim in claims), 0.8)
            self.assertEqual(first["execution_authority"], "none")
            encoded = str(first["report"])
            self.assertNotIn("route", encoded.lower())
            self.assertNotIn('"x"', encoded)
            self.assertNotIn('"y"', encoded)

            # A second episode must preserve the same semantic questions and
            # must not create duplicate records or upgrade their status.
            second = session.start_episode({"frame": [[2]], "levels_completed": 0, "state": "NOT_FINISHED"})
            self.assertEqual(len(second["report"]["claims"]["undetermined"]), 3)
            self.assertEqual(second["report"]["evidence_counts"]["total"], 0)

    def test_ready_requires_language_and_supported_control(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = CognitionSession(self._store(Path(directory)), session_id="s3")
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            session.propose({"claims": [
                {"id": "type", "kind": "game_type", "subject": "board", "claim": "A grid game.", "reason": "Grid.", "falsifier": "No grid.", "next_test": "Observe."},
                {"id": "role", "kind": "object_role", "subject": "color-7", "claim": "Color 7 may be the player.", "reason": "It is isolated.", "falsifier": "Another object moves.", "next_test": "Apply."},
                {"id": "control", "kind": "control", "subject": "ACTION1", "claim": "It moves.", "reason": "Available.", "falsifier": "No change.", "next_test": "Apply."},
                {"id": "goal", "kind": "success_condition", "subject": "goal", "claim": "Reach the special cell.", "reason": "Distinct cell.", "falsifier": "No win.", "next_test": "Touch it."},
                {"id": "strategy", "kind": "strategy", "subject": "L1", "claim": "Probe one move at a time.", "reason": "Unknown.", "falsifier": "Batch is required.", "next_test": "Probe."},
            ]})
            session.select_experiment({"claim_ids": ["control"], "question": "move?", "information_gain": "movement", "action": {"name": "ACTION1"}, "expected": {"frame_changed": True}})
            session.record_action({"frame": [[2]], "levels_completed": 0, "state": "NOT_FINISHED"}, action={"name": "ACTION1"})
            session.analyze({"results": [{"claim_id": "control", "status": "certain", "explanation": "Frame changed."}]})
            ready = session.ready_for_solve()
            self.assertEqual(ready["state"], "READY")
            self.assertIn("cognition.ready_for_solve", [event["type"] for event in session.events])


if __name__ == "__main__":
    unittest.main()
