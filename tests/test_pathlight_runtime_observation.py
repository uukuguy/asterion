from __future__ import annotations

import copy
import hashlib
import json
import unittest
from typing import cast

from asterion.pathlight import PathlightError
from asterion.pathlight.runtime_observation import (
    ContextFrameObservation,
    ContextSegmentSummary,
    ModelCallObservation,
    RuntimeObservationBatch,
    ToolCallObservation,
    validate_runtime_observation_batch,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_batch() -> RuntimeObservationBatch:
    first_segment = ContextSegmentSummary(
        segment_index=0,
        role="user",
        structure_kind="message",
        content_sha256=_digest("secret input"),
        content_length=12,
        source_call_sha256=None,
        missing_evidence=False,
    )
    second_segment = ContextSegmentSummary(
        segment_index=1,
        role="tool-result",
        structure_kind="tool-result",
        content_sha256=_digest("secret tool result"),
        content_length=18,
        source_call_sha256=_digest("call-1"),
        missing_evidence=False,
    )
    frame = ContextFrameObservation(
        frame_index=1, segments=(first_segment, second_segment)
    )
    call = ModelCallObservation(
        request_index=1,
        frame_sha256=frame.frame_sha256,
        model_sha256=_digest("model identity"),
        request_sha256=_digest("request"),
        response_sha256=_digest("response"),
        response_length=8,
        input_tokens=10,
        output_tokens=3,
        status="completed",
        boundary_observed=True,
    )
    tool = ToolCallObservation(
        call_sha256=_digest("call-1"),
        tool_sha256=_digest("tool identity"),
        arguments_sha256=_digest("secret arguments"),
        result_sha256=_digest("secret tool result"),
        result_length=18,
        status="completed",
    )
    return RuntimeObservationBatch.build(
        run_sha256=_digest("run"),
        frames=(frame,),
        model_calls=(call,),
        tools=(tool,),
    )


def _valid_batch_mapping() -> dict[str, object]:
    return _valid_batch().to_mapping()


class RuntimeObservationTests(unittest.TestCase):
    def test_runtime_observation_is_canonical_content_safe_and_closed(self) -> None:
        batch = _valid_batch()

        self.assertEqual(validate_runtime_observation_batch(batch.to_mapping()), batch)
        rendered = json.dumps(batch.to_mapping())
        self.assertNotIn("secret input", rendered)
        self.assertNotIn("secret tool result", rendered)
        self.assertNotIn("secret arguments", rendered)

    def test_runtime_observation_rejects_unknown_fields_and_noncanonical_order(self) -> None:
        mapping = _valid_batch_mapping()
        frames = mapping["frames"]
        assert type(frames) is list
        first_frame = frames[0]
        assert type(first_frame) is dict
        segments = first_frame["segments"]
        assert type(segments) is list
        segments.reverse()
        with self.assertRaisesRegex(PathlightError, "runtime observation is invalid"):
            validate_runtime_observation_batch(mapping)

        mapping = _valid_batch_mapping()
        mapping["private_prompt"] = "SENTINEL_PRIVATE"
        with self.assertRaisesRegex(PathlightError, "runtime observation is invalid"):
            validate_runtime_observation_batch(mapping)

    def test_runtime_observation_requires_contiguous_indexes_resolved_frames_and_unique_calls(self) -> None:
        cases: dict[str, dict[str, object]] = {}

        noncontiguous = _valid_batch_mapping()
        frames = noncontiguous["frames"]
        assert type(frames) is list
        frame = frames[0]
        assert type(frame) is dict
        frame["frame_index"] = 2
        cases["frame indexes"] = noncontiguous

        unresolved_frame = _valid_batch_mapping()
        model_calls = unresolved_frame["model_calls"]
        assert type(model_calls) is list
        model_call = model_calls[0]
        assert type(model_call) is dict
        model_call["frame_sha256"] = _digest("unknown frame")
        cases["model call frame"] = unresolved_frame

        duplicate_tools = _valid_batch_mapping()
        tools = duplicate_tools["tools"]
        assert type(tools) is list
        tools.append(copy.deepcopy(tools[0]))
        cases["tool calls"] = duplicate_tools

        for name, mapping in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(
                PathlightError, "runtime observation is invalid"
            ):
                validate_runtime_observation_batch(mapping)

    def test_runtime_observation_rejects_subclasses_and_private_string_fields(self) -> None:
        class HostileDict(dict[str, object]):
            pass

        class HostileList(list[object]):
            pass

        with self.assertRaisesRegex(PathlightError, "runtime observation is invalid"):
            validate_runtime_observation_batch(HostileDict(_valid_batch_mapping()))

        mapping = _valid_batch_mapping()
        mapping["missing_evidence"] = HostileList()
        with self.assertRaisesRegex(PathlightError, "runtime observation is invalid"):
            validate_runtime_observation_batch(mapping)

        for field in ("request_sha256", "response_sha256", "model_sha256"):
            mapping = _valid_batch_mapping()
            calls = mapping["model_calls"]
            assert type(calls) is list
            call = calls[0]
            assert type(call) is dict
            call[field] = "SENTINEL_PRIVATE"
            with self.subTest(field=field), self.assertRaisesRegex(
                PathlightError, "runtime observation is invalid"
            ):
                validate_runtime_observation_batch(mapping)

    def test_missing_request_boundary_is_explicit_and_canonical(self) -> None:
        segment = ContextSegmentSummary(
            segment_index=0,
            role="unknown",
            structure_kind="missing",
            content_sha256=None,
            content_length=None,
            source_call_sha256=None,
            missing_evidence=True,
        )
        frame = ContextFrameObservation(frame_index=1, segments=(segment,))
        call = ModelCallObservation(
            request_index=1,
            frame_sha256=frame.frame_sha256,
            model_sha256=None,
            request_sha256=None,
            response_sha256=None,
            response_length=None,
            input_tokens=None,
            output_tokens=None,
            status="missing",
            boundary_observed=False,
        )
        batch = RuntimeObservationBatch.build(
            run_sha256=_digest("run"),
            frames=(frame,),
            model_calls=(call,),
            tools=(),
            missing_evidence=(
                "context-segment",
                "model-identity",
                "model-request",
                "model-request-boundary",
                "model-response",
                "token-usage",
            ),
        )

        self.assertEqual(
            batch.missing_evidence,
            (
                "context-segment",
                "model-identity",
                "model-request",
                "model-request-boundary",
                "model-response",
                "token-usage",
            ),
        )
        self.assertEqual(validate_runtime_observation_batch(batch.to_mapping()), batch)

    def test_tool_result_segment_must_match_its_exact_tool_observation(self) -> None:
        tool = _valid_batch().tools[0]
        for name, content_sha256, content_length in (
            ("digest", _digest("other result"), tool.result_length),
            ("length", tool.result_sha256, 99),
        ):
            segment = ContextSegmentSummary(
                segment_index=0,
                role="tool-result",
                structure_kind="tool-result",
                content_sha256=content_sha256,
                content_length=content_length,
                source_call_sha256=tool.call_sha256,
                missing_evidence=False,
            )
            frame = ContextFrameObservation(frame_index=1, segments=(segment,))
            call = ModelCallObservation(
                request_index=1,
                frame_sha256=frame.frame_sha256,
                model_sha256=_digest("model identity"),
                request_sha256=_digest("request"),
                response_sha256=_digest("response"),
                response_length=8,
                input_tokens=10,
                output_tokens=3,
                status="completed",
                boundary_observed=True,
            )
            with self.subTest(name=name), self.assertRaisesRegex(
                PathlightError, "runtime observation is invalid"
            ):
                RuntimeObservationBatch.build(
                    run_sha256=_digest("run"),
                    frames=(frame,),
                    model_calls=(call,),
                    tools=(tool,),
                )

    def test_missing_optional_facts_require_every_derived_evidence_label(self) -> None:
        segment = ContextSegmentSummary(
            segment_index=0,
            role="unknown",
            structure_kind="missing",
            content_sha256=None,
            content_length=None,
            source_call_sha256=None,
            missing_evidence=True,
        )
        frame = ContextFrameObservation(frame_index=1, segments=(segment,))
        call = ModelCallObservation(
            request_index=1,
            frame_sha256=frame.frame_sha256,
            model_sha256=None,
            request_sha256=None,
            response_sha256=None,
            response_length=None,
            input_tokens=None,
            output_tokens=None,
            status="missing",
            boundary_observed=False,
        )
        expected_labels = (
            "context-segment",
            "model-identity",
            "model-request",
            "model-request-boundary",
            "model-response",
            "token-usage",
        )

        for omitted in expected_labels:
            labels = tuple(label for label in expected_labels if label != omitted)
            with self.subTest(omitted=omitted), self.assertRaisesRegex(
                PathlightError, "runtime observation is invalid"
            ):
                RuntimeObservationBatch.build(
                    run_sha256=_digest("run"),
                    frames=(frame,),
                    model_calls=(call,),
                    tools=(),
                    missing_evidence=labels,
                )

    def test_unobserved_tool_result_is_empty_linked_and_explicit(self) -> None:
        tool = ToolCallObservation(
            call_sha256=_digest("call-1"),
            tool_sha256=_digest("tool identity"),
            arguments_sha256=_digest("secret arguments"),
            result_sha256=None,
            result_length=None,
            status="completed",
        )
        segment = ContextSegmentSummary(
            segment_index=0,
            role="tool-result",
            structure_kind="tool-result",
            content_sha256=None,
            content_length=None,
            source_call_sha256=tool.call_sha256,
            missing_evidence=True,
        )
        frame = ContextFrameObservation(frame_index=1, segments=(segment,))
        call = ModelCallObservation(
            request_index=1,
            frame_sha256=frame.frame_sha256,
            model_sha256=_digest("model identity"),
            request_sha256=_digest("request"),
            response_sha256=_digest("response"),
            response_length=8,
            input_tokens=10,
            output_tokens=3,
            status="completed",
            boundary_observed=True,
        )

        with self.assertRaisesRegex(PathlightError, "runtime observation is invalid"):
            RuntimeObservationBatch.build(
                run_sha256=_digest("run"),
                frames=(frame,),
                model_calls=(call,),
                tools=(tool,),
            )

        batch = RuntimeObservationBatch.build(
            run_sha256=_digest("run"),
            frames=(frame,),
            model_calls=(call,),
            tools=(tool,),
            missing_evidence=("context-segment", "tool-result"),
        )
        self.assertEqual(validate_runtime_observation_batch(batch.to_mapping()), batch)

    def test_missing_tool_facts_require_fixed_evidence_labels(self) -> None:
        tool = ToolCallObservation(
            call_sha256=_digest("call-1"),
            tool_sha256=None,
            arguments_sha256=None,
            result_sha256=None,
            result_length=None,
            status="completed",
        )
        expected_labels = ("tool-arguments", "tool-identity", "tool-result")

        for omitted in expected_labels:
            labels = tuple(label for label in expected_labels if label != omitted)
            with self.subTest(omitted=omitted), self.assertRaisesRegex(
                PathlightError, "runtime observation is invalid"
            ):
                RuntimeObservationBatch.build(
                    run_sha256=_digest("run"),
                    frames=(),
                    model_calls=(),
                    tools=(tool,),
                    missing_evidence=labels,
                )

    def test_hostile_keys_and_values_are_normalized_without_invocation_or_leakage(self) -> None:
        class HostileKey:
            def __init__(self, hash_value: int) -> None:
                self.hash_value = hash_value
                self.armed = False
                self.invoked = False

            def __hash__(self) -> int:
                if self.armed:
                    self.invoked = True
                    raise RuntimeError("SENTINEL_PRIVATE_HASH")
                return self.hash_value

            def __eq__(self, other: object) -> bool:
                del other
                if self.armed:
                    self.invoked = True
                    raise RuntimeError("SENTINEL_PRIVATE_EQ")
                return False

        class HostileValue:
            def __eq__(self, other: object) -> bool:
                del other
                raise RuntimeError("SENTINEL_PRIVATE_VALUE")

        hostile_key = HostileKey(hash("schema"))
        hostile_mapping = cast(dict[object, object], dict(_valid_batch_mapping()))
        hostile_mapping[hostile_key] = None
        hostile_key.armed = True
        hostile_key.invoked = False

        cases = {
            "hostile-key": hostile_mapping,
            "hostile-value": {
                **_valid_batch_mapping(),
                "schema": HostileValue(),
            },
        }
        for name, mapping in cases.items():
            with self.subTest(name=name):
                try:
                    validate_runtime_observation_batch(mapping)  # type: ignore[arg-type]
                except Exception as error:
                    self.assertIs(type(error), PathlightError)
                    self.assertEqual(
                        str(error), "Pathlight runtime observation is invalid"
                    )
                    self.assertNotIn("SENTINEL_PRIVATE", str(error))
                else:
                    self.fail("hostile observation mapping was accepted")
        self.assertFalse(hostile_key.invoked)
