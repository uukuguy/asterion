from __future__ import annotations

import hashlib
import json
import unittest

from asterion.pathlight import (
    ContextSegmentSummary,
    PathlightError,
    ProviderRequestObservation,
    RuntimeObservationBatch,
    validate_runtime_observation_batch,
)
from asterion.runtimes.pi_observation import PiObservationBuilder


def _clock() -> int:
    return 1


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _provider_context(index: int, messages: list[dict[str, object]]) -> dict[str, object]:
    return {
        "type": "provider_request_context",
        "requestIndex": index,
        "provider": "SENTINEL_PROVIDER",
        "model": "SENTINEL_MODEL",
        "messages": messages,
    }


def _user(content: str) -> dict[str, object]:
    return {"role": "user", "content": content}


def _tool_result(call_id: str, result: str) -> dict[str, object]:
    return {
        "role": "toolResult",
        "toolCallId": call_id,
        "content": result,
    }


def _tool_start(
    call_id: str, name: str, arguments: object
) -> dict[str, object]:
    return {
        "type": "tool_execution_start",
        "toolCallId": call_id,
        "toolName": name,
        "args": arguments,
    }


def _tool_end(call_id: str, result: object, is_error: bool) -> dict[str, object]:
    return {
        "type": "tool_execution_end",
        "toolCallId": call_id,
        "result": result,
        "isError": is_error,
    }


def _assistant_end(
    content: str, *, input_tokens: int, output_tokens: int, is_error: bool = False
) -> dict[str, object]:
    return {
        "type": "message_end",
        "message": {
            "role": "assistant",
            "stopReason": "error" if is_error else "stop",
            "content": content,
            "usage": {"input": input_tokens, "output": output_tokens},
        },
    }


def _verified_request(
    request_index: int,
    *,
    payload: str | None = None,
    segments: tuple[ContextSegmentSummary, ...] | None = None,
) -> ProviderRequestObservation:
    return ProviderRequestObservation.build(
        request_index=request_index,
        payload_sha256=_digest(payload or f"exact-payload-{request_index}"),
        payload_bytes=13,
        shape_sha256=_digest(f"shape-{request_index}"),
        field_count=9,
        leaf_count=5,
        text_characters=42,
        private_reference_sha256=_digest(f"private-record-{request_index}"),
        segments=segments
        if segments is not None
        else (
            ContextSegmentSummary(
                0, "system", "contract", _digest("sys"), 3, None, False
            ),
            ContextSegmentSummary(
                1,
                "user",
                "message",
                _digest(f"question-{request_index}"),
                8,
                None,
                False,
            ),
        ),
    )


class PiObservationBuilderTests(unittest.TestCase):
    def test_reconciles_verified_provider_request_atomically(self) -> None:
        builder = PiObservationBuilder(_clock)
        builder.consume(_provider_context(1, [_user("inferred-private")]), 10)
        request = _verified_request(1)

        builder.reconcile_provider_requests((request,))
        batch = builder.complete("run")

        self.assertEqual(batch.model_calls[0].request_sha256, request.payload_sha256)
        self.assertEqual(batch.frames[0].segments, request.segments)
        self.assertEqual(batch.provider_requests, (request,))
        self.assertNotIn("model-request", batch.missing_evidence)
        self.assertIn("model-request-boundary", batch.missing_evidence)

    def test_reconciliation_rejects_duplicate_noncontiguous_and_wrong_count(self) -> None:
        builder = PiObservationBuilder(_clock)
        builder.consume(_provider_context(1, [_user("one")]), 10)
        builder.consume(_provider_context(2, [_user("two")]), 20)
        inferred = builder.complete("run")
        request = _verified_request(1)
        cases = (
            (request, request),
            (_verified_request(2), _verified_request(3)),
            (request,),
        )

        for values in cases:
            with self.subTest(indexes=tuple(value.request_index for value in values)):
                builder.reconcile_provider_requests(values)
                batch = builder.complete("run")
                self.assertEqual(batch.provider_requests, ())
                self.assertEqual(batch.frames, inferred.frames)
                self.assertEqual(batch.model_calls, inferred.model_calls)
                self.assertEqual(batch.missing_evidence, inferred.missing_evidence)

    def test_provider_request_rejects_segment_index_drift(self) -> None:
        with self.assertRaises(PathlightError):
            _verified_request(
                1,
                segments=(
                    ContextSegmentSummary(
                        1, "user", "message", _digest("question"), 8, None, False
                    ),
                ),
            )

    def test_rollback_crossing_reconciliation_discards_verified_requests(self) -> None:
        builder = PiObservationBuilder(_clock)
        checkpoint = builder.checkpoint()
        builder.consume(_provider_context(1, [_user("discarded")]), 10)
        builder.reconcile_provider_requests((_verified_request(1),))

        builder.rollback(checkpoint)
        builder.consume(_provider_context(1, [_user("kept")]), 20)
        batch = builder.complete("run")

        self.assertEqual(batch.provider_requests, ())
        self.assertEqual(batch.model_calls[0].request_sha256, _digest(json.dumps(
            [_user("kept")], sort_keys=True, separators=(",", ":")
        )))

    def test_reconciliation_after_rollback_uses_retried_request(self) -> None:
        builder = PiObservationBuilder(_clock)
        checkpoint = builder.checkpoint()
        builder.consume(_provider_context(1, [_user("discarded")]), 10)
        builder.rollback(checkpoint)
        builder.consume(_provider_context(1, [_user("kept")]), 20)
        request = _verified_request(1, payload="kept-exact-payload")

        builder.reconcile_provider_requests((request,))
        batch = builder.complete("run")

        self.assertEqual(batch.provider_requests, (request,))
        self.assertEqual(batch.model_calls[0].request_sha256, request.payload_sha256)

    def test_v2_provider_request_round_trip_is_content_safe_and_digest_bound(self) -> None:
        builder = PiObservationBuilder(_clock)
        builder.consume(_provider_context(1, [_user("SENTINEL_RAW_REQUEST")]), 10)
        request = _verified_request(1, payload="SENTINEL_RAW_REQUEST")
        builder.reconcile_provider_requests((request,))
        batch = builder.complete("run")

        mapping = batch.to_mapping()
        validated = validate_runtime_observation_batch(mapping)

        self.assertEqual(mapping["schema"], "asterion.pathlight-runtime-observation/v2")
        self.assertEqual(validated, batch)
        self.assertNotIn("SENTINEL_RAW_REQUEST", json.dumps(mapping))
        changed = RuntimeObservationBatch.build(
            run_sha256=batch.run_sha256,
            frames=batch.frames,
            model_calls=batch.model_calls,
            tools=batch.tools,
            provider_requests=(
                ProviderRequestObservation.build(
                    request_index=1,
                    payload_sha256=request.payload_sha256,
                    payload_bytes=request.payload_bytes + 1,
                    shape_sha256=request.shape_sha256,
                    field_count=request.field_count,
                    leaf_count=request.leaf_count,
                    text_characters=request.text_characters,
                    private_reference_sha256=request.private_reference_sha256,
                    segments=request.segments,
                ),
            ),
            missing_evidence=batch.missing_evidence,
        )
        self.assertNotEqual(changed.batch_sha256, batch.batch_sha256)

        falsely_timed_call = type(batch.model_calls[0])(
            request_index=batch.model_calls[0].request_index,
            frame_sha256=batch.model_calls[0].frame_sha256,
            model_sha256=batch.model_calls[0].model_sha256,
            request_sha256=batch.model_calls[0].request_sha256,
            response_sha256=batch.model_calls[0].response_sha256,
            response_length=batch.model_calls[0].response_length,
            input_tokens=batch.model_calls[0].input_tokens,
            output_tokens=batch.model_calls[0].output_tokens,
            status=batch.model_calls[0].status,
            boundary_observed=True,
        )
        with self.assertRaises(PathlightError):
            RuntimeObservationBatch.build(
                run_sha256=batch.run_sha256,
                frames=batch.frames,
                model_calls=(falsely_timed_call,),
                tools=batch.tools,
                provider_requests=batch.provider_requests,
                missing_evidence=tuple(
                    label
                    for label in batch.missing_evidence
                    if label != "model-request-boundary"
                ),
            )

        legacy = dict(mapping)
        legacy["schema"] = "asterion.pathlight-runtime-observation/v1"
        with self.assertRaises(PathlightError):
            validate_runtime_observation_batch(legacy)

    def test_links_tool_result_into_the_next_model_frame(self) -> None:
        builder = PiObservationBuilder(_clock)
        builder.consume(_provider_context(1, [_user("q")]), 10)
        builder.consume(_tool_start("c1", "grep", {"pattern": "secret"}), 20)
        builder.consume(_tool_end("c1", "secret result", False), 30)
        builder.consume(
            _provider_context(2, [_user("q"), _tool_result("c1", "secret result")]),
            40,
        )
        builder.consume(_assistant_end("answer", input_tokens=20, output_tokens=4), 50)

        batch = builder.complete("run-private")

        self.assertEqual(len(batch.frames), 2)
        self.assertEqual(len(batch.model_calls), 2)
        self.assertEqual(batch.frames[1].segments[-1].source_call_sha256, _digest("c1"))
        self.assertEqual(
            (batch.frames[1].segments[-1].content_sha256, batch.frames[1].segments[-1].content_length),
            (batch.tools[0].result_sha256, batch.tools[0].result_length),
        )
        self.assertNotIn("secret", json.dumps(batch.to_mapping()))
        self.assertNotIn("SENTINEL_PROVIDER", repr(batch))

    def test_transformed_tool_result_keeps_observed_context_without_lineage(self) -> None:
        builder = PiObservationBuilder(_clock)
        builder.consume(_provider_context(1, [_user("q")]), 10)
        builder.consume(_tool_start("c1", "grep", {"pattern": "private"}), 20)
        builder.consume(_tool_end("c1", "private complete result", False), 30)
        builder.consume(
            _provider_context(
                2,
                [
                    _user("q"),
                    _tool_result("c1", "private truncated result"),
                ],
            ),
            40,
        )

        batch = builder.complete("run-private")
        segment = batch.frames[1].segments[-1]

        self.assertEqual(segment.content_sha256, _digest("private truncated result"))
        self.assertEqual(segment.content_length, len("private truncated result"))
        self.assertIsNone(segment.source_call_sha256)
        self.assertTrue(segment.missing_evidence)
        self.assertIn("context-segment", batch.missing_evidence)
        self.assertEqual(batch.tools[0].result_sha256, _digest("private complete result"))
        rendered = json.dumps(batch.to_mapping())
        self.assertNotIn("private complete result", rendered)
        self.assertNotIn("private truncated result", rendered)

    def test_rollback_discards_a_retried_attempt(self) -> None:
        builder = PiObservationBuilder(_clock)
        checkpoint = builder.checkpoint()
        builder.consume(_provider_context(1, [_user("discarded")]), 10)
        builder.consume(_assistant_end("discarded", input_tokens=1, output_tokens=1), 20)
        builder.rollback(checkpoint)
        builder.consume(_provider_context(1, [_user("kept")]), 30)
        builder.consume(_assistant_end("kept", input_tokens=2, output_tokens=3), 40)

        batch = builder.complete("run")

        self.assertEqual(len(batch.frames), 1)
        self.assertEqual(len(batch.model_calls), 1)
        self.assertEqual(batch.model_calls[0].input_tokens, 2)
        self.assertNotIn("discarded", json.dumps(batch.to_mapping()))

    def test_duplicate_request_index_fails_closed_to_missing_request_evidence(self) -> None:
        builder = PiObservationBuilder(_clock)
        builder.consume(_provider_context(1, [_user("one")]), 10)
        builder.consume(_provider_context(1, [_user("duplicate")]), 11)

        batch = builder.complete("run")

        self.assertEqual(batch.frames, ())
        self.assertEqual(batch.model_calls, ())
        self.assertEqual(
            batch.missing_evidence,
            ("context-frame", "model-request", "model-request-boundary"),
        )

    def test_initial_request_index_cannot_skip_without_a_retry_boundary(self) -> None:
        builder = PiObservationBuilder(_clock)
        builder.consume(_provider_context(3, [_user("partial")]), 10)

        batch = builder.complete("run")

        self.assertEqual(batch.frames, ())
        self.assertEqual(batch.model_calls, ())
        self.assertIn("context-frame", batch.missing_evidence)

    def test_malformed_context_and_unmatched_tool_result_are_explicitly_missing(self) -> None:
        builder = PiObservationBuilder(_clock)
        builder.consume({"type": "provider_request_context", "requestIndex": 1}, 1)
        builder.consume(_tool_end("unmatched", "private", False), 2)

        batch = builder.complete("run")

        self.assertIn("context-segment", batch.missing_evidence)
        self.assertIn("model-identity", batch.missing_evidence)
        self.assertIn("model-request", batch.missing_evidence)
        self.assertIn("tool-boundary", batch.missing_evidence)
        self.assertIn("tool-identity", batch.missing_evidence)
        self.assertIn("tool-arguments", batch.missing_evidence)
        self.assertNotIn("private", json.dumps(batch.to_mapping()))

    def test_tool_error_is_retained_without_result_leakage(self) -> None:
        builder = PiObservationBuilder(_clock)
        builder.consume(_provider_context(1, [_user("q")]), 10)
        builder.consume(_tool_start("c1", "grep", {"private": "args"}), 20)
        builder.consume(_tool_end("c1", "private error", True), 30)
        builder.consume(_assistant_end("answer", input_tokens=1, output_tokens=2), 40)

        batch = builder.complete("run")

        self.assertEqual(batch.tools[0].status, "failed")
        self.assertNotIn("private", json.dumps(batch.to_mapping()))

    def test_repeated_timestamps_do_not_change_the_observation(self) -> None:
        builder = PiObservationBuilder(_clock)
        builder.consume(_provider_context(1, [_user("q")]), 7)
        builder.consume(_assistant_end("answer", input_tokens=1, output_tokens=2), 7)

        batch = builder.complete("run")

        self.assertEqual(batch.model_calls[0].status, "completed")
        self.assertEqual(batch.model_calls[0].input_tokens, 1)

    def test_no_provider_context_is_conservatively_explicit(self) -> None:
        builder = PiObservationBuilder(_clock)
        builder.consume(_tool_start("c1", "grep", {"x": "private"}), 1)

        batch = builder.complete("cancelled-run")

        self.assertEqual(batch.frames, ())
        self.assertEqual(batch.model_calls, ())
        self.assertIn("context-frame", batch.missing_evidence)
        self.assertIn("model-request-boundary", batch.missing_evidence)


if __name__ == "__main__":
    unittest.main()
