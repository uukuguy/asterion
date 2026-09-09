from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from asterion.agents.prime.trace import PrimeTraceRecorder
from tools.compare_prime_p7_runs import build_parser as build_compare_parser
from tools.compare_prime_p7_runs import main as compare_main
from tools.run_asterion_prime_p7 import (
    LiveSolveError,
    P7LiveExecution,
    build_parser,
    classify_live_result,
)


def _sealed_trace(path: Path, *, outcome: str, action_count: int = 1) -> Path:
    trace_root = path / outcome
    trace_root.mkdir()
    recorder = PrimeTraceRecorder(trace_root)
    identities = {"model_id": "deepseek-v4-flash", "reasoning_id": "asterion.prime"}
    for index in range(action_count):
        recorder.append(
            "arc.action",
            identities,
            {
                "action": "ACTION1",
                "before_sha256": "sha256:" + f"{index:064x}"[-64:],
                "after_sha256": "sha256:" + f"{index + 1:064x}"[-64:],
                "levels_completed": 0,
            },
        )
    recorder.append("session.terminal", identities, {"outcome": outcome})
    recorder.seal()
    return trace_root / "prime-trace.jsonl"


class TestPrimeP7LiveCommand(unittest.TestCase):
    def test_live_command_exposes_no_tuning_knobs(self) -> None:
        parser = build_parser()

        self.assertEqual(type(parser), argparse.ArgumentParser)
        self.assertEqual(sorted(action.dest for action in parser._actions), ["help"])

    def test_success_requires_authoritative_level_transition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = P7LiveExecution(
                run_id="p7-live-test",
                completed_level_count=0,
                primitive_action_count=13,
                replay_verified=True,
                sealed_trace=True,
                cleanup_complete=True,
                trace_root=Path(directory),
                receipt={},
                comparison_report=None,
            )

            with self.assertRaisesRegex(LiveSolveError, "level transition"):
                classify_live_result(result)

    def test_success_requires_replay_trace_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for field in ("replay_verified", "sealed_trace", "cleanup_complete"):
                values = {
                    "run_id": "p7-live-test",
                    "completed_level_count": 1,
                    "primitive_action_count": 13,
                    "replay_verified": True,
                    "sealed_trace": True,
                    "cleanup_complete": True,
                    "trace_root": Path(directory),
                    "receipt": {},
                    "comparison_report": None,
                }
                values[field] = False
                with self.subTest(field=field):
                    with self.assertRaises(LiveSolveError):
                        classify_live_result(P7LiveExecution(**values))

    def test_compare_cli_labels_operator_stopped_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asterion = _sealed_trace(root, outcome="level-completed", action_count=2)
            baseline = _sealed_trace(root, outcome="operator-stopped", action_count=3)
            output = root / "report.json"

            status = compare_main(
                [
                    "--asterion",
                    str(asterion),
                    "--baseline",
                    str(baseline),
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(status, 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["baseline_label"], "operator-stopped")
            self.assertEqual(report["schema"], "asterion.prime.p7-live-comparison/v1")
            self.assertEqual(report["comparison"]["right"]["outcome"], "operator-stopped")
            self.assertNotIn("private", json.dumps(report, sort_keys=True))

    def test_compare_parser_requires_only_three_paths(self) -> None:
        parser = build_compare_parser()

        self.assertEqual(
            sorted(action.dest for action in parser._actions),
            ["asterion", "baseline", "help", "output"],
        )


if __name__ == "__main__":
    unittest.main()
