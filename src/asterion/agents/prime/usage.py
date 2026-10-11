"""Observed throughput, cache reuse and reported estimates; no budget authority."""
from __future__ import annotations

from decimal import Decimal
import math

from asterion.runtime.protocol import validate_usage_payload


class UsageStatistics:
    def __init__(self):
        self.events = 0
        self.input_tokens = self.output_tokens = 0
        self._parts = {key: 0 for key in (
            'uncached_input_tokens', 'cache_read_tokens', 'cache_write_tokens')}
        self._covered = dict.fromkeys(self._parts, 0)
        self._cost = Decimal(0)
        self._cost_events = 0

    def record(self, payload):
        validate_usage_payload(payload)
        self.events += 1
        self.input_tokens += payload['input_tokens']
        self.output_tokens += payload['output_tokens']
        for key in self._parts:
            if key in payload:
                self._parts[key] += payload[key]
                self._covered[key] += 1
        cost = payload.get('reported_cost')
        if cost is not None:
            self._cost += Decimal(str(cost['total']))
            self._cost_events += 1

    def snapshot(self):
        result = dict(input_tokens=self.input_tokens, output_tokens=self.output_tokens,
                      usage_events=self.events)
        for key, value in self._parts.items():
            result[key] = value if self.events and self._covered[key] == self.events else None
            result[key + '_covered_events'] = self._covered[key]
        cache_complete = bool(self.events) and all(
            count == self.events for count in self._covered.values())
        result['cache_statistics_complete'] = cache_complete
        result['cache_read_ratio'] = (self._parts['cache_read_tokens'] / self.input_tokens
                                     if cache_complete and self.input_tokens else None)
        value = float(self._cost)
        cost_known = self._cost_events > 0 and math.isfinite(value)
        result['reported_cost'] = (dict(currency='USD', total=value, source='pi_sdk_estimate')
                                  if cost_known and self._cost_events == self.events else None)
        result['reported_cost_known_total_usd'] = value if cost_known else None
        result['reported_cost_covered_events'] = self._cost_events
        return result
