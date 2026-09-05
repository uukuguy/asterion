"""Exact private workload contracts for P3 development."""

from __future__ import annotations

import unittest


class TestPrimeP3DevelopmentWorkload(unittest.TestCase):
    def test_fixed_sources_oracle_and_role_budgets_are_canonical(self) -> None:
        from asterion.applications.prime_agent.operator import p3_development_workload as subject

        self.assertIn(b"low <= value <= high", subject.P3_INITIAL_SOURCE_BYTES)
        self.assertIn(b"low <= value < high", subject.P3_EXPECTED_SOURCE_BYTES)
        self.assertEqual(subject.P3_ORACLE_CASES, ((5, 1, 5, False), (3, 1, 5, True)))
        self.assertEqual(subject.P3_ROLE_MODEL_CALLBACKS, {"root": 2, "implementation": 2, "review": 4})
        self.assertEqual(subject.P3_ROLE_TOOL_CALLS, {"root": 1, "implementation": 1, "review": 2})
        self.assertEqual(subject.P3_CHILD_COUNT, 2)
        self.assertEqual(subject.P3_MAX_DEPTH, 1)

    def test_validators_reject_mutation_bool_and_private_extras(self) -> None:
        from asterion.applications.prime_agent.operator import p3_development_workload as subject

        self.assertEqual(subject.validate_p3_aggregate_bytes(subject.P3_AGGREGATE_BYTES), subject.P3_AGGREGATE)
        for value in (b'{"child_count":true}\n', subject.P3_AGGREGATE_BYTES + b"x"):
            with self.subTest(value=value):
                with self.assertRaises(subject.PrimeP3DevelopmentWorkloadError):
                    subject.validate_p3_aggregate_bytes(value)
        with self.assertRaises(subject.PrimeP3DevelopmentWorkloadError):
            subject.validate_p3_source_bytes(subject.P3_EXPECTED_SOURCE_BYTES + b"# private\n")
