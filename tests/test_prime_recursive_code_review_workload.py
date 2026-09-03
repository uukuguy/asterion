"""Closed workload identity tests for the Prime P3 recursive code review."""

from __future__ import annotations

from hashlib import sha256
import json
import unittest

from asterion.applications.prime_agent.operator.ipython_workload import (
    PRIME_IPYTHON_CODING_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.operator.programmatic_long_context_workload import (
    PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.operator.recursive_code_review_workload import (
    RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS,
    RECURSIVE_CODE_REVIEW_P3_FOLLOW_UP_ROLE_ID,
    RECURSIVE_CODE_REVIEW_P3_ROLE_ID,
    RECURSIVE_CODE_REVIEW_P3_SCENARIO_ID,
    RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST,
    is_recursive_code_review_workload,
    recursive_code_review_workload_manifest_bytes,
)


class TestRecursiveCodeReviewWorkload(unittest.TestCase):
    def test_manifest_has_one_exact_immutable_canonical_digest(self) -> None:
        encoded = recursive_code_review_workload_manifest_bytes()

        self.assertEqual(
            RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST,
            "sha256:" + sha256(encoded).hexdigest(),
        )
        self.assertEqual(
            encoded,
            json.dumps(json.loads(encoded), sort_keys=True, separators=(",", ":")).encode(),
        )
        self.assertIn(b'"scenario_id":"prime.recursive-workflow/v1"', encoded)
        self.assertEqual(RECURSIVE_CODE_REVIEW_P3_SCENARIO_ID, "prime.recursive-workflow/v1")
        self.assertEqual(RECURSIVE_CODE_REVIEW_P3_ROLE_ID, "prime.recursive-workflow")
        self.assertEqual(len(RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS), 2)
        self.assertIn(RECURSIVE_CODE_REVIEW_P3_FOLLOW_UP_ROLE_ID, RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS)

    def test_p1_and_p2_workloads_are_not_admitted(self) -> None:
        for workload in (
            PRIME_IPYTHON_CODING_WORKLOAD_DIGEST,
            PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
            "sha256:" + "0" * 64,
        ):
            with self.subTest(workload=workload):
                self.assertNotEqual(RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST, workload)
                self.assertFalse(is_recursive_code_review_workload(workload))

