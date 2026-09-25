from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from asterion.applications.prime.p7.failed_attempts import (
    FailedAttemptEvidenceError,
    select_failed_attempt_advice,
)


class FailedAttemptEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runs_root = Path(".asterion-private/prime-p7-live").resolve()
        self.candidates = []
        if self.runs_root.is_dir():
            for run in self.runs_root.iterdir():
                if run.is_symlink() or not run.is_dir():
                    continue
                try:
                    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
                    broker = summary["broker"]
                    sweep = summary["diagnostics"]["sweep"]
                    if (broker["game_id"] == "bp35-0a0ad940" and broker["seed"] == 0
                            and sweep["target_level"] == 1 and broker["terminal_reason"] in
                            {"human-baseline", "game-over", "action-cap"}):
                        self.candidates.append(run)
                except (OSError, KeyError, TypeError, ValueError):
                    continue

    def test_selects_two_sealed_same_game_failures(self) -> None:
        if len(self.candidates) < 2:
            self.skipTest("local BP35 sealed failures are not present")
        advice = select_failed_attempt_advice(
            self.runs_root, game_id="bp35-0a0ad940", seed=0, target_level=1
        )
        self.assertEqual(advice.source_count, 2)
        self.assertEqual(advice.source_run_ids, tuple(sorted((run.name for run in self.candidates if json.loads((run / "summary.json").read_text())["sealed_trace"] and json.loads((run / "summary.json").read_text())["replay_verified"] and json.loads((run / "summary.json").read_text())["cleanup_complete"]), reverse=True)[:2]))
        self.assertEqual(advice.fact_count, sum(len(run.actions) for run in advice.runs))
        self.assertRegex(advice.source_digest, r"^sha256:[0-9a-f]{64}$")

    def test_symlinked_run_is_excluded(self) -> None:
        if not self.candidates:
            self.skipTest("local BP35 sealed failure is not present")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "linked").symlink_to(self.candidates[0], target_is_directory=True)
            advice = select_failed_attempt_advice(
                root, game_id="bp35-0a0ad940", seed=0, target_level=1
            )
            self.assertEqual(advice.source_count, 0)

    def test_malformed_matching_candidate_fails_closed(self) -> None:
        if not self.candidates:
            self.skipTest("local BP35 sealed failure is not present")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "malformed"
            run.mkdir()
            source = self.candidates[0] / "summary.json"
            summary = json.loads(source.read_text(encoding="utf-8"))
            summary["run_id"] = "malformed"
            (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(FailedAttemptEvidenceError):
                select_failed_attempt_advice(root, game_id="bp35-0a0ad940", seed=0, target_level=1)


if __name__ == "__main__":
    unittest.main()
