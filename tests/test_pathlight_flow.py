from __future__ import annotations

import hashlib
import json
import unittest
from collections.abc import ItemsView, Iterator, Mapping
from typing import cast

from asterion.pathlight import (
    MemoryPathlightRecorder,
    PathlightError,
    RuntimeObservationBatch,
    TraceEvent,
    TraceGraph,
    project_trace_flow,
)
from asterion.pathlight.protocol import trace_graph_digest
from asterion.workflow_evidence.runtime import _RuntimePathlightProjection
from tests.test_workflow_evidence_runtime import (
    _native_events,
    _request,
    _two_frame_batch,
    _two_tool_flow,
)


TRACE_ID = "00000000-0000-4000-8000-000000000101"
ROOT_ID = "00000000-0000-4000-8000-000000000102"
FRAME_ONE_ID = "00000000-0000-4000-8000-000000000103"
MODEL_ONE_ID = "00000000-0000-4000-8000-000000000104"
TOOL_ID = "00000000-0000-4000-8000-000000000105"
FRAME_TWO_ID = "00000000-0000-4000-8000-000000000106"
SEGMENT_ID = "00000000-0000-4000-8000-000000000107"
MODEL_TWO_ID = "00000000-0000-4000-8000-000000000108"
SENTINEL = "SENTINEL_PRIVATE_RUNTIME_CONTENT"


class _HostileMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        del key
        raise RuntimeError(SENTINEL)

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError(SENTINEL)

    def __len__(self) -> int:
        raise RuntimeError(SENTINEL)

    def items(self) -> ItemsView[str, object]:
        raise RuntimeError(SENTINEL)


class _HostileBoundary(BaseException):
    pass


class _HostileBaseExceptionMapping(_HostileMapping):
    def items(self) -> ItemsView[str, object]:
        raise _HostileBoundary(SENTINEL)


class _ProcessControlMapping(_HostileMapping):
    def __init__(self, error: KeyboardInterrupt | SystemExit) -> None:
        self._error = error

    def items(self) -> ItemsView[str, object]:
        raise self._error


def _link(relation: str, span_id: str) -> dict[str, str]:
    return {"relation": relation, "trace_id": TRACE_ID, "span_id": span_id}


def _rich_trace() -> dict[str, object]:
    return TraceGraph.build(
        TRACE_ID,
        (
            TraceEvent.start(TRACE_ID, ROOT_ID, None, 1, "runtime"),
            TraceEvent.start(
                TRACE_ID,
                FRAME_ONE_ID,
                ROOT_ID,
                2,
                "context-frame",
                attributes={"frame_index": 0, "segment_count": 1},
                links=(_link("consumed-by", MODEL_ONE_ID),),
            ),
            TraceEvent.complete(TRACE_ID, FRAME_ONE_ID, 3, kind="context-frame"),
            TraceEvent.start(
                TRACE_ID,
                MODEL_ONE_ID,
                ROOT_ID,
                4,
                "model-call",
                attributes={"input_tokens": 4, "output_tokens": 2},
                links=(_link("derived-from", FRAME_ONE_ID),),
            ),
            TraceEvent.complete(TRACE_ID, MODEL_ONE_ID, 5, kind="model-call"),
            TraceEvent.start(
                TRACE_ID,
                TOOL_ID,
                ROOT_ID,
                6,
                "tool-call",
                attributes={"tool_id": "a" * 64, "missing_evidence": True},
            ),
            TraceEvent.complete(TRACE_ID, TOOL_ID, 7, kind="tool-call"),
            TraceEvent.start(
                TRACE_ID,
                FRAME_TWO_ID,
                ROOT_ID,
                8,
                "context-frame",
                attributes={"frame_index": 1, "segment_count": 1},
                links=(_link("consumed-by", MODEL_TWO_ID),),
            ),
            TraceEvent.start(
                TRACE_ID,
                SEGMENT_ID,
                FRAME_TWO_ID,
                9,
                "context-frame",
                attributes={
                    "segment_index": 0,
                    "segment_role": "tool-result",
                    "structure_kind": "tool-result",
                    "missing_evidence": True,
                },
                links=(_link("produced-by", TOOL_ID),),
            ),
            TraceEvent.complete(TRACE_ID, SEGMENT_ID, 10, kind="context-frame"),
            TraceEvent.complete(TRACE_ID, FRAME_TWO_ID, 11, kind="context-frame"),
            TraceEvent.start(
                TRACE_ID,
                MODEL_TWO_ID,
                ROOT_ID,
                12,
                "model-call",
                attributes={"input_tokens": 6, "output_tokens": 3},
                links=(_link("derived-from", FRAME_TWO_ID),),
            ),
            TraceEvent.complete(TRACE_ID, MODEL_TWO_ID, 13, kind="model-call"),
            TraceEvent.complete(TRACE_ID, ROOT_ID, 14, kind="runtime"),
        ),
    ).to_mapping()


def _runtime_graph(
    observation: RuntimeObservationBatch | None,
    events: tuple[tuple[str, dict[str, object]], ...],
) -> Mapping[str, object]:
    recorder = MemoryPathlightRecorder(TRACE_ID)
    projection = _RuntimePathlightProjection(recorder)
    observed: list[tuple[Mapping[str, object], int | None, int | None]] = []
    for index, (event_type, payload) in enumerate(events):
        event: Mapping[str, object] = {"type": event_type, "payload": payload}
        observed.append((event, index + 2, index + 2))
    projection.project(
        _request(),
        observed,
        evidence={"usage": {"input_tokens": 7, "output_tokens": 11}},
        native_observation=observation,
        runtime_id="fixture.runtime",
        invocation_started_ns=1,
        invocation_ended_ns=len(events) + 3,
    )
    return recorder.snapshot()


def _sequence_tuple(node: Mapping[str, object], key: str) -> tuple[int, ...]:
    value = node[key]
    if not isinstance(value, tuple) or any(type(item) is not int for item in value):
        raise AssertionError("flow sequence projection is invalid")
    return cast(tuple[int, ...], value)


class PathlightFlowTests(unittest.TestCase):
    def test_flow_projects_frame_model_tool_frame_mainline(self) -> None:
        flow = project_trace_flow(_rich_trace())

        self.assertEqual(
            [(node["kind"], node["status"]) for node in flow],
            [
                ("context-frame", "completed"),
                ("model-call", "completed"),
                ("tool-call", "completed"),
                ("context-frame", "completed"),
                ("model-call", "completed"),
            ],
        )
        self.assertEqual(flow[3]["caused_by_sequence"], flow[2]["sequence"])
        self.assertEqual(flow[0]["consumed_by_sequences"], (flow[1]["sequence"],))
        self.assertEqual(flow[3]["parent_sequence"], 1)
        self.assertTrue(flow[3]["missing_evidence"])
        self.assertNotIn(SENTINEL, json.dumps(flow))

    def test_real_rich_and_fallback_tool_lifecycle_has_distinct_safe_summaries(
        self,
    ) -> None:
        observation = _two_frame_batch()
        fallback_result = json.dumps(
            "SENTINEL_NATIVE_RESULT", sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        cases = (
            (
                "rich",
                observation,
                _native_events(),
                observation.tools[0].result_sha256,
                observation.tools[0].result_length,
            ),
            (
                "fallback",
                None,
                _native_events(),
                hashlib.sha256(fallback_result).hexdigest(),
                len(fallback_result),
            ),
        )

        for name, native, events, result_sha256, result_length in cases:
            with self.subTest(name=name):
                flow = project_trace_flow(_runtime_graph(native, events))
                tool = next(node for node in flow if node["kind"] == "tool-call")
                attributes = tool["attributes"]
                assert isinstance(attributes, Mapping)

                self.assertIn("arguments_sha256", attributes)
                self.assertIn("result_sha256", attributes)
                self.assertEqual(attributes["result_sha256"], result_sha256)
                self.assertEqual(attributes["result_length"], result_length)
                self.assertNotIn("content_sha256", attributes)
                self.assertNotIn("content_length", attributes)

    def test_real_two_tool_graphs_preserve_all_canonical_causes(self) -> None:
        cases = (
            ("sequential", False, False),
            ("same-frame-overlap", True, False),
            ("split-frame-overlap", True, True),
        )

        for name, overlap, split_frames in cases:
            with self.subTest(name=name):
                observation, events = _two_tool_flow(
                    overlap=overlap,
                    reverse_segments=False,
                    split_frames=split_frames,
                )
                flow = project_trace_flow(_runtime_graph(observation, events))
                frames = [
                    node
                    for node in flow
                    if node["kind"] == "context-frame"
                    and node["produced_by_sequences"]
                ]
                causes = tuple(
                    sequence
                    for frame in frames
                    for sequence in _sequence_tuple(frame, "caused_by_sequences")
                )
                tool_sequences = tuple(
                    cast(int, node["sequence"])
                    for node in flow
                    if node["kind"] == "tool-call"
                )

                self.assertEqual(tuple(sorted(causes)), tool_sequences)
                self.assertEqual(
                    tuple(
                        sorted(
                            sequence
                            for frame in frames
                            for sequence in _sequence_tuple(
                                frame, "produced_by_sequences"
                            )
                        )
                    ),
                    tool_sequences,
                )
                if split_frames:
                    self.assertEqual(
                        [
                            len(_sequence_tuple(frame, "caused_by_sequences"))
                            for frame in frames
                        ],
                        [1, 1],
                    )
                    self.assertTrue(all(frame["caused_by_sequence"] is not None for frame in frames))
                else:
                    self.assertEqual(len(frames), 1)
                    self.assertEqual(frames[0]["caused_by_sequences"], tool_sequences)
                    self.assertIsNone(frames[0]["caused_by_sequence"])

    def test_real_fallback_graph_keeps_single_cause_compatibility(self) -> None:
        flow = project_trace_flow(_runtime_graph(None, _native_events()))
        caused_frames = [
            node
            for node in flow
            if node["kind"] == "context-frame" and node["caused_by_sequences"]
        ]

        self.assertEqual(len(caused_frames), 1)
        causes = _sequence_tuple(caused_frames[0], "caused_by_sequences")
        self.assertEqual(
            caused_frames[0]["caused_by_sequence"],
            causes[0],
        )

    def test_flow_rejects_hostile_or_semantically_unsupported_mappings(self) -> None:
        with self.assertRaises(PathlightError) as raised:
            project_trace_flow(_HostileMapping())
        self.assertNotIn(SENTINEL, str(raised.exception))

        trace = _rich_trace()
        events = trace["events"]
        assert isinstance(events, list)
        first_frame = events[1]
        assert isinstance(first_frame, dict)
        links = first_frame["links"]
        assert isinstance(links, list)
        link = links[0]
        assert isinstance(link, dict)
        link["relation"] = "related-to"
        trace["trace_sha256"] = trace_graph_digest(trace)

        with self.assertRaises(PathlightError):
            project_trace_flow(trace)

    def test_flow_normalizes_hostile_base_exceptions_without_context(self) -> None:
        with self.assertRaises(PathlightError) as raised:
            project_trace_flow(_HostileBaseExceptionMapping())

        self.assertEqual(str(raised.exception), "Pathlight trace flow is invalid")
        self.assertNotIn(SENTINEL, str(raised.exception))
        self.assertIsNone(raised.exception.__context__)
        self.assertIsNone(raised.exception.__cause__)

    def test_flow_propagates_process_control_base_exceptions(self) -> None:
        for error in (KeyboardInterrupt(), SystemExit(7)):
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                project_trace_flow(_ProcessControlMapping(error))


if __name__ == "__main__":
    unittest.main()
