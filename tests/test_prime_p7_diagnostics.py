from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.diagnostics import analyze_trace


def noop_then_life_loss_trace():
    directory = tempfile.TemporaryDirectory()
    recorder = PrimeTraceRecorder(Path(directory.name))
    identities = {"model_id": "deepseek-r1", "reasoning_id": "sol"}
    for sequence in range(3):
        recorder.append(
            "arc.action",
            identities,
            {
                "action": "ACTION1",
                "before_sha256": "state-0",
                "after_sha256": "state-0",
                "information_gain": 0.0,
            },
        )
    recorder.append(
        "arc.action",
        identities,
        {
            "action": "ACTION2",
            "before_sha256": "state-0",
            "after_sha256": "state-1",
            "resource_reset": True,
            "information_gain": 1.0,
        },
    )
    recorder.append("hypothesis.contradicted", identities, {"hypothesis": "private"})
    recorder.seal()
    entries = recorder.entries
    directory.cleanup()
    return entries


class TestPrimeP7Diagnostics(unittest.TestCase):
    def test_repeated_noop_and_resource_reset_are_labeled(self) -> None:
        report = analyze_trace(noop_then_life_loss_trace())

        self.assertGreaterEqual(report.repeated_action_streak, 3)
        self.assertEqual(report.no_op_streak, 3)
        self.assertEqual(report.deaths, 1)
        self.assertEqual(report.contradicted_hypotheses, 1)
        self.assertEqual(report.experiment_information_gain, (0.0, 0.0, 0.0, 1.0))

    def test_analysis_is_deterministic_and_does_not_expose_private_payload(self) -> None:
        entries = noop_then_life_loss_trace()
        self.assertEqual(analyze_trace(entries), analyze_trace(entries))
        self.assertNotIn("private", repr(analyze_trace(entries)))
