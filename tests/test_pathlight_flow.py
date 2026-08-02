from __future__ import annotations

import json
import unittest
from collections.abc import ItemsView, Iterator, Mapping

from asterion.pathlight import PathlightError, TraceEvent, TraceGraph, project_trace_flow
from asterion.pathlight.protocol import trace_graph_digest


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


if __name__ == "__main__":
    unittest.main()
