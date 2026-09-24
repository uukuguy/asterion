from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.list_prime_p7_games import inventory, main


class TestPrimeP7GameInventory(unittest.TestCase):
    def test_only_verified_run_with_unambiguous_game_identity_contributes_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = root / "arc-agi-3"
            runs_root = root / "runs"
            self._metadata(arc_root, "alpha", "11111111", "Alpha", [4, 5, 6])
            self._metadata(arc_root, "beta", "22222222", "Beta", [7, 8])

            self._summary(
                runs_root / "run-alpha",
                run_id="run-alpha",
                levels=2,
                score="12.5",
                game_id="alpha-11111111",
            )
            self._summary(
                runs_root / "run-beta",
                run_id="run-beta",
                levels=1,
                score="99",
                game_id="beta-22222222",
                verified=False,
            )

            rows = inventory(arc_root, runs_root)

            self.assertEqual(
                rows,
                [
                    {
                        "game_id": "alpha-11111111",
                        "title": "Alpha",
                        "tags": "keyboard",
                        "total_levels": 3,
                        "completed_levels": 2,
                        "run_id": "run-alpha",
                        "score": "12.5",
                        "status": "verified",
                    },
                    {
                        "game_id": "beta-22222222",
                        "title": "Beta",
                        "tags": "click",
                        "total_levels": 2,
                        "completed_levels": 0,
                        "run_id": "—",
                        "score": "—",
                        "status": "no verified run",
                    },
                ],
            )

    def test_ambiguous_or_incomplete_runs_are_excluded_and_output_is_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = root / "arc-agi-3"
            runs_root = root / "runs"
            self._metadata(arc_root, "alpha", "11111111", "Alpha", [1])
            self._summary(
                runs_root / "ambiguous",
                run_id="ambiguous",
                levels=1,
                score="9",
                game_id=None,
                recording_names=(
                    "alpha-11111111-first.jsonl",
                    "alpha-11111111-second.jsonl",
                ),
            )

            rows = inventory(arc_root, runs_root)
            self.assertEqual(rows[0]["completed_levels"], 0)
            self.assertEqual(rows[0]["run_id"], "—")

            with patch("sys.stdout.write") as write:
                self.assertEqual(main(["--arc-root", str(arc_root), "--runs-root", str(runs_root)]), 0)
                output = "".join(call.args[0] for call in write.call_args_list)
            self.assertIn("alpha-11111111", output)
            self.assertNotIn(str(root), output)
            self.assertNotIn("first.jsonl", output)
            self.assertNotIn("secret", output)

    def test_requires_receipt_integrity_and_broker_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = root / "arc-agi-3"
            runs_root = root / "runs"
            self._metadata(arc_root, "alpha", "11111111", "Alpha", [1, 2])
            self._summary(
                runs_root / "bad-hash",
                run_id="bad-hash",
                levels=1,
                score="NaN",
                game_id="alpha-11111111",
                receipt_sha256="bad",
            )
            self._summary(
                runs_root / "too-many",
                run_id="too-many",
                levels=3,
                score="9",
                game_id="alpha-11111111",
            )
            self._summary(
                runs_root / "good",
                run_id="good",
                levels=1,
                score="9",
                game_id="alpha-11111111",
                recording_names=("beta-22222222-recording.jsonl",),
            )

            rows = inventory(arc_root, runs_root)
            self.assertEqual(rows[0]["completed_levels"], 0)

    def test_rejects_metadata_path_mismatch_and_symlinked_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = root / "arc-agi-3"
            runs_root = root / "runs"
            self._metadata(arc_root, "wrong", "11111111", "Wrong", [1])
            metadata = arc_root / "environment_files" / "wrong" / "11111111" / "metadata.json"
            metadata.write_text(
                json.dumps({"game_id": "other-11111111", "title": "Wrong", "tags": []}),
                encoding="utf-8",
            )
            if hasattr(Path, "symlink_to"):
                linked = arc_root / "environment_files" / "linked" / "22222222"
                linked.mkdir(parents=True)
                linked.joinpath("metadata.json").symlink_to(metadata)
            self.assertEqual(inventory(arc_root, runs_root), [])

    def test_missing_local_assets_report_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("sys.stdout.write") as write:
                self.assertEqual(main(["--arc-root", str(root), "--runs-root", str(root / "runs")]), 1)
                output = "".join(call.args[0] for call in write.call_args_list)
            self.assertEqual(output.strip(), "P7 local inventory unavailable")

    def test_old_unknown_game_and_invalid_scores_do_not_break_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = root / "arc-agi-3"
            runs_root = root / "runs"
            self._metadata(arc_root, "alpha", "11111111", "Alpha", [1])
            self._summary(
                runs_root / "unknown-game",
                run_id="unknown-game",
                levels=1,
                score="9",
                game_id=None,
                recording_names=("other-22222222-recording.jsonl",),
            )
            for name, score in (("negative", "-999"), ("high", "999"), ("multiline", "1\n2")):
                with self.subTest(score=score):
                    self._summary(
                        runs_root / name,
                        run_id=name,
                        levels=1,
                        score=score,
                        game_id="alpha-11111111",
                    )
            rows = inventory(arc_root, runs_root)
            self.assertEqual(rows[0]["completed_levels"], 0)

    @staticmethod
    def _metadata(root: Path, short_id: str, version: str, title: str, baseline: list[int]) -> None:
        path = root / "environment_files" / short_id / version
        path.mkdir(parents=True)
        (path / "metadata.json").write_text(
            json.dumps(
                {
                    "game_id": f"{short_id}-{version}",
                    "title": title,
                    "tags": ["keyboard" if short_id == "alpha" else "click"],
                    "baseline_actions": baseline,
                    "local_dir": "/private/fixture/path",
                }
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _summary(
        directory: Path,
        *,
        run_id: str,
        levels: int,
        score: str,
        game_id: str | None,
        verified: bool = True,
        recording_names: tuple[str, ...] | None = None,
        receipt_sha256: str = "a" * 64,
    ) -> None:
        directory.mkdir(parents=True)
        (directory / "summary.json").write_text(
            json.dumps(
                {
                    "schema": "asterion.prime.p7-live-private-summary/v1",
                    "run_id": run_id,
                    "receipt": {
                        "completed_level_count": levels,
                        "partial_game_score": score,
                        "receipt_sha256": receipt_sha256,
                        "primitive_action_count": 3,
                    },
                    "sealed_trace": verified,
                    "replay_verified": verified,
                    "cleanup_complete": verified,
                    "broker": {
                        "levels_completed": levels,
                        "primitive_actions": 3,
                        "terminal_reason": "level-completed",
                        **({"game_id": game_id} if game_id else {}),
                    },
                }
            ),
            encoding="utf-8",
        )
        names = recording_names or ((f"{game_id}-recording.jsonl",) if game_id else ())
        recording_dir = directory / "recordings" / "private-session"
        recording_dir.mkdir(parents=True)
        for name in names:
            (recording_dir / name).write_text("private secret frame", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
