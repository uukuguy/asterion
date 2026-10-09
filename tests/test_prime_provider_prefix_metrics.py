import json
import os
from pathlib import Path
import tempfile
import unittest

from asterion.agents.prime.context_view_metrics import ProviderPrefixMetricsFile


def payload():
    sample = dict(requests=1, input_bytes=100, previous_input_bytes=0,
                  common_prefix_bytes=0, common_prefix_items=0, input_items=2,
                  previous_input_items=0, system_changed=0, cache_key_changed=0, tools_changed=0,
                  unmeasurable_requests=0, peak_input_bytes=100)
    return dict(version='asterion.prime-provider-prefix-metrics/v1',
                measurement='provider-hook-responses-input-json-utf8',
                latest=sample, samples=[sample], samples_truncated=0)


class TestProviderPrefixMetrics(unittest.TestCase):
    def test_regular_owned_file_numeric_roundtrip_and_close(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'prefix.json'
            record = ProviderPrefixMetricsFile(path)
            self.addCleanup(record.close)
            self.assertEqual(record.read(), {'status': 'not-recorded'})
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            os.write(record.descriptor, json.dumps(payload()).encode())
            self.assertEqual(record.read(), {'status': 'recorded', **payload()})
            descriptor = record.descriptor
            record.close()
            record.close()
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_prefix_bounds_flags_and_closed_shape_redact_body(self):
        with tempfile.TemporaryDirectory() as root:
            record = ProviderPrefixMetricsFile(Path(root) / 'prefix.json')
            self.addCleanup(record.close)
            for field, bad in (('common_prefix_bytes', 1), ('common_prefix_items', 1),
                               ('system_changed', 2), ('tools_changed', 2), ('input_bytes', True),
                               ('peak_input_bytes', 99), ('unmeasurable_requests', 2),
                               ('private_body', 'SENTINEL_PRIVATE_PREFIX')):
                with self.subTest(field=field):
                    value = payload()
                    value['latest'][field] = bad
                    self._write(record, value)
                    self.assertEqual(record.read(), {'status': 'unavailable'})
            huge = payload()
            huge['samples'] *= 1025
            self._write(record, huge)
            self.assertEqual(record.read(), {'status': 'unavailable'})
            self.assertNotIn('SENTINEL', repr(record))

    def test_chronology_and_final_after_sample_cap(self):
        with tempfile.TemporaryDirectory() as root:
            record = ProviderPrefixMetricsFile(Path(root) / 'prefix.json')
            self.addCleanup(record.close)
            value = payload()
            second = dict(value['latest'], requests=2, input_bytes=150,
                          previous_input_bytes=100, common_prefix_bytes=99,
                          common_prefix_items=2, input_items=3,
                          previous_input_items=2, peak_input_bytes=150)
            value['samples'].append(second)
            value['latest'] = second
            self._write(record, value)
            self.assertEqual(record.read()['status'], 'recorded')
            value['samples'] = list(reversed(value['samples']))
            self._write(record, value)
            self.assertEqual(record.read(), {'status': 'unavailable'})
            value = payload()
            value['latest'] = second
            value['samples_truncated'] = 1
            self._write(record, value)
            self.assertEqual(record.read()['status'], 'recorded')

    @staticmethod
    def _write(record, value):
        body = json.dumps(value).encode()
        os.pwrite(record.descriptor, body, 0)
        os.ftruncate(record.descriptor, len(body))
