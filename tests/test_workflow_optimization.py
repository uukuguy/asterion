"""Tests for non-executing, explicitly authorized workflow optimization proposals."""

from __future__ import annotations

import hashlib
import unittest

from asterion.workflow_evidence import (
    WorkflowEvidenceError,
    create_optimization_proposal,
    diagnose_workflow_comparison,
)


class TestWorkflowOptimization(unittest.TestCase):
    def test_proposal_is_a_digest_only_request_not_execution_authority(self) -> None:
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
        proposal = create_optimization_proposal(
            diagnosis,
            change_digest=hashlib.sha256(b"private configuration change").hexdigest(),
        )

        self.assertEqual(proposal["status"], "proposed")
        self.assertTrue(proposal["requires_operator_authorization"])
        self.assertFalse(proposal["execution_authorized"])
        self.assertNotIn("private configuration change", str(proposal))

    def test_refuses_to_propose_when_evidence_is_not_comparable(self) -> None:
        diagnosis = diagnose_workflow_comparison(
            {
                "schema": "asterion.workflow-comparison/v1",
                "status": "not-comparable",
                "reasons": ["scope-identity-mismatch"],
            }
        )

        with self.assertRaises(WorkflowEvidenceError):
            create_optimization_proposal(diagnosis, change_digest="a" * 64)


if __name__ == "__main__":
    unittest.main()
