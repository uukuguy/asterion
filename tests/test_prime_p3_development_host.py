from __future__ import annotations
import unittest


class TestPrimeP3DevelopmentHost(unittest.TestCase):
    def test_oracle_requires_exact_counts_and_canonical_files(self) -> None:
        from asterion.applications.prime_agent.operator import p3_development_host as host
        from asterion.applications.prime_agent.operator import p3_development_workload as work
        observations = {"child_count": 2, "max_depth": 1, "model_callback_count": 10, "remaining_child_count": 0, "retained_follow_up_count": 1, "tool_call_count": 4}
        trace = host.make_p3_development_trace(source=work.P3_EXPECTED_SOURCE_BYTES, tests=work.P3_EXPECTED_TEST_BYTES, aggregate=work.P3_AGGREGATE_BYTES, observations=observations)
        self.assertRegex(trace.trace_sha256, r"^sha256:[0-9a-f]{64}$")
