"""Offline recovery of one replay-verified P7 trace append race."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


class _RecordingEngine:
    game_id = "ls20-9607627b"
    seed = 0

    def __init__(self, *, recordings_dir: Path, game: object) -> None:
        self.calls = 0
        self._path = recordings_dir / "session" / "ls20.jsonl"
        self._path.parent.mkdir(parents=True)
        self._write("RESET")
        self._write("RESET")

    def _observation(self) -> dict[str, object]:
        return {
            "available_actions": ["ACTION1", "ACTION6"],
            "frame": [[[self.calls]]],
            "levels_completed": self.calls // 2,
            "state": "NOT_FINISHED",
            "win_levels": 7,
        }

    def _write(self, action: str, data: dict[str, int] | None = None) -> None:
        row = {
            "data": {
                "action_input": {"data": data or {}, "id": action},
                "available_actions": ["ACTION1", "ACTION6"],
                "frame": [[[self.calls]]],
                "full_reset": False,
                "game_id": self.game_id,
                "guid": self._path.parent.name,
                "levels_completed": self.calls // 2,
                "state": "NOT_FINISHED",
                "win_levels": 7,
            }
        }
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")

    def observe(self) -> dict[str, object]:
        return self._observation()

    def step(
        self, action: str, data: dict[str, int] | None = None
    ) -> dict[str, object]:
        if action != "RESET":
            self.calls += 1
        self._write(action, data)
        return self._observation()

    def close(self) -> None:
        pass


class TestRecoverPrimeP7TraceRace(unittest.TestCase):
    def test_materializes_new_sealed_prefix_without_changing_source(self) -> None:
        from asterion.applications.prime.p7.solutions import load_best_prefix
        from tools.list_prime_p7_games import inventory
        from tools.recover_prime_p7_trace_race import recover_trace_race

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = self._arc_root(root)
            source = self._race_source(root)
            source_snapshot = {
                path.relative_to(source): path.read_bytes()
                for path in source.rglob("*")
                if path.is_file()
            }
            with (
                mock.patch(
                    "tools.recover_prime_p7_trace_race.live.safe_run_id",
                    return_value="p7-live-20260925080000-0123456789abcdef01234567",
                ),
                mock.patch(
                    "tools.recover_prime_p7_trace_race.live.ArcadeEngine",
                    side_effect=lambda recordings_dir, game, **_: _RecordingEngine(
                        recordings_dir=recordings_dir, game=game
                    ),
                ),
                mock.patch(
                    "asterion.applications.prime.p7.solutions._fresh_engine",
                    side_effect=lambda _arc, game, recordings: _RecordingEngine(
                        recordings_dir=recordings, game=game
                    ),
                ),
            ):
                recovered = recover_trace_race(
                    operator_root=root,
                    arc_root=arc_root,
                    source_run_id=source.name,
                )
                prefix = load_best_prefix(
                    arc_root,
                    root / ".asterion-private" / "prime-p7-live",
                    "ls20-9607627b",
                    0,
                )

            self.assertNotEqual(recovered, source)
            self.assertEqual(
                source_snapshot,
                {
                    path.relative_to(source): path.read_bytes()
                    for path in source.rglob("*")
                    if path.is_file()
                },
            )
            self.assertIsNotNone(prefix)
            assert prefix is not None
            self.assertEqual(prefix.source_run_id, recovered.name)
            self.assertEqual((prefix.levels_completed, len(prefix.transitions)), (1, 2))
            summary = json.loads((recovered / "summary.json").read_text())
            self.assertTrue(summary["sealed_trace"])
            self.assertTrue(summary["replay_verified"])
            self.assertEqual(summary["diagnostics"]["recovered_from"], source.name)
            trace = (recovered / "trace" / "prime-trace.jsonl").read_text()
            self.assertIn('"kind":"arc.recovery.source"', trace)
            self.assertNotIn('"kind":"arc.usage.reported"', trace)
            row = next(
                value
                for value in inventory(
                    arc_root, root / ".asterion-private" / "prime-p7-live"
                )
                if value["game_id"] == "ls20-9607627b"
            )
            self.assertEqual(row["completed_levels"], 1)
            self.assertEqual(row["run_id"], recovered.name)

    def test_rejects_a_second_chain_break_before_creating_output(self) -> None:
        from tools.recover_prime_p7_trace_race import RecoveryError, recover_trace_race

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = self._arc_root(root)
            source = self._race_source(root)
            trace = source / "trace" / "prime-trace.jsonl"
            rows = trace.read_text().splitlines()
            rows.insert(1, rows[0])
            trace.write_text("\n".join(rows) + "\n")

            with (
                mock.patch(
                    "tools.recover_prime_p7_trace_race.live.ArcadeEngine",
                    side_effect=lambda recordings_dir, game, **_: _RecordingEngine(
                        recordings_dir=recordings_dir, game=game
                    ),
                ),
                self.assertRaisesRegex(RecoveryError, "recovery source is unavailable"),
            ):
                recover_trace_race(
                    operator_root=root,
                    arc_root=arc_root,
                    source_run_id=source.name,
                )

            runs = root / ".asterion-private" / "prime-p7-live"
            self.assertEqual(tuple(runs.iterdir()), (source,))

    def test_rejects_a_symlinked_private_evidence_ancestor(self) -> None:
        from tools.recover_prime_p7_trace_race import RecoveryError, recover_trace_race

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = self._arc_root(root)
            source = self._race_source(root)
            private = root / ".asterion-private"
            relocated = root / "relocated-private"
            private.rename(relocated)
            private.symlink_to(relocated, target_is_directory=True)

            with (
                mock.patch(
                    "tools.recover_prime_p7_trace_race.live.ArcadeEngine",
                    side_effect=lambda recordings_dir, game, **_: _RecordingEngine(
                        recordings_dir=recordings_dir, game=game
                    ),
                ),
                self.assertRaisesRegex(RecoveryError, "recovery source is unavailable"),
            ):
                recover_trace_race(
                    operator_root=root,
                    arc_root=arc_root,
                    source_run_id=source.name,
                )

    @staticmethod
    def _arc_root(root: Path) -> Path:
        game = root / "arc" / "environment_files" / "ls20" / "9607627b"
        game.mkdir(parents=True)
        (game / "ls20.py").write_text("# fixture\n")
        (game / "metadata.json").write_text(
            json.dumps(
                {
                    "baseline_actions": [22, 123, 73, 84, 96, 192, 186],
                    "game_id": "ls20-9607627b",
                    "win_levels": 7,
                }
            )
        )
        return root / "arc"

    @staticmethod
    def _race_source(root: Path) -> Path:
        from asterion.agents.prime.trace import _entry_digest
        from tests.test_prime_p7_solutions import TestP7SavedSolutions

        run = (
            root
            / ".asterion-private"
            / "prime-p7-live"
            / "p7-live-20260924230447-46fc1ea55b4041a6f56f8786"
        )
        TestP7SavedSolutions._write_run(run)
        summary_path = run / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary.update(
            {
                "completed_prefix": None,
                "failure": {"message": "trace is unavailable", "type": "PrimeTraceError"},
                "replay_verified": True,
                "sealed_trace": False,
            }
        )
        summary_path.write_text(json.dumps(summary, sort_keys=True))
        primary_recording = next((run / "recordings").glob("*/*.jsonl"))
        recording_rows = [
            json.loads(row) for row in primary_recording.read_text().splitlines()
        ]
        for row in recording_rows:
            row["data"]["action_input"]["reasoning"] = None
        primary_recording.write_text(
            "\n".join(json.dumps(row) for row in recording_rows) + "\n"
        )
        for name in ("replay-recordings", "prefix-replay-recordings"):
            target = run / name / "session"
            target.mkdir(parents=True)
            target.joinpath("ls20.jsonl").write_bytes(
                primary_recording.read_bytes()
            )

        trace_path = run / "trace" / "prime-trace.jsonl"
        original = [json.loads(row) for row in trace_path.read_text().splitlines()]
        first, second, completed, sealed = original
        orphan = {
            "identities": second["identities"],
            "kind": "arc.usage.reported",
            "payload": {"input_tokens": 7, "output_tokens": 3},
            "previous_sha256": first["sha256"],
            "sequence": 2,
        }
        orphan["sha256"] = _entry_digest(
            orphan["sequence"],
            orphan["kind"],
            orphan["identities"],
            orphan["payload"],
            orphan["previous_sha256"],
        )
        completed["sequence"] = 4
        completed["previous_sha256"] = second["sha256"]
        completed["sha256"] = _entry_digest(
            completed["sequence"],
            completed["kind"],
            completed["identities"],
            completed["payload"],
            completed["previous_sha256"],
        )
        sealed["sequence"] = 5
        sealed["previous_sha256"] = completed["sha256"]
        sealed["payload"] = {
            "entry_count": 4,
            "final_sha256": completed["sha256"],
        }
        sealed["sha256"] = _entry_digest(
            sealed["sequence"],
            sealed["kind"],
            sealed["identities"],
            sealed["payload"],
            sealed["previous_sha256"],
        )
        rows = [first, orphan, second, completed, sealed]
        trace_path.write_text(
            "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)
            + "\n"
        )
        (run / "trace" / "prime-trace.seal.json").write_text(
            json.dumps(
                {
                    "entry_count": len(rows),
                    "final_sha256": sealed["sha256"],
                    "sealed_at": "2026-09-24T23:09:39+00:00",
                },
                sort_keys=True,
            )
        )
        return run


if __name__ == "__main__":
    unittest.main()
