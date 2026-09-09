from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.comparison import compare_runs


def recorded_run(*, model: str, action: str, outcome: str):
    directory = tempfile.TemporaryDirectory()
    recorder = PrimeTraceRecorder(Path(directory.name))
    identities = {"model_id": model, "reasoning_id": "sol"}
    recorder.append(
        "arc.action",
        identities,
        {
            "action": action,
            "before_sha256": "state-0",
            "after_sha256": "state-1",
            "prompt": "sentinel-secret",
            "code": "private-code",
            "frame": [[1]],
        },
    )
    recorder.append("session.terminal", identities, {"outcome": outcome, "path": "/private/path"})
    recorder.seal()
    entries = recorder.entries
    directory.cleanup()
    return entries


class TestPrimeP7Comparison(unittest.TestCase):
    def test_comparison_normalizes_safe_differential_markers(self) -> None:
        report = compare_runs(
            recorded_run(model="deepseek-r1", action="ACTION1", outcome="action-cap"),
            recorded_run(model="sol", action="ACTION2", outcome="manual-stop-61"),
        )

        self.assertEqual(report.schema, "asterion.prime.p7-differential/v1")
        self.assertEqual(report.left["model_id"], report.left["model_id"])
        self.assertTrue(str(report.left["model_id"]).startswith("sha256:"))
        self.assertEqual(report.right["actions"], ("ACTION2",))
        self.assertEqual(report.right["outcome"], "manual-stop-61")
        self.assertNotIn("official_failure", report.deltas)

    def test_public_differential_never_serializes_private_trace_data(self) -> None:
        report = compare_runs(
            recorded_run(model="sentinel-secret", action="ACTION1", outcome="action-cap"),
            recorded_run(model="sol", action="ACTION2", outcome="manual-stop-61"),
        )

        public = json.dumps(asdict(report), sort_keys=True)
        for private in ("sentinel-secret", "private-code", "/private/path", "[[1]]"):
            self.assertNotIn(private, public)
