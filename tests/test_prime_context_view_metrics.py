import json
import os
from pathlib import Path
import tempfile
import unittest

from asterion.agents.prime.context_view_metrics import ContextViewMetricsFile


def payload():
    values = dict(requests=1, assistant_bytes=2, current_snapshot_bytes=3,
                  tool_result_bytes=4, other_bytes=5, total_bytes=14,
                  peak_total_bytes=14, cumulative_total_bytes=14,
                  unmeasurable_requests=0)
    return dict(version='asterion.prime-context-view-metrics/v1',
                measurement='extension-hook-json-utf8', latest=values,
                samples=[values], samples_truncated=0)


class TestContextViewMetrics(unittest.TestCase):
    def test_inherited_file_roundtrip_and_lifecycle(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'metrics.json'
            record = ContextViewMetricsFile(path)
            fd = record.descriptor
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(record.read(), {'status': 'not-recorded'})
            os.write(fd, json.dumps(payload()).encode())
            self.assertEqual(record.read(), {'status': 'recorded', **payload()})
            record.close()
            record.close()
            with self.assertRaises(OSError):
                os.fstat(fd)
            self.assertEqual(json.loads(path.read_text()), payload())

    def test_closed_numeric_shape_and_bounds_redact_untrusted_content(self):
        with tempfile.TemporaryDirectory() as root:
            record = ContextViewMetricsFile(Path(root) / 'metrics.json')
            cases = []
            secret = payload()
            secret['secret'] = 'SENTINEL_PRIVATE_BODY'
            cases.append(secret)
            boolean = payload()
            boolean['latest']['total_bytes'] = True
            cases.append(boolean)
            mismatch = payload()
            mismatch['latest']['total_bytes'] = 15
            cases.append(mismatch)
            large = payload()
            large['samples'] *= 1025
            cases.append(large)
            for value in cases:
                with self.subTest(case=len(json.dumps(value))):
                    data = json.dumps(value).encode()
                    os.pwrite(record.descriptor, data, 0)
                    os.ftruncate(record.descriptor, len(data))
                    self.assertEqual(record.read(), {'status': 'unavailable'})
                    self.assertNotIn('SENTINEL', repr(record))
            record.close()

    def test_existing_file_or_symlink_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'existing'
            path.write_text('KEEP')
            link = Path(root) / 'link'
            link.symlink_to(path)
            for target in (path, link):
                with self.subTest(target=target.name):
                    with self.assertRaises(OSError):
                        ContextViewMetricsFile(target)
            self.assertEqual(path.read_text(), 'KEEP')
