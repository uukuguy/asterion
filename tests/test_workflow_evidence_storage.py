from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
from pathlib import Path

from asterion.pathlight import TraceEvent, TraceGraph
from asterion.workflow_evidence import write_workflow_observation_bundle


def _completed_record() -> dict[str, object]:
    graph: dict[str, object] = {
        "schema": "asterion.workflow-evidence/v1",
        "run_id": "run-1",
        "input_digest": "a" * 64,
        "terminal_status": "completed",
        "tools": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "artifacts": [],
    }
    graph["graph_sha256"] = hashlib.sha256(
        json.dumps(graph, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return graph


def _completed_pathlight_trace(
    trace_id: str = "00000000-0000-4000-8000-000000000001",
) -> dict[str, object]:
    return TraceGraph.build(
        trace_id,
        (
            TraceEvent.start(trace_id, trace_id, None, 1, "task"),
            TraceEvent.complete(trace_id, trace_id, 2),
        ),
    ).to_mapping()


class WorkflowEvidenceStorageTests(unittest.TestCase):
    def test_writes_canonical_observation_bundle_to_explicit_new_file(self) -> None:
        record = _completed_record()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow-evidence.json"

            write_workflow_observation_bundle(path, (record,))

            bundle = json.loads(path.read_text(encoding="utf-8"))
            mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(bundle["schema"], "asterion.workflow-observation-bundle/v1")
        self.assertEqual(bundle["records"], [record])
        self.assertEqual(bundle["pathlight_traces"], [])
        self.assertEqual(mode, 0o600)
        self.assertEqual(
            bundle["bundle_sha256"],
            hashlib.sha256(
                json.dumps(
                    {
                        "schema": "asterion.workflow-observation-bundle/v1",
                        "records": [record],
                        "pathlight_traces": [],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )

    def test_rejects_existing_or_noncanonical_target_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "workflow-evidence.json"
            existing.write_text("keep", encoding="utf-8")

            with self.assertRaises(ValueError):
                write_workflow_observation_bundle(existing, (_completed_record(),))

            self.assertEqual(existing.read_text(encoding="utf-8"), "keep")
            with self.assertRaises(ValueError):
                write_workflow_observation_bundle(root / "other.json", (_completed_record(),))

    def test_writes_validated_pathlight_traces_into_bundle_digest(self) -> None:
        record = _completed_record()
        trace = _completed_pathlight_trace()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow-evidence.json"

            write_workflow_observation_bundle(
                path,
                (record,),
                pathlight_traces=(trace,),
            )

            bundle = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(bundle["pathlight_traces"], [trace])
        self.assertEqual(
            bundle["bundle_sha256"],
            hashlib.sha256(
                json.dumps(
                    {
                        "schema": "asterion.workflow-observation-bundle/v1",
                        "records": [record],
                        "pathlight_traces": [trace],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )

    def test_rejects_tampered_pathlight_graph_before_creating_output(self) -> None:
        trace = _completed_pathlight_trace()
        trace["events"][0]["attributes"] = {"content_length": 1}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow-evidence.json"

            with self.assertRaises(ValueError):
                write_workflow_observation_bundle(
                    path,
                    (_completed_record(),),
                    pathlight_traces=(trace,),
                )

            self.assertFalse(path.exists())

    def test_rejects_duplicate_pathlight_trace_identity_before_creating_output(
        self,
    ) -> None:
        trace = _completed_pathlight_trace()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow-evidence.json"

            with self.assertRaises(ValueError):
                write_workflow_observation_bundle(
                    path,
                    (_completed_record(),),
                    pathlight_traces=(trace, trace),
                )

            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
