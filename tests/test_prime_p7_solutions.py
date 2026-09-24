"""Saved P7 prefixes are private, sealed, and replayed before reuse."""

from __future__ import annotations

import json
from pathlib import Path
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
