"""Zero-model selection and evidence gates for one P7 next-level attempt."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


GAME = "lp85-305b61c3"


class TestPrimeP7NextLevel(unittest.TestCase):
    def test_cli_output_omits_private_manifest_path(self) -> None:
        from tools.run_prime_p7_next_level import main

        private_path = "/private/SENTINEL-OPERATOR-ROOT/.asterion-private/next.json"
        result = {"status": "unverified", "game_id": GAME, "target_level": 3,
                  "stop_reason": "execution-stalled-evidence-invalid",
                  "run_ids": ["p7-live-20260925000000-" + "a" * 24],
                  "manifest": private_path, "prefix_replay_sha256": "sha256:private"}
        output = StringIO()
        with patch("tools.run_prime_p7_next_level.run_next_level", return_value=result), \
             redirect_stdout(output):
            exit_code = main(["--arc-root", "/tmp/arc", "--game", "lp85"])
        self.assertEqual(exit_code, 1)
        self.assertNotIn("SENTINEL-OPERATOR-ROOT", output.getvalue())
        self.assertNotIn("sha256:private", output.getvalue())
        self.assertEqual(json.loads(output.getvalue()), {
            "status": "unverified", "game_id": GAME, "target_level": 3,
            "stop_reason": "execution-stalled-evidence-invalid",
            "run_ids": result["run_ids"],
        })

    def test_cli_error_omits_private_path(self) -> None:
        from tools.run_prime_p7_next_level import main

        sentinel = "/private/SENTINEL-OPERATOR-ROOT/.asterion-private/missing"
        stdout = StringIO()
        stderr = StringIO()
        with patch("tools.run_prime_p7_next_level.run_next_level",
                   side_effect=FileNotFoundError(sentinel)), \
             redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(["--arc-root", "/tmp/arc", "--game", "lp85"])
        self.assertEqual(exit_code, 1)
        self.assertNotIn("SENTINEL-OPERATOR-ROOT", stdout.getvalue())
        self.assertNotIn("SENTINEL-OPERATOR-ROOT", stderr.getvalue())
        self.assertEqual(stderr.getvalue(), "[p7-next-level] preflight or evidence invalid\n")

    def test_success_needs_new_sealed_replay_and_cleanup(self) -> None:
        from tools.run_prime_p7_next_level import _verified_success
        from tests.test_prime_p7_targeted_ab import TestPrimeP7TargetedAB
        from asterion.applications.prime.p7.broker import ArcTransition
        from tools.run_prime_p7_sweep import _read_hash_chained_trace

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "p7-live-20260925000000-" + "a" * 24
            prefix = TestPrimeP7TargetedAB._prefix()
            TestPrimeP7TargetedAB._arm(root, run_id, "verified", prefix)
            rows = _read_hash_chained_trace(root / run_id / "trace" / "prime-trace.jsonl")
            transitions = tuple(ArcTransition(
                row["payload"]["sequence"], row["payload"]["action"],
                row["payload"]["before_sha256"], row["payload"]["after_sha256"],
                row["payload"]["levels_completed"],
            ) for row in rows if row["kind"] == "arc.action")
            verified = SimpleNamespace(source_run_id=run_id, levels_completed=2,
                                       transitions=transitions,
                                       replay_sha256=json.loads((root / run_id / "summary.json").read_text())["broker"]["replay_sha256"])
            with patch("tools.run_prime_p7_next_level.load_best_prefix", return_value=verified):
                success = _verified_success(root, root, run_id, GAME, 2, 38, prefix)
            self.assertEqual(success["level_actions"], 3)
            summary_path = root / run_id / "summary.json"
            summary = json.loads(summary_path.read_text())
            summary["cleanup_complete"] = False
            summary_path.write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError, "seal or summary"):
                _verified_success(root, root, run_id, GAME, 2, 38, prefix)

    def test_selects_exactly_one_level_after_verified_prefix(self) -> None:
        from tools.run_prime_p7_next_level import run_next_level

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc = root / "arc"
            arc.mkdir()
            runs = root / ".asterion-private" / "prime-p7-live"
            runs.mkdir(parents=True)
            prefix = SimpleNamespace(game_id=GAME, seed=0, win_levels=4,
                                     levels_completed=2, transitions=(object(), object()),
                                     source_run_id="saved-l2", replay_sha256="sha256:old")
            calls = []

            def attempt(scheduler, game_id, level, timeout):
                calls.append((game_id, level, timeout,
                              scheduler.config.unbounded_second_round))
                scheduler._stop_reason = "execution-stalled-evidence-invalid"
                scheduler._new_runs.append("p7-live-20260925000000-" + "a" * 24)
                return -15

            with patch("tools.run_prime_p7_next_level._read_catalog", return_value=(
                {"game_id": GAME, "alias": "lp85", "win_levels": 4,
                 "baseline_actions": (9, 38, 20, 15)},
            )), patch("tools.run_prime_p7_next_level.load_best_prefix", return_value=prefix), \
                 patch("tools.run_prime_p7_next_level.SweepScheduler._attempt", attempt):
                result = run_next_level(root, arc, "lp85")
            self.assertEqual(calls, [(GAME, 3, 1800, True)])
            self.assertEqual(result["status"], "unverified")
            self.assertEqual(result["target_level"], 3)
            self.assertEqual(result["stop_reason"], "execution-stalled-evidence-invalid")

    def test_missing_or_complete_prefix_never_launches(self) -> None:
        from tools.run_prime_p7_next_level import run_next_level

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc = root / "arc"
            arc.mkdir()
            runs = root / ".asterion-private" / "prime-p7-live"
            runs.mkdir(parents=True)
            metadata = ({"game_id": GAME, "alias": "lp85", "win_levels": 2,
                         "baseline_actions": (9, 38)},)
            with patch("tools.run_prime_p7_next_level._read_catalog", return_value=metadata), \
                 patch("tools.run_prime_p7_next_level.SweepScheduler._attempt") as attempt:
                with patch("tools.run_prime_p7_next_level.load_best_prefix", return_value=None):
                    with self.assertRaisesRegex(ValueError, "prefix"):
                        run_next_level(root, arc, "lp85")
                prefix = SimpleNamespace(game_id=GAME, seed=0, win_levels=2,
                                         levels_completed=2, transitions=(object(),),
                                         source_run_id="saved", replay_sha256="sha256:old")
                with patch("tools.run_prime_p7_next_level.load_best_prefix", return_value=prefix):
                    with self.assertRaisesRegex(ValueError, "complete"):
                        run_next_level(root, arc, "lp85")
                attempt.assert_not_called()
