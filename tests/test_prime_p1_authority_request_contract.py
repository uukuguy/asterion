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
    b'"asterion.prime-p1-request-contract/v2","identity":{"application_id":'
    b'"prime.ipython-coding","application_version":"1.0.0","assembly_ref":'
    b'"prime.ipython-coding@1.0.0","implementation_ref":'
    b'"prime.ipython-coding@1.0.0","package_ref":"prime-agent@1.0.0",'
    b'"prime_sdk_ref":"prime-agent@0.7.1","provider_id":"prime-agent",'
    b'"runtime_id":"prime.agent"},"model_tools":["ipython"],"oracle_sha256":'
    b'"85ee4060b19a5ee375e4c6258f45b1df722f53efd8310f56603b31639fa3c4eb",'
    b'"workload_sha256":"21e33f624940b7715de04f30a68223e04b52061823ad5947daba3b294c9e1cd6"}'
)
_DIGEST = "7bbe643efb2efdc764a06f8d4a20aa92b4de60bb15285bf32a2a5b3937424b97"
_ALLOWED_IMPORT_MODULES = frozenset(
    {
        "__future__",
        "hashlib",
        "json",
        ".ipython_workload",
    }
)


def _has_only_allowed_imports(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                return False
            modules.add("." * node.level + node.module)
    return modules <= _ALLOWED_IMPORT_MODULES


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
                "format": "asterion.prime-p1-request-contract/v2",
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
                "workload_sha256": "21e33f624940b7715de04f30a68223e04b52061823ad5947daba3b294c9e1cd6",
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
        self.assertTrue(_has_only_allowed_imports(source))
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

    def test_import_allowlist_rejects_absolute_authority_host_import(self) -> None:
        hostile_source = (
            "from asterion.applications.prime_agent.operator.model_session_host "
            "import PrimeP1ModelSessionHost\n"
        )
        self.assertFalse(_has_only_allowed_imports(hostile_source))


def _walk(value: object) -> tuple[object, ...]:
    if isinstance(value, dict):
        return (value, *(item for nested in value.values() for item in _walk(nested)))
    if isinstance(value, list):
        return tuple(item for nested in value for item in _walk(nested))
    return (value,)


if __name__ == "__main__":
    unittest.main()
