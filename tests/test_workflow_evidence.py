"""Tests for framework-level, content-safe workflow evidence."""

from __future__ import annotations

import hashlib
import json
import unittest

from asterion.workflow_evidence import WorkflowEvidenceError, collect_workflow_evidence


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class TestWorkflowEvidence(unittest.TestCase):
    def test_collects_validated_runtime_flow_without_private_content(self) -> None:
        answer_digest = _digest("private final answer")
        graph = collect_workflow_evidence(
            (
                {
                    "protocol": "asterion.agent-runtime/v1",
                    "run_id": "run-1",
                    "sequence": 1,
                    "type": "run.started",
                    "payload": {"capabilities": ["search"]},
                },
                {
                    "protocol": "asterion.agent-runtime/v1",
                    "run_id": "run-1",
                    "sequence": 2,
                    "type": "tool.call",
                    "payload": {
                        "call_id": "call-1",
                        "name": "search",
                        "arguments": {"query": "private query"},
                    },
                },
                {
                    "protocol": "asterion.agent-runtime/v1",
                    "run_id": "run-1",
                    "sequence": 3,
                    "type": "tool.result",
                    "payload": {
                        "call_id": "call-1",
                        "output": "private tool output",
                        "is_error": False,
                    },
                },
                {
                    "protocol": "asterion.agent-runtime/v1",
                    "run_id": "run-1",
                    "sequence": 4,
                    "type": "usage.reported",
                    "payload": {"input_tokens": 10, "output_tokens": 4},
                },
                {
                    "protocol": "asterion.agent-runtime/v1",
                    "run_id": "run-1",
                    "sequence": 5,
                    "type": "artifact.created",
                    "payload": {
                        "artifact": {
                            "artifact_id": "answer",
                            "kind": "answer",
                            "media_type": "text/plain",
                            "sha256": answer_digest,
                        }
                    },
                },
                {
                    "protocol": "asterion.agent-runtime/v1",
                    "run_id": "run-1",
                    "sequence": 6,
                    "type": "run.completed",
                    "payload": {"status": "completed"},
                },
            ),
            input_digest=_digest("private prompt"),
        )

        self.assertEqual(graph["schema"], "asterion.workflow-evidence/v1")
        self.assertEqual(graph["run_id"], "run-1")
        self.assertEqual(graph["terminal_status"], "completed")
        self.assertRegex(graph["graph_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(graph["usage"], {"input_tokens": 10, "output_tokens": 4})
        self.assertEqual(graph["tools"], [{"name": "search", "calls": 1, "errors": 0}])
        self.assertEqual(graph["artifacts"], [{"artifact_id": "answer", "sha256": answer_digest}])
        rendered = json.dumps(graph, sort_keys=True)
        self.assertNotIn("private prompt", rendered)
        self.assertNotIn("private query", rendered)
        self.assertNotIn("private tool output", rendered)

    def test_graph_digest_is_deterministic_for_the_same_runtime_evidence(self) -> None:
        events = (
            {
                "protocol": "asterion.agent-runtime/v1",
                "run_id": "run-2",
                "sequence": 1,
                "type": "run.started",
                "payload": {"capabilities": []},
            },
            {
                "protocol": "asterion.agent-runtime/v1",
                "run_id": "run-2",
                "sequence": 2,
                "type": "run.completed",
                "payload": {"status": "cancelled"},
            },
        )

        first = collect_workflow_evidence(events, input_digest=_digest("input"))
        second = collect_workflow_evidence(events, input_digest=_digest("input"))

        self.assertEqual(first["graph_sha256"], second["graph_sha256"])
        self.assertEqual(first["terminal_status"], "cancelled")

    def test_rejects_artifact_digest_mismatch(self) -> None:
        events = (
            {
                "protocol": "asterion.agent-runtime/v1",
                "run_id": "run-1",
                "sequence": 1,
                "type": "run.started",
                "payload": {"capabilities": []},
            },
            {
                "protocol": "asterion.agent-runtime/v1",
                "run_id": "run-1",
                "sequence": 2,
                "type": "artifact.created",
                "payload": {
                    "artifact": {
                        "artifact_id": "answer",
                        "kind": "answer",
                        "media_type": "text/plain",
                        "sha256": _digest("expected"),
                    }
                },
            },
            {
                "protocol": "asterion.agent-runtime/v1",
                "run_id": "run-1",
                "sequence": 3,
                "type": "run.completed",
                "payload": {"status": "completed"},
            },
        )

        with self.assertRaises(WorkflowEvidenceError):
            collect_workflow_evidence(
                events,
                input_digest=_digest("input"),
                artifact_digests={"answer": _digest("different")},
            )


if __name__ == "__main__":
    unittest.main()
