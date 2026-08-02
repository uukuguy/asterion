from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
from pathlib import Path

from asterion.pathlight import TraceEvent, TraceGraph
from asterion.workflow_evidence import (
    WorkflowEvidenceError,
    read_workflow_observation_bundle,
    write_workflow_observation_bundle,
)


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


def _mutated_bundle_path(root: Path, mutation: str) -> Path:
    path = root / "workflow-evidence.json"
    trace = _completed_pathlight_trace()
    write_workflow_observation_bundle(path, (_completed_record(),), pathlight_traces=(trace,))
    if mutation == "symlink":
        target = root / "source.json"
        path.rename(target)
        path.symlink_to(target)
        return path
    if mutation == "corrupted-json":
        path.write_text("{", encoding="utf-8")
        return path

    document = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "bundle-digest":
        document["bundle_sha256"] = "0" * 64
    elif mutation == "trace-digest":
        document["pathlight_traces"][0]["trace_sha256"] = "0" * 64
    elif mutation == "duplicate-run":
        document["records"].append(document["records"][0])
        document["bundle_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    "schema": document["schema"],
                    "records": document["records"],
                    "pathlight_traces": document["pathlight_traces"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    elif mutation == "duplicate-trace":
        document["pathlight_traces"].append(document["pathlight_traces"][0])
        document["bundle_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    "schema": document["schema"],
                    "records": document["records"],
                    "pathlight_traces": document["pathlight_traces"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    elif mutation == "unknown-field":
        document["private_sentinel"] = "SECRET-WORKFLOW-EVIDENCE"
    else:
        raise AssertionError(f"unknown mutation: {mutation}")
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class WorkflowEvidenceStorageTests(unittest.TestCase):
    def test_reads_written_bundle_as_immutable_validated_value(self) -> None:
        trace = _completed_pathlight_trace()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow-evidence.json"
            write_workflow_observation_bundle(
                path,
                (_completed_record(),),
                pathlight_traces=(trace,),
            )

            bundle = read_workflow_observation_bundle(path)

            self.assertEqual(
                bundle.bundle_sha256,
                json.loads(path.read_text(encoding="utf-8"))["bundle_sha256"],
            )
            self.assertEqual(
                bundle.pathlight_traces[0]["trace_sha256"],
                trace["trace_sha256"],
            )
            with self.assertRaises(TypeError):
                bundle.pathlight_traces[0]["trace_id"] = "mutated"  # type: ignore[index]
            self.assertIsInstance(bundle.pathlight_traces[0]["events"], tuple)
            with self.assertRaises(TypeError):
                bundle.records[0]["usage"]["input_tokens"] = 1  # type: ignore[index]

    def test_reader_rejects_invalid_or_tampered_bundle(self) -> None:
        mutations = (
            "symlink",
            "corrupted-json",
            "bundle-digest",
            "trace-digest",
            "duplicate-run",
            "duplicate-trace",
            "unknown-field",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(WorkflowEvidenceError):
                    read_workflow_observation_bundle(
                        _mutated_bundle_path(Path(directory), mutation)
                    )

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
