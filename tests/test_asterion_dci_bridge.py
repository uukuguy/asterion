from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from asterion.dci.bridge import project_dci_run
from asterion.dci.run import DciRunResult
from asterion.runtime.host import RunEvent


def fixture_result(output_dir: Path, *, final_text: str = "SECRET-ANSWER") -> DciRunResult:
    return DciRunResult(
        output_dir=output_dir,
        final_text=final_text,
        events=(
            RunEvent("run", 1, "run.started", {"capabilities": []}),
            RunEvent(
                "run",
                2,
                "artifact.created",
                {
                    "artifact": {
                        "artifact_id": "final-answer",
                        "kind": "answer",
                        "media_type": "text/plain",
                        "uri": "final.txt",
                    }
                },
            ),
            RunEvent("run", 3, "run.completed", {"status": "completed"}),
        ),
        status="completed",
    )


class AsterionDciBridgeTests(unittest.TestCase):
    def test_projection_preserves_native_references_without_answer_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            projection = project_dci_run(fixture_result(Path(temporary_directory) / "run"))

        self.assertEqual(projection.events[0]["type"], "research.completed")
        self.assertEqual(projection.artifacts[0]["media_type"], "application/vnd.dci.research+json")
        self.assertEqual(
            dict(projection.artifacts[0]["value"]),
            {
                "answer_artifact_uri": "final.txt",
                "conversation_artifact_uri": "conversation.json",
                "events_artifact_uri": "events.jsonl",
                "latest_model_context_artifact_uri": "latest_model_context.json",
                "protocol_artifact_uri": "protocol/",
                "state_artifact_uri": "state.json",
            },
        )
        self.assertNotIn("SECRET-ANSWER", repr(projection))

    def test_projection_rejects_a_noncompleted_native_result(self) -> None:
        result = fixture_result(Path("run"))
        invalid = DciRunResult(
            output_dir=result.output_dir,
            final_text=result.final_text,
            events=result.events[:-1],
            status="failed",
        )
        with self.assertRaisesRegex(ValueError, "completed"):
            project_dci_run(invalid)

    def test_projection_adds_only_an_evaluation_artifact_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "run"
            output_dir.mkdir()
            (output_dir / "eval_result.json").write_text('{"is_correct": true}')
            projection = project_dci_run(fixture_result(output_dir))

        self.assertEqual(
            dict(projection.artifacts[0]["value"])["evaluation_artifact_uri"],
            "eval_result.json",
        )

    def test_projection_adds_body_free_context_policy_summary_and_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "run"
            output_dir.mkdir()
            policy_path = output_dir / "context-policy.json"
            policy_path.write_text(
                json.dumps(
                    {
                        "prompt": "SECRET-PROMPT",
                        "answer": "SECRET-ANSWER",
                        "tool": "SECRET-TOOL-BODY",
                        "credential": "SECRET-CREDENTIAL",
                    }
                )
            )
            policy_path.chmod(0o600)
            summary = {
                "schema": "dci.context-policy-evidence/v2",
                "profile": "level3",
                "contract_version": "dci.context-profile/v1",
                "extension_version": "0.1.0",
                "extension_sha256": "b" * 64,
                "truncated_results": 2,
                "compactions": 1,
                "preserved_turns": 12,
                "summary_attempts": 0,
                "summary_successes": 0,
                "summary_suppressed": False,
            }
            (output_dir / "state.json").write_text(
                json.dumps(
                    {
                        "context_policy": {
                            "artifact": "context-policy.json",
                            "sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
                            "public_summary": summary,
                        }
                    }
                )
            )
            projection = project_dci_run(fixture_result(output_dir))

        value = dict(projection.artifacts[0]["value"])
        self.assertEqual(value["context_policy_artifact_uri"], "context-policy.json")
        self.assertEqual(value["context_policy"]["profile"], "level3")
        self.assertEqual(
            value["context_policy"]["contract_version"],
            "dci.context-profile/v1",
        )
        self.assertEqual(value["context_policy"]["extension_version"], "0.1.0")
        self.assertEqual(value["context_policy"]["compactions"], 1)
        self.assertNotIn("SECRET", repr(value))


if __name__ == "__main__":
    unittest.main()
