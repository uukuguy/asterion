"""Exact private workload contracts for P3 development."""

from __future__ import annotations

import unittest


class TestPrimeP3DevelopmentWorkload(unittest.TestCase):
    def test_fixed_sources_oracle_and_role_budgets_are_canonical(self) -> None:
        from asterion.applications.prime_agent.operator import p3_development_workload as subject

        self.assertIn(b"low <= value <= high", subject.P3_INITIAL_SOURCE_BYTES)
        self.assertIn(b"low <= value < high", subject.P3_EXPECTED_SOURCE_BYTES)
        self.assertEqual(subject.P3_ORACLE_CASES, ((5, 1, 5, False), (3, 1, 5, True)))
        self.assertEqual(subject.P3_ROLE_MODEL_CALLBACKS, {"root": 4, "implementation": 2, "review": 4})
        self.assertEqual(subject.P3_ROLE_TOOL_CALLS, {"root": 1, "implementation": 1, "review": 2})
        self.assertEqual(subject.P3_CHILD_COUNT, 2)
        self.assertEqual(subject.P3_MAX_DEPTH, 1)
        self.assertEqual(sum(subject.P3_ROLE_MODEL_CALLBACKS.values()), 10)
        self.assertEqual(sum(subject.P3_ROLE_TOOL_CALLS.values()), 4)

    def test_validators_reject_mutation_bool_and_private_extras(self) -> None:
        from asterion.applications.prime_agent.operator import p3_development_workload as subject

        self.assertEqual(subject.validate_p3_aggregate_bytes(subject.P3_AGGREGATE_BYTES), subject.P3_AGGREGATE)
        for value in (b'{"child_count":true}\n', subject.P3_AGGREGATE_BYTES + b"x"):
            with self.subTest(value=value):
                with self.assertRaises(subject.PrimeP3DevelopmentWorkloadError):
                    subject.validate_p3_aggregate_bytes(value)
        with self.assertRaises(subject.PrimeP3DevelopmentWorkloadError):
            subject.validate_p3_source_bytes(subject.P3_EXPECTED_SOURCE_BYTES + b"# private\n")

    def test_exported_artifacts_are_immutable_and_cannot_poison_validators(self) -> None:
        from asterion.applications.prime_agent.operator import p3_development_workload as subject

        for artifact in (subject.P3_IMPLEMENTATION_ARTIFACT, subject.P3_REVIEW_ARTIFACT, subject.P3_FOLLOW_UP_ARTIFACT, subject.P3_AGGREGATE):
            with self.subTest(artifact=artifact):
                with self.assertRaises(TypeError):
                    artifact["private"] = "mutation"
        with self.assertRaises(TypeError):
            subject.P3_FOLLOW_UP_ARTIFACT["oracle_cases"][0][0] = True
        self.assertEqual(subject.validate_p3_aggregate_bytes(subject.P3_AGGREGATE_BYTES), subject.P3_AGGREGATE)

    def test_digests_remain_exact_after_exported_values_are_observed(self) -> None:
        from hashlib import sha256
        from asterion.applications.prime_agent.operator import p3_development_workload as subject

        self.assertEqual(subject.P3_EXPECTED_SOURCE_DIGEST, "sha256:" + sha256(subject.P3_EXPECTED_SOURCE_BYTES).hexdigest())
        self.assertEqual(subject.P3_DEVELOPMENT_WORKLOAD_DIGEST, "sha256:" + sha256(subject.P3_DEVELOPMENT_WORKLOAD_BYTES).hexdigest())

    def test_workload_binds_expected_patch_test_and_artifact_schema_identities(self) -> None:
        from hashlib import sha256
        import json
        from asterion.applications.prime_agent.operator import p3_development_workload as subject

        manifest = json.loads(subject.P3_DEVELOPMENT_WORKLOAD_BYTES)
        self.assertEqual(manifest["expected_source_sha256"], sha256(subject.P3_EXPECTED_SOURCE_BYTES).hexdigest())
        self.assertEqual(manifest["expected_test_sha256"], sha256(subject.P3_EXPECTED_TEST_BYTES).hexdigest())
        self.assertEqual(manifest["implementation_artifact_sha256"], sha256(subject.P3_IMPLEMENTATION_BYTES).hexdigest())
        self.assertEqual(manifest["review_artifact_sha256"], sha256(subject.P3_REVIEW_BYTES).hexdigest())
        self.assertEqual(manifest["follow_up_artifact_sha256"], sha256(subject.P3_FOLLOW_UP_BYTES).hexdigest())
        self.assertNotEqual(manifest["expected_source_sha256"], sha256(b"def in_range(value: int, low: int, high: int) -> bool:\n    return low < value < high\n").hexdigest())
        self.assertNotEqual(manifest["expected_test_sha256"], sha256(subject.P3_INITIAL_TEST_BYTES).hexdigest())
        self.assertNotEqual(manifest["review_artifact_sha256"], sha256(b'{"format":"changed"}\n').hexdigest())

    def test_workload_binds_seed_prompts_and_closed_artifact_names(self) -> None:
        from hashlib import sha256
        import json
        from asterion.applications.prime_agent.operator import p3_development_workload as subject

        manifest = json.loads(subject.P3_DEVELOPMENT_WORKLOAD_BYTES)
        self.assertEqual(subject.P3_SEED_FILENAMES, ("solution.py", "test_solution.py"))
        self.assertEqual(len(subject.P3_ARTIFACT_FILENAMES), 4)
        self.assertIn('spawn("implementation")', subject.P3_ROOT_PROMPT)
        self.assertEqual(manifest["seed_sha256"]["solution.py"], sha256(subject.P3_INITIAL_SOURCE_BYTES).hexdigest())
        self.assertEqual(manifest["prompts_sha256"]["root"], sha256(subject.P3_ROOT_PROMPT.encode()).hexdigest())
        self.assertEqual(manifest["artifact_schema_sha256"], sha256(subject.P3_ARTIFACT_SCHEMA_BYTES).hexdigest())
