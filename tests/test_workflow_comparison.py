"""Tests for framework-level workflow evidence comparisons."""

from __future__ import annotations

import hashlib
import unittest

from asterion.workflow_evidence import (
    collect_workflow_evidence,
    compare_workflow_evidence,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _evidence(run_id: str, *, input_tokens: int, output_tokens: int) -> dict[str, object]:
    return collect_workflow_evidence(
        (
            {
                "protocol": "asterion.agent-runtime/v1",
                "run_id": run_id,
                "sequence": 1,
                "type": "run.started",
                "payload": {"capabilities": []},
            },
            {
                "protocol": "asterion.agent-runtime/v1",
                "run_id": run_id,
                "sequence": 2,
                "type": "usage.reported",
                "payload": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
            },
            {
                "protocol": "asterion.agent-runtime/v1",
                "run_id": run_id,
                "sequence": 3,
                "type": "run.completed",
                "payload": {"status": "completed"},
            },
        ),
        input_digest=_digest("private input"),
    )


class TestWorkflowComparison(unittest.TestCase):
    def test_compares_exactly_matched_scopes_without_disclosing_scope(self) -> None:
        comparison = compare_workflow_evidence(
            _evidence("baseline", input_tokens=10, output_tokens=4),
            _evidence("candidate", input_tokens=12, output_tokens=7),
            baseline_scope={"case_digests": [_digest("case-a")], "evaluator": "v1"},
            candidate_scope={"case_digests": [_digest("case-a")], "evaluator": "v1"},
        )

        self.assertEqual(comparison["status"], "comparable")
        self.assertEqual(comparison["usage_delta"], {"input_tokens": 2, "output_tokens": 3})
        self.assertRegex(comparison["scope_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("case-a", str(comparison))

    def test_refuses_to_compare_different_scopes(self) -> None:
        comparison = compare_workflow_evidence(
            _evidence("baseline", input_tokens=10, output_tokens=4),
            _evidence("candidate", input_tokens=12, output_tokens=7),
            baseline_scope={"case_digests": [_digest("case-a")], "evaluator": "v1"},
            candidate_scope={"case_digests": [_digest("case-b")], "evaluator": "v1"},
        )

        self.assertEqual(comparison["status"], "not-comparable")
        self.assertEqual(comparison["reasons"], ["scope-identity-mismatch"])
        self.assertNotIn("usage_delta", comparison)


if __name__ == "__main__":
    unittest.main()
