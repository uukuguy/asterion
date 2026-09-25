from __future__ import annotations

import json
import tempfile
import sys
import time
from unittest.mock import patch
import unittest
from pathlib import Path


class TestPrimeP7Sweep(unittest.TestCase):
    def test_unbounded_first_round_selects_only_unstarted_first_levels(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scheduler = SweepScheduler(SweepConfig(
                arc_root=root / "arc", runs_root=root / "runs",
                games=("ar25-1", "bp35-2", "ls20-9607627b"),
                unbounded_first_round=True,
            ))
            scheduler._next_level = lambda game_id: {"ar25-1": 2, "bp35-2": 1, "ls20-9607627b": 2}[game_id]  # type: ignore[method-assign]
            scheduler._is_complete = lambda _game_id, _level: False  # type: ignore[method-assign]
            attempts: list[tuple[str, int, float | None]] = []
            scheduler._attempt = lambda game_id, level, timeout: attempts.append((game_id, level, timeout)) or 1  # type: ignore[method-assign]
            scheduler._attempt_result = lambda _game_id, _level: False  # type: ignore[method-assign]
            result = scheduler.run()

        self.assertEqual(attempts, [("bp35-2", 1, None)])
        self.assertEqual(result.attempted, 1)
        self.assertEqual(result.preexisting_level_one, ("ar25-1",))
        self.assertEqual(result.newly_verified_level_one, ())
        self.assertEqual(result.attempted_unsolved_level_one, ("bp35-2",))
        self.assertEqual(result.stopped_reason, "completed")

    def test_unbounded_first_round_rejects_any_budget_cap(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with self.assertRaisesRegex(ValueError, "first round"):
            SweepScheduler(SweepConfig(
                Path("arc"), Path("runs"), unbounded_first_round=True,
                global_token_cap=1,
            ))

    def test_unbounded_first_round_never_advances_a_verified_game_to_level_two(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scheduler = SweepScheduler(SweepConfig(
                arc_root=root / "arc", runs_root=root / "runs", games=("bp35-2",),
                unbounded_first_round=True,
            ))
            scheduler._next_level = lambda game_id: 1  # type: ignore[method-assign]
            scheduler._is_complete = lambda _game_id, _level: False  # type: ignore[method-assign]
            attempts: list[tuple[str, int]] = []
            scheduler._attempt = lambda game_id, level, _timeout: attempts.append((game_id, level)) or 0  # type: ignore[method-assign]
            scheduler._attempt_result = lambda _game_id, _level: True  # type: ignore[method-assign]
            result = scheduler.run()

        self.assertEqual(attempts, [("bp35-2", 1)])
        self.assertEqual(result.newly_verified_level_one, ("bp35-2",))

    def test_first_round_recognizes_sealed_recovered_level_one_receipt(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "runs" / "p7-live-recovered"
            run.mkdir(parents=True)
            (run / "summary.json").write_text(json.dumps({
                "schema": "asterion.prime.p7-live-private-summary/v1",
                "run_id": run.name,
                "replay_verified": True, "sealed_trace": True, "cleanup_complete": True,
                "broker": {"game_id": "ar25-1", "seed": 0, "levels_completed": 1,
                           "primitive_actions": 22, "terminal_reason": "level-completed"},
                "receipt": {"completed_level_count": 1, "primitive_action_count": 22,
                            "receipt_sha256": "a" * 64},
            }), encoding="utf-8")
            scheduler = SweepScheduler(SweepConfig(root / "arc", root / "runs", unbounded_first_round=True))
            scheduler._catalog = lambda: ({"game_id": "ar25-1", "baseline_actions": (22,), "win_levels": 8},)  # type: ignore[method-assign]
            self.assertEqual(scheduler._verified_level_one_games(), frozenset({"ar25-1"}))

    def test_default_budget_matches_authorized_first_sweep(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig

        config = SweepConfig(Path("arc"), Path("runs"))
        self.assertEqual(config.global_token_cap, 3_500_000)
        self.assertEqual(config.wallclock_cap, 4 * 60 * 60)

    def test_round_robin_attempts_one_next_level_per_game(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scheduler = SweepScheduler(
                SweepConfig(arc_root=root / "arc", runs_root=root / "runs", games=("a-1", "b-2"), global_token_cap=100, max_attempts=2)
            )
            attempts: list[tuple[str, int]] = []

            def attempt(game_id: str, level: int, _timeout: float) -> int:
                attempts.append((game_id, level))
                return 0

            scheduler._attempt = attempt  # type: ignore[method-assign]
            scheduler._next_level = lambda game_id: 1  # type: ignore[method-assign]
            scheduler._is_complete = lambda _game_id, _level: False  # type: ignore[method-assign]
            scheduler._attempt_result = lambda _game_id, _level: True  # type: ignore[method-assign]
            result = scheduler.run()

        self.assertEqual(attempts, [("a-1", 1), ("b-2", 1)])
        self.assertEqual(result.attempted, 2)

    def test_resume_attempts_first_levels_before_saved_second_level(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scheduler = SweepScheduler(SweepConfig(
                arc_root=root / "arc", runs_root=root / "runs", games=("a-1", "b-2"), max_attempts=2,
            ))
            attempts: list[tuple[str, int]] = []
            scheduler._next_level = lambda game_id: 2 if game_id == "a-1" else 1  # type: ignore[method-assign]
            scheduler._is_complete = lambda _game_id, _level: False  # type: ignore[method-assign]
            scheduler._attempt = lambda game_id, level, _timeout: attempts.append((game_id, level)) or 1  # type: ignore[method-assign]
            scheduler._attempt_result = lambda _game_id, _level: False  # type: ignore[method-assign]
            scheduler.run()
        self.assertEqual(attempts, [("b-2", 1), ("a-1", 2)])

    def test_failed_game_is_blocked_until_the_sweep_ends(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scheduler = SweepScheduler(
                SweepConfig(arc_root=root / "arc", runs_root=root / "runs", games=("a-1", "b-2"), global_token_cap=100, max_attempts=2)
            )
            attempts: list[tuple[str, int]] = []

            def attempt(game_id: str, level: int, _timeout: float) -> int:
                attempts.append((game_id, level))
                return 1 if game_id == "a-1" else 0

            scheduler._attempt = attempt  # type: ignore[method-assign]
            scheduler._next_level = lambda _game_id: 1  # type: ignore[method-assign]
            scheduler._is_complete = lambda _game_id, _level: False  # type: ignore[method-assign]
            scheduler._attempt_result = lambda game_id, _level: game_id == "b-2"  # type: ignore[method-assign]
            result = scheduler.run()

        self.assertEqual(attempts, [("a-1", 1), ("b-2", 1)])
        self.assertEqual(result.blocked, ("a-1",))

    def test_usage_is_summed_and_missing_usage_stops_after_model_activity(self) -> None:
        from tools.run_prime_p7_sweep import read_run_usage

        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            trace = run / "trace"
            trace.mkdir()
            from asterion.agents.prime.trace import PrimeTraceRecorder

            recorder = PrimeTraceRecorder(trace)
            recorder.append("arc.usage.reported", {"runtime": "test"}, {"input_tokens": 4, "output_tokens": 6})
            recorder.append("arc.usage.reported", {"runtime": "test"}, {"input_tokens": 3, "output_tokens": 2})
            recorder.close()
            self.assertEqual(read_run_usage(run), (7, 8, False, False))

            (trace / "prime-trace.jsonl").write_text("", encoding="utf-8")
            (run / "worker-cells.jsonl").write_text("{}\n", encoding="utf-8")
            self.assertEqual(read_run_usage(run), (0, 0, True, True))

            (run / "worker-cells.jsonl").unlink()
            self.assertEqual(read_run_usage(run), (0, 0, True, True))

    def test_running_child_is_stopped_at_reported_token_cap(self) -> None:
        self._assert_monitored_child("budget", "token-cap", 11)

    def test_corrupt_running_trace_stops_and_preserves_valid_usage(self) -> None:
        self._assert_monitored_child("corrupt", "usage-trace-integrity-error", 11)

    def _assert_monitored_child(self, mode: str, reason: str, total: int) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler
        import os

        source = str(Path(__file__).resolve().parents[1] / "src")
        script = """
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from asterion.agents.prime.trace import PrimeTraceRecorder
trace = Path(sys.argv[2]) / 'run-1' / 'trace'
trace.mkdir(parents=True)
recorder = PrimeTraceRecorder(trace)
recorder.append('arc.usage.reported', {'runtime': 'test'}, {'input_tokens': 3, 'output_tokens': 4})
if sys.argv[3] == 'corrupt':
    with (trace / 'prime-trace.jsonl').open('a') as handle:
        handle.write('{}\\n')
time.sleep(10)
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scheduler = SweepScheduler(SweepConfig(
                arc_root=root / "arc", runs_root=root / "runs", repo_root=root,
                global_token_cap=10 if mode == "budget" else 100,
                command=(sys.executable, "-c", script, source, str(root / "runs"), mode), guest_machine=None,
            ))
            scheduler._input_tokens = 4
            started = time.monotonic()
            with patch("tools.run_prime_p7_sweep.os.killpg", wraps=os.killpg) as kill:
                scheduler._attempt("a-1", 1, 4)
            self.assertLess(time.monotonic() - started, 3)
            self.assertTrue(kill.called)
            self.assertEqual(scheduler._stop_reason, reason)
            self.assertEqual(scheduler._input_tokens + scheduler._output_tokens, total)
            self.assertEqual(scheduler._new_runs, ["run-1"])

    def test_live_reader_ignores_only_unfinished_last_row(self) -> None:
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from tools.run_prime_p7_sweep import read_run_usage

        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "trace").mkdir()
            recorder = PrimeTraceRecorder(run / "trace")
            recorder.append("arc.usage.reported", {"runtime": "test"}, {"input_tokens": 3, "output_tokens": 4})
            recorder.close()
            with (run / "trace" / "prime-trace.jsonl").open("ab") as handle:
                handle.write(b'{"unfinished":')
            self.assertEqual(read_run_usage(run, in_progress=True), (3, 4, False, False))
            self.assertEqual(read_run_usage(run), (3, 4, False, True))

    def test_nested_broker_status_defers_known_overbaseline_attempt(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scheduler = SweepScheduler(SweepConfig(arc_root=root / "arc", runs_root=root / "runs", games=("ls20-1",)))
            scheduler._catalog = lambda: ({"game_id": "ls20-1", "baseline_actions": (20, 123), "win_levels": 2},)  # type: ignore[method-assign]
            run = root / "runs" / "old"
            (run / "recordings").mkdir(parents=True)
            (run / "recordings" / "ls20-1-session.jsonl").write_text("", encoding="utf-8")
            (run / "summary.json").write_text(json.dumps({
                "replay_verified": False,
                "diagnostics": {"broker_status": {"levels_completed": 1, "primitive_actions": 200}},
            }), encoding="utf-8")
            self.assertIn(("ls20-1", 2), scheduler._find_deferred_levels())

    def test_nonzero_seed_is_rejected(self) -> None:
        from tools.run_prime_p7_sweep import main

        with self.assertRaises(SystemExit):
            main(["--arc-root", "/tmp/arc", "--seed", "1"])

    def test_nonfinite_wallclock_cannot_disable_budget(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with self.assertRaises(ValueError):
            SweepScheduler(SweepConfig(Path("arc"), Path("runs"), wallclock_cap=float("nan")))

    def test_child_without_run_evidence_stops_sweep(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scheduler = SweepScheduler(SweepConfig(
                arc_root=root / "arc", runs_root=root / "runs", games=("a-1",),
                repo_root=root, command=("/usr/bin/false",), guest_machine=None,
            ))
            scheduler._catalog = lambda: ({"game_id": "a-1", "baseline_actions": (20,), "win_levels": 1},)  # type: ignore[method-assign]
            result = scheduler.run()
        self.assertEqual(result.attempted, 1)
        self.assertEqual(result.stopped_reason, "child-evidence-missing")

    def test_unconfirmed_guest_cleanup_halts_sweep(self) -> None:
        import subprocess
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scheduler = SweepScheduler(SweepConfig(
                arc_root=root / "arc", runs_root=root / "runs", repo_root=root,
                command=("/usr/bin/false",), guest_machine="ubuntu",
            ))
            with patch("tools.run_prime_p7_sweep.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
                scheduler._attempt("a-1", 1, 1)
            self.assertEqual(scheduler._stop_reason, "guest-cleanup-unconfirmed")

    def test_attempt_summary_requires_matching_verified_terminal(self) -> None:
        from tools.run_prime_p7_sweep import _valid_attempt_summary

        base = {
            "schema": "asterion.prime.p7-live-private-summary/v1",
            "run_id": "run-1", "replay_verified": True, "sealed_trace": True,
            "cleanup_complete": True,
            "broker": {"game_id": "a-1", "seed": 0, "levels_completed": 0,
                       "primitive_actions": 20, "terminal_reason": "human-baseline"},
            "diagnostics": {"sweep": {"scope": "offline-research", "target_level": 1,
                                      "level_action_cap": 20, "run_action_cap": 20}},
        }
        self.assertTrue(_valid_attempt_summary(base, "run-1", "a-1", 1, 2))
        self.assertFalse(_valid_attempt_summary(base, "run-1", "b-2", 1, 2))
        self.assertFalse(_valid_attempt_summary(base, "run-1", "a-1", 2, 2))
        self.assertFalse(_valid_attempt_summary(base, "run-1", "a-1", 1, 0))
        self.assertFalse(_valid_attempt_summary({**base, "sealed_trace": False}, "run-1", "a-1", 1, 2))
        self.assertFalse(_valid_attempt_summary({**base, "broker": {**base["broker"], "terminal_reason": "active"}}, "run-1", "a-1", 1, 2))

    def test_longer_human_baseline_gets_longer_bounded_attempt(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        scheduler = SweepScheduler(SweepConfig(Path("arc"), Path("runs")))
        scheduler._catalog = lambda: ({"game_id": "a-1", "baseline_actions": (20, 78), "win_levels": 2},)  # type: ignore[method-assign]
        self.assertEqual(scheduler._timeout_for_level("a-1", 1), 600)
        self.assertGreater(scheduler._timeout_for_level("a-1", 2), 1200)
        self.assertLessEqual(scheduler._timeout_for_level("a-1", 2), 1800)


if __name__ == "__main__":
    unittest.main()
