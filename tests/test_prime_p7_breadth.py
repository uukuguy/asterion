from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest


class TestPrimeP7Breadth(unittest.TestCase):
    def test_preflight_selects_unverified_l1_and_exact_l1_prefixes_for_l2(self) -> None:
        from tools.run_prime_p7_breadth import BreadthCampaignConfig, BreadthCampaignController

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = BreadthCampaignController(BreadthCampaignConfig(
                root / "arc", root / "runs", root, root, guest_machine=None,
            ))
            controller._catalog = lambda: (
                {"game_id": "aa11-00000000", "baseline_actions": (5, 7), "win_levels": 2},
                {"game_id": "bb22-00000000", "baseline_actions": (6, 8), "win_levels": 2},
                {"game_id": "cc33-00000000", "baseline_actions": (4, 9), "win_levels": 2},
            )
            controller._best_prefix = lambda game: {
                "aa11-00000000": None,
                "bb22-00000000": SimpleNamespace(levels_completed=1),
                "cc33-00000000": SimpleNamespace(levels_completed=2),
            }[game]
            data = controller.preflight()

        self.assertEqual(data["schema"], "asterion.prime.p7-breadth-preflight/v1")
        self.assertEqual(data["level_one"], ["aa11-00000000"])
        self.assertEqual(data["level_two"], ["bb22-00000000"])
        self.assertEqual(data["already_verified_level_two"], ["cc33-00000000"])

    def test_preflight_cli_never_runs_attempts(self) -> None:
        from tools.run_prime_p7_breadth import BreadthCampaignController, main

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            BreadthCampaignController, "preflight",
            return_value={"schema": "asterion.prime.p7-breadth-preflight/v1", "level_one": [], "level_two": []},
        ), patch.object(BreadthCampaignController, "run") as run, contextlib.redirect_stdout(output):
            result = main(["--operator-root", directory, "--arc-root", directory, "--preflight-only"])

        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["schema"], "asterion.prime.p7-breadth-preflight/v1")
        run.assert_not_called()

    def test_running_entry_requires_manual_audit_and_does_not_retry(self) -> None:
        from tools.run_prime_p7_breadth import BreadthCampaignConfig, BreadthCampaignController

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = root / "runs"
            runs.mkdir(exist_ok=True)
            (runs / "breadth-resweep-campaign.json").write_text(json.dumps({
                "schema": "asterion.prime.p7-breadth-campaign/v1",
                "campaign_id": "breadth-resweep-" + "a" * 32,
                "seed": 0, "run_timeout_seconds": 1800, "no_action_stall_seconds": 300,
                "terminal_attempts": [{
                    "status": "running", "game_id": "aa11-00000000", "target_level": 1,
                    "run_id": "run-aa",
                }],
            }), encoding="utf-8")
            controller = BreadthCampaignController(BreadthCampaignConfig(
                root / "arc", runs, root, root, guest_machine=None,
            ))
            with patch.object(controller, "_attempt_pair") as attempt:
                result = controller.run()

        self.assertEqual(result.stopped_reason, "breadth-running-entry-requires-audit")
        attempt.assert_not_called()

    def test_reconcile_marks_interrupted_run_without_calling_model(self) -> None:
        import tools.run_prime_p7_breadth as breadth
        from tools.run_prime_p7_breadth import BreadthCampaignConfig, BreadthCampaignController

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = root / "runs"
            run = runs / ("p7-live-20260925132710-" + "d" * 32)
            (run / "trace").mkdir(parents=True)
            recording = run / "recordings" / "session"
            recording.mkdir(parents=True)
            (recording / "game.jsonl").write_text(
                json.dumps({"timestamp": "2026-09-25T13:27:11+00:00", "data": {"game_id": "aa11-00000000"}}) + "\n",
                encoding="utf-8",
            )
            ledger = {
                "schema": "asterion.prime.p7-breadth-campaign/v1",
                "campaign_id": "breadth-resweep-" + "c" * 32,
                "seed": 0, "run_timeout_seconds": 1800, "no_action_stall_seconds": 300,
                "terminal_attempts": [{
                    "status": "running", "game_id": "aa11-00000000", "target_level": 1,
                    "started_at": "2026-09-25T13:27:04+00:00",
                }],
            }
            runs.mkdir(exist_ok=True)
            (runs / "breadth-resweep-campaign.json").write_text(json.dumps(ledger), encoding="utf-8")
            controller = BreadthCampaignController(BreadthCampaignConfig(root / "arc", runs, root, root, guest_machine=None))
            rows = (
                {"identities": breadth.P7_TRACE_IDENTITIES, "kind": "arc.action", "payload": {}, "sha256": "sha256:" + "b" * 64},
            )
            with patch.object(controller, "_metadata", return_value={"aa11-00000000": {"baseline_actions": (5,)}}), \
                 patch.object(controller, "_interrupted_run_candidates", return_value=(run,)), \
                 patch.object(breadth, "_read_hash_chained_trace", return_value=rows), \
                 patch.object(breadth, "read_run_usage", return_value=(3, 4, False, False)), \
                 patch.object(breadth, "_recorded_game_id", return_value="aa11-00000000"):
                result = controller.reconcile_running(guest_cleanup_confirmed=True)

            self.assertEqual(result["outcome"], "interrupted")
            saved = json.loads((runs / "breadth-resweep-campaign.json").read_text())
            self.assertEqual(saved["terminal_attempts"][0]["status"], "interrupted")
            self.assertEqual(saved["terminal_attempts"][0]["run_id"], run.name)

    def test_atomic_ledger_is_private_and_preflight_does_not_create_it(self) -> None:
        from tools.run_prime_p7_breadth import BreadthCampaignConfig, BreadthCampaignController

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = BreadthCampaignController(BreadthCampaignConfig(
                root / "arc", root / "runs", root, root, guest_machine=None,
            ))
            controller._catalog = lambda: ()
            controller.preflight()
            self.assertFalse((root / "runs" / "breadth-resweep-campaign.json").exists())
            ledger = controller._load_or_create_ledger()
            self.assertEqual(ledger["schema"], "asterion.prime.p7-breadth-campaign/v1")
            self.assertEqual((root / "runs" / "breadth-resweep-campaign.json").stat().st_mode & 0o777, 0o600)

    def test_real_scheduler_uses_research_mode_with_uncapped_budget(self) -> None:
        from tools.run_prime_p7_breadth import BreadthCampaignConfig, BreadthCampaignController

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = BreadthCampaignController(BreadthCampaignConfig(
                root / "arc", root / "runs", root, root,
            ))
            level_one = controller._make_scheduler(1)
            level_two = controller._make_scheduler(2)

        self.assertTrue(level_one.config.unbounded_first_round)
        self.assertFalse(level_one.config.unbounded_second_round)
        self.assertTrue(level_two.config.unbounded_second_round)
        self.assertFalse(level_two.config.unbounded_first_round)
        self.assertIsNone(level_one.config.global_token_cap)
        self.assertIsNone(level_one.config.wallclock_cap)

    def test_run_finishes_level_one_queue_before_recomputing_level_two(self) -> None:
        from tools.run_prime_p7_breadth import BreadthCampaignConfig, BreadthCampaignController

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = BreadthCampaignController(BreadthCampaignConfig(
                root / "arc", root / "runs", root, root, guest_machine=None,
            ))
            controller._catalog = lambda: (
                {"game_id": "aa11-00000000", "baseline_actions": (5, 7), "win_levels": 2},
                {"game_id": "bb22-00000000", "baseline_actions": (6, 8), "win_levels": 2},
            )
            progress = {"aa11-00000000": 0, "bb22-00000000": 1}
            calls: list[tuple[str, int]] = []
            controller._best_prefix = lambda game: (
                None if progress[game] == 0 else SimpleNamespace(levels_completed=progress[game])
            )

            def attempt(_ledger: dict, game: str, level: int) -> dict:
                calls.append((game, level))
                progress[game] = level
                return {"attempted": 1, "verified": True, "runs": (), "input_tokens": 0,
                        "output_tokens": 0, "stop_reason": "completed"}

            controller._attempt_pair = attempt
            result = controller.run()

        self.assertEqual(calls, [("aa11-00000000", 1), ("aa11-00000000", 2), ("bb22-00000000", 2)])
        self.assertEqual(result.newly_verified_level_one, ("aa11-00000000",))
        self.assertEqual(result.newly_verified_level_two, ("aa11-00000000", "bb22-00000000"))

    def test_terminal_pair_is_deduplicated_on_resume(self) -> None:
        from tools.run_prime_p7_breadth import BreadthCampaignConfig, BreadthCampaignController

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = root / "runs"
            runs.mkdir()
            ledger = {
                "schema": "asterion.prime.p7-breadth-campaign/v1",
                "campaign_id": "breadth-resweep-" + "b" * 32,
                "seed": 0, "run_timeout_seconds": 1800, "no_action_stall_seconds": 300,
                "terminal_attempts": [{
                    "game_id": "aa11-00000000", "target_level": 2, "run_id": "run-aa",
                    "outcome": "verified", "action_count": 5, "input_tokens": 3,
                    "output_tokens": 4, "stop_reason": "completed", "evidence_sha256": "sha256:" + "a" * 64,
                }],
            }
            (runs / "breadth-resweep-campaign.json").write_text(json.dumps(ledger), encoding="utf-8")
            controller = BreadthCampaignController(BreadthCampaignConfig(
                root / "arc", runs, root, root, guest_machine=None,
            ))
            controller._terminal_entry_is_valid = lambda _entry: True
            controller._catalog = lambda: ({"game_id": "aa11-00000000", "baseline_actions": (5, 7), "win_levels": 2},)
            controller._best_prefix = lambda _game: SimpleNamespace(levels_completed=1)
            with patch.object(controller, "_attempt_pair") as attempt:
                result = controller.run()

        self.assertEqual(result.attempted, 0)
        attempt.assert_not_called()

    def test_verified_entry_uses_its_run_after_a_later_prefix_exists(self) -> None:
        import tools.run_prime_p7_breadth as breadth
        from tools.run_prime_p7_breadth import BreadthCampaignConfig, BreadthCampaignController

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "runs" / "run-l1"
            (run / "trace").mkdir(parents=True)
            (run / "trace" / "prime-trace.jsonl").write_text("trace\n", encoding="utf-8")
            controller = BreadthCampaignController(BreadthCampaignConfig(
                root / "arc", root / "runs", root, root, guest_machine=None,
            ))
            controller._metadata = lambda: {
                "aa11-00000000": {"baseline_actions": (5, 7), "win_levels": 2},
            }
            controller._best_prefix = lambda _game: (_ for _ in ()).throw(AssertionError("used global best prefix"))
            entry = {
                "game_id": "aa11-00000000", "target_level": 1, "run_id": "run-l1",
                "outcome": "verified", "action_count": 1, "input_tokens": 3,
                "output_tokens": 4, "stop_reason": "completed", "evidence_sha256": "sha256:" + "a" * 64,
            }
            rows = (
                {"identities": breadth.P7_TRACE_IDENTITIES, "kind": "arc.action", "payload": {}, "sha256": "sha256:" + "b" * 64},
                {"identities": breadth.P7_TRACE_IDENTITIES, "kind": "trace.sealed", "payload": {}, "sha256": "sha256:" + "a" * 64},
            )
            with patch.object(breadth, "_read_hash_chained_trace", return_value=rows), \
                 patch.object(breadth, "read_run_usage", return_value=(3, 4, False, False)), \
                 patch.object(breadth, "_recorded_game_id", return_value="aa11-00000000"), \
                 patch.object(breadth, "_valid_attempt_summary", return_value=True), \
                 patch.object(breadth, "_load_one", return_value=SimpleNamespace(source_run_id="run-l1", levels_completed=1)):
                self.assertTrue(controller._terminal_entry_is_valid(entry))


if __name__ == "__main__":
    unittest.main()
