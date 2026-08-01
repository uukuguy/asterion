from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

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


class WorkflowEvidenceStorageTests(unittest.TestCase):
    def test_writes_canonical_observation_bundle_to_explicit_new_file(self) -> None:
        record = _completed_record()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow-evidence.json"

            write_workflow_observation_bundle(path, (record,))

            bundle = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(bundle["schema"], "asterion.workflow-observation-bundle/v1")
        self.assertEqual(bundle["records"], [record])
        self.assertEqual(
            bundle["bundle_sha256"],
            hashlib.sha256(
                json.dumps(
                    {
                        "schema": "asterion.workflow-observation-bundle/v1",
                        "records": [record],
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


if __name__ == "__main__":
    unittest.main()
