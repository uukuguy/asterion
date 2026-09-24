from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import sleep
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path

from asterion.agents.prime.trace import (
    PrimeTraceEntry, PrimeTraceError, PrimeTraceRecorder, validate_trace,
)
from asterion.applications.prime.p7.diagnostics import analyze_trace


class TestPrimeTraceRecorder(unittest.TestCase):
    def test_trace_is_contiguous_and_hash_chained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            identities = {"model_id": "deepseek-r1", "reasoning_id": "sol"}

            first = recorder.append("session.started", identities, {})
            second = recorder.append("arc.action", identities, {"action": "ACTION1"})

            self.assertEqual(second.sequence, first.sequence + 1)
            self.assertEqual(second.previous_sha256, first.sha256)
            self.assertNotIn("ACTION1", repr(second))

    def test_seal_prevents_append_and_public_seal_redacts_private_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            identities = {"model_id": "deepseek-r1", "reasoning_id": "sol"}
            recorder.append(
                "model.prompt",
                identities,
                {"prompt": "sentinel-secret", "code": "private-code", "path": "/private/path"},
            )

            seal = recorder.seal()

            public = json.dumps({"seal": seal.__dict__ if hasattr(seal, "__dict__") else {
                "entry_count": seal.entry_count,
                "final_sha256": seal.final_sha256,
                "sealed_at": seal.sealed_at,
            }}, sort_keys=True)
            self.assertNotIn("sentinel-secret", public)
            self.assertNotIn("private-code", public)
            self.assertNotIn("/private/path", public)
            with self.assertRaises(PrimeTraceError):
                recorder.append("arc.action", identities, {})

    def test_rejects_identity_change_and_non_json_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            recorder.append("session.started", {"model_id": "one"}, {})
            with self.assertRaises(PrimeTraceError):
                recorder.append("arc.action", {"model_id": "two"}, {})
            with self.assertRaises(PrimeTraceError):
                recorder.append("arc.action", {"model_id": "one"}, {"value": object()})

    def test_analysis_requires_the_final_seal_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            identities = {"model_id": "deepseek-r1", "reasoning_id": "sol"}
            recorder.append("arc.action", identities, {"action": "ACTION1"})
            with self.assertRaises(PrimeTraceError):
                analyze_trace(recorder.snapshot())

            recorder.seal()
            sealed = recorder.entries
            self.assertEqual(sealed[-1].kind, "trace.sealed")
            self.assertEqual(recorder.seal().final_sha256, sealed[-1].sha256)
            with self.assertRaises(PrimeTraceError):
                analyze_trace(sealed[:-1] + (replace(sealed[-1], payload={}),))

    def test_concurrent_actions_usage_and_sealing_preserve_disk_chain(self) -> None:
        # Disk I/O releases the GIL: force overlap at the historical race boundary.
        original_write = PrimeTraceRecorder._write_descriptor

        def slow_write(descriptor: int, payload: object) -> None:
            sleep(0.002)
            original_write(descriptor, payload)

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            identities = {"model_id": "one"}
            start = Barrier(8)

            def append_events(worker: int) -> None:
                start.wait(timeout=5)
                for index in range(5):
                    recorder.append(
                        "arc.action" if worker % 2 else "runtime.usage",
                        identities,
                        {"worker": worker, "index": index},
                    )

            with patch.object(PrimeTraceRecorder, "_write_descriptor", staticmethod(slow_write)):
                with ThreadPoolExecutor(max_workers=8) as executor:
                    list(executor.map(append_events, range(8)))
                self.assertEqual(
                    [entry.sequence for entry in recorder.snapshot()],
                    list(range(1, 41)),
                )
                # Sealing from multiple shutdown paths must publish just one marker.
                def seal_trace(_: int):
                    start.wait(timeout=5)
                    return recorder.seal()

                with ThreadPoolExecutor(max_workers=8) as executor:
                    seals = list(executor.map(seal_trace, range(8)))

            self.assertTrue(all(seal == seals[0] for seal in seals))
            self.assertEqual(seals[0].entry_count, 41)
            disk_entries = tuple(
                PrimeTraceEntry(**json.loads(line))
                for line in (Path(directory) / "prime-trace.jsonl").read_text().splitlines()
            )
            self.assertEqual(validate_trace(disk_entries), recorder.entries)
            self.assertEqual(len({
                (entry.payload["worker"], entry.payload["index"])
                for entry in disk_entries[:-1]
            }), 40)
            self.assertEqual(
                json.loads((Path(directory) / "prime-trace.seal.json").read_text())["final_sha256"],
                disk_entries[-1].sha256,
            )
