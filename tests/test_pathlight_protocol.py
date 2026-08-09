from __future__ import annotations

import copy
import hashlib
import json
import unittest

from asterion.pathlight import (
    PathlightError,
    TraceEvent,
    TraceGraph,
    trace_graph_digest,
    validate_trace_graph,
)


def opaque_id(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012x}"


TRACE_ID = opaque_id(1)
OTHER_TRACE_ID = opaque_id(2)
ROOT_SPAN_ID = opaque_id(3)
CHILD_SPAN_ID = opaque_id(4)
MISSING_SPAN_ID = opaque_id(5)


class PathlightProtocolTests(unittest.TestCase):
    def test_accepts_closed_long_running_control_kinds_and_attributes(self) -> None:
        event = TraceEvent.start(
            TRACE_ID,
            ROOT_SPAN_ID,
            None,
            1,
            "system",
            attributes={
                "session_id": "a" * 64,
                "control_event_sha256": "b" * 64,
                "control_event_type": "session.running",
                "control_status": "running",
                "generation": 1,
                "event_sequence": 2,
                "authority_revision": 1,
                "journal_position": 4,
            },
        )

        self.assertEqual(event.kind, "system")
        self.assertEqual(event.attributes["control_status"], "running")

    def test_rejects_terminal_duration_that_disagrees_with_monotonic_timestamps(
        self,
    ) -> None:
        trace_id = TRACE_ID
        span_id = ROOT_SPAN_ID
        with self.assertRaisesRegex(PathlightError, "duration"):
            TraceGraph.build(
                trace_id,
                (
                    TraceEvent.start(
                        trace_id, span_id, None, 1, "task", timestamp_ns=10
                    ),
                    TraceEvent.complete(
                        trace_id,
                        span_id,
                        2,
                        timestamp_ns=30,
                        attributes={"duration_ns": 19},
                    ),
                ),
            )

    STRING_ATTRIBUTE_VALUES = {
        "action_id": "a" * 64,
        "artifact_id": "a" * 64,
        "authority_id": "a" * 64,
        "call_id": "a" * 64,
        "checkpoint_id": "a" * 64,
        "component_id": "a" * 64,
        "control_event_sha256": "a" * 64,
        "control_event_type": "session.running",
        "control_reason_sha256": "a" * 64,
        "control_status": "running",
        "content_sha256": "a" * 64,
        "coverage_sha256": "a" * 64,
        "evidence_ref": "a" * 64,
        "event_id": "a" * 64,
        "failure_class": "unknown",
        "goal_id": "a" * 64,
        "metric_contract_id": "a" * 64,
        "metric_name": "input-tokens",
        "model_id": "a" * 64,
        "observation_sha256": "a" * 64,
        "policy_sha256": "a" * 64,
        "request_sha256": "a" * 64,
        "response_sha256": "a" * 64,
        "runtime_id": "a" * 64,
        "session_id": "a" * 64,
        "scope_sha256": "a" * 64,
        "segment_role": "assistant",
        "source_call_sha256": "a" * 64,
        "structure_kind": "context-frame",
        "tool_id": "a" * 64,
        "system_id": "a" * 64,
        "unit": "count",
    }

    def test_accepts_only_fixed_native_observation_attributes(self) -> None:
        attributes = {
            "boundary_observed": True,
            "frame_index": 1,
            "request_index": 2,
            "segment_count": 3,
            "segment_index": 0,
            "segment_role": "tool-result",
            "source_call_sha256": "a" * 64,
            "request_sha256": "b" * 64,
            "response_sha256": "c" * 64,
            "response_length": 4,
            "observation_sha256": "d" * 64,
            "structure_kind": "message",
        }

        event = TraceEvent.start(
            TRACE_ID, ROOT_SPAN_ID, None, 1, "context-frame", attributes=attributes
        )

        self.assertEqual(dict(event.attributes), attributes)
        for key in ("frame_index", "request_index", "segment_count", "segment_index"):
            with self.subTest(key=key), self.assertRaises(PathlightError):
                TraceEvent.start(
                    TRACE_ID,
                    ROOT_SPAN_ID,
                    None,
                    1,
                    "context-frame",
                    attributes={key: True},
                )

    def test_missing_evidence_labels_are_closed_sorted_and_immutable(self) -> None:
        event = TraceEvent.start(
            TRACE_ID,
            ROOT_SPAN_ID,
            None,
            1,
            "model-call",
            attributes={"missing_evidence_labels": ("model-request-boundary",)},
        )

        self.assertEqual(
            event.attributes["missing_evidence_labels"],
            ("model-request-boundary",),
        )
        mapping = TraceGraph.build(
            TRACE_ID,
            (event, TraceEvent.complete(TRACE_ID, ROOT_SPAN_ID, 2, kind="model-call")),
        ).to_mapping()
        self.assertEqual(
            mapping["events"][0]["attributes"]["missing_evidence_labels"],
            ["model-request-boundary"],
        )
        for labels in (
            ["model-request-boundary"],
            ("model-request-boundary", "model-request-boundary"),
            ("model-response", "model-request-boundary"),
            ("SENTINEL_PRIVATE_GAP_REASON",),
        ):
            with self.subTest(labels=labels), self.assertRaises(PathlightError):
                TraceEvent.start(
                    TRACE_ID,
                    ROOT_SPAN_ID,
                    None,
                    1,
                    "model-call",
                    attributes={"missing_evidence_labels": labels},
                )

    def complete_graph(self) -> TraceGraph:
        return TraceGraph.build(
            trace_id=TRACE_ID,
            events=(
                TraceEvent.start(
                    TRACE_ID,
                    ROOT_SPAN_ID,
                    None,
                    1,
                    "task",
                    attributes={"component_id": "a" * 64},
                    timestamp_ns=10,
                ),
                TraceEvent.start(
                    TRACE_ID,
                    CHILD_SPAN_ID,
                    ROOT_SPAN_ID,
                    2,
                    "tool-call",
                    attributes={
                        "content_sha256": "a" * 64,
                        "content_length": 12,
                    },
                    links=(
                        {
                            "relation": "caused-next",
                            "trace_id": TRACE_ID,
                            "span_id": ROOT_SPAN_ID,
                        },
                    ),
                    timestamp_ns=20,
                ),
                TraceEvent.complete(
                    TRACE_ID, CHILD_SPAN_ID, 3, kind="tool-call", timestamp_ns=30
                ),
                TraceEvent.complete(TRACE_ID, ROOT_SPAN_ID, 4, timestamp_ns=40),
            ),
        )

    def test_trace_graph_preserves_context_flow_without_text(self) -> None:
        graph = TraceGraph.build(
            trace_id=TRACE_ID,
            events=(
                TraceEvent.start(TRACE_ID, ROOT_SPAN_ID, None, 1, "task"),
                TraceEvent.complete(TRACE_ID, ROOT_SPAN_ID, 2),
            ),
        )

        payload = graph.to_mapping()

        self.assertEqual(payload["schema"], "asterion.pathlight-trace/v1")
        self.assertNotIn("input_text", repr(payload))
        validate_trace_graph(payload)

    def test_rejects_noncontiguous_sequence_and_unknown_parent(self) -> None:
        with self.assertRaises(PathlightError):
            TraceGraph.build(
                TRACE_ID,
                (TraceEvent.start(TRACE_ID, opaque_id(6), MISSING_SPAN_ID, 2, "task"),),
            )

    def test_canonical_mapping_has_a_stable_digest(self) -> None:
        payload = self.complete_graph().to_mapping()

        self.assertEqual(payload["trace_sha256"], trace_graph_digest(payload))
        self.assertEqual(
            payload["trace_sha256"],
            hashlib.sha256(
                json.dumps(
                    {
                        key: value
                        for key, value in payload.items()
                        if key != "trace_sha256"
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )

    def test_graph_is_not_affected_by_source_attribute_or_link_mutation(self) -> None:
        attributes = {"content_length": 1}
        link = {
            "relation": "related-to",
            "trace_id": TRACE_ID,
            "span_id": ROOT_SPAN_ID,
        }
        event = TraceEvent.start(
            TRACE_ID,
            ROOT_SPAN_ID,
            None,
            1,
            "task",
            attributes=attributes,
            links=(link,),
        )
        attributes["content_length"] = 99
        link["span_id"] = "changed"
        graph = TraceGraph.build(
            TRACE_ID, (event, TraceEvent.complete(TRACE_ID, ROOT_SPAN_ID, 2))
        )

        payload = graph.to_mapping()

        self.assertEqual(payload["events"][0]["attributes"]["content_length"], 1)
        self.assertEqual(payload["events"][0]["links"][0]["span_id"], ROOT_SPAN_ID)
        with self.assertRaises(TypeError):
            event.attributes["content_length"] = 2  # type: ignore[index]

    def test_rejects_unsafe_attributes_and_private_content_sentinel(self) -> None:
        for name, attributes in {
            "unknown-key": {"input_text": "sentinel-private-content"},
            "prompt-key": {"prompt_sha256": "a" * 64},
            "raw-string-metric": {"metric_value": "sentinel-private-content"},
            "bad-digest": {"content_sha256": "sentinel-private-content"},
            "negative-length": {"content_length": -1},
            "bool-length": {"content_length": True},
        }.items():
            with self.subTest(name=name), self.assertRaises(PathlightError):
                TraceEvent.start(
                    TRACE_ID, ROOT_SPAN_ID, None, 1, "task", attributes=attributes
                )

    def test_rejects_private_content_for_every_string_attribute(self) -> None:
        for key in self.STRING_ATTRIBUTE_VALUES:
            with self.subTest(key=key), self.assertRaises(PathlightError):
                TraceEvent.start(
                    TRACE_ID,
                    ROOT_SPAN_ID,
                    None,
                    1,
                    "task",
                    attributes={key: "sentinel-private-content"},
                )

    def test_accepts_only_trusted_public_string_attribute_values(self) -> None:
        for key, value in self.STRING_ATTRIBUTE_VALUES.items():
            with self.subTest(key=key):
                event = TraceEvent.start(
                    TRACE_ID, ROOT_SPAN_ID, None, 1, "task", attributes={key: value}
                )
                self.assertEqual(event.attributes[key], value)

    def test_rejects_private_content_for_every_core_identifier(self) -> None:
        cases = {
            "trace-id": {
                "trace_id": "sentinel-private-content",
                "span_id": ROOT_SPAN_ID,
                "parent_span_id": None,
                "links": (),
            },
            "span-id": {
                "trace_id": TRACE_ID,
                "span_id": "sentinel-private-content",
                "parent_span_id": None,
                "links": (),
            },
            "parent-span-id": {
                "trace_id": TRACE_ID,
                "span_id": CHILD_SPAN_ID,
                "parent_span_id": "sentinel-private-content",
                "links": (),
            },
            "link-trace-id": {
                "trace_id": TRACE_ID,
                "span_id": ROOT_SPAN_ID,
                "parent_span_id": None,
                "links": (
                    {
                        "relation": "related-to",
                        "trace_id": "sentinel-private-content",
                        "span_id": ROOT_SPAN_ID,
                    },
                ),
            },
            "link-span-id": {
                "trace_id": TRACE_ID,
                "span_id": ROOT_SPAN_ID,
                "parent_span_id": None,
                "links": (
                    {
                        "relation": "related-to",
                        "trace_id": TRACE_ID,
                        "span_id": "sentinel-private-content",
                    },
                ),
            },
        }
        for name, values in cases.items():
            with self.subTest(name=name), self.assertRaises(PathlightError):
                TraceEvent.start(sequence=1, kind="task", **values)

    def test_rejects_malformed_identity_parentage_lifecycle_and_sequences(self) -> None:
        cases = {
            "trace-mismatch": (
                TraceEvent.start(OTHER_TRACE_ID, ROOT_SPAN_ID, None, 1, "task"),
                TraceEvent.complete(OTHER_TRACE_ID, ROOT_SPAN_ID, 2),
            ),
            "missing-root": (
                TraceEvent.start(TRACE_ID, CHILD_SPAN_ID, MISSING_SPAN_ID, 1, "task"),
                TraceEvent.complete(TRACE_ID, CHILD_SPAN_ID, 2),
            ),
            "second-root": (
                TraceEvent.start(TRACE_ID, opaque_id(6), None, 1, "task"),
                TraceEvent.start(TRACE_ID, opaque_id(7), None, 2, "task"),
                TraceEvent.complete(TRACE_ID, opaque_id(6), 3),
                TraceEvent.complete(TRACE_ID, opaque_id(7), 4),
            ),
            "duplicate-start": (
                TraceEvent.start(TRACE_ID, ROOT_SPAN_ID, None, 1, "task"),
                TraceEvent.start(TRACE_ID, ROOT_SPAN_ID, None, 2, "task"),
                TraceEvent.complete(TRACE_ID, ROOT_SPAN_ID, 3),
            ),
            "unmatched-terminal": (TraceEvent.complete(TRACE_ID, ROOT_SPAN_ID, 1),),
            "open-span": (TraceEvent.start(TRACE_ID, ROOT_SPAN_ID, None, 1, "task"),),
            "parent-terminates-before-child": (
                TraceEvent.start(TRACE_ID, ROOT_SPAN_ID, None, 1, "task"),
                TraceEvent.start(TRACE_ID, CHILD_SPAN_ID, ROOT_SPAN_ID, 2, "task"),
                TraceEvent.complete(TRACE_ID, ROOT_SPAN_ID, 3),
                TraceEvent.complete(TRACE_ID, CHILD_SPAN_ID, 4),
            ),
            "sequence-gap": (
                TraceEvent.start(TRACE_ID, ROOT_SPAN_ID, None, 1, "task"),
                TraceEvent.complete(TRACE_ID, ROOT_SPAN_ID, 3),
            ),
            "sequence-out-of-order": (
                TraceEvent.start(TRACE_ID, ROOT_SPAN_ID, None, 2, "task"),
                TraceEvent.complete(TRACE_ID, ROOT_SPAN_ID, 1),
            ),
        }
        for name, events in cases.items():
            with self.subTest(name=name), self.assertRaises(PathlightError):
                TraceGraph.build(TRACE_ID, events)

    def test_rejects_cross_trace_link_and_unknown_link_target(self) -> None:
        for name, link in {
            "cross-trace": {
                "relation": "derived-from",
                "trace_id": OTHER_TRACE_ID,
                "span_id": ROOT_SPAN_ID,
            },
            "unknown-target": {
                "relation": "derived-from",
                "trace_id": TRACE_ID,
                "span_id": MISSING_SPAN_ID,
            },
        }.items():
            with self.subTest(name=name), self.assertRaises(PathlightError):
                TraceGraph.build(
                    TRACE_ID,
                    (
                        TraceEvent.start(
                            TRACE_ID, ROOT_SPAN_ID, None, 1, "task", links=(link,)
                        ),
                        TraceEvent.complete(TRACE_ID, ROOT_SPAN_ID, 2),
                    ),
                )

    def test_validator_rejects_unknown_fields_and_digest_mismatch(self) -> None:
        payload = self.complete_graph().to_mapping()
        cases = {
            "unknown-graph-field": {**payload, "private_path": "/secret"},
            "unknown-event-field": {
                **payload,
                "events": [
                    {**payload["events"][0], "answer": "sentinel-private-content"},
                    *payload["events"][1:],
                ],
            },
            "digest-mismatch": {**payload, "trace_id": OTHER_TRACE_ID},
        }
        for name, malformed in cases.items():
            with self.subTest(name=name), self.assertRaises(PathlightError):
                validate_trace_graph(malformed)

    def test_validator_does_not_modify_its_input(self) -> None:
        payload = self.complete_graph().to_mapping()
        before = copy.deepcopy(payload)

        validate_trace_graph(payload)

        self.assertEqual(payload, before)


if __name__ == "__main__":
    unittest.main()
