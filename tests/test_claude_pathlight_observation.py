from __future__ import annotations

import json
import unittest

from asterion.runtimes.claude_observation import ClaudeObservationBuilder


def _assistant_tool_use(
    call_id: str, name: str, arguments: object
) -> dict[str, object]:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": call_id,
                    "name": name,
                    "input": arguments,
                }
            ],
        },
    }


def _user_tool_result(call_id: str, result: object, *, is_error: bool = False) -> dict[str, object]:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": result,
                    "is_error": is_error,
                }
            ],
        },
    }


def _assistant_text(text: str) -> dict[str, object]:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def _result(*, is_error: bool, text: str, input_tokens: int = 7, output_tokens: int = 3) -> dict[str, object]:
    return {
        "type": "result",
        "is_error": is_error,
        "result": text,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


class ClaudeObservationBuilderTests(unittest.TestCase):
    def test_claude_builder_records_known_segments_and_marks_request_boundary_missing(self) -> None:
        builder = ClaudeObservationBuilder()
        builder.consume(_assistant_tool_use("c1", "Grep", {"pattern": "secret"}), 10)
        builder.consume(_user_tool_result("c1", "secret result"), 20)
        builder.consume(_assistant_text("answer"), 30)
        builder.consume(_result(is_error=False, text="answer"), 40)

        batch = builder.complete("run-private")

        self.assertTrue(all(not call.boundary_observed for call in batch.model_calls))
        self.assertIn("model-request-boundary", batch.missing_evidence)
        self.assertEqual(batch.frames[-1].segments[-1].role, "tool-result")
        self.assertNotIn("secret", json.dumps(batch.to_mapping()))

    def test_host_input_is_the_only_initial_context_digest_and_is_explicitly_incomplete(self) -> None:
        builder = ClaudeObservationBuilder()
        builder.record_host_input("private question")
        builder.consume(_assistant_text("private answer"), 10)
        builder.consume(_result(is_error=False, text="private answer"), 20)

        batch = builder.complete("run")
        initial = batch.frames[0].segments[0]

        self.assertEqual(initial.role, "user")
        self.assertTrue(initial.missing_evidence)
        self.assertIsNone(batch.model_calls[0].request_sha256)
        self.assertNotIn("private", json.dumps(batch.to_mapping()))

    def test_failed_result_creates_a_failed_model_call_without_guessing_a_request(self) -> None:
        builder = ClaudeObservationBuilder()
        builder.consume(_result(is_error=True, text="private failure"), 10)

        batch = builder.complete("run")

        self.assertEqual(len(batch.model_calls), 1)
        self.assertEqual(batch.model_calls[0].status, "failed")
        self.assertFalse(batch.model_calls[0].boundary_observed)
        self.assertIsNone(batch.model_calls[0].request_sha256)
        self.assertNotIn("private", json.dumps(batch.to_mapping()))

    def test_unmatched_tool_result_remains_an_explicitly_missing_tool_boundary(self) -> None:
        builder = ClaudeObservationBuilder()
        builder.consume(_user_tool_result("unknown", "private result"), 10)
        builder.consume(_assistant_text("answer"), 20)

        batch = builder.complete("run")

        self.assertEqual(batch.tools[0].status, "missing")
        self.assertIn("tool-boundary", batch.missing_evidence)
        self.assertNotIn("private", json.dumps(batch.to_mapping()))

    def test_replaying_the_same_stream_has_the_same_digest(self) -> None:
        events = (
            _assistant_tool_use("c1", "Grep", {"pattern": "private"}),
            _user_tool_result("c1", "private result"),
            _assistant_text("private answer"),
            _result(is_error=False, text="private answer"),
        )
        first = ClaudeObservationBuilder()
        second = ClaudeObservationBuilder()
        for timestamp, event in enumerate(events):
            first.consume(event, timestamp)
            second.consume(event, timestamp + 100)

        self.assertEqual(first.complete("run").batch_sha256, second.complete("run").batch_sha256)


if __name__ == "__main__":
    unittest.main()
