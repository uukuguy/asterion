"""Focused tests for the one-shot P7 retry controller."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import run_prime_p7_retry as retry


class _FakeScheduler:
    instances: list["_FakeScheduler"] = []

    def __init__(self, config) -> None:
        self.config = config
        self._new_runs = []
        self._stop_reason = "completed"
        self.attempts = []
        self.__class__.instances.append(self)

    def _attempt(self, game_id, level, timeout):
        self.attempts.append((game_id, level, timeout))
        self._new_runs.append("p7-live-new")


class _FakePrefix:
    def __init__(self, game_id: str, levels_completed: int, transitions: tuple) -> None:
        self.game_id = game_id
        self.levels_completed = levels_completed
        self.transitions = transitions


class TestP7RetryController(unittest.TestCase):
    def setUp(self) -> None:
        _FakeScheduler.instances.clear()

    def test_preflight_only_does_not_load_scheduler_or_model(self) -> None:
        with patch.object(retry, "preflight", return_value={"schema": "x", "ready": True}) as check:
            with patch.object(retry, "_load_sweep_module") as load:
                result = retry.main([
                    "--operator-root", ".", "--arc-root", ".", "--game", "bp35", "--preflight-only",
                ])
        self.assertEqual(result, 0)
        check.assert_called_once()
        load.assert_not_called()

    def test_run_once_attempts_once_writes_prefix_replay_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = retry.RetryConfig(root, root, root / "runs", "bp35")
            check = {"target_level": 1, "prefix_actions": 21}
            metadata = {"game_id": "bp35-0a0ad940", "win_levels": 1}
            metrics = {
                "run_id": "p7-live-new",
                "status": "unsuccessful",
                "action_count": 21,
                "input_tokens": 10,
                "output_tokens": 2,
            }
            fake_prefix = _FakePrefix(
                "bp35-0a0ad940", 0, transitions=tuple(range(21)),
            )
            fake_sweep = type("Sweep", (), {
                "SweepConfig": lambda **kwargs: kwargs, "SweepScheduler": _FakeScheduler,
            })
            with (
                patch.object(retry, "preflight", return_value=check),
                patch.object(retry, "resolve_game", return_value=metadata),
                patch.object(retry, "_probe_guest"),
                patch.object(retry, "_load_sweep_module", return_value=fake_sweep),
                patch.object(retry, "_run_metrics", return_value=metrics),
                patch.object(
                    retry, "load_best_prefix", return_value=fake_prefix,
                ),
                patch.object(
                    retry, "_safe_summary",
                    return_value={
                        "diagnostics": {"sweep": {"prefix_actions": 21}},
                    },
                ),
            ):
                result = retry.run_once(config)
            self.assertEqual(fake_prefix.levels_completed, 0)
            scheduler = _FakeScheduler.instances[0]
            self.assertEqual(scheduler.attempts, [("bp35-0a0ad940", 1, 1800)])
            self.assertNotIn("ASTERION_PRIME_P7_RETRY_MODE", retry.os.environ)
            manifests = tuple((root / "runs" / "retry-manifests").glob("*.json"))
            self.assertEqual(len(manifests), 1)
            body = json.loads(manifests[0].read_text())
            self.assertEqual(body["breadth_ledger_touched"], False)
            self.assertEqual(body["prefix_actions"], 21)
            self.assertNotIn("source_digest", body)
            self.assertNotIn("failed_attempt_advice", body)
            self.assertFalse((root / "runs" / "breadth-resweep-campaign.json").exists())
            self.assertEqual(result["prefix_actions"], 21)

    def test_prefix_replay_validation_rejects_mismatched_count(self) -> None:
        fake_prefix = _FakePrefix(
            "bp35-0a0ad940", 0, transitions=tuple(range(20)),
        )
        with tempfile.TemporaryDirectory() as directory:
            runs_root = Path(directory) / "runs"
            run_id = "p7-live-new"
            (runs_root / run_id).mkdir(parents=True)
            (runs_root / run_id / "summary.json").write_text(json.dumps({
                "diagnostics": {"sweep": {"prefix_actions": 21}},
            }))
            with self.assertRaises(ValueError):
                retry._validate_prefix_replay(
                    runs_root, run_id, "bp35-0a0ad940", 0, 1,
                )
            self.assertEqual(len(fake_prefix.transitions), 20)

    def test_guest_probe_stops_before_scheduler_on_timeout(self) -> None:
        config = retry.RetryConfig(Path("/tmp"), Path("/tmp"), Path("/tmp"), "bp35", guest_machine="ubuntu")
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(["orb"], 20)) as run:
            with self.assertRaisesRegex(ValueError, "P7 guest is unavailable"):
                retry._probe_guest(config)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][-1], "/bin/true")

    def test_makefile_does_not_set_retry_marker(self) -> None:
        makefile = (Path(__file__).parents[1] / "Makefile").read_text(encoding="utf-8")
        self.assertNotIn("ASTERION_PRIME_P7_RETRY_MODE", makefile)
        self.assertIn("p7-retry-preflight", makefile)


if __name__ == "__main__":
    unittest.main()