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


class PathlightProtocolTests(unittest.TestCase):
    def complete_graph(self) -> TraceGraph:
        return TraceGraph.build(
            trace_id="trace-1",
            events=(
                TraceEvent.start(
                    "trace-1",
                    "root",
                    None,
                    1,
                    "task",
                    attributes={"component_id": "example.runner"},
                    timestamp_ns=10,
                ),
                TraceEvent.start(
                    "trace-1",
                    "child",
                    "root",
                    2,
                    "tool-call",
                    attributes={
                        "content_sha256": "a" * 64,
                        "content_length": 12,
                    },
                    links=(
                        {
                            "relation": "caused-next",
                            "trace_id": "trace-1",
                            "span_id": "root",
                        },
                    ),
                    timestamp_ns=20,
                ),
                TraceEvent.complete(
                    "trace-1", "child", 3, kind="tool-call", timestamp_ns=30
                ),
                TraceEvent.complete("trace-1", "root", 4, timestamp_ns=40),
            ),
        )

    def test_trace_graph_preserves_context_flow_without_text(self) -> None:
        graph = TraceGraph.build(
            trace_id="trace-1",
            events=(
                TraceEvent.start("trace-1", "root", None, 1, "task"),
                TraceEvent.complete("trace-1", "root", 2),
            ),
        )

        payload = graph.to_mapping()

        self.assertEqual(payload["schema"], "asterion.pathlight-trace/v1")
        self.assertNotIn("input_text", repr(payload))
        validate_trace_graph(payload)

    def test_rejects_noncontiguous_sequence_and_unknown_parent(self) -> None:
        with self.assertRaises(PathlightError):
            TraceGraph.build(
                "trace-1",
                (TraceEvent.start("trace-1", "x", "missing", 2, "task"),),
            )

    def test_canonical_mapping_has_a_stable_digest(self) -> None:
        payload = self.complete_graph().to_mapping()

        self.assertEqual(payload["trace_sha256"], trace_graph_digest(payload))
        self.assertEqual(
            payload["trace_sha256"],
            hashlib.sha256(
                json.dumps(
                    {key: value for key, value in payload.items() if key != "trace_sha256"},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )

    def test_graph_is_not_affected_by_source_attribute_or_link_mutation(self) -> None:
        attributes = {"content_length": 1}
        link = {
            "relation": "related-to",
            "trace_id": "trace-1",
            "span_id": "root",
        }
        event = TraceEvent.start(
            "trace-1", "root", None, 1, "task", attributes=attributes, links=(link,)
        )
        attributes["content_length"] = 99
        link["span_id"] = "changed"
        graph = TraceGraph.build(
            "trace-1", (event, TraceEvent.complete("trace-1", "root", 2))
        )

        payload = graph.to_mapping()

        self.assertEqual(payload["events"][0]["attributes"]["content_length"], 1)
        self.assertEqual(payload["events"][0]["links"][0]["span_id"], "root")
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
                TraceEvent.start("trace-1", "root", None, 1, "task", attributes=attributes)

    def test_rejects_malformed_identity_parentage_lifecycle_and_sequences(self) -> None:
        cases = {
            "trace-mismatch": (
                TraceEvent.start("other-trace", "root", None, 1, "task"),
                TraceEvent.complete("other-trace", "root", 2),
            ),
            "missing-root": (
                TraceEvent.start("trace-1", "child", "missing", 1, "task"),
                TraceEvent.complete("trace-1", "child", 2),
            ),
            "second-root": (
                TraceEvent.start("trace-1", "one", None, 1, "task"),
                TraceEvent.start("trace-1", "two", None, 2, "task"),
                TraceEvent.complete("trace-1", "one", 3),
                TraceEvent.complete("trace-1", "two", 4),
            ),
            "duplicate-start": (
                TraceEvent.start("trace-1", "root", None, 1, "task"),
                TraceEvent.start("trace-1", "root", None, 2, "task"),
                TraceEvent.complete("trace-1", "root", 3),
            ),
            "unmatched-terminal": (
                TraceEvent.complete("trace-1", "root", 1),
            ),
            "open-span": (TraceEvent.start("trace-1", "root", None, 1, "task"),),
            "parent-terminates-before-child": (
                TraceEvent.start("trace-1", "root", None, 1, "task"),
                TraceEvent.start("trace-1", "child", "root", 2, "task"),
                TraceEvent.complete("trace-1", "root", 3),
                TraceEvent.complete("trace-1", "child", 4),
            ),
            "sequence-gap": (
                TraceEvent.start("trace-1", "root", None, 1, "task"),
                TraceEvent.complete("trace-1", "root", 3),
            ),
            "sequence-out-of-order": (
                TraceEvent.start("trace-1", "root", None, 2, "task"),
                TraceEvent.complete("trace-1", "root", 1),
            ),
        }
        for name, events in cases.items():
            with self.subTest(name=name), self.assertRaises(PathlightError):
                TraceGraph.build("trace-1", events)

    def test_rejects_cross_trace_link_and_unknown_link_target(self) -> None:
        for name, link in {
            "cross-trace": {
                "relation": "derived-from",
                "trace_id": "other-trace",
                "span_id": "root",
            },
            "unknown-target": {
                "relation": "derived-from",
                "trace_id": "trace-1",
                "span_id": "missing",
            },
        }.items():
            with self.subTest(name=name), self.assertRaises(PathlightError):
                TraceGraph.build(
                    "trace-1",
                    (
                        TraceEvent.start(
                            "trace-1", "root", None, 1, "task", links=(link,)
                        ),
                        TraceEvent.complete("trace-1", "root", 2),
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
            "digest-mismatch": {**payload, "trace_id": "trace-2"},
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
