from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class TestRunObservationLog(unittest.TestCase):
    def test_records_safe_events_and_public_snapshot(self) -> None:
        from asterion.runtime.observation import RunObservationLog

        with tempfile.TemporaryDirectory() as directory:
            log = RunObservationLog(Path(directory), "run-1")
            log.record("run.started")
            log.record("run.phase", {"phase": "prime.sidecar"})
            log.record("run.heartbeat", {"phase": "prime.rlm", "elapsed_seconds": "5"})
            snapshot = log.terminal("external-limited", "checkpoint_lifecycle")

            self.assertEqual(snapshot["status"], "external-limited")
            self.assertEqual(snapshot["last_sequence"], 4)
            events = [json.loads(line) for line in (Path(directory) / "run-1.events.jsonl").read_text().splitlines()]
            self.assertEqual(
                [event["type"] for event in events],
                ["run.started", "run.phase", "run.heartbeat", "run.terminal"],
            )

    def test_rejects_private_or_unknown_payload(self) -> None:
        from asterion.runtime.observation import RunObservationError, RunObservationLog

        with tempfile.TemporaryDirectory() as directory:
            log = RunObservationLog(Path(directory), "run-1")
            with self.assertRaises(RunObservationError):
                log.record("run.phase", {"prompt": "secret"})

    def test_resumes_sequence_from_a_valid_existing_log(self) -> None:
        from asterion.runtime.observation import RunObservationLog

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = RunObservationLog(root, "run-1")
            first.record("run.started")
            second = RunObservationLog(root, "run-1")
            event = second.record("run.phase", {"phase": "prime.rlm"})

        self.assertEqual(event["sequence"], 2)
