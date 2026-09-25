from __future__ import annotations

import json
import tempfile
import sys
import time
from unittest.mock import patch
import unittest
from pathlib import Path


class TestPrimeP7Sweep(unittest.TestCase):
    def test_second_round_stall_window_is_five_minutes_without_new_action(self) -> None:
        from tools.run_prime_p7_sweep import _ACTION_STALL_SECONDS, _action_stall_reached

        self.assertEqual(_ACTION_STALL_SECONDS, 5 * 60)
        started = 100.0
        self.assertFalse(_action_stall_reached(started, started, 399.9))
        self.assertTrue(_action_stall_reached(started, started, 400.0))
        self.assertFalse(_action_stall_reached(started, 399.0, 400.0))

    @staticmethod
    def _execution_failure_fixture(root: Path):
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcTransition
        from asterion.applications.prime.p7.private_trace import P7_TRACE_IDENTITIES
        from asterion.applications.prime.p7.score import replay_sha256
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        game_id, run_id = "lp85-305b61c3", "fixture-failed"
        run = root / "runs" / run_id
        trace = run / "trace"
        trace.mkdir(parents=True)
        transitions = tuple(ArcTransition(i, "ACTION1", "sha256:" + str(i - 1) * 64,
                                          "sha256:" + str(i) * 64, 1) for i in (1, 2))
        prefix = {
            "game_id": game_id, "seed": 0, "win_levels": 8,
            "levels_completed": 1, "primitive_actions": 1,
            "terminal_reason": "level-completed",
            "replay_sha256": replay_sha256(transitions[:1], terminal_reason="level-completed"),
        }
        recorder = PrimeTraceRecorder(trace)
        for item in transitions:
            recorder.append("arc.action", P7_TRACE_IDENTITIES, {
                "sequence": item.sequence, "action": item.action,
                "before_sha256": item.before_sha256, "after_sha256": item.after_sha256,
                "levels_completed": item.levels_completed,
            })
        recorder.append("arc.usage.reported", P7_TRACE_IDENTITIES, {"input_tokens": 10, "output_tokens": 2})
        recorder.append("arc.run.partial", P7_TRACE_IDENTITIES, prefix)
        recorder.seal()
        summary = {
            "schema": "asterion.prime.p7-live-private-summary/v1", "run_id": run_id,
            "replay_verified": True, "sealed_trace": True, "cleanup_complete": True,
            "broker": None, "completed_prefix": prefix, "failure": {"type": "ApplicationRunError", "message": "fixture"},
            "diagnostics": {
                "sweep": {"scope": "offline-research", "target_level": 2,
                          "prefix_actions": 1, "level_action_cap": 38, "run_action_cap": 39},
                "broker_status": {"primitive_actions": 2, "levels_completed": 1,
                                  "actions_remaining": 37, "target_level": 2, "terminal_reason": "active"},
            },
        }
        (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        scheduler = SweepScheduler(SweepConfig(root / "arc", root / "runs", unbounded_second_round=True))
        scheduler._catalog = lambda: ({"game_id": game_id, "baseline_actions": (9, 38), "win_levels": 8},)
        entry = {"game_id": game_id, "run_id": run_id, "outcome": "execution-failed"}
        return scheduler, run, summary, entry

    def test_second_round_execution_failure_requires_exact_sealed_partial(self) -> None:
        from copy import deepcopy
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as directory:
            scheduler, run, summary, entry = self._execution_failure_fixture(Path(directory))
            with patch("tools.run_prime_p7_sweep.load_best_prefix", return_value=SimpleNamespace(levels_completed=1)):
                self.assertTrue(scheduler._campaign_entry_is_valid(entry))
                mutations = (
                    ("cleanup_complete", False), ("replay_verified", False), ("sealed_trace", False),
                    ("run_id", "other-run"), ("failure", {"type": "ValueError"}),
                    ("broker", {}),
                )
                for key, value in mutations:
                    with self.subTest(field=key):
                        changed = {**summary, key: value}
                        (run / "summary.json").write_text(json.dumps(changed), encoding="utf-8")
                        self.assertFalse(scheduler._campaign_entry_is_valid(entry))
                for section, key, value in (
                    ("sweep", "target_level", 1), ("sweep", "run_action_cap", 40),
                    ("sweep", "level_action_cap", 39), ("sweep", "prefix_actions", 2),
                    ("broker_status", "terminal_reason", "game-over"),
                    ("broker_status", "primitive_actions", 40),
                    ("broker_status", "levels_completed", 2),
                ):
                    with self.subTest(section=section, field=key):
                        changed = deepcopy(summary)
                        changed["diagnostics"][section][key] = value
                        (run / "summary.json").write_text(json.dumps(changed), encoding="utf-8")
                        self.assertFalse(scheduler._campaign_entry_is_valid(entry))
                for key, value in (("seed", 1), ("game_id", "other-game"), ("levels_completed", 2)):
                    changed = deepcopy(summary)
                    changed["completed_prefix"][key] = value
                    (run / "summary.json").write_text(json.dumps(changed), encoding="utf-8")
                    self.assertFalse(scheduler._campaign_entry_is_valid(entry))
                (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
            with patch("tools.run_prime_p7_sweep.load_best_prefix", return_value=SimpleNamespace(levels_completed=2)):
                self.assertFalse(scheduler._execution_failure_is_valid(entry["run_id"], entry["game_id"]))
                self.assertTrue(scheduler._campaign_entry_is_valid(entry))
            trace = run / "trace" / "prime-trace.jsonl"
            trace.write_text(trace.read_text().replace('"input_tokens":10', '"input_tokens":11'), encoding="utf-8")
            with patch("tools.run_prime_p7_sweep.load_best_prefix", return_value=SimpleNamespace(levels_completed=1)):
                self.assertFalse(scheduler._campaign_entry_is_valid(entry))

    def test_second_round_execution_stall_uses_same_strict_partial_evidence(self) -> None:
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as directory:
            scheduler, _run, _summary, entry = self._execution_failure_fixture(Path(directory))
            entry["outcome"] = "execution-stalled"
            with patch("tools.run_prime_p7_sweep.load_best_prefix", return_value=SimpleNamespace(levels_completed=1)):
                self.assertFalse(scheduler._campaign_entry_is_valid(entry))

    def test_second_round_execution_stall_accepts_unsealed_trace_with_receipt(self) -> None:
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as directory:
            scheduler, run, _summary, entry = self._execution_failure_fixture(Path(directory))
            trace = run / "trace" / "prime-trace.jsonl"
            rows = trace.read_text(encoding="utf-8").splitlines()
            trace.write_text("\n".join(rows[:-2]) + "\n", encoding="utf-8")
            (run / "summary.json").unlink()
            (run / "recordings").mkdir()
            (run / "recordings" / f"{entry['game_id']}-fixture.jsonl").write_text("{}\n", encoding="utf-8")
            (run / "stall-receipt.json").write_text(json.dumps({
                "schema": "asterion.prime.p7-stall-receipt/v1",
                "game_id": entry["game_id"], "run_id": entry["run_id"], "seed": 0,
                "action_count": 2, "stall_seconds": 300,
                "cleanup_complete": True,
                "trace_final_sha256": json.loads(rows[-3])["sha256"],
            }), encoding="utf-8")
            with patch("tools.run_prime_p7_sweep.load_best_prefix", return_value=SimpleNamespace(levels_completed=1, primitive_actions=1)):
                entry["outcome"] = "execution-stalled"
                self.assertTrue(scheduler._campaign_entry_is_valid(entry))
                receipt_path = run / "stall-receipt.json"
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt_path.write_text(json.dumps({**receipt, "action_count": 1}), encoding="utf-8")
                self.assertFalse(scheduler._campaign_entry_is_valid(entry))
                receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
                moved = run / "stall-receipt-target.json"
                moved.write_text(receipt_path.read_text(encoding="utf-8"), encoding="utf-8")
                receipt_path.unlink()
                receipt_path.symlink_to(moved.name)
                self.assertFalse(scheduler._campaign_entry_is_valid(entry))

    def test_second_round_execution_failure_records_and_skips_on_resume(self) -> None:
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as directory:
            scheduler, _run, _summary, entry = self._execution_failure_fixture(Path(directory))
            scheduler._second_round_campaign_is_ready = lambda _games: True
            scheduler._next_level = lambda _game: 2
            scheduler._is_complete = lambda *_args: False
            scheduler._new_runs.append(entry["run_id"])
            scheduler._selected_games = lambda: (entry["game_id"],)
            def attempt(*_args):
                scheduler._stop_reason = "execution-failed"
                return 1
            scheduler._attempt = attempt
            with patch("tools.run_prime_p7_sweep.load_best_prefix", return_value=SimpleNamespace(levels_completed=1)):
                result = scheduler.run()
                self.assertEqual(result.stopped_reason, "completed")
                self.assertEqual(result.execution_failed_level_two, (entry["game_id"],))
                self.assertEqual(result.attempted_unsolved_level_two, ())
                self.assertEqual(scheduler._load_or_create_campaign()["terminal_attempts"], [entry])
                with patch.object(scheduler, "_attempt") as called:
                    resumed = scheduler.run()
                    called.assert_not_called()
                self.assertEqual(resumed.previously_execution_failed_level_two, (entry["game_id"],))
        self.assertEqual(resumed.previously_attempted_unsolved_level_two, ())

    def test_second_round_execution_stall_records_and_skips_on_resume(self) -> None:
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as directory:
            scheduler, _run, _summary, entry = self._execution_failure_fixture(Path(directory))
            scheduler._second_round_campaign_is_ready = lambda _games: True
            scheduler._next_level = lambda _game: 2
            scheduler._is_complete = lambda *_args: False
            scheduler._new_runs.append(entry["run_id"])
            scheduler._selected_games = lambda: (entry["game_id"],)

            def attempt(*_args):
                scheduler._stop_reason = "execution-stalled"
                return 1

            scheduler._attempt = attempt
            scheduler._execution_stalled_is_valid = lambda *_args, **_kwargs: True  # type: ignore[method-assign]
            with patch("tools.run_prime_p7_sweep.load_best_prefix", return_value=SimpleNamespace(levels_completed=1)):
                result = scheduler.run()
                self.assertEqual(result.stopped_reason, "completed")
                self.assertEqual(result.execution_stalled_level_two, (entry["game_id"],))
                self.assertEqual(result.previously_execution_stalled_level_two, ())
                with patch.object(scheduler, "_attempt") as called:
                    resumed = scheduler.run()
                    called.assert_not_called()
                self.assertEqual(resumed.previously_execution_stalled_level_two, (entry["game_id"],))

    def test_second_round_adopts_only_explicit_valid_failure_once(self) -> None:
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as directory:
            scheduler, run, summary, entry = self._execution_failure_fixture(Path(directory))
            scheduler._second_round_campaign_is_ready = lambda _games: True
            with patch("tools.run_prime_p7_sweep.load_best_prefix", return_value=SimpleNamespace(levels_completed=1)), patch.object(scheduler, "_attempt") as attempt:
                for run_id in ("missing", "../fixture-failed"):
                    with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                        scheduler.adopt_execution_failure(run_id)
                self.assertFalse(scheduler._campaign_path().exists())
                (run / "summary.json").write_text(json.dumps({**summary, "cleanup_complete": False}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    scheduler.adopt_execution_failure(entry["run_id"])
                self.assertFalse(scheduler._campaign_path().exists())
                (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
                self.assertEqual(scheduler.adopt_execution_failure(entry["run_id"]), entry["game_id"])
                with self.assertRaises(ValueError):
                    scheduler.adopt_execution_failure(entry["run_id"])
                self.assertEqual(scheduler._load_or_create_campaign()["terminal_attempts"], [entry])
                attempt.assert_not_called()

    def test_second_round_attempt_classifies_partial_only_after_nonzero_exit(self) -> None:
        from types import SimpleNamespace
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        for returncode in (0, 1):
            with self.subTest(returncode=returncode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                scheduler = SweepScheduler(SweepConfig(root / "arc", root / "runs", repo_root=root,
                                            command=("fixture",), guest_machine=None, unbounded_second_round=True))
                scheduler._catalog = lambda: ({"game_id": "lp85-305b61c3", "baseline_actions": (9, 38), "win_levels": 8},)
                def launch(*_args, **_kwargs):
                    self._execution_failure_fixture(root)
                    return SimpleNamespace(returncode=returncode, communicate=lambda **_kw: ("", ""))
                with patch("tools.run_prime_p7_sweep.subprocess.Popen", side_effect=launch), patch(
                    "tools.run_prime_p7_sweep.load_best_prefix", return_value=SimpleNamespace(levels_completed=1),
                ):
                    scheduler._attempt("lp85-305b61c3", 2, 1800)
                self.assertEqual(scheduler._stop_reason, "execution-failed" if returncode else "child-evidence-invalid")

    def test_execution_failure_adoption_cli_never_launches_paid_work(self) -> None:
        import contextlib
        import io
        from tools.run_prime_p7_sweep import SweepScheduler, main

        for accepted in (False, True):
            with self.subTest(accepted=accepted), tempfile.TemporaryDirectory() as directory:
                output = io.StringIO()
                with patch.object(SweepScheduler, "adopt_execution_failure", return_value="lp85-305b61c3",
                                  side_effect=None if accepted else ValueError("private-sentinel")), patch.object(SweepScheduler, "run") as run, contextlib.redirect_stdout(output):
                    result = main(["--operator-root", directory, "--arc-root", directory,
                                   "--unbounded-second-round", "--adopt-execution-failure", "fixture-failed"])
                self.assertEqual(result, 0 if accepted else 1)
                self.assertNotIn("private-sentinel", output.getvalue())
                self.assertEqual(json.loads(output.getvalue())["recorded"], accepted)
                run.assert_not_called()

    def test_second_round_requires_pinned_catalog_and_verified_prefixes(self) -> None:
        from types import SimpleNamespace
        from tools.run_prime_p7_sweep import (
            _FIRST_ROUND_CATALOG_GAME_IDS, _SECOND_ROUND_GAME_IDS, SweepConfig, SweepScheduler,
        )

        scheduler = SweepScheduler(SweepConfig(Path("arc"), Path("runs"), unbounded_second_round=True))
        scheduler._catalog = lambda: tuple({"game_id": game_id} for game_id in _FIRST_ROUND_CATALOG_GAME_IDS)  # type: ignore[method-assign]
        games = scheduler._selected_games()
        self.assertEqual(games, _SECOND_ROUND_GAME_IDS)
        with patch("tools.run_prime_p7_sweep.load_best_prefix", return_value=SimpleNamespace(levels_completed=1)):
            self.assertTrue(scheduler._second_round_campaign_is_ready(games))
        with patch("tools.run_prime_p7_sweep.load_best_prefix", return_value=None):
            self.assertFalse(scheduler._second_round_campaign_is_ready(games))
        scheduler._catalog = lambda: tuple({"game_id": game_id} for game_id in _FIRST_ROUND_CATALOG_GAME_IDS[:-1])  # type: ignore[method-assign]
        self.assertFalse(scheduler._second_round_campaign_is_ready(scheduler._selected_games()))

    def test_second_round_visits_each_level_two_once_and_ignores_old_deferral(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scheduler = SweepScheduler(SweepConfig(
                root / "arc", root / "runs", games=("a-1", "b-2", "c-3"),
                unbounded_second_round=True,
            ))
            scheduler._second_round_campaign_is_ready = lambda _games: True  # type: ignore[method-assign]
            scheduler._load_or_create_campaign = lambda: {"terminal_attempts": [
                {"game_id": "c-3", "outcome": "unsolved"},
            ]}  # type: ignore[method-assign]
            scheduler._next_level = lambda game_id: {"a-1": 2, "b-2": 2, "c-3": 2}[game_id]  # type: ignore[method-assign]
            scheduler._is_complete = lambda _game_id, _level: False  # type: ignore[method-assign]
            scheduler._deferred_levels = frozenset({("a-1", 2)})
            scheduler._attempt = lambda game_id, level, timeout: (attempts.append((game_id, level, timeout)), 0 if game_id == "a-1" else 1)[1]  # type: ignore[method-assign]
            scheduler._attempt_result = lambda game_id, _level: game_id == "a-1"  # type: ignore[method-assign]
            scheduler._record_campaign_attempt = lambda *_args: None  # type: ignore[method-assign]
            attempts: list[tuple[str, int, float | None]] = []
            result = scheduler.run()

        self.assertEqual(attempts, [("a-1", 2, 1800), ("b-2", 2, 1800)])
        self.assertEqual(result.newly_verified_level_two, ("a-1",))
        self.assertEqual(result.attempted_unsolved_level_two, ("b-2",))
        self.assertEqual(result.previously_attempted_unsolved_level_two, ("c-3",))
        self.assertEqual(result.stopped_reason, "completed")

    def test_second_round_requires_thirty_minutes_and_timeout_trace_at_level_one(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler, _trace_reached_level

        with self.assertRaisesRegex(ValueError, "30-minute"):
            SweepScheduler(SweepConfig(Path("arc"), Path("runs"), unbounded_second_round=True, run_timeout=None))
        self.assertFalse(_trace_reached_level(({
            "kind": "arc.action", "payload": {"levels_completed": 0},
        },), 1))
        self.assertTrue(_trace_reached_level(({
            "kind": "arc.action", "payload": {"levels_completed": 1},
        },), 1))

    def test_unbounded_first_round_rejects_missing_catalog_before_attempt(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scheduler = SweepScheduler(SweepConfig(root / "arc", root / "runs", unbounded_first_round=True))
            scheduler._catalog = lambda: ()  # type: ignore[method-assign]
            attempts: list[tuple[str, int]] = []
            scheduler._attempt = lambda game_id, level, _timeout: attempts.append((game_id, level)) or 0  # type: ignore[method-assign]
            result = scheduler.run()

        self.assertEqual(attempts, [])
        self.assertEqual(result.stopped_reason, "first-round-catalog-invalid")

    def test_unbounded_first_round_requires_pinned_inventory_and_ar25_replay(self) -> None:
        from types import SimpleNamespace
        from tools.run_prime_p7_sweep import (
            _FIRST_ROUND_CATALOG_GAME_IDS, SweepConfig, SweepScheduler,
        )

        game_ids = _FIRST_ROUND_CATALOG_GAME_IDS
        scheduler = SweepScheduler(SweepConfig(Path("arc"), Path("runs"), unbounded_first_round=True))
        scheduler._catalog = lambda: tuple({"game_id": game_id} for game_id in game_ids)  # type: ignore[method-assign]
        games = scheduler._selected_games()
        with patch("tools.run_prime_p7_sweep.load_best_prefix", return_value=SimpleNamespace(levels_completed=1)):
            self.assertTrue(scheduler._first_round_campaign_is_ready(games))
        scheduler._catalog = lambda: tuple({"game_id": game_id} for game_id in game_ids[:-1])  # type: ignore[method-assign]
        with patch("tools.run_prime_p7_sweep.load_best_prefix") as replay:
            self.assertFalse(scheduler._first_round_campaign_is_ready(scheduler._selected_games()))
            replay.assert_not_called()

    def test_unbounded_first_round_rejects_swapped_catalog_game_id(self) -> None:
        from types import SimpleNamespace
        from tools.run_prime_p7_sweep import (
            _FIRST_ROUND_CATALOG_GAME_IDS, SweepConfig, SweepScheduler,
        )

        scheduler = SweepScheduler(SweepConfig(Path("arc"), Path("runs"), unbounded_first_round=True))
        swapped = (*_FIRST_ROUND_CATALOG_GAME_IDS[:-1], "zz99-deadbeef")
        scheduler._catalog = lambda: tuple({"game_id": game_id} for game_id in swapped)  # type: ignore[method-assign]
        with patch("tools.run_prime_p7_sweep.load_best_prefix", return_value=SimpleNamespace(levels_completed=1)):
            self.assertFalse(scheduler._first_round_campaign_is_ready(scheduler._selected_games()))

    def test_first_round_resume_skips_only_campaign_recorded_unsolved_game(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = root / "runs"
            runs.mkdir()
            campaign = {
                "schema": "asterion.prime.p7-first-round-campaign/v1",
                "campaign_id": "first-round-0123456789abcdef0123456789abcdef",
                "catalog_game_ids": ["a-1", "b-2"],
                "terminal_attempts": [{"game_id": "a-1", "run_id": "run-a", "outcome": "unsolved"}],
            }
            scheduler = SweepScheduler(SweepConfig(
                root / "arc", runs, games=("a-1", "b-2"), unbounded_first_round=True,
            ))
            scheduler._first_round_campaign_is_ready = lambda _games: True  # type: ignore[method-assign]
            scheduler._first_round_catalog_ids = lambda: ("a-1", "b-2")  # type: ignore[method-assign]
            scheduler._load_or_create_campaign = lambda: campaign  # type: ignore[method-assign]
            scheduler._next_level = lambda _game_id: 1  # type: ignore[method-assign]
            scheduler._is_complete = lambda _game_id, _level: False  # type: ignore[method-assign]
            attempts: list[tuple[str, int]] = []
            scheduler._attempt = lambda game_id, level, _timeout: attempts.append((game_id, level)) or 1  # type: ignore[method-assign]
            scheduler._attempt_result = lambda _game_id, _level: False  # type: ignore[method-assign]
            result = scheduler.run()

        self.assertEqual(attempts, [("b-2", 1)])
        self.assertEqual(result.previously_attempted_unsolved_level_one, ("a-1",))

    def test_campaign_ledger_rejects_nonexistent_duplicate_or_mismatched_evidence(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = root / "runs"
            runs.mkdir()
            scheduler = SweepScheduler(SweepConfig(root / "arc", runs, unbounded_first_round=True))
            scheduler._first_round_catalog_ids = lambda: ("a-1", "b-2")  # type: ignore[method-assign]
            base = {
                "schema": "asterion.prime.p7-first-round-campaign/v1",
                "campaign_id": "first-round-0123456789abcdef0123456789abcdef",
                "catalog_game_ids": ["a-1", "b-2"],
            }
            for attempts in (
                [{"game_id": "a-1", "run_id": "missing", "outcome": "unsolved"}],
                [{"game_id": "a-1", "run_id": "same", "outcome": "unsolved"}, {"game_id": "b-2", "run_id": "same", "outcome": "unsolved"}],
                [{"game_id": "b-2", "run_id": "missing", "outcome": "verified"}],
            ):
                with self.subTest(attempts=attempts):
                    (runs / "first-round-campaign.json").write_text(json.dumps({**base, "terminal_attempts": attempts}), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        scheduler._load_or_create_campaign()

    def test_unbounded_first_round_keeps_thirty_minute_per_game_limit(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        scheduler = SweepScheduler(SweepConfig(Path("arc"), Path("runs"), unbounded_first_round=True))
        self.assertEqual(scheduler._timeout_for_level("bp35-0a0ad940", 1), 30 * 60)

    def test_first_round_records_admitted_unsealed_timeout_and_continues(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scheduler = SweepScheduler(SweepConfig(
                root / "arc", root / "runs", games=("a-1",), unbounded_first_round=True,
            ))
            scheduler._first_round_campaign_is_ready = lambda _games: True  # type: ignore[method-assign]
            scheduler._first_round_catalog_ids = lambda: ("a-1",)  # type: ignore[method-assign]
            scheduler._next_level = lambda _game_id: 1  # type: ignore[method-assign]
            scheduler._is_complete = lambda _game_id, _level: False  # type: ignore[method-assign]
            scheduler._attempt = lambda *_args: setattr(scheduler, "_stop_reason", "timed-out-unsealed") or 1  # type: ignore[method-assign]
            scheduler._record_campaign_attempt = lambda *_args: None  # type: ignore[method-assign]
            result = scheduler.run()

        self.assertEqual(result.stopped_reason, "completed")
        self.assertEqual(result.timed_out_unsealed_level_one, ("a-1",))

    def test_attempt_forwards_runtime_unbounded_marker_for_research_rounds(self) -> None:
        from types import SimpleNamespace
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = SimpleNamespace(returncode=1, communicate=lambda **_kwargs: ("", ""))
            first_round = SweepScheduler(SweepConfig(
                root / "arc", root / "runs", command=("attempt",), guest_machine=None,
                unbounded_first_round=True,
            ))
            second_round = SweepScheduler(SweepConfig(
                root / "arc", root / "runs", command=("attempt",), guest_machine=None,
                unbounded_second_round=True,
            ))
            bounded = SweepScheduler(SweepConfig(
                root / "arc", root / "runs", command=("attempt",), guest_machine=None,
            ))
            with patch("tools.run_prime_p7_sweep.subprocess.Popen", return_value=process) as popen:
                first_round._attempt("a-1", 1, 30 * 60)
                first_environment = popen.call_args.kwargs["env"]
                second_round._attempt("a-1", 2, 30 * 60)
                second_environment = popen.call_args.kwargs["env"]
                bounded._attempt("a-1", 1, 1)
                bounded_environment = popen.call_args.kwargs["env"]

        self.assertEqual(first_environment["ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND"], "1")
        self.assertEqual(first_environment["OPERATION_MODE"], "offline")
        self.assertEqual(first_environment["ASTERION_PRIME_P7_ATTEMPT_SECONDS"], "1830")
        self.assertEqual(second_environment["ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND"], "1")
        self.assertEqual(second_environment["OPERATION_MODE"], "offline")
        self.assertEqual(second_environment["ASTERION_PRIME_P7_ATTEMPT_SECONDS"], "1830")
        self.assertEqual(bounded_environment["ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND"], "")
        self.assertEqual(bounded_environment["OPERATION_MODE"], "")

    def test_make_forwards_first_round_runtime_marker_and_offline_mode(self) -> None:
        makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text(encoding="utf-8")
        recipe = makefile.split("asterion-prime-p7-solve asterion-prime-p7-level-witness asterion-prime-p7-sweep-attempt:\n", 1)[1]
        self.assertIn("ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND", recipe)
        self.assertIn("OPERATION_MODE", recipe)

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
            scheduler._first_round_campaign_is_ready = lambda _games: True  # type: ignore[method-assign]
            scheduler._is_complete = lambda _game_id, _level: False  # type: ignore[method-assign]
            attempts: list[tuple[str, int, float | None]] = []
            scheduler._attempt = lambda game_id, level, timeout: attempts.append((game_id, level, timeout)) or 1  # type: ignore[method-assign]
            scheduler._attempt_result = lambda _game_id, _level: False  # type: ignore[method-assign]
            scheduler._record_campaign_attempt = lambda *_args: None  # type: ignore[method-assign]
            result = scheduler.run()

        self.assertEqual(attempts, [("bp35-2", 1, 30 * 60)])
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
            scheduler._first_round_campaign_is_ready = lambda _games: True  # type: ignore[method-assign]
            scheduler._is_complete = lambda _game_id, _level: False  # type: ignore[method-assign]
            attempts: list[tuple[str, int]] = []
            scheduler._attempt = lambda game_id, level, _timeout: attempts.append((game_id, level)) or 0  # type: ignore[method-assign]
            scheduler._attempt_result = lambda _game_id, _level: True  # type: ignore[method-assign]
            scheduler._record_campaign_attempt = lambda *_args: None  # type: ignore[method-assign]
            result = scheduler.run()

        self.assertEqual(attempts, [("bp35-2", 1)])
        self.assertEqual(result.newly_verified_level_one, ("bp35-2",))

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
