"""Closed identity tests for the canonical Prime P1 workload."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import unittest

from asterion.applications.prime_agent.operator.ipython_workload import (
    PRIME_IPYTHON_CODING_EXPECTED_RESULT_SHA256,
    PRIME_IPYTHON_CODING_WORKLOAD_DIGEST,
    _parse_prime_ipython_coding_workload,
    is_prime_ipython_coding_workload,
    prime_ipython_coding_workload_bytes,
)


_IMAGE = Path(__file__).resolve().parents[1] / "src/asterion/applications/prime_agent/operator/image"
_WORKLOAD = _IMAGE / "fixture/workload.json"
_EXPECTED = {
    "capability_ref": "prime.ipython-coding@1.0.0",
    "expected_result_sha256": "f4ebce1e8a4576db9235f6d8c67dffd9718931f64a07960e1d83b3809d3ce022",
    "final_oracle_passed": True,
    "format": "asterion.prime-ipython-coding-workload/v1",
    "initial_oracle_passed": False,
    "ipython_tool_call_count": 1,
    "model_request_count": 1,
    "model_tools": ["ipython"],
    "oracle_sha256": "85ee4060b19a5ee375e4c6258f45b1df722f53efd8310f56603b31639fa3c4eb",
    "prime_sdk_ref": "prime-agent@0.7.1",
    "starter_sha256": "4f8e0bca0f70582bad96caa292823ac29577633bebd9f76257617dc92ab6832f",
    "version": "1.0.0",
    "workload_id": "prime.ipython-coding",
    "workspace_mutation_required": True,
}


class TestPrimeIpythonWorkload(unittest.TestCase):
    def test_image_fixture_is_the_exact_canonical_workload(self) -> None:
        payload = _WORKLOAD.read_bytes()

        self.assertEqual(
            payload,
            json.dumps(_EXPECTED, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n",
        )
        self.assertEqual(json.loads(payload), _EXPECTED)
        self.assertEqual(prime_ipython_coding_workload_bytes(), payload)
        self.assertEqual(PRIME_IPYTHON_CODING_WORKLOAD_DIGEST, "sha256:" + sha256(payload).hexdigest())
        self.assertEqual(PRIME_IPYTHON_CODING_EXPECTED_RESULT_SHA256, _EXPECTED["expected_result_sha256"])
        self.assertNotEqual(PRIME_IPYTHON_CODING_WORKLOAD_DIGEST.removeprefix("sha256:"), PRIME_IPYTHON_CODING_EXPECTED_RESULT_SHA256)

    def test_parser_rejects_noncanonical_or_altered_workload_bytes(self) -> None:
        payload = json.dumps(_EXPECTED, indent=2, sort_keys=True).encode("utf-8")

        with self.assertRaises(ValueError):
            _parse_prime_ipython_coding_workload(payload)
        with self.assertRaises(ValueError):
            _parse_prime_ipython_coding_workload(
                prime_ipython_coding_workload_bytes().replace(b'"model_request_count":1', b'"model_request_count":2')
            )

    def test_selector_admits_only_the_workload_digest(self) -> None:
        self.assertTrue(is_prime_ipython_coding_workload(PRIME_IPYTHON_CODING_WORKLOAD_DIGEST))
        self.assertFalse(is_prime_ipython_coding_workload(PRIME_IPYTHON_CODING_EXPECTED_RESULT_SHA256))
        self.assertFalse(is_prime_ipython_coding_workload(PRIME_IPYTHON_CODING_WORKLOAD_DIGEST.upper()))
        self.assertFalse(is_prime_ipython_coding_workload(1))
