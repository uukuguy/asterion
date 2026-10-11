from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime.p3.operator import _drive_success, run_success_path
from asterion.runtime.protocol import ProtocolError
from asterion.services.diagnostics import (
    FailureDiagnostic, FailureMetadata, LimitDiagnostic, MemoryDiagnosticSink,
    ResourceLimitExceeded, capture_failure, capture_limit, limit_diagnostic,
)


class TestLimitDiagnostics(unittest.TestCase):
    def diagnostic(self):
        return LimitDiagnostic("compaction-token-limit", "admission", "rejected",
            48001, 48000, "tokens", "estimate", "authority")

    def test_safe_capture_and_typed_cause(self):
        sink = MemoryDiagnosticSink()
        wrapper = RuntimeError("PRIVATE-PROMPT-CREDENTIAL-PATH")
        wrapper.__cause__ = ResourceLimitExceeded(self.diagnostic())
        wrapper.failure_metadata = FailureMetadata()
        identity = capture_failure(sink, stage="prime.compaction", error=wrapper,
            subject_id="PRIVATE-SESSION-ID", capability_ref="PRIVATE-CAPABILITY")
        record = sink.get(identity)
        self.assertEqual(record.limit_diagnostic, self.diagnostic())
        self.assertEqual(record.failure_code, "compaction-token-limit")
        self.assertNotIn("PRIVATE", repr(record))

    def test_no_sink_and_failed_sink_do_not_replace_reason(self):
        class Broken:
            def record(self, value):
                raise RuntimeError("PRIVATE-SINK")
        for sink in (None, Broken()):
            with self.subTest(sink=type(sink).__name__):
                self.assertIsNone(capture_limit(sink, stage="prime.compaction",
                    diagnostic=self.diagnostic(), subject_id="operation-1"))
        error = ResourceLimitExceeded(self.diagnostic())
        self.assertEqual(str(error), "resource limit exceeded")
        self.assertEqual(error.failure_code, "compaction-token-limit")
        self.assertIsInstance(error, ValueError)

    def test_capture_limit_records_same_typed_diagnostic(self):
        sink = MemoryDiagnosticSink()
        identity = capture_limit(sink, stage="prime.compaction",
            diagnostic=self.diagnostic(), subject_id="operation-1")
        self.assertEqual(sink.get(identity).limit_diagnostic, self.diagnostic())

    def test_validation_closed_fields_and_numeric_bounds(self):
        changes = [{field: "PRIVATE"} for field in
                   ("limit_code", "phase", "action", "unit", "measurement", "config_source")]
        changes += [{field: []} for field in
                    ("limit_code", "phase", "action", "unit", "measurement", "config_source")]
        changes += [{"observed": value} for value in (True, -1, 2**53, 1.5, None)]
        changes += [{"limit": value} for value in (True, -1, 2**53, 1.5, None)]
        changes += [{"measurement": "unavailable"}, {"unit": "bytes"}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(self.diagnostic(), **change)
        with self.assertRaises(FrozenInstanceError):
            self.diagnostic().limit = 1
        replace(self.diagnostic(), observed=0, limit=2**53-1, measurement="exact")
        replace(self.diagnostic(), observed=2**53-1, measurement="conservative-bound")
        replace(self.diagnostic(), observed=None, measurement="unavailable")

    def test_depleted_authority_retains_exact_zero_limit(self):
        diagnostic = replace(self.diagnostic(), limit_code="compaction-cost-limit",
            observed=1, limit=0, unit="cost-micros", measurement="exact")
        sink = MemoryDiagnosticSink()
        identity = capture_limit(sink, stage="prime.compaction",
            diagnostic=diagnostic, subject_id="operation-1")
        self.assertEqual(sink.get(identity).limit_diagnostic.limit, 0)
        self.assertEqual(sink.get(identity).limit_diagnostic.observed, 1)

    def test_code_unit_mapping_and_closed_enum_values(self):
        codes = {
            "tokens": ("compaction-token-limit", "compaction-input-bound-unavailable"),
            "cost-micros": ("compaction-cost-limit",),
            "callbacks": ("compaction-callback-limit", "prime-model-callback-limit", "prime-tool-callback-limit"),
            "milliseconds": ("compaction-deadline", "prime-deadline"),
            "bytes": ("witness-frame-limit", "summarization-material-limit", "ipython-output-limit",
                      "context-memory-limit", "context-archive-limit", "pi-output-limit"),
        }
        for unit, values in codes.items():
            for code in values:
                with self.subTest(code=code):
                    replace(self.diagnostic(), limit_code=code, unit=unit)
                    with self.assertRaises(ValueError):
                        replace(self.diagnostic(), limit_code=code, unit="bytes" if unit != "bytes" else "tokens")
        for field, values in {
            "phase": ("admission", "execution", "settlement"),
            "action": ("observed", "rejected", "stopped", "recovery-required"),
            "config_source": ("framework-default", "application", "operator", "authority"),
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    replace(self.diagnostic(), **{field: value})

    def test_untyped_attributes_and_cycles_are_ignored(self):
        error = RuntimeError("PRIVATE")
        error.limit_diagnostic = {"limit_code": "PRIVATE"}
        error.failure_code = "PRIVATE"
        error.__cause__ = error
        self.assertIsNone(limit_diagnostic(error))
        sink = MemoryDiagnosticSink()
        identity = capture_failure(sink, stage="prime.compaction", error=error, subject_id="operation-1")
        self.assertIsNone(sink.get(identity).limit_diagnostic)
        self.assertNotIn("PRIVATE", repr(sink.get(identity)))
        with self.assertRaises(ValueError):
            ResourceLimitExceeded(error.limit_diagnostic)
        subclass = type("DiagnosticSubclass", (LimitDiagnostic,), {})
        error.limit_diagnostic = subclass("compaction-token-limit", "admission", "rejected",
            1, 1, "tokens", "exact", "authority")
        self.assertIsNone(limit_diagnostic(error))
        with self.assertRaises(ValueError):
            ResourceLimitExceeded(error.limit_diagnostic)

    def test_failure_diagnostic_preserves_seven_positional_fields(self):
        metadata = FailureMetadata()
        record = FailureDiagnostic("identity", "stage", "RuntimeError", "subject", None, None, metadata)
        self.assertIs(record.failure_metadata, metadata)
        self.assertIsNone(record.limit_diagnostic)


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


class PrivateFailureBoundsTests(unittest.TestCase):
    def test_wrapped_typed_failure_reaches_safe_p7_projection(self):
        from asterion.runtimes.pi_rpc import PiRpcPromptFailure
        from asterion.services.diagnostics import FailureMetadata
        from asterion.applications.prime.p7.operator import _safe_failure_diagnostic
        metadata = FailureMetadata(http_status=400, provider_code="invalid_request_error")
        error = RuntimeError("PRIVATE-WRAPPER")
        error.__cause__ = PiRpcPromptFailure(metadata)
        sink = MemoryDiagnosticSink()
        identity = capture_failure(sink, stage="pi.prompt", error=error, subject_id="PRIVATE-IDENTITY")
        safe = _safe_failure_diagnostic(sink.get(identity))
        self.assertEqual(safe["failure_code"], "pi-provider-execution")
        self.assertTrue(safe["failure_metadata"]["permanent_rejection"])
        self.assertEqual(safe["failure_metadata"]["http_status"], 400)
        self.assertNotIn("PRIVATE", repr(safe))

    def test_private_sink_caps_and_mode(self):
        import json
        import tempfile
        from pathlib import Path
        from asterion.services.diagnostics import (FailureMetadata, capture_private_failure)
        from asterion.services.private_failure import FilePrivateFailureSink
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failures.jsonl"
            sink = FilePrivateFailureSink(path)
            for _ in range(20):
                capture_private_failure(sink, FailureMetadata(), {"errorMessage": "秘密" * 5000}, remaining_bytes=65536)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertLessEqual(path.stat().st_size, 65536)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertGreater(len(records), 1)
            self.assertTrue(all(record["truncated"] for record in records))
            self.assertTrue(all(record["observed_bytes"] > record["retained_bytes"] for record in records))
            self.assertTrue(all(record["retained_bytes"] == len(record["error_text"].encode()) for record in records))
            self.assertTrue(all(len(line) <= 8192 for line in path.read_bytes().splitlines(keepends=True)))

    def test_private_error_with_unpaired_surrogate_cannot_interrupt_transport(self):
        import json
        from asterion.services.diagnostics import FailureMetadata, capture_private_failure

        records = []
        metadata = FailureMetadata(stop_reason="error", http_status=400)
        error_text = "bad\ud800message"
        tagged, retained = capture_private_failure(
            SimpleNamespace(record=records.append), metadata,
            {"errorMessage": error_text}, remaining_bytes=65536,
        )
        self.assertEqual(tagged.http_status, 400)
        self.assertIsNotNone(tagged.diagnostic_id)
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].error_bytes)["errorMessage"], error_text)
        self.assertEqual(retained, len(records[0].error_bytes))
        self.assertEqual(records[0].observed_bytes, retained)
