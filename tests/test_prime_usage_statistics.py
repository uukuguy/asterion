"""Focused accounting boundaries; no provider or game calls."""
import unittest

from asterion.agents.prime.usage import UsageStatistics


class TestUsageStatistics(unittest.TestCase):
    def test_cache_and_reported_estimate_remain_distinct_from_throughput(self):
        usage = UsageStatistics()
        for _ in range(2):
            usage.record(dict(input_tokens=100, output_tokens=5,
                              uncached_input_tokens=10, cache_read_tokens=80, cache_write_tokens=10,
                              reported_cost=dict(currency='USD', total=0.012, source='pi_sdk_estimate')))
        snapshot = usage.snapshot()
        self.assertEqual(snapshot['input_tokens'], 200)
        self.assertEqual(snapshot['cache_read_tokens'], 160)
        self.assertEqual(snapshot['cache_read_ratio'], 0.8)
        self.assertEqual(snapshot['reported_cost']['total'], 0.024)
        self.assertEqual(snapshot['reported_cost']['source'], 'pi_sdk_estimate')

    def test_missing_statistics_are_unknown_even_after_a_known_event(self):
        usage = UsageStatistics()
        self.assertIsNone(usage.snapshot()['cache_read_tokens'])
        usage.record(dict(input_tokens=100, output_tokens=5, uncached_input_tokens=10,
                          cache_read_tokens=90, cache_write_tokens=0,
                          reported_cost=dict(currency='USD', total=0, source='pi_sdk_estimate')))
        usage.record(dict(input_tokens=20, output_tokens=2))
        snapshot = usage.snapshot()
        self.assertIsNone(snapshot['cache_read_tokens'])
        self.assertFalse(snapshot['cache_statistics_complete'])
        self.assertEqual(snapshot['cache_read_tokens_covered_events'], 1)
        self.assertIsNone(snapshot['reported_cost'])
        self.assertEqual(snapshot['reported_cost_known_total_usd'], 0)
        self.assertEqual(snapshot['reported_cost_covered_events'], 1)
