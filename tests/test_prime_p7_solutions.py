"""Saved P7 prefixes are private, sealed, and replayed before reuse."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


class _Engine:
    game_id = "ls20-9607627b"
    seed = 0

    def __init__(self) -> None:
        self.calls = 0

    def observe(self) -> dict[str, object]:
        return {
            "available_actions": ["ACTION1", "ACTION6"],
            "frame": [[[self.calls]]],
            "levels_completed": self.calls // 2,
            "state": "NOT_FINISHED",
            "win_levels": 7,
        }

    def step(self, action: str, data: dict[str, int] | None = None) -> dict[str, object]:
        if action == "ACTION6":
            assert data == {"x": 12, "y": 34}
        if action != "RESET":
            self.calls += 1
        return self.observe()


class TestP7SavedSolutions(unittest.TestCase):
    def test_rejects_run_without_completed_cleanup(self) -> None:
        from asterion.applications.prime.p7.solutions import load_best_prefix

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = self._arc_root(root)
            runs_root = root / "runs"
            run = runs_root / "p7-unclean"
            self._write_run(run)
            summary_path = run / "summary.json"
            summary = json.loads(summary_path.read_text())
            summary["cleanup_complete"] = False
            summary_path.write_text(json.dumps(summary))
            with patch(
                "asterion.applications.prime.p7.solutions._fresh_engine",
                side_effect=lambda _root, _game, _recordings: _Engine(),
            ):
                self.assertIsNone(load_best_prefix(arc_root, runs_root, "ls20-9607627b", 0))

    def test_loads_sealed_click_prefix_and_replays_it(self) -> None:
        from asterion.applications.prime.p7.solutions import load_best_prefix

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = self._arc_root(root)
            runs_root = root / "runs"
            self._write_run(runs_root / "p7-old")
            with patch(
                "asterion.applications.prime.p7.solutions._fresh_engine",
                side_effect=lambda _root, _game, _recordings: _Engine(),
            ):
                prefix = load_best_prefix(arc_root, runs_root, "ls20-9607627b", 0)
        assert prefix is not None
        self.assertEqual((prefix.levels_completed, len(prefix.transitions)), (1, 2))
        self.assertEqual(prefix.transitions[0].data, (("x", 12), ("y", 34)))

    def test_rejects_changed_digest_wrong_game_and_symlinked_run(self) -> None:
        from asterion.applications.prime.p7.solutions import load_best_prefix

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = self._arc_root(root)
            runs_root = root / "runs"
            run = runs_root / "p7-old"
            self._write_run(run)
            trace = run / "trace" / "prime-trace.jsonl"
            trace.write_text(trace.read_text().replace("after_sha256", "after_digest", 1))
            self.assertIsNone(load_best_prefix(arc_root, runs_root, "ls20-9607627b", 0))
            self._write_run(runs_root / "p7-good")
            self.assertIsNone(load_best_prefix(arc_root, runs_root, "tu93-0768757b", 0))
            linked = runs_root / "linked"
            linked.symlink_to(run, target_is_directory=True)
            self.assertIsNone(load_best_prefix(arc_root, runs_root, "ls20-9607627b", 0))

    def test_preserves_reset_and_can_truncate_a_verified_longer_prefix(self) -> None:
        from asterion.applications.prime.p7.solutions import load_best_prefix

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = self._arc_root(root)
            runs_root = root / "runs"
            self._write_run(runs_root / "p7-two-level", target_level=2)
            with patch(
                "asterion.applications.prime.p7.solutions._fresh_engine",
                side_effect=lambda _root, _game, _recordings: _Engine(),
            ):
                full = load_best_prefix(arc_root, runs_root, "ls20-9607627b", 0)
                truncated = load_best_prefix(
                    arc_root, runs_root, "ls20-9607627b", 0, max_level=1
                )
        assert full is not None and truncated is not None
        self.assertEqual(full.levels_completed, 2)
        self.assertEqual([item.action for item in full.transitions], ["ACTION6", "ACTION1", "ACTION1", "RESET", "ACTION1"])
        self.assertEqual((truncated.levels_completed, len(truncated.transitions)), (1, 2))

    def test_salvages_only_a_sealed_completed_prefix_from_failed_later_level(self) -> None:
        from asterion.applications.prime.p7.solutions import load_best_prefix

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = self._arc_root(root)
            runs_root = root / "runs"
            self._write_partial_run(runs_root / "p7-failed-after-level-one")
            with patch(
                "asterion.applications.prime.p7.solutions._fresh_engine",
                side_effect=lambda _root, _game, _recordings: _Engine(),
            ):
                prefix = load_best_prefix(arc_root, runs_root, "ls20-9607627b", 0)
        assert prefix is not None
        self.assertEqual((prefix.levels_completed, len(prefix.transitions)), (1, 2))
        self.assertEqual([item.action for item in prefix.transitions], ["ACTION6", "ACTION1"])

    def test_rejects_partial_prefix_without_completed_level_or_cleanup(self) -> None:
        from asterion.applications.prime.p7.solutions import load_best_prefix

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = self._arc_root(root)
            runs_root = root / "runs"
            empty = runs_root / "p7-empty-partial"
            self._write_partial_run(empty, completed_levels=0)
            incomplete_cleanup = runs_root / "p7-unclean-partial"
            self._write_partial_run(incomplete_cleanup)
            summary_path = incomplete_cleanup / "summary.json"
            summary = json.loads(summary_path.read_text())
            summary["cleanup_complete"] = False
            summary_path.write_text(json.dumps(summary))
            with patch(
                "asterion.applications.prime.p7.solutions._fresh_engine",
                side_effect=lambda _root, _game, _recordings: _Engine(),
            ):
                self.assertIsNone(load_best_prefix(arc_root, runs_root, "ls20-9607627b", 0))

    def test_rejects_partial_prefix_when_later_recorded_action_differs(self) -> None:
        from asterion.applications.prime.p7.solutions import load_best_prefix

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = self._arc_root(root)
            runs_root = root / "runs"
            run = runs_root / "p7-mismatched-later-action"
            self._write_partial_run(run)
            recording_path = run / "recordings" / "session" / "ls20.jsonl"
            rows = recording_path.read_text().splitlines()
            rows[-1] = rows[-1].replace('"ACTION1"', '"ACTION2"')
            recording_path.write_text("\n".join(rows) + "\n")
            with patch(
                "asterion.applications.prime.p7.solutions._fresh_engine",
                side_effect=lambda _root, _game, _recordings: _Engine(),
            ):
                self.assertIsNone(load_best_prefix(arc_root, runs_root, "ls20-9607627b", 0))

    def test_rejects_trace_or_recording_directory_symlink_escape(self) -> None:
        from asterion.applications.prime.p7.solutions import load_best_prefix

        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            arc_root = self._arc_root(root)
            runs_root = root / "runs"
            run = runs_root / "p7-old"
            self._write_run(run)
            trace = run / "trace"
            moved_trace = Path(outside) / "trace"
            shutil.move(trace, moved_trace)
            trace.symlink_to(moved_trace, target_is_directory=True)
            with patch(
                "asterion.applications.prime.p7.solutions._fresh_engine",
                side_effect=lambda _root, _game, _recordings: _Engine(),
            ):
                self.assertIsNone(load_best_prefix(arc_root, runs_root, "ls20-9607627b", 0))
            trace.unlink()
            shutil.move(moved_trace, trace)
            session = run / "recordings" / "session"
            moved_session = Path(outside) / "session"
            shutil.move(session, moved_session)
            session.symlink_to(moved_session, target_is_directory=True)
            with patch(
                "asterion.applications.prime.p7.solutions._fresh_engine",
                side_effect=lambda _root, _game, _recordings: _Engine(),
            ):
                self.assertIsNone(load_best_prefix(arc_root, runs_root, "ls20-9607627b", 0))

    @staticmethod
    def _arc_root(root: Path) -> Path:
        game = root / "arc" / "environment_files" / "ls20" / "9607627b"
        game.mkdir(parents=True)
        (game / "ls20.py").write_text("# fixture\n")
        (game / "metadata.json").write_text(
            json.dumps({"game_id": "ls20-9607627b", "baseline_actions": [22, 123, 73, 84, 96, 192, 186], "win_levels": 7})
        )
        return root / "arc"

    @staticmethod
    def _write_run(run: Path, *, target_level: int = 1) -> None:
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcAction, ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.private_trace import P7_TRACE_IDENTITIES

        trace_root = run / "trace"
        trace_root.mkdir(parents=True)
        game = P7GameSelection("ls20-9607627b", 0, target_level)
        broker = ArcBroker(engine=_Engine(), game=game)
        broker.act((ArcAction("ACTION6", (("x", 12), ("y", 34))), "ACTION1"))
        if target_level == 2:
            broker.act(("ACTION1",))
            broker.act(("RESET",))
            broker.act(("ACTION1",))
        receipt = broker.seal()
        recorder = PrimeTraceRecorder(trace_root)
        for transition in broker.journal:
            payload = {"action": transition.action, "after_sha256": transition.after_sha256, "before_sha256": transition.before_sha256, "levels_completed": transition.levels_completed, "sequence": transition.sequence}
            if transition.data:
                payload["data"] = dict(transition.data)
            recorder.append("arc.action", P7_TRACE_IDENTITIES, payload)
        recorder.append("arc.run.completed", P7_TRACE_IDENTITIES, {"game_id": game.game_id, "seed": 0, "win_levels": 7, "levels_completed": target_level, "primitive_actions": len(broker.journal), "replay_sha256": receipt.replay_sha256, "terminal_reason": receipt.terminal_reason})
        recorder.seal()
        recording = run / "recordings" / "session"
        recording.mkdir(parents=True)
        rows = [{"data": {"game_id": game.game_id, "win_levels": 7, "action_input": {"id": "RESET", "data": {}}}}]
        rows.extend({"data": {"game_id": game.game_id, "win_levels": 7, "action_input": {"id": item.action, "data": dict(item.data)}}} for item in broker.journal)
        (recording / "ls20.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        (run / "worker-cells.jsonl").write_text("")
        (run / "summary.json").write_text(json.dumps({"schema": "asterion.prime.p7-live-private-summary/v1", "run_id": run.name, "receipt": {"completed_level_count": target_level, "primitive_action_count": len(broker.journal)}, "broker": {"game_id": game.game_id, "seed": 0, "win_levels": 7, "levels_completed": target_level, "primitive_actions": len(broker.journal), "terminal_reason": receipt.terminal_reason, "replay_sha256": receipt.replay_sha256}, "replay_verified": True, "sealed_trace": True, "cleanup_complete": True, "comparison_report": None, "reason": None, "failure": None, "diagnostics": {"worker_cell_count": 0}}))

    @staticmethod
    def _write_partial_run(run: Path, *, completed_levels: int = 1) -> None:
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcAction, ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.private_trace import P7_TRACE_IDENTITIES
        from asterion.applications.prime.p7.score import replay_sha256

        trace_root = run / "trace"
        trace_root.mkdir(parents=True)
        game = P7GameSelection("ls20-9607627b", 0, 7)
        broker = ArcBroker(engine=_Engine(), game=game)
        if completed_levels:
            broker.act((ArcAction("ACTION6", (("x", 12), ("y", 34))), "ACTION1"))
        broker.act(("ACTION1",))
        transitions = broker.journal
        prefix = transitions[: next(index for index, item in enumerate(transitions, 1) if item.levels_completed == completed_levels)] if completed_levels else ()
        prefix_digest = replay_sha256(prefix, terminal_reason="level-completed") if prefix else ""
        completed_prefix = {
            "game_id": game.game_id,
            "seed": 0,
            "win_levels": 7,
            "levels_completed": completed_levels,
            "primitive_actions": len(prefix),
            "replay_sha256": prefix_digest,
            "terminal_reason": "level-completed",
        }
        recorder = PrimeTraceRecorder(trace_root)
        for transition in transitions:
            payload = {"action": transition.action, "after_sha256": transition.after_sha256, "before_sha256": transition.before_sha256, "levels_completed": transition.levels_completed, "sequence": transition.sequence}
            if transition.data:
                payload["data"] = dict(transition.data)
            recorder.append("arc.action", P7_TRACE_IDENTITIES, payload)
        recorder.append("arc.run.partial", P7_TRACE_IDENTITIES, completed_prefix)
        recorder.seal()
        recording = run / "recordings" / "session"
        recording.mkdir(parents=True)
        rows = [{"data": {"game_id": game.game_id, "win_levels": 7, "action_input": {"id": "RESET", "data": {}}}}]
        rows.extend({"data": {"game_id": game.game_id, "win_levels": 7, "action_input": {"id": item.action, "data": dict(item.data)}}} for item in transitions)
        (recording / "ls20.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        (run / "worker-cells.jsonl").write_text("")
        (run / "summary.json").write_text(json.dumps({"schema": "asterion.prime.p7-live-private-summary/v1", "run_id": run.name, "receipt": {}, "broker": None, "completed_prefix": completed_prefix, "replay_verified": True, "sealed_trace": True, "cleanup_complete": True, "comparison_report": None, "reason": "P7 live solve unsuccessful", "failure": {"type": "RuntimeError"}, "diagnostics": {"worker_cell_count": 0}}))
