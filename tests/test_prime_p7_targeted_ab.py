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
    @staticmethod
    def _prefix():
        from asterion.applications.prime.p7.broker import ArcTransition
        from asterion.applications.prime.p7.score import replay_sha256

        transition = ArcTransition(1, "ACTION1", "sha256:" + "0" * 64,
                                   "sha256:" + "1" * 64, 1)
        return SimpleNamespace(game_id=GAME, seed=0, levels_completed=1,
                               win_levels=8, transitions=(transition,),
                               source_run_id="saved-l1",
                               replay_sha256=replay_sha256((transition,), terminal_reason="level-completed"))

    @staticmethod
    def _arm(runs: Path, run_id: str, variant: str, prefix, *,
             first_action: str = "ACTION1", terminal: str = "level-completed",
             seal_sidecar: bool = True, replay_override: str | None = None) -> None:
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcTransition
        from asterion.applications.prime.p7.private_trace import P7_TRACE_IDENTITIES
        from asterion.applications.prime.p7.score import replay_sha256

        run = runs / run_id
        trace = run / "trace"
        trace.mkdir(parents=True)
        transitions = [ArcTransition(1, first_action, "sha256:" + "0" * 64,
                                     "sha256:" + "1" * 64, 1)]
        for sequence in range(2, 5):
            transitions.append(ArcTransition(
                sequence, "ACTION1", "sha256:" + str(sequence - 1) * 64,
                "sha256:" + str(sequence) * 64,
                2 if sequence == 4 and terminal == "level-completed" else 1,
            ))
        replay = replay_override or replay_sha256(transitions, terminal_reason=terminal)
        recorder = PrimeTraceRecorder(trace)
        for action in transitions:
            recorder.append("arc.action", P7_TRACE_IDENTITIES, {
                "sequence": action.sequence, "action": action.action,
                "before_sha256": action.before_sha256,
                "after_sha256": action.after_sha256,
                "levels_completed": action.levels_completed,
            })
        recorder.append("arc.usage.reported", P7_TRACE_IDENTITIES,
                        {"input_tokens": 20, "output_tokens": 5})
        broker = {"game_id": GAME, "seed": 0, "win_levels": 8,
                  "levels_completed": 2 if terminal == "level-completed" else 1,
                  "primitive_actions": 4,
                  "terminal_reason": terminal, "replay_sha256": replay}
        recorder.append("arc.run.completed", P7_TRACE_IDENTITIES, broker)
        recorder.seal()
        if not seal_sidecar:
            (trace / "prime-trace.seal.json").unlink()
        summary = {
            "schema": "asterion.prime.p7-live-private-summary/v1",
            "run_id": run_id, "replay_verified": True, "sealed_trace": True,
            "cleanup_complete": True, "broker": broker,
            "diagnostics": {"prediction_variant": variant,
                            "sweep": {"scope": "offline-research", "target_level": 2,
                                      "prefix_actions": len(prefix.transitions),
                                      "level_action_cap": 38, "run_action_cap": 39}},
            "experiment": {"prediction_variant": variant, "model": "deepseek-v4-flash",
                           "game_id": GAME, "seed": 0, "target_level": 2,
                           "action_cap": 39, "deadline_ms": None, "stall_seconds": None},
        }
        (run / "summary.json").write_text(json.dumps(summary))

    def test_one_game_equal_constraints_and_distinct_private_runs(self) -> None:
        from tools.run_prime_p7_targeted_ab import run_targeted_ab
        from tools.run_prime_p7_sweep import SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "arc").mkdir()
            runs = root / ".asterion-private" / "prime-p7-live"
            runs.mkdir(parents=True)
            catalog = ({"game_id": GAME, "alias": "lp85", "baseline_actions": (9, 38), "win_levels": 8},)
            prefix = self._prefix()
            variants = []

            def attempt(scheduler, game_id, level, timeout):
                import os

                variant = os.environ["ASTERION_PRIME_P7_HISTORY_VARIANT"]
                variants.append((variant, game_id, level, timeout,
                                 scheduler.config.unbounded_second_round))
                run_id = f"p7-live-2026092512000{len(variants)}-abcdefabcdefabcdefabcdef"
                self._arm(runs, run_id, variant, prefix)
                scheduler._new_runs.append(run_id)
                return 0

            with patch("tools.run_prime_p7_targeted_ab._read_catalog", return_value=catalog), patch(
                "tools.run_prime_p7_targeted_ab.load_best_prefix", return_value=prefix
            ), patch.object(SweepScheduler, "_attempt", attempt):
                manifest = run_targeted_ab(root, root / "arc", "lp85", guest_machine="ubuntu")
            self.assertEqual([row[0] for row in variants], ["legacy", "verified"])
            self.assertTrue(all(row[1:] == (GAME, 2, 1800, True) for row in variants))
            self.assertEqual(len({arm["run_id"] for arm in manifest["arms"]}), 2)
            self.assertEqual([arm["level_two_actions"] for arm in manifest["arms"]], [3, 3])
            self.assertEqual([arm["input_tokens"] for arm in manifest["arms"]], [20, 20])
            self.assertFalse((runs / "second-round-campaign.json").exists())
            self.assertEqual(manifest["arms"][0]["outcome"], "verified")

    def test_forged_first_arm_stops_before_verified(self) -> None:
        from tools.run_prime_p7_targeted_ab import run_targeted_ab
        from tools.run_prime_p7_sweep import SweepScheduler

        for defect in ("different-prefix", "missing-sidecar", "early-baseline", "false-replay-digest"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "arc").mkdir()
                runs = root / ".asterion-private" / "prime-p7-live"
                runs.mkdir(parents=True)
                prefix = self._prefix()
                calls = []

                def attempt(scheduler, game_id, level, timeout):
                    calls.append((game_id, level, timeout))
                    run_id = f"p7-live-2026092512000{len(calls)}-abcdefabcdefabcdefabcdef"
                    self._arm(runs, run_id, "legacy", prefix,
                              first_action="ACTION2" if defect == "different-prefix" else "ACTION1",
                              terminal="human-baseline" if defect == "early-baseline" else "level-completed",
                              seal_sidecar=defect != "missing-sidecar",
                              replay_override="sha256:" + "f" * 64 if defect == "false-replay-digest" else None)
                    scheduler._new_runs.append(run_id)
                    return 1 if defect == "early-baseline" else 0

                with patch("tools.run_prime_p7_targeted_ab._read_catalog", return_value=(
                    {"game_id": GAME, "baseline_actions": (9, 38), "win_levels": 8},
                )), patch("tools.run_prime_p7_targeted_ab.load_best_prefix", return_value=prefix), patch.object(
                    SweepScheduler, "_attempt", attempt,
                ):
                    with self.assertRaises(ValueError):
                        run_targeted_ab(root, root / "arc", GAME, guest_machine="ubuntu")
                self.assertEqual(calls, [(GAME, 2, 1800)])

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
