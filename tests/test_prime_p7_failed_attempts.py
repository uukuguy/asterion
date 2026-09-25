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

    def test_partial_level_two_is_scoped_to_verified_prefix(self) -> None:
        advice = select_failed_attempt_advice(
            self.runs_root, game_id="bp35-0a0ad940", seed=0, target_level=2
        )
        if not advice.source_count:
            self.skipTest("local BP35 level-two partial evidence is not present")
        self.assertEqual(advice.runs[0].source_type, "sealed-partial-failure")
        self.assertGreater(advice.runs[0].prefix_action_count, 0)
        self.assertLess(advice.runs[0].prefix_action_count, advice.runs[0].action_count)
        self.assertTrue(advice.runs[0].evidence_digest.startswith("sha256:"))

    def test_stall_is_admitted_as_observation(self) -> None:
        try:
            advice = select_failed_attempt_advice(
                self.runs_root, game_id="cd82-fb555c5d", seed=0, target_level=2
            )
        except FailedAttemptEvidenceError:
            self.skipTest("local CD82 stall evidence is not present")
        if not advice.source_count:
            self.skipTest("local CD82 stall evidence is not present")
        self.assertEqual(advice.runs[0].source_type, "execution-stall-observation")
        self.assertEqual(advice.runs[0].terminal_reason, "execution-stalled")
        self.assertTrue(advice.runs[0].evidence_digest.startswith("sha256:"))

    def test_stall_for_another_target_level_is_not_selected(self) -> None:
        advice = select_failed_attempt_advice(
            self.runs_root, game_id="cd82-fb555c5d", seed=0, target_level=3
        )
        self.assertEqual(advice.source_count, 0)


if __name__ == "__main__":
    unittest.main()
