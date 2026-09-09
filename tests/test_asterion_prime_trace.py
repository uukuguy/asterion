from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from asterion.agents.prime.trace import PrimeTraceError, PrimeTraceRecorder
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
