"""Zero-model checks for the operator-only targeted P7 comparison."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


GAME = "lp85-305b61c3"


class TestPrimeP7TargetedAB(unittest.TestCase):
    def test_one_game_equal_constraints_and_distinct_private_runs(self) -> None:
        from tools.run_prime_p7_targeted_ab import run_targeted_ab
        from tools.run_prime_p7_sweep import SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "arc").mkdir()
            runs = root / ".asterion-private" / "prime-p7-live"
            runs.mkdir(parents=True)
            catalog = ({"game_id": GAME, "baseline_actions": (9, 38), "win_levels": 8},)
            prefix = SimpleNamespace(game_id=GAME, seed=0, levels_completed=1,
                                     win_levels=8, transitions=(object(),),
                                     source_run_id="saved-l1", replay_sha256="sha256:prefix")
            variants = []

            def attempt(scheduler, game_id, level, timeout):
                import os

                variant = os.environ["ASTERION_PRIME_P7_HISTORY_VARIANT"]
                variants.append((variant, game_id, level, timeout,
                                 scheduler.config.unbounded_second_round))
                run_id = f"p7-live-2026092512000{len(variants)}-abcdefabcdefabcdefabcdef"
                run = runs / run_id
                (run / "trace").mkdir(parents=True)
                (run / "trace" / "prime-trace.jsonl").write_text("trace\n")
                summary = {
                    "schema": "asterion.prime.p7-live-private-summary/v1",
                    "run_id": run_id, "replay_verified": True, "sealed_trace": True,
                    "cleanup_complete": True,
                    "broker": {"game_id": GAME, "seed": 0, "levels_completed": 1,
                               "primitive_actions": 4, "terminal_reason": "human-baseline"},
                    "diagnostics": {"prediction_variant": variant,
                                    "sweep": {"scope": "offline-research", "target_level": 2,
                                              "prefix_actions": 1, "level_action_cap": 38,
                                              "run_action_cap": 39}},
                    "experiment": {"prediction_variant": variant, "model": "deepseek-v4-flash",
                                   "game_id": GAME, "seed": 0, "target_level": 2,
                                   "action_cap": 39, "deadline_ms": None,
                                   "stall_seconds": None},
                }
                (run / "summary.json").write_text(json.dumps(summary))
                scheduler._new_runs.append(run_id)
                return 1

            with patch("tools.run_prime_p7_targeted_ab._read_catalog", return_value=catalog), patch(
                "tools.run_prime_p7_targeted_ab.load_best_prefix", return_value=prefix
            ), patch.object(SweepScheduler, "_attempt", attempt), patch(
                "tools.run_prime_p7_targeted_ab._read_hash_chained_trace",
                return_value=(*({"kind": "arc.action"} for _ in range(4)),
                              {"kind": "arc.usage.reported"},
                              {"kind": "trace.sealed", "sha256": "sha256:seal"}),
            ), patch("tools.run_prime_p7_targeted_ab.read_run_usage", return_value=(20, 5, False, False)):
                manifest = run_targeted_ab(root, root / "arc", GAME, guest_machine="ubuntu")
            self.assertEqual([row[0] for row in variants], ["legacy", "verified"])
            self.assertTrue(all(row[1:] == (GAME, 2, 1800, True) for row in variants))
            self.assertEqual(len({arm["run_id"] for arm in manifest["arms"]}), 2)
            self.assertEqual([arm["level_two_actions"] for arm in manifest["arms"]], [3, 3])
            self.assertEqual([arm["input_tokens"] for arm in manifest["arms"]], [20, 20])
            self.assertFalse((runs / "second-round-campaign.json").exists())
            self.assertEqual(manifest["arms"][0]["outcome"], "unsolved")

    def test_invalid_first_arm_aborts_before_verified(self) -> None:
        from tools.run_prime_p7_targeted_ab import run_targeted_ab
        from tools.run_prime_p7_sweep import SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "arc").mkdir()
            runs = root / ".asterion-private" / "prime-p7-live"
            runs.mkdir(parents=True)
            prefix = SimpleNamespace(game_id=GAME, seed=0, levels_completed=1,
                                     win_levels=8, transitions=(object(),),
                                     source_run_id="saved-l1", replay_sha256="sha256:prefix")
            with patch("tools.run_prime_p7_targeted_ab._read_catalog", return_value=(
                {"game_id": GAME, "baseline_actions": (9, 38), "win_levels": 8},
            )), patch("tools.run_prime_p7_targeted_ab.load_best_prefix", return_value=prefix), patch.object(
                SweepScheduler, "_attempt", return_value=1,
            ) as attempt:
                with self.assertRaises(ValueError):
                    run_targeted_ab(root, root / "arc", GAME, guest_machine="ubuntu")
            self.assertEqual(attempt.call_count, 1)
            self.assertFalse((runs / "second-round-campaign.json").exists())

    def test_guest_cleanup_failure_aborts_and_preserves_private_record(self) -> None:
        from tools.run_prime_p7_targeted_ab import run_targeted_ab
        from tools.run_prime_p7_sweep import SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "arc").mkdir()
            runs = root / ".asterion-private" / "prime-p7-live"
            runs.mkdir(parents=True)
            prefix = SimpleNamespace(game_id=GAME, seed=0, levels_completed=1,
                                     win_levels=8, transitions=(object(),),
                                     source_run_id="saved-l1", replay_sha256="sha256:prefix")

            calls = []

            def failed_cleanup(scheduler, game_id, level, timeout):
                calls.append((game_id, level, timeout))
                scheduler._stop_reason = "guest-cleanup-unconfirmed"
                return 1

            with patch("tools.run_prime_p7_targeted_ab._read_catalog", return_value=(
                {"game_id": GAME, "baseline_actions": (9, 38), "win_levels": 8},
            )), patch("tools.run_prime_p7_targeted_ab.load_best_prefix", return_value=prefix), patch.object(
                SweepScheduler, "_attempt", failed_cleanup,
            ):
                with self.assertRaisesRegex(ValueError, "guest-cleanup-unconfirmed"):
                    run_targeted_ab(root, root / "arc", GAME, guest_machine="ubuntu")
            self.assertEqual(calls, [(GAME, 2, 1800)])
            manifests = list((root / ".asterion-private" / "prime-p7-targeted-ab").glob("*.json"))
            self.assertEqual(len(manifests), 1)
            self.assertEqual(json.loads(manifests[0].read_text())["status"], "aborted")

    def test_rejects_unknown_game_or_missing_verified_prefix_before_attempt(self) -> None:
        from tools.run_prime_p7_targeted_ab import run_targeted_ab
        from tools.run_prime_p7_sweep import SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "arc").mkdir()
            with patch("tools.run_prime_p7_targeted_ab._read_catalog", return_value=(
                {"game_id": GAME, "baseline_actions": (9, 38), "win_levels": 8},
            )), patch("tools.run_prime_p7_targeted_ab.load_best_prefix", return_value=None), patch.object(
                SweepScheduler, "_attempt",
            ) as attempt:
                with self.assertRaises(ValueError):
                    run_targeted_ab(root, root / "arc", "wrong-game", guest_machine="ubuntu")
                with self.assertRaises(ValueError):
                    run_targeted_ab(root, root / "arc", GAME, guest_machine="ubuntu")
            attempt.assert_not_called()
