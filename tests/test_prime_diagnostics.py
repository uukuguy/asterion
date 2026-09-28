from __future__ import annotations

from types import SimpleNamespace
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime.p3.operator import _drive_success, run_success_path
from asterion.runtime.protocol import ProtocolError
from asterion.services.diagnostics import MemoryDiagnosticSink, capture_failure


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


class TestFailureCodeDiagnostics(unittest.TestCase):
    def test_protocol_failure_code_is_bounded_without_message(self) -> None:
        sink = MemoryDiagnosticSink()
        diagnostic_id = capture_failure(
            sink,
            stage="capability.execute",
            error=ProtocolError("Pi runtime provider execution failed"),
            subject_id="run-1",
        )
        self.assertIsNotNone(diagnostic_id)
        record = sink.get(diagnostic_id)
        self.assertEqual(record.failure_code, "pi-provider-execution")
        self.assertNotIn("Pi runtime provider execution failed", repr(record))

    def test_prime_protocol_failure_codes_are_bounded(self) -> None:
        cases = {
            "Asterion-prime transport protocol failed": "prime-transport-protocol",
            "Asterion-prime native result is malformed": "prime-native-result",
            "Asterion-prime native terminal is invalid": "prime-native-terminal",
            "Asterion-prime continuation is invalid": "prime-continuation",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                sink = MemoryDiagnosticSink()
                diagnostic_id = capture_failure(
                    sink,
                    stage="capability.execute",
                    error=ProtocolError(message),
                    subject_id="run-1",
                )
                assert diagnostic_id is not None
                record = sink.get(diagnostic_id)
                self.assertEqual(record.failure_code, expected)
                self.assertNotIn(message, repr(record))

    def test_native_callback_rejection_has_bounded_failure_code(self) -> None:
        sink = MemoryDiagnosticSink()
        callback_rejected = type("_CallbackRejected", (Exception,), {})
        diagnostic_id = capture_failure(
            sink,
            stage="pi.prompt",
            error=callback_rejected("PRIVATE-CALLBACK-PAYLOAD"),
            subject_id="run-1",
        )
        assert diagnostic_id is not None
        record = sink.get(diagnostic_id)
        self.assertEqual(record.failure_code, "prime-native-callback")
        self.assertNotIn("PRIVATE-CALLBACK-PAYLOAD", repr(record))

    def test_native_callback_rejection_reason_is_bounded(self) -> None:
        sink = MemoryDiagnosticSink()
        callback_rejected = type("_CallbackRejected", (Exception,), {})
        error = callback_rejected()
        error.failure_code = "Asterion-prime native event is invalid"
        diagnostic_id = capture_failure(
            sink,
            stage="pi.prompt",
            error=error,
            subject_id="run-1",
        )
        assert diagnostic_id is not None
        record = sink.get(diagnostic_id)
        self.assertEqual(record.failure_code, "prime-native-event")
        self.assertNotIn("Asterion-prime native event is invalid", repr(record))
