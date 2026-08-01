"""Regression coverage for IR-aware DCI tool analysis."""

from __future__ import annotations

import unittest

from asterion.capabilities.dci.implementation.evaluation.analysis import (
    compute_detailed_analysis,
)


class TestDciAnalysisIr(unittest.TestCase):
    def test_tool_summary_uses_ndcg_for_ir_runs_without_qa_verdicts(self) -> None:
        analysis = compute_detailed_analysis(
            results=[
                {
                    "query_id": "q-1",
                    "run_status": "completed",
                    "is_correct": None,
                    "ndcg_at_10": 0.8,
                    "tool_metrics": {
                        "by_tool": {
                            "search": {
                                "call_count": 2,
                                "duration_seconds": 1.5,
                                "error_count": 0,
                            }
                        }
                    },
                    "agent_usage": {},
                    "judge_usage": {},
                    "judge_cost_estimate_usd": {},
                }
            ],
            rows=[{"query_id": "q-1", "gold_docs": []}],
            summary={"counts": {}, "totals": {}},
        )

        tool = analysis["tool_summary"]["search"]
        self.assertEqual(tool["qa_evaluated_queries_when_used"], 0)
        self.assertIsNone(tool["accuracy_when_used"])
        self.assertEqual(tool["ir_evaluated_queries_when_used"], 1)
        self.assertEqual(tool["mean_ndcg_at_10_when_used"], 0.8)


if __name__ == "__main__":
    unittest.main()
