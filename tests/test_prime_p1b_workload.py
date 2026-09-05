"""Closed identity tests for the independent Prime P1-B development workload."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import unittest

from asterion.applications.prime_agent.operator.p1b_workload import (
    PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_EXPECTED_RESULT_SHA256,
    PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST,
    _parse_p1b_development_workload,
    is_p1b_development_workload,
    p1b_development_workload_bytes,
)


_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "src/asterion/applications/prime_agent/operator/image/fixture/p1b-workload.json"
)
_EXPECTED = {
    "capability_ref": "prime.ipython-coding@1.0.0",
    "continuity_probe_count": 12,
    "expected_result_sha256": "f4ebce1e8a4576db9235f6d8c67dffd9718931f64a07960e1d83b3809d3ce022",
    "final_oracle_passed": True,
    "format": "asterion.prime-ipython-coding-p1b-development-workload/v1",
    "initial_oracle_passed": False,
    "ipython_tool_call_count": 2,
    "kernel_generation_count": 1,
    "kernel_restart_count": 0,
    "manual_compact_count": 1,
    "model_cell_execution_count": 2,
    "model_tools": ["ipython"],
    "oracle_sha256": "85ee4060b19a5ee375e4c6258f45b1df722f53efd8310f56603b31639fa3c4eb",
    "prime_sdk_ref": "prime-agent@0.7.1",
    "prompt_count": 2,
    "provider_request_count": 5,
    "source_sha256": "486a083f857430c7d6a452ebf881d1b8c46063c128b51162ffdebef0c1f71c7a",
    "starter_sha256": "4f8e0bca0f70582bad96caa292823ac29577633bebd9f76257617dc92ab6832f",
    "version": "1.0.0",
    "workload_id": "prime.ipython-coding-p1b-development",
    "workspace_mutation_required": True,
}


class TestPrimeP1BWorkload(unittest.TestCase):
    def test_fixture_is_the_exact_canonical_development_workload(self) -> None:
        payload = _FIXTURE.read_bytes()

        self.assertEqual(
            payload,
            json.dumps(_EXPECTED, sort_keys=True, separators=(",", ":")).encode("utf-8")
            + b"\n",
        )
        self.assertEqual(json.loads(payload), _EXPECTED)
        self.assertEqual(p1b_development_workload_bytes(), payload)
        self.assertEqual(
            PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST,
            "sha256:" + sha256(payload).hexdigest(),
        )
        self.assertEqual(
            PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_EXPECTED_RESULT_SHA256,
            _EXPECTED["expected_result_sha256"],
        )

    def test_parser_rejects_a_changed_fixed_count(self) -> None:
        altered = p1b_development_workload_bytes().replace(
            b'"provider_request_count":5', b'"provider_request_count":4'
        )

        with self.assertRaises(ValueError):
            _parse_p1b_development_workload(altered)

    def test_public_declaration_contains_no_authority_values(self) -> None:
        declared = json.loads(p1b_development_workload_bytes())

        for forbidden_key in (
            "prompt_text",
            "workspace_path",
            "provider_config",
            "model_id",
            "credential",
            "command",
            "environment",
            "env",
        ):
            with self.subTest(forbidden_key=forbidden_key):
                self.assertNotIn(forbidden_key, declared)

    def test_selector_admits_only_the_development_workload_digest(self) -> None:
        self.assertTrue(
            is_p1b_development_workload(
                PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST
            )
        )
        self.assertFalse(is_p1b_development_workload("sha256:" + "0" * 64))
        self.assertFalse(is_p1b_development_workload(1))
