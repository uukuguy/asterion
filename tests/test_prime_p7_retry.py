"""Focused tests for the one-shot P7 retry controller."""

from __future__ import annotations

import json
from pathlib import Path
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


class TestP7RetryController(unittest.TestCase):
    def setUp(self) -> None:
        _FakeScheduler.instances.clear()

    def test_preflight_only_does_not_load_scheduler_or_model(self) -> None:
        with patch.object(retry, "preflight", return_value={"schema": "x", "ready": True}) as check:
            with patch.object(retry, "_load_sweep_module") as load:
                result = retry.main(["--operator-root", ".", "--arc-root", ".", "--game", "bp35", "--preflight-only"])
        self.assertEqual(result, 0)
        check.assert_called_once()
        load.assert_not_called()

    def test_run_once_attempts_once_records_advice_and_private_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = retry.RetryConfig(root, root, root / "runs", "bp35")
            check = {
                "target_level": 1,
                "source_run_ids": ["old", "new"],
                "source_digest": "sha256:" + "a" * 64,
                "source_count": 2,
                "fact_count": 42,
            }
            metadata = {"game_id": "bp35-0a0ad940", "win_levels": 1}
            metrics = {
                "run_id": "p7-live-new",
                "status": "unsuccessful",
                "action_count": 21,
                "input_tokens": 10,
                "output_tokens": 2,
                "failed_attempt_advice": {
                    "source_run_ids": ["old", "new"],
                    "source_digest": check["source_digest"],
                    "source_count": 2,
                    "fact_count": 42,
                },
            }
            fake_sweep = type("Sweep", (), {"SweepConfig": lambda **kwargs: kwargs, "SweepScheduler": _FakeScheduler})
            with (
                patch.object(retry, "preflight", return_value=check),
                patch.object(retry, "resolve_game", return_value=metadata),
                patch.object(retry, "_load_sweep_module", return_value=fake_sweep),
                patch.object(retry, "_run_metrics", return_value=metrics),
            ):
                result = retry.run_once(config)
            scheduler = _FakeScheduler.instances[0]
            self.assertEqual(scheduler.attempts, [("bp35-0a0ad940", 1, 1800)])
            self.assertEqual(retry.os.environ["ASTERION_PRIME_P7_RETRY_MODE"], "same-game-failed-attempt")
            manifests = tuple((root / "runs" / "retry-manifests").glob("*.json"))
            self.assertEqual(len(manifests), 1)
            self.assertEqual(json.loads(manifests[0].read_text())["breadth_ledger_touched"], False)
            self.assertEqual(result["source_digest"], check["source_digest"])
            self.assertFalse((root / "runs" / "breadth-resweep-campaign.json").exists())

    def test_advice_binding_rejects_changed_source(self) -> None:
        expected = {"source_run_ids": ["one"], "source_digest": "sha256:" + "a" * 64, "source_count": 1, "fact_count": 2}
        observed = dict(expected, source_run_ids=["other"])
        with self.assertRaises(ValueError):
            retry._validate_advice_binding(observed, expected)

    def test_makefile_forwards_exact_retry_marker(self) -> None:
        makefile = (Path(__file__).parents[1] / "Makefile").read_text(encoding="utf-8")
        self.assertIn("ASTERION_PRIME_P7_RETRY_MODE=same-game-failed-attempt", makefile)
        self.assertIn(
            'if [ "$$ASTERION_PRIME_P7_RETRY_MODE" = same-game-failed-attempt ]; then ORBENV=',
            makefile,
        )
        self.assertIn("p7-retry-preflight", makefile)


if __name__ == "__main__":
    unittest.main()
