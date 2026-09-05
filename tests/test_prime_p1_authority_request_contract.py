"""Tests for the fixed, non-authoritative Prime P1 request contract."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
from pathlib import Path
import unittest
from typing import Any, cast
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_request_contract import (
    canonical_prime_p1_request_contract_bytes,
    prime_p1_request_contract_sha256,
)


_GOLDEN = (
    b'{"controls":{"deadline_milliseconds":60000,"max_cost_microunits":10000,'
    b'"max_input_bytes":4096,"max_input_tokens":1024,"max_output_bytes":4096,'
    b'"max_output_tokens":1024,"max_requests":1},"format":'
    b'"asterion.prime-p1-request-contract/v1","identity":{"application_id":'
    b'"prime.ipython-coding","application_version":"1.0.0","assembly_ref":'
    b'"prime.ipython-coding@1.0.0","implementation_ref":'
    b'"prime.ipython-coding@1.0.0","package_ref":"prime-agent@1.0.0",'
    b'"prime_sdk_ref":"prime-agent@0.7.1","provider_id":"prime-agent",'
    b'"runtime_id":"prime.agent"},"model_tools":["ipython"],"oracle_sha256":'
    b'"85ee4060b19a5ee375e4c6258f45b1df722f53efd8310f56603b31639fa3c4eb",'
    b'"workload_sha256":"f4ebce1e8a4576db9235f6d8c67dffd9718931f64a07960e1d83b3809d3ce022"}'
)
_DIGEST = "b574630f0d31c7ea92f93812389a8efe79ac4b953da04797a2d598329f99aa34"


class TestPrimeP1AuthorityRequestContract(unittest.TestCase):
    def test_exact_canonical_bytes_digest_and_recursive_schema(self) -> None:
        payload = canonical_prime_p1_request_contract_bytes()
        self.assertEqual(payload, _GOLDEN)
        self.assertEqual(prime_p1_request_contract_sha256(), _DIGEST)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), _DIGEST)
        decoded = json.loads(payload)
        self.assertEqual(
            decoded,
            {
                "format": "asterion.prime-p1-request-contract/v1",
                "controls": {
                    "deadline_milliseconds": 60_000,
                    "max_cost_microunits": 10_000,
                    "max_input_bytes": 4096,
                    "max_output_bytes": 4096,
                    "max_input_tokens": 1024,
                    "max_output_tokens": 1024,
                    "max_requests": 1,
                },
                "identity": {
                    "provider_id": "prime-agent",
                    "application_id": "prime.ipython-coding",
                    "application_version": "1.0.0",
                    "assembly_ref": "prime.ipython-coding@1.0.0",
                    "implementation_ref": "prime.ipython-coding@1.0.0",
                    "package_ref": "prime-agent@1.0.0",
                    "prime_sdk_ref": "prime-agent@0.7.1",
                    "runtime_id": "prime.agent",
                },
                "model_tools": ["ipython"],
                "workload_sha256": "f4ebce1e8a4576db9235f6d8c67dffd9718931f64a07960e1d83b3809d3ce022",
                "oracle_sha256": "85ee4060b19a5ee375e4c6258f45b1df722f53efd8310f56603b31639fa3c4eb",
            },
        )

    def test_is_zero_input_immutable_and_host_independent(self) -> None:
        def forbidden(*_: object, **__: object) -> object:
            raise AssertionError("host state access is forbidden")

        with (
            patch.object(os, "getcwd", side_effect=forbidden),
            patch.object(os, "getenv", side_effect=forbidden),
            patch.dict(os.environ, {"PYTHONHASHSEED": "hostile"}),
        ):
            first = canonical_prime_p1_request_contract_bytes()
            second = canonical_prime_p1_request_contract_bytes()
            digest = prime_p1_request_contract_sha256()
        self.assertIsInstance(first, bytes)
        self.assertEqual(first, second)
        self.assertEqual(digest, _DIGEST)
        with self.assertRaises(TypeError):
            cast(Any, canonical_prime_p1_request_contract_bytes)("widen")
        with self.assertRaises(TypeError):
            cast(Any, prime_p1_request_contract_sha256)("widen")

    def test_has_no_authority_or_host_imports_or_forbidden_contract_keys(self) -> None:
        import asterion.applications.prime_agent.operator.authority_request_contract as module

        source = Path(inspect.getfile(module)).read_text(encoding="utf-8")
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom)
        }
        self.assertTrue(
            imports.isdisjoint(
                {
                    "authority_config",
                    "authority_resources",
                    "docker",
                    "model_session_host",
                    "network",
                    "os",
                    "socket",
                    "subprocess",
                }
            )
        )
        decoded = json.loads(canonical_prime_p1_request_contract_bytes())
        keys = {
            key.lower()
            for value in _walk(decoded)
            if isinstance(value, dict)
            for key in value
        }
        self.assertTrue(
            keys.isdisjoint(
                {
                    "api_key",
                    "command",
                    "credential",
                    "docker",
                    "executable",
                    "image",
                    "model",
                    "path",
                    "platform",
                    "prompt",
                    "secret",
                }
            )
        )


def _walk(value: object) -> tuple[object, ...]:
    if isinstance(value, dict):
        return (value, *(item for nested in value.values() for item in _walk(nested)))
    if isinstance(value, list):
        return tuple(item for nested in value for item in _walk(nested))
    return (value,)


if __name__ == "__main__":
    unittest.main()
