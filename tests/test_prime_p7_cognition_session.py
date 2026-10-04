from __future__ import annotations

from pathlib import Path
from contextlib import redirect_stderr
import io
import json
import tempfile
import unittest

from asterion.applications.prime.p7.cognition_session import (
    CognitionPersistenceError,
    CognitionSession,
    CognitionSessionError,
)
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
                "information_gain": "Separates movement from no-effect.", "action": {"name": "ACTION2"}, "expected": {"frame": [[2]]},
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

    def test_one_action_can_update_multiple_hypotheses_independently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = CognitionSession(self._store(Path(directory)), session_id="multi-evidence")
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            session.propose({"claims": [
                {"id": "actor", "kind": "object_role", "subject": "color-7", "claim": "Color 7 is controlled.", "reason": "It is isolated.", "falsifier": "Another object moves.", "next_test": "Move once."},
                {"id": "direction", "kind": "control", "subject": "ACTION2", "claim": "ACTION2 moves right.", "reason": "The action is directional.", "falsifier": "It moves elsewhere.", "next_test": "Apply ACTION2."},
                {"id": "goal", "kind": "success_condition", "subject": "level", "claim": "The move reaches the goal.", "reason": "The target is adjacent.", "falsifier": "The level does not advance.", "next_test": "Check levels_completed."},
            ]})
            session.select_experiment({
                "claim_ids": ["actor", "direction", "goal"], "question": "What changed?",
                "information_gain": "Separates actor, direction, and goal effects.",
                "action": {"name": "ACTION2"}, "expected": {"frame": [[2]]},
            })
            session.record_action({"frame": [[2]], "levels_completed": 0, "state": "NOT_FINISHED"}, action={"name": "ACTION2"})
            snapshot = session.analyze({"results": [
                {"claim_id": "actor", "status": "certain", "explanation": "Only color 7 moved."},
                {"claim_id": "direction", "status": "certain", "explanation": "The settled frame is one cell right."},
                {"claim_id": "goal", "status": "falsified", "explanation": "levels_completed stayed at zero."},
            ]})
            claims = {item["id"]: item for values in snapshot["report"]["claims"].values() if isinstance(values, list) for item in values}
            self.assertEqual(claims["actor"]["status"], "certain")
            self.assertEqual(claims["direction"]["status"], "certain")
            self.assertEqual(claims["goal"]["status"], "falsified")
            self.assertEqual(claims["actor"]["evidence_count"], 1)

    def test_stale_or_unbound_actions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = CognitionSession(self._store(Path(directory)), session_id="s2")
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            with self.assertRaises(CognitionSessionError):
                session.record_action({"frame": [[2]], "levels_completed": 0, "state": "NOT_FINISHED"}, action={"name": "ACTION1"})
            with self.assertRaises(CognitionSessionError):
                session.ready_for_solve()

    def test_experiment_state_predicate_uses_runtime_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = CognitionSession(self._store(Path(directory)), session_id="states")
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            self._claim(session)
            with self.assertRaises(CognitionSessionError):
                session.select_experiment({
                    "claim_ids": ["control-right"], "question": "state?",
                    "information_gain": "terminal state", "action": {"name": "ACTION2"},
                    "expected": {"state": "WON"},
                })

    def test_experiment_expected_result_alias_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = CognitionSession(self._store(Path(directory)), session_id="expected-alias")
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            self._claim(session)
            selected = session.select_experiment({
                "claim_ids": ["control-right"],
                "information_question": "Does ACTION2 move right?",
                "action": {"name": "ACTION2"},
                "expected_result": {"cell": {"x": 0, "y": 0, "value": 2}},
            })
            self.assertEqual(selected["state"], "EXPERIMENT_SELECTED")
            session.record_action(
                {"frame": [[2]], "levels_completed": 0, "state": "NOT_FINISHED"},
                action={"name": "ACTION2"},
            )
            analyzed = session.analyze({
                "results": [{
                    "claim_id": "control-right",
                    "outcome": "supported",
                    "observation": "The cell changed as predicted.",
                }],
            })
            self.assertEqual(analyzed["state"], "ANALYZED")
            self.assertIsNone(analyzed["session"]["pending"])

    def test_event_persistence_failure_is_not_silent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            event_root = Path(directory) / "event-root"
            event_root.write_text("not-a-directory", encoding="utf-8")
            with self.assertRaises(CognitionPersistenceError):
                CognitionSession(self._store(Path(directory)), session_id="persist", event_root=event_root)

    def test_live_log_records_each_cognition_event_and_claim_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            session = CognitionSession(store, session_id="visible")
            self.assertEqual(session.live_log_path, store.path.parent / "cognition-live-visible.jsonl")
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            self._claim(session)
            session.select_experiment({
                "claim_ids": ["control-right"], "question": "Does ACTION2 move right?",
                "information_gain": "movement", "action": {"name": "ACTION2"},
                "expected": {"frame": [[2]]},
            })
            session.record_action(
                {"frame": [[2]], "levels_completed": 0, "state": "NOT_FINISHED"},
                action={"name": "ACTION2"},
            )
            session.analyze({"results": [{
                "claim_id": "control-right", "status": "certain", "explanation": "The actor moved right.",
            }]})
            lines = session.live_log_path.read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in lines]
            event_types = [event["type"] for event in events]
            self.assertIn("cognition.session.started", event_types)
            self.assertIn("cognition.episode.started", event_types)
            self.assertIn("cognition.hypothesis.proposed", event_types)
            self.assertIn("cognition.experiment.selected", event_types)
            self.assertIn("cognition.action.executed", event_types)
            self.assertIn("cognition.observation.analyzed", event_types)
            action_event = next(event for event in events if event["type"] == "cognition.action.executed")
            self.assertTrue(action_event["changed"])
            self.assertEqual(action_event["levels_completed"], 0)
            changed = [claim for event in events for claim in event.get("claim_changes", [])]
            observed = [claim for claim in changed if claim["id"] == "control-right"][-1]
            self.assertEqual(observed["status"], "certain")
            self.assertEqual(observed["confidence"], 0.5)

    def test_console_cognition_progress_is_compact_while_live_log_keeps_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stream = io.StringIO()
            with redirect_stderr(stream):
                session = CognitionSession(self._store(root), session_id="compact")
                session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
                self._claim(session)
            lines = stream.getvalue().splitlines()
            self.assertTrue(any("event type=cognition.session.started" in line for line in lines))
            self.assertTrue(any("event type=cognition.hypothesis.proposed" in line for line in lines))
            self.assertTrue(any("hypothesis-summary count=" in line for line in lines))
            self.assertTrue(all(len(line) <= 512 for line in lines))
            self.assertNotIn('"claim_changes"', stream.getvalue())
            live_events = [
                json.loads(line)
                for line in session.live_log_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertTrue(any("claim_changes" in event for event in live_events))

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
            session.select_experiment({"claim_ids": ["control"], "question": "move?", "information_gain": "movement", "action": {"name": "ACTION1"}, "expected": {"frame": [[2]]}})
            session.record_action({"frame": [[2]], "levels_completed": 0, "state": "NOT_FINISHED"}, action={"name": "ACTION1"})
            session.analyze({"results": [{"claim_id": "control", "status": "certain", "explanation": "Frame changed."}]})
            for claim_id in ("type", "role", "goal", "strategy"):
                session.store.resolve(
                    claim_id, status="certain", evidence=f"s3/{claim_id}",
                    explanation="Independent runtime evidence supports the claim.",
                )
            ready = session.ready_for_solve()
            self.assertEqual(ready["state"], "READY")
            self.assertIn("cognition.ready_for_solve", [event["type"] for event in session.events])

    def test_ready_allows_feedback_driven_solve_with_partial_game_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = CognitionSession(self._store(Path(directory)), session_id="partial-ready")
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            session.propose({"claims": [{
                "id": "partial-control",
                "kind": "control",
                "subject": "ACTION1",
                "claim": "ACTION1 may move the controllable object.",
                "reason": "The initial scene has one salient object and ACTION1 is available.",
                "falsifier": "The object does not move after ACTION1.",
                "next_test": "Select ACTION1 with a concrete frame prediction.",
            }]})
            ready = session.ready_for_solve()
            self.assertEqual(ready["state"], "READY")
            self.assertEqual(ready["session"]["validation"]["reason"], "solve-attempt-ready")

    def test_ready_session_can_continue_cognition_guided_solve_testing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = CognitionSession(self._store(Path(directory)), session_id="ready-followup")
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            session.propose({"claims": [
                {"id": "type", "kind": "game_type", "subject": "board", "claim": "A grid game.", "reason": "Grid.", "falsifier": "No grid.", "next_test": "Observe."},
                {"id": "role", "kind": "object_role", "subject": "color-7", "claim": "Color 7 may be the player.", "reason": "It is isolated.", "falsifier": "Another object moves.", "next_test": "Apply."},
                {"id": "control", "kind": "control", "subject": "ACTION1", "claim": "It moves.", "reason": "Available.", "falsifier": "No change.", "next_test": "Apply."},
                {"id": "goal", "kind": "success_condition", "subject": "goal", "claim": "Reach the special cell.", "reason": "Distinct cell.", "falsifier": "No win.", "next_test": "Touch it."},
                {"id": "strategy", "kind": "strategy", "subject": "L1", "claim": "Probe one move at a time.", "reason": "Unknown.", "falsifier": "Batch is required.", "next_test": "Probe."},
            ]})
            session.select_experiment({"claim_ids": ["control"], "question": "move?", "information_gain": "movement", "action": {"name": "ACTION1"}, "expected": {"frame": [[2]]}})
            session.record_action({"frame": [[2]], "levels_completed": 0, "state": "NOT_FINISHED"}, action={"name": "ACTION1"})
            session.analyze({"results": [{"claim_id": "control", "status": "certain", "explanation": "Moved."}]})
            for claim_id in ("type", "role", "goal", "strategy"):
                session.store.resolve(
                    claim_id, status="certain", evidence=f"ready-followup/{claim_id}",
                    explanation="Independent runtime evidence supports the claim.",
                )
            session.ready_for_solve()
            accepted = session.propose({"claims": [{
                "id": "solve-next", "kind": "strategy", "subject": "L1", "claim": "Repeat the tested movement.", "reason": "Control is confirmed.", "falsifier": "It does not progress.", "next_test": "Apply ACTION1 again.",
            }]})
            self.assertEqual(accepted, 1)

    def test_new_session_resumes_ready_semantics_for_same_game_level(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = CognitionSession(self._store(root), session_id="first-run")
            first.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            first.propose({"claims": [
                {"id": "known-type", "kind": "game_type", "subject": "board", "claim": "A grid game.", "reason": "Grid.", "falsifier": "No grid.", "next_test": "Observe."},
                {"id": "known-role", "kind": "object_role", "subject": "color-7", "claim": "Color 7 is the player.", "reason": "It moves.", "falsifier": "Another object moves.", "next_test": "Probe."},
                {"id": "known-control", "kind": "control", "subject": "ACTION1", "claim": "ACTION1 moves the player.", "reason": "A prior probe moved it.", "falsifier": "The player does not move.", "next_test": "Repeat."},
                {"id": "known-goal", "kind": "success_condition", "subject": "goal", "claim": "Reach the goal.", "reason": "The level reports completion there.", "falsifier": "The level does not complete.", "next_test": "Reach it."},
                {"id": "known-strategy", "kind": "strategy", "subject": "L1", "claim": "Use confirmed movement semantics.", "reason": "The control is known.", "falsifier": "The movement diverges.", "next_test": "Follow the current model."},
            ]})
            for claim_id in ("known-type", "known-role", "known-control", "known-goal", "known-strategy"):
                first.store.resolve(
                    claim_id, status="certain", evidence=f"first-run/{claim_id}",
                    explanation="The runtime observed evidence supporting the claim.",
                )

            resumed = CognitionSession(self._store(root), session_id="second-run")
            snapshot = resumed.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            self.assertEqual(snapshot["state"], "READY")
            self.assertEqual(snapshot["session"]["state"], "READY")
            self.assertEqual(snapshot["session"]["episode_actions"], 0)
            self.assertIn("cognition.ready_for_solve", [event["type"] for event in resumed.events])
            self.assertEqual(snapshot["report"]["scope"]["game_id"], "synthetic-game")

            # A different level has its own semantic ledger and must still
            # begin with exploration instead of inheriting L1 certainty.
            other_level = CognitionSession(
                SemanticCognitionStore(root, "synthetic-game", 0, 2, level=1),
                session_id="other-level",
            )
            other_snapshot = other_level.start_episode(
                {"frame": [[1]], "levels_completed": 1, "state": "NOT_FINISHED"}
            )
            self.assertEqual(other_snapshot["state"], "OBSERVE")

    def test_generic_frame_change_cannot_confirm_directional_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = CognitionSession(self._store(Path(directory)), session_id="generic-frame")
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            self._claim(session)
            session.select_experiment({
                "claim_ids": ["control-right"], "question": "Did the scene change?",
                "information_gain": "Detects any effect, not its meaning.",
                "action": {"name": "ACTION2"}, "expected": {"frame_changed": True},
            })
            session.record_action({"frame": [[2]], "levels_completed": 0, "state": "NOT_FINISHED"}, action={"name": "ACTION2"})
            snapshot = session.analyze({"results": [{"claim_id": "control-right", "status": "certain", "explanation": "A frame changed."}]})
            claim = next(item for item in snapshot["report"]["claims"]["control"] if item["id"] == "control-right")
            self.assertEqual(claim["status"], "undetermined")
            self.assertEqual(claim["evidence_count"], 0)

    def test_open_expected_predicate_accepts_llm_judgment_with_action_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = CognitionSession(self._store(Path(directory)), session_id="open-predicate")
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            self._claim(session)
            session.select_experiment({
                "claim_ids": ["control-right"], "question": "Did the actor move toward the goal?",
                "information_gain": "Tests the semantic movement interpretation.",
                "action": {"name": "ACTION2"},
                "expected": {"actor_moved_toward_goal": True, "confidence": "high"},
            })
            session.record_action(
                {"frame": [[2]], "levels_completed": 0, "state": "NOT_FINISHED"},
                action={"name": "ACTION2"},
            )
            session.analyze({"results": [{
                "claim_id": "control-right", "status": "certain",
                "explanation": "The actor moved toward the goal in the observed frame.",
            }]})
            claim = next(item for item in session.snapshot()["report"]["control"] if item["id"] == "control-right")
            self.assertEqual(claim["status"], "certain")
            self.assertIn("predicate=llm judgment", claim["evidence"][0]["explanation"])

    def test_open_expected_predicate_must_be_nonempty_json_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = CognitionSession(self._store(Path(directory)), session_id="open-shape")
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            self._claim(session)
            for expected in ({}, {"value": {1, 2}}):
                with self.subTest(expected=expected):
                    with self.assertRaises(CognitionSessionError):
                        session.select_experiment({
                            "claim_ids": ["control-right"], "question": "shape?",
                            "information_gain": "shape", "action": {"name": "ACTION2"},
                            "expected": expected,
                        })

    def test_open_analysis_accepts_llm_envelope_and_defaults_missing_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = CognitionSession(self._store(Path(directory)), session_id="open-analysis")
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            self._claim(session)
            session.select_experiment({
                "claim_ids": ["control-right"], "question": "What happened?",
                "information_gain": "semantic", "action": {"name": "ACTION2"},
                "expected": {"actor_moved": True},
            })
            session.record_action({"frame": [[2]], "levels_completed": 0, "state": "NOT_FINISHED"}, action={"name": "ACTION2"})
            snapshot = session.analyze({
                "claim_ids": ["control-right"],
                "interpretation": "The actor moved toward the goal.",
                "assessment": "uncertain",
            })
            claim = next(item for item in snapshot["report"]["claims"]["control"] if item["id"] == "control-right")
            self.assertEqual(claim["status"], "undetermined")
            self.assertEqual(claim["evidence_count"], 0)

    def test_open_analysis_rejects_forged_executable_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = CognitionSession(self._store(Path(directory)), session_id="analysis-action")
            session.start_episode({"frame": [[1]], "levels_completed": 0, "state": "NOT_FINISHED"})
            self._claim(session)
            session.select_experiment({
                "claim_ids": ["control-right"], "question": "What happened?",
                "information_gain": "semantic", "action": {"name": "ACTION2"},
                "expected": {"actor_moved": True},
            })
            session.record_action({"frame": [[2]], "levels_completed": 0, "state": "NOT_FINISHED"}, action={"name": "ACTION2"})
            with self.assertRaises(CognitionSessionError):
                session.analyze({"claim_ids": ["control-right"], "status": "certain", "action": {"name": "ACTION1"}})
    def test_concrete_frame_prediction_matches_broker_tuple_frame(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = CognitionSession(self._store(Path(directory)), session_id="tuple-frame")
            session.start_episode({"frame": ((1,),), "levels_completed": 0, "state": "NOT_FINISHED"})
            self._claim(session)
            session.select_experiment({
                "claim_ids": ["control-right"], "question": "Does the predicted scene occur?",
                "information_gain": "Checks the concrete settled frame.",
                "action": {"name": "ACTION2"}, "expected": {"frame": [[2]]},
            })
            session.record_action({"frame": ((2,),), "levels_completed": 0, "state": "NOT_FINISHED"}, action={"name": "ACTION2"})
            snapshot = session.analyze({"results": [{"claim_id": "control-right", "status": "certain", "explanation": "The predicted frame occurred."}]})
            claim = next(item for item in snapshot["report"]["claims"]["control"] if item["id"] == "control-right")
            self.assertEqual(claim["status"], "certain")


if __name__ == "__main__":
    unittest.main()
