"""Tests for evidence-only, framework-level workflow diagnosis."""

from __future__ import annotations

import unittest

from asterion.workflow_evidence import diagnose_workflow_comparison


class TestWorkflowDiagnosis(unittest.TestCase):
    def test_marks_scope_mismatch_as_not_comparable_not_a_failure_cause(self) -> None:
        diagnosis = diagnose_workflow_comparison(
            {
                "schema": "asterion.workflow-comparison/v1",
                "status": "not-comparable",
                "reasons": ["scope-identity-mismatch"],
            }
        )

        self.assertEqual(diagnosis["state"], "not-comparable")
        self.assertEqual(diagnosis["missing_evidence"], ["matching-scope"])
        self.assertEqual(diagnosis["observations"], [])

    def test_reports_observed_deltas_without_claiming_causality(self) -> None:
        diagnosis = diagnose_workflow_comparison(
            {
                "schema": "asterion.workflow-comparison/v1",
                "status": "comparable",
                "baseline_graph_sha256": "a" * 64,
                "candidate_graph_sha256": "b" * 64,
                "scope_sha256": "c" * 64,
                "terminal_status_changed": False,
                "usage_delta": {"input_tokens": 2, "output_tokens": -1},
            }
        )

        self.assertEqual(diagnosis["state"], "ready")
        self.assertEqual(
            diagnosis["observations"],
            [
                {"kind": "input-tokens-delta", "value": 2},
                {"kind": "output-tokens-delta", "value": -1},
            ],
        )
        self.assertEqual(diagnosis["hypotheses"], [])
        self.assertRegex(diagnosis["diagnosis_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
