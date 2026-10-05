from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
from asterion.applications.prime.p7.observation_state import ObservationState
from asterion.applications.prime.p7.score import digest
from asterion.capabilities.prime_arc_agi_3_solver import PrimeArcAgi3SolveReceipt


class TestPrimeP7Console(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "p7-test-run"
        self.root.mkdir()
        self.recording = self.root / "recordings" / "record-session" / "game-record.jsonl"
        self.recording.parent.mkdir(parents=True)
        self.summary = {
            "schema": "asterion.prime.p7-live-private-summary/v1", "run_id": self.root.name,
            "experiment": {"game_id": "sp80-test", "model": "test-model", "target_level": 1, "seed": 0},
            "diagnostics": {}, "receipt": {}, "sealed_trace": False, "replay_verified": False,
        }
        self.write_summary()

    def write_summary(self):
        (self.root / "summary.json").write_text(json.dumps(self.summary), encoding="utf-8")

    def observation(self, action="RESET", color=0, completed=0, layers=1):
        return {"timestamp": "2026-10-05T10:00:00+00:00", "data": {
            "game_id": "sp80-test", "guid": "game-guid", "state": "NOT_FINISHED",
            "levels_completed": completed, "win_levels": 3, "available_actions": [1, 2, 3, 4, 5, 6],
            "action_input": {"id": action, "data": {}, "reasoning": None}, "full_reset": False,
            "frame": [[[color] * 64 for _ in range(64)] for _ in range(layers)],
        }}

    def write_recording(self, rows):
        self.recording.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def observation_hash(self, row):
        data = row["data"]
        return digest({"frame": data["frame"], "state": data["state"], "levels_completed": data["levels_completed"],
                       "win_levels": data["win_levels"], "available_actions": [f"ACTION{i}" for i in data["available_actions"]]})

    def write_trace(self, events, sealed=False):
        directory = self.root / "trace"
        directory.mkdir()
        recorder = PrimeTraceRecorder(directory)
        identities = {"application_id": "prime.arc-agi-3-solving", "model_id": "test-model"}
        for kind, payload in events:
            recorder.append(kind, identities, payload)
        if sealed:
            recorder.seal()
        else:
            recorder.close()

    def action_payload(self, before, after, sequence=1):
        return {"action": after["data"]["action_input"]["id"], "before_sha256": self.observation_hash(before),
                "after_sha256": self.observation_hash(after), "levels_completed": after["data"]["levels_completed"], "sequence": sequence}

    def test_duplicate_reset_and_noop_are_distinct(self):
        initial = self.observation()
        noop = self.observation("ACTION1")
        self.write_recording([initial, copy.deepcopy(initial), noop])
        self.write_trace([("arc.action", self.action_payload(initial, noop))])
        before = self.recording.read_bytes()
        state = build_console_snapshot(self.root)
        level = state["levels"][0]
        self.assertEqual(len(level["frames"]), 2)
        self.assertEqual(state["run"]["primitive_action_count"], 1)
        self.assertEqual(level["actions"][0]["changed_cells"], 0)
        self.assertEqual(level["actions"][0]["trace_sequence"], 1)
        self.assertEqual(level["actions"][0]["decision_id"], None)
        self.assertEqual(self.recording.read_bytes(), before)
        self.assertEqual(state["run"]["status"], "incomplete")

    def test_level_advance_and_layers_keep_actual_metadata(self):
        initial = self.observation()
        advanced = self.observation("ACTION4", 1, completed=1, layers=2)
        advanced["data"]["frame"][0][0][0] = 2
        following = self.observation("ACTION1", 3, completed=1)
        self.write_recording([initial, advanced, following])
        state = build_console_snapshot(self.root)
        first, second, third = state["levels"]
        self.assertEqual(first["status"], "successful")
        self.assertEqual(len(first["frames"]), 3)
        self.assertEqual([f["levels_completed"] for f in first["frames"]], [0, 1, 1])
        self.assertEqual(first["actions"][0]["after_frame"], first["frames"][-1]["id"])
        self.assertEqual(second["actions"][0]["before_frame"], second["frames"][0]["id"])
        self.assertEqual(second["frames"][0]["id"], first["frames"][-1]["id"])
        self.assertEqual(second["status"], "incomplete")
        self.assertEqual(third["status"], "not-run")
        self.assertEqual(state["run"]["completed_level_count"], 1)
        self.assertIsNone(first["receipt"])

    def test_pixel_measurements_do_not_invent_model_conclusions(self):
        initial = self.observation(color=12)
        before = initial["data"]["frame"][0]
        before[0] = [14] * 64
        for y in range(16, 20):
            before[y][12:32] = [9] * 20
        moved = copy.deepcopy(initial)
        moved["data"]["action_input"]["id"] = "ACTION4"
        after = moved["data"]["frame"][0]
        after[0][62:] = [0, 0]
        for y in range(16, 20):
            after[y][12:16] = [12] * 4
            after[y][32:36] = [9] * 4
        self.write_recording([initial, moved])
        state = build_console_snapshot(self.root)
        action = state["levels"][0]["actions"][0]
        self.assertEqual(action["changed_cells"], 34)
        measurements = action["visual_observations"]
        self.assertIn("蓝色（9）像素整体向右4格；形状和数量不变。", measurements)
        self.assertIn("绿色（14）像素数：64 → 62。", measurements)
        self.assertNotIn("进度", "".join(measurements))
        self.assertIsNone(action["decision_id"])
        self.assertEqual(state["levels"][0]["cognition"]["scope"], "unavailable")

    def test_full_frame_change_is_not_reported_as_no_change(self):
        self.write_recording([self.observation(), self.observation("ACTION1", color=1)])
        action = build_console_snapshot(self.root)["levels"][0]["actions"][0]
        self.assertEqual(action["visual_observations"], ["画面发生变化。"])

    def test_unknown_palette_entry_keeps_recording_readable(self):
        initial = self.observation(color=12)
        initial["data"]["frame"][0][1][1] = 16
        moved = copy.deepcopy(initial)
        moved["data"]["action_input"]["id"] = "ACTION4"
        moved["data"]["frame"][0][1][1] = 12
        moved["data"]["frame"][0][1][2] = 16
        self.write_recording([initial, moved])
        action = build_console_snapshot(self.root)["levels"][0]["actions"][0]
        self.assertEqual(action["visual_observations"], ["颜色编号16像素整体向右1格；形状和数量不变。"])

    def test_truncated_recording_preserves_prefix_without_cross_gap_actions(self):
        self.write_recording([self.observation(), self.observation("ACTION1", 1)])
        with self.recording.open("a") as file:
            file.write('{"unfinished":\n')
            file.write(json.dumps(self.observation("ACTION2", 2)) + "\n")
        state = build_console_snapshot(self.root)
        self.assertEqual(len(state["levels"][0]["frames"]), 3)
        self.assertEqual(len(state["levels"][0]["actions"]), 1)
        self.assertTrue(any("跨缺口" in w for w in state["warnings"]))

    def test_missing_recordings_does_not_use_replay_directory(self):
        replay = self.root / "replay" / "recordings" / "session"
        replay.mkdir(parents=True)
        (replay / "game.jsonl").write_text(json.dumps(self.observation()))
        state = build_console_snapshot(self.root)
        self.assertEqual(state["run"]["primitive_action_count"], 0)
        self.assertEqual(state["levels"][0]["frames"], [])

    def test_ambiguous_recordings_are_not_selected_or_merged(self):
        self.write_recording([self.observation()])
        (self.recording.parent / "second.jsonl").write_bytes(self.recording.read_bytes())
        state = build_console_snapshot(self.root)
        self.assertEqual(state["levels"][0]["frames"], [])
        self.assertTrue(any("多份录制" in w for w in state["warnings"]))

    def test_cross_game_and_guid_mismatches_reject_recording(self):
        for field, value in (("game_id", "another-game"), ("guid", "another-session"), ("win_levels", 2)):
            with self.subTest(field=field):
                second = self.observation("ACTION1")
                second["data"][field] = value
                self.write_recording([self.observation(), second])
                state = build_console_snapshot(self.root)
                self.assertEqual(state["levels"][0]["frames"], [])

    def test_summary_identity_mismatch_raises_public_safe_error(self):
        self.summary["run_id"] = "private-path-sentinel"
        self.write_summary()
        with self.assertRaisesRegex(ValueError, "^console evidence unavailable$"):
            build_console_snapshot(self.root)

    def test_modern_observation_digest_matches_exact_trace(self):
        initial, after = self.observation(), self.observation("ACTION4", 1)
        self.write_recording([initial, after])
        payload = self.action_payload(initial, after)
        for key, row in (("before_sha256", initial), ("after_sha256", after)):
            data = row["data"]
            observation = {k: data[k] for k in ("frame", "levels_completed", "state", "win_levels")}
            observation["available_actions"] = [f"ACTION{i}" for i in data["available_actions"]]
            payload[key] = digest(ObservationState.from_observation(observation).to_projection())
        self.write_trace([("arc.action", payload)])
        self.assertEqual(build_console_snapshot(self.root)["levels"][0]["actions"][0]["trace_sequence"], 1)

    def success_summary(self):
        receipt = PrimeArcAgi3SolveReceipt.create(run_id=self.root.name, completed_level_count=1,
                                                primitive_action_count=1, partial_game_score="1.000000")
        self.summary["receipt"] = {**vars(receipt), "receipt_sha256": receipt.receipt_sha256.removeprefix("sha256:")}
        self.summary["broker"] = {"game_id": "sp80-test", "seed": 0, "win_levels": 3,
                                  "levels_completed": 1, "primitive_actions": 1,
                                  "replay_sha256": "sha256:" + "a" * 64, "terminal_reason": "level-completed"}
        self.summary["sealed_trace"] = self.summary["replay_verified"] = True
        self.write_summary()

    def test_success_requires_complete_action_and_terminal_proof(self):
        initial, after = self.observation(), self.observation("ACTION4", 1, completed=1)
        self.write_recording([initial, after])
        self.success_summary()
        self.write_trace([("arc.action", self.action_payload(initial, after)),
                          ("arc.run.completed", self.summary["broker"])], sealed=True)
        state = build_console_snapshot(self.root)
        self.assertEqual(state["run"]["status"], "successful")
        self.assertTrue(state["run"]["sealed_trace"])
        self.assertTrue(state["run"]["replay_verified"])
        self.assertIsNotNone(state["levels"][0]["receipt"])

    def test_sealed_unrelated_trace_and_summary_flags_do_not_promote_success(self):
        self.write_recording([self.observation(), self.observation("ACTION4", 1, completed=1)])
        self.success_summary()
        self.write_trace([("prime.model.round", {"round_index": 0})], sealed=True)
        state = build_console_snapshot(self.root)
        self.assertEqual(state["run"]["status"], "incomplete")
        self.assertTrue(state["run"]["sealed_trace"])
        self.assertFalse(state["run"]["replay_verified"])
        self.assertTrue(all(level["receipt"] is None for level in state["levels"]))

    def test_conflicting_completed_count_does_not_promote_success(self):
        initial, after = self.observation(), self.observation("ACTION4", 1, completed=1)
        self.write_recording([initial, after])
        self.success_summary()
        terminal = {**self.summary["broker"], "primitive_actions": 2}
        self.write_trace([("arc.action", self.action_payload(initial, after)), ("arc.run.completed", terminal)], sealed=True)
        self.assertFalse(build_console_snapshot(self.root)["run"]["replay_verified"])

    def test_malformed_rows_reject_bool_colors_and_invalid_dimensions(self):
        for color in (True, -1, 256):
            with self.subTest(color=color):
                self.write_recording([self.observation(color=color)])
                self.assertEqual(build_console_snapshot(self.root)["levels"][0]["frames"], [])
        row = self.observation()
        row["data"]["frame"][0].pop()
        self.write_recording([row])
        self.assertEqual(build_console_snapshot(self.root)["levels"][0]["frames"], [])

    def test_size_bound_reports_missing_evidence(self):
        self.write_recording([self.observation()])
        with patch("asterion.applications.prime.p7.console_snapshot._MAX_FILE", 16):
            state = build_console_snapshot(self.root)
        self.assertEqual(state["levels"][0]["frames"], [])
        self.assertTrue(any("大小限制" in warning for warning in state["warnings"]))

    def test_symlink_recording_is_not_followed(self):
        target = Path(self.temporary.name) / "external.jsonl"
        target.write_text(json.dumps(self.observation()))
        self.recording.symlink_to(target)
        self.assertEqual(build_console_snapshot(self.root)["levels"][0]["frames"], [])

    def test_round_signals_never_infer_action_link_or_export_payload(self):
        initial, after = self.observation(), self.observation("ACTION4", 1)
        self.write_recording([initial, after])
        self.write_trace([("arc.action", self.action_payload(initial, after)), ("prime.model.round", {
            "round_index": 0, "prompt_signals": ["mechanics-prior", "PROMPT_SECRET"],
            "output_signals": ["action", "PROVIDER_SECRET"], "prompt": "PROMPT_SECRET", "output": "PROVIDER_SECRET",
        })])
        state = build_console_snapshot(self.root)
        decision = state["levels"][0]["decisions"][0]
        self.assertEqual(decision["action_ids"], [])
        self.assertEqual(decision["prompt_signals"], ["mechanics-prior"])
        self.assertEqual(decision["output_signals"], ["action"])
        self.assertIsNone(state["levels"][0]["actions"][0]["decision_id"])
        self.assertNotIn("SECRET", json.dumps(state))

    def test_multilevel_rounds_remain_run_scoped(self):
        self.write_recording([self.observation(), self.observation("ACTION1", 1, completed=1)])
        self.write_trace([("prime.model.round", {"round_index": 0, "prompt_signals": [], "output_signals": []})])
        state = build_console_snapshot(self.root)
        self.assertEqual(len(state["decisions"]), 1)
        self.assertTrue(all(not item["decisions"] for item in state["levels"]))

    def test_truncated_trace_keeps_verified_prefix_and_tampering_stops_it(self):
        initial, after = self.observation(), self.observation("ACTION1", 1)
        self.write_recording([initial, after])
        self.write_trace([("arc.action", self.action_payload(initial, after))])
        trace = self.root / "trace" / "prime-trace.jsonl"
        with trace.open("a") as file:
            file.write('{"incomplete":')
        state = build_console_snapshot(self.root)
        self.assertEqual(state["levels"][0]["actions"][0]["trace_sequence"], 1)
        row = json.loads(trace.read_text().splitlines()[0])
        row["payload"]["action"] = "ACTION4"
        trace.write_text(json.dumps(row) + "\n")
        state = build_console_snapshot(self.root)
        self.assertIsNone(state["levels"][0]["actions"][0]["trace_sequence"])

    def cognition(self):
        sid = self.root.name + "-cognition"
        claim = {"id": "fresh-grid-band-game", "kind": "game_type", "status": "certain", "evidence_count": 1,
                 "claim": "这是一个网格移动谜题。", "prompt": "PROMPT_SECRET"}
        self.summary["diagnostics"] = {"semantic_cognition": {
            "semantic": {"confirmed_knowledge": [claim, copy.deepcopy(claim)],
                         "scope": {"game_id": "sp80-test", "level": 0, "seed": 0, "win_levels": 3}},
            "cognition_session": {"session": {"session_id": sid}, "events": []}},
            "world_model_facts": {"confirmed": {"entities": 2, "mechanics": 1, "relations": 0, "secret": "SECRET"},
                                  "hypotheses": 3, "current_level": 0, "private_path": "/Users/SECRET"}, "pi_stderr": "SECRET"}
        return sid

    def test_final_cognition_reuses_stable_renderer_and_only_current_level(self):
        sid = self.cognition()
        self.summary["diagnostics"]["semantic_cognition"]["semantic"]["scope"]["level"] = 1
        self.summary["diagnostics"]["world_model_facts"]["current_level"] = 1
        self.write_summary()
        self.write_recording([self.observation(), self.observation("ACTION1", 1, completed=1)])
        (self.root.parent / f"semantic-events-{sid}.json").write_text(json.dumps({
            "schema": "asterion.prime.p7-semantic-cognition-events/v1", "events": [
                {"session_id": sid, "sequence": 1, "type": "cognition.hypothesis.confirmed",
                 "claim_ids": ["fresh-grid-band-game"], "explanation": "实测确认移动。", "provider": "SECRET"}]}))
        state = build_console_snapshot(self.root)
        first, second, _ = state["levels"]
        self.assertEqual(first["cognition"]["scope"], "unavailable")
        cognition = second["cognition"]
        self.assertEqual(cognition["scope"], "final")
        self.assertEqual(cognition["stable_description"].count("游戏类型："), 1)
        self.assertIn("网格移动谜题", cognition["stable_description"])
        self.assertEqual(cognition["world_map_facts"]["confirmed"], {"entities": 2, "mechanics": 1, "relations": 0})
        self.assertEqual(cognition["updates"][0]["changes"][0]["claim"], "实测确认移动。")
        self.assertNotIn("SECRET", json.dumps(state))

    def test_action_availability_tracks_frames_and_meanings_keep_evidence_status(self):
        self.cognition()
        semantic = self.summary["diagnostics"]["semantic_cognition"]["semantic"]
        semantic["claims"] = {"control": [
            {"id": "right", "kind": "control", "status": "certain", "claim": "当前位置ACTION4使颜色9横带右移四格。"},
            {"id": "left", "kind": "control", "status": "undetermined", "claim": "ACTION3可能使横带左移。"},
            {"id": "old-left", "kind": "control", "status": "falsified", "claim": "ACTION3使横带上移。"},
            {"id": "pair", "kind": "control", "status": "certain", "claim": "ACTION1和ACTION2使横带移动。"},
            {"id": "range", "kind": "control", "status": "certain", "claim": "ACTION1/2为上下移动。"},
        ]}
        self.write_summary()
        initial = self.observation()
        after = self.observation("ACTION4")
        after["data"]["available_actions"] = [1, 2]
        self.write_recording([initial, after])
        level = build_console_snapshot(self.root)["levels"][0]
        self.assertIn("ACTION4", level["frames"][0]["available_actions"])
        self.assertEqual(level["frames"][1]["available_actions"], ["ACTION1", "ACTION2"])
        meanings = level["cognition"]["action_meanings"]
        self.assertEqual(set(meanings), {"ACTION3", "ACTION4"})
        self.assertEqual(meanings["ACTION4"][0]["status"], "certain")
        self.assertIn("蓝色（9）", meanings["ACTION4"][0]["claim"])
        self.assertEqual([entry["status"] for entry in meanings["ACTION3"]], ["undetermined", "falsified"])

    def test_mismatched_sibling_cognition_events_are_never_used(self):
        sid = self.cognition()
        self.write_summary()
        self.write_recording([self.observation()])
        (self.root.parent / f"semantic-events-{sid}.json").write_text(json.dumps({
            "schema": "asterion.prime.p7-semantic-cognition-events/v1", "events": [
                {"session_id": "other-session", "sequence": 1, "type": "cognition.hypothesis.confirmed",
                 "claim_ids": ["fresh-grid-band-game"], "explanation": "SECRET"}]}))
        state = build_console_snapshot(self.root)
        self.assertEqual(state["levels"][0]["cognition"]["updates"], [])
        self.assertNotIn("SECRET", json.dumps(state))

    def test_cognition_scope_mismatch_cannot_be_attached_to_next_level(self):
        self.cognition()
        self.write_summary()
        self.write_recording([self.observation(), self.observation("ACTION1", 1, completed=1)])
        state = build_console_snapshot(self.root)
        self.assertTrue(all(level["cognition"]["scope"] == "unavailable" for level in state["levels"]))

    def test_generic_private_paths_and_world_fact_scope_are_rejected(self):
        self.cognition()
        semantic = self.summary["diagnostics"]["semantic_cognition"]["semantic"]
        semantic["confirmed_knowledge"] = [{"id": "hostile", "kind": "rule", "status": "certain",
                                            "claim": "读取/Volumes/Research/credential-sentinel文件。"}]
        self.summary["diagnostics"]["world_model_facts"]["current_level"] = 1
        self.write_summary()
        self.write_recording([self.observation()])
        state = build_console_snapshot(self.root)
        self.assertNotIn("credential-sentinel", json.dumps(state))
        self.assertEqual(state["levels"][0]["cognition"]["world_map_facts"], {})

    def test_exact_live_cognition_preserves_event_claim_changes(self):
        sid = self.cognition()
        self.write_summary()
        self.write_recording([self.observation()])
        event = {"session_id": sid, "sequence": 1, "type": "cognition.session.started", "claim_changes": [
            {"id": "new-proposal", "kind": "rule", "status": "undetermined", "claim": "横条接触结构可能过关。", "reason": "SECRET"}]}
        (self.root.parent / f"cognition-live-{sid}.jsonl").write_text(json.dumps(event) + "\n")
        state = build_console_snapshot(self.root)
        updates = state["levels"][0]["cognition"]["updates"]
        self.assertEqual(updates[0]["changes"], [{"id": "new-proposal", "kind": "rule", "status": "undetermined", "claim": "横条接触结构可能过关。"}])
        self.assertNotIn("SECRET", json.dumps(state))

    def test_non_scalar_hostile_fields_are_skipped_without_disclosure(self):
        for field in ("state", "action_input"):
            with self.subTest(field=field):
                row = self.observation()
                row["data"][field] = {"id": ["SECRET"], "data": {}}
                self.write_recording([row])
                self.assertEqual(build_console_snapshot(self.root)["levels"][0]["frames"], [])

    def test_hostile_fields_coordinates_and_private_prose_are_stripped(self):
        self.cognition()
        semantic = self.summary["diagnostics"]["semantic_cognition"]["semantic"]
        semantic["confirmed_knowledge"] = [{"id": "hostile", "kind": "rule", "status": "certain",
                                            "claim": "private /Users/SECRET/trace.jsonl api_key=SECRET"}]
        self.summary["diagnostics"]["semantic_cognition"]["cognition_session"]["events"] = [{
            "session_id": self.root.name + "-cognition", "sequence": 1, "type": "cognition.hypothesis.confirmed",
            "claim_ids": ["hostile"], "explanation": "Bearer SECRET"}]
        self.write_summary()
        initial, after = self.observation(), self.observation("ACTION6", 1)
        initial["data"]["action_input"]["reasoning"] = "SECRET"
        after["data"]["action_input"]["data"] = {"x": 3, "y": 4, "provider_payload": "SECRET"}
        after["data"]["private_path"] = "/Users/SECRET"
        self.write_recording([initial, after])
        state = build_console_snapshot(self.root)
        self.assertEqual(state["levels"][0]["actions"][0]["data"], {"x": 3, "y": 4})
        self.assertNotIn("SECRET", json.dumps(state))


if __name__ == "__main__":
    unittest.main()
