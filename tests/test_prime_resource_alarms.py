"""Safe operator presentation of resource limits; no provider transport."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from asterion.applications.prime.resource_alarms import ResourceAlarmSink, resource_alarm
from asterion.services.diagnostics import FailureDiagnostic, LimitDiagnostic, capture_limit


class TestResourceAlarms(unittest.TestCase):
    def test_hard_soft_dedupe_and_distinct_operations(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'resource-alarms.jsonl'
            visible = []
            sink = ResourceAlarmSink(path, emit=visible.append)
            diagnostic = LimitDiagnostic('witness-frame-limit', 'admission',
                'rejected', 8193, 8192, 'bytes', 'exact', 'application')
            for operation in ('PRIVATE-op-1', 'PRIVATE-op-1', 'PRIVATE-op-2'):
                capture_limit(sink, stage='prime.compaction', diagnostic=diagnostic,
                              subject_id=operation)
            self.assertEqual(len(visible), 2)
            self.assertEqual(len(path.read_text().splitlines()), 2)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(visible[0]['configuration'], 'PrimeCompactionPolicy.max_frame_bytes')
            self.assertEqual((visible[0]['observed'], visible[0]['limit'], visible[0]['outcome']),
                             (8193, 8192, 'rejected'))
            soft = replace(diagnostic, action='observed', measurement='estimate')
            capture_limit(sink, stage='prime.compaction', diagnostic=soft, subject_id='op-3')
            self.assertEqual((visible[-1]['measurement'], visible[-1]['outcome']), ('estimate', 'observed'))
            visible[0]['limit'] = 99
            self.assertEqual(sink.alarms[0]['limit'], 8192)
            with self.assertRaises(TypeError):
                sink.alarms[0]['limit'] = 0
            self.assertNotIn('PRIVATE', json.dumps([dict(item) for item in sink.alarms]))

    def test_independent_failures_retain_safe_alarm(self):
        def broken_emit(value):
            raise RuntimeError('PRIVATE-CREDENTIAL')
        class Broken:
            def record(self, value):
                raise RuntimeError('PRIVATE-PROVIDER-PAYLOAD')
        with tempfile.TemporaryDirectory() as temporary:
            for persist_fails in (False, True):
                with self.subTest(persist_fails=persist_fails):
                    visible = []
                    path = Path(temporary) / ('missing/alarms.jsonl' if persist_fails else 'alarms.jsonl')
                    sink = ResourceAlarmSink(path, emit=visible.append if persist_fails else broken_emit,
                                             downstream=Broken())
                    diagnostic = LimitDiagnostic('compaction-token-limit', 'admission',
                        'rejected', 1, 0, 'tokens', 'exact', 'authority')
                    capture_limit(sink, stage='prime.compaction', diagnostic=diagnostic,
                                  subject_id='PRIVATE-OPERATION')
                    self.assertEqual(len(sink.alarms), 1)
                    self.assertEqual(sink.alarms[0]['limit'], 0)
                    if persist_fails:
                        self.assertEqual(len(visible), 1)
                    else:
                        self.assertEqual(len(path.read_text().splitlines()), 1)
                    self.assertNotIn('PRIVATE', json.dumps([dict(item) for item in sink.alarms]))

    def test_closed_projection_and_fixed_authority_configuration(self):
        record = FailureDiagnostic('a' * 32, 'PRIVATE-prompt', 'PRIVATE-error', 'b' * 64,
            None, 'PRIVATE-failure', limit_diagnostic=LimitDiagnostic('prime-parent-token-limit',
                'admission', 'rejected', 8, 7, 'tokens', 'exact', 'authority'))
        alarm = resource_alarm(record)
        self.assertEqual(alarm['configuration'], 'RemainingBudget.controller_tokens/aggregate_tokens')
        self.assertNotIn('PRIVATE', json.dumps(alarm))
        deadline = replace(record, limit_diagnostic=LimitDiagnostic('prime-deadline', 'admission',
            'rejected', 2, 1, 'milliseconds', 'exact', 'authority'))
        self.assertEqual(resource_alarm(deadline)['configuration'], 'RunRequest.deadline_ms')
        self.assertIsNone(resource_alarm(replace(record, limit_diagnostic=None)))
        for bad in (object(), replace(record, diagnostic_id='PRIVATE-ID'),
                    replace(record, limit_diagnostic={'observed': 'PRIVATE'})):
            with self.subTest(value=type(bad).__name__), self.assertRaises(ValueError):
                resource_alarm(bad)

    def test_operator_progress_and_final_result_retain_safe_alarm(self):
        from contextlib import redirect_stderr
        from dataclasses import asdict
        import io
        from asterion.applications.prime.p1 import operator as p1
        from asterion.applications.prime.p7 import operator as p7
        with tempfile.TemporaryDirectory() as temporary:
            for operator in (p1, p7):
                with self.subTest(operator=operator.__name__):
                    output = io.StringIO()
                    sink = ResourceAlarmSink(Path(temporary) / 'alarms.jsonl', emit=operator._public_resource_alarm)
                    with redirect_stderr(output):
                        capture_limit(sink, stage='PRIVATE-stage', subject_id='PRIVATE-operation',
                            diagnostic=LimitDiagnostic('witness-frame-limit', 'admission', 'rejected',
                                2, 1, 'bytes', 'exact', 'application'))
                    self.assertIn('resource-limit', output.getvalue())
                    self.assertNotIn('PRIVATE', output.getvalue())
                    self.assertEqual(sink.get(sink.alarms[0]['diagnostic_id']).limit_diagnostic.limit, 1)
            receipt = p7._public_receipt('unsuccessful', 'p7-test', resource_alarms=sink.alarms)
            self.assertEqual(receipt['resource_alarms'][0]['limit'], 1)
            result = p1.P1PublicResult('p1-test', 'protocol-failure', resource_alarms=tuple(dict(a) for a in sink.alarms))
            self.assertEqual(asdict(result)['resource_alarms'][0]['limit'], 1)
