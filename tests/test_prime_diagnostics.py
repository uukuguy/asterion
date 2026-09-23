from __future__ import annotations

from types import SimpleNamespace
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime.p3.operator import _drive_success, run_success_path
from asterion.services.diagnostics import MemoryDiagnosticSink


class _Runner:
    async def admit_child(self, **kwargs):
        return SimpleNamespace(child_run_id="child-1")

    def record_child_cost(self, *args, **kwargs):
        pass


class _Oracle:
    def check(self, **kwargs):
        raise RuntimeError("PRIVATE-ORACLE-PAYLOAD")


class TestPrimeStageDiagnostics(unittest.IsolatedAsyncioTestCase):
    def resources(self, sink):
        return SimpleNamespace(
            root_run_id="root-1",
            root_identity=SimpleNamespace(generation=1),
            child_identity=SimpleNamespace(generation=2),
            mode="success",
            child_runner=_Runner(),
            p3_oracle=_Oracle(),
            diagnostics=sink,
        )

    async def test_worker_failure_captures_stage_without_payload(self):
        sink = MemoryDiagnosticSink()
        with patch(
            "asterion.applications.prime.p3.operator._fake_worker_payload_sha",
            side_effect=RuntimeError("PRIVATE-WORKER-PAYLOAD"),
        ):
            with self.assertRaises(RuntimeError):
                await _drive_success(self.resources(sink))
        records = list(sink._records.values())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].stage, "prime.worker")
        self.assertNotIn("PRIVATE-WORKER-PAYLOAD", repr(records[0]))

    async def test_oracle_failure_captures_stage_without_payload(self):
        sink = MemoryDiagnosticSink()
        with self.assertRaises(RuntimeError):
            await _drive_success(self.resources(sink))
        records = list(sink._records.values())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].stage, "prime.oracle")
        self.assertNotIn("PRIVATE-ORACLE-PAYLOAD", repr(records[0]))


class TestP3OperatorDiagnosticInjection(unittest.TestCase):
    def test_worker_failure_is_private_and_public_result_is_empty(self):
        sink = MemoryDiagnosticSink()
        with tempfile.TemporaryDirectory() as temporary:
            environment = {
                "ASTERION_PRIME_OPERATOR_ROOT": str(Path.cwd()),
                "ASTERION_PRIME_P3_PRIVATE_ROOT": str(Path(temporary) / "private"),
                "ASTERION_PRIME_P3_MODE": "success",
            }
            output = io.StringIO()
            with patch(
                "asterion.applications.prime.p3.operator._fake_worker_payload_sha",
                side_effect=RuntimeError("PRIVATE-WORKER-PAYLOAD"),
            ), redirect_stdout(output):
                result = run_success_path(environment, diagnostics=sink)
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(), "")
        records = list(sink._records.values())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].stage, "prime.worker")
        self.assertNotIn("PRIVATE-WORKER-PAYLOAD", repr(records[0]))
