"""Closed workload and completion contract tests for Prime P2."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from hashlib import sha256
import json
import unittest
from typing import Any, cast

from asterion.applications.prime_agent.operator.ipython_workload import (
    PRIME_IPYTHON_CODING_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.operator.programmatic_long_context_workload import (
    PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_SHA256,
    PROGRAMMATIC_LONG_CONTEXT_P2_ORACLE_SHA256,
    PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
    ProgrammaticLongContextCompletion,
    ProgrammaticLongContextWorkloadError,
    canonical_programmatic_long_context_completion_bytes,
    is_programmatic_long_context_workload,
    programmatic_long_context_workload_manifest_bytes,
    verify_programmatic_long_context_completion,
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _completion(**changes: object) -> ProgrammaticLongContextCompletion:
    values: dict[str, object] = {
        "response_sha256": _digest("a"),
        "program_sha256": _digest("a"),
        "aggregate_sha256": _digest("b"),
    }
    values.update(changes)
    return ProgrammaticLongContextCompletion(**cast(Any, values))


class TestProgrammaticLongContextWorkload(unittest.TestCase):
    def test_workload_manifest_has_one_exact_canonical_digest(self) -> None:
        encoded = programmatic_long_context_workload_manifest_bytes()

        self.assertEqual(
            PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
            "sha256:" + sha256(encoded).hexdigest(),
        )
        self.assertEqual(
            encoded,
            json.dumps(json.loads(encoded), sort_keys=True, separators=(",", ":")).encode(),
        )
        self.assertIn(b'"role_id":"prime.programmatic-long-context"', encoded)

    def test_p1_workload_cannot_be_used_as_p2_workload(self) -> None:
        self.assertNotEqual(
            PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
            PRIME_IPYTHON_CODING_WORKLOAD_DIGEST,
        )
        self.assertFalse(
            is_programmatic_long_context_workload(PRIME_IPYTHON_CODING_WORKLOAD_DIGEST)
        )

    def test_rejects_fixed_identity_and_result_substitution(self) -> None:
        for name in ("corpus_sha256", "oracle_sha256"):
            with self.subTest(name=name), self.assertRaises(TypeError):
                ProgrammaticLongContextCompletion(  # type: ignore[call-arg]
                    response_sha256=_digest("a"),
                    program_sha256=_digest("a"),
                    aggregate_sha256=_digest("b"),
                    **cast(Any, {name: _digest("c")}),
                )
        cases = (
            ("response-program", {"program_sha256": _digest("c")} ),
            ("tool", {"active_tool_names": ("shell",)}),
            ("not-disposed", {"session_disposed": False}),
        )
        for name, changes in cases:
            with self.subTest(name=name), self.assertRaises(
                ProgrammaticLongContextWorkloadError
            ):
                verify_programmatic_long_context_completion(_completion(**changes))

    def test_completion_bytes_are_canonical_immutable_and_redacted(self) -> None:
        completion = _completion(response_sha256="SECRET-RESPONSE", program_sha256="SECRET-RESPONSE")

        self.assertNotIn("SECRET-RESPONSE", repr(completion))
        self.assertNotIn("SECRET-RESPONSE", str(completion))
        with self.assertRaises(ProgrammaticLongContextWorkloadError) as raised:
            canonical_programmatic_long_context_completion_bytes(completion)
        self.assertNotIn("SECRET-RESPONSE", str(raised.exception))
        with self.assertRaises(FrozenInstanceError):
            completion.aggregate_sha256 = _digest("c")  # type: ignore[misc]

        encoded = canonical_programmatic_long_context_completion_bytes(_completion())
        self.assertEqual(
            encoded,
            json.dumps(json.loads(encoded), sort_keys=True, separators=(",", ":")).encode(),
        )
        self.assertIn(PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_SHA256.encode(), encoded)
        self.assertIn(PROGRAMMATIC_LONG_CONTEXT_P2_ORACLE_SHA256.encode(), encoded)
