from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
from pathlib import Path

from asterion.capabilities.dci.implementation.pathlight.coverage import (
    analyze_coverage_run,
    prepare_coverage_registry,
    validate_coverage_manifest_bytes,
    validate_coverage_registry_bytes,
)
from asterion.capabilities.dci.implementation.config import DciPaths, DciPiPaths
from asterion.capabilities.dci.implementation.evaluation.artifacts import (
    DciConversationFeatures,
    DciRunRecorder,
)
from asterion.capabilities.dci.implementation.runtime.run import DciRunRequest


class DciPathlightCoverageRegistryTests(unittest.TestCase):
    def test_registry_binds_source_order_rows_without_evidence_spans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "dataset.jsonl"
            rows = [
                {
                    "query_id": f"q-{index}",
                    "query": f"query {index}",
                    "gold_ids": [f"doc-{index}.txt"],
                }
                for index in range(12)
            ]
            dataset.write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )
            corpus = root / "corpus"
            corpus.mkdir()
            for index in range(12):
                (corpus / f"doc-{index}.txt").write_text(
                    f"body {index}\n", encoding="utf-8"
                )
            output = root / "coverage"

            registry = prepare_coverage_registry(
                dataset_id="bright.biology",
                dataset_path=dataset,
                corpus_dir=corpus,
                selected_count=10,
                output_root=output,
            )

            self.assertEqual(registry.selected_count, 10)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
            self.assertEqual(
                [entry.query_sha256 for entry in registry.manifests],
                [
                    hashlib.sha256(
                        (json.dumps(f"q-{index}", separators=(",", ":")) + "\n").encode()
                    ).hexdigest()
                    for index in range(10)
                ],
            )
            manifest_path = output / registry.manifests[0].relative_path
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(manifest), {"schema", "dataset_id", "query_id", "documents"}
            )
            self.assertNotIn("evidence_spans", json.dumps(manifest))
            self.assertEqual(stat.S_IMODE(manifest_path.stat().st_mode), 0o600)
            public = json.loads((output / "registry.json").read_text(encoding="utf-8"))
            self.assertEqual(
                set(public),
                {"schema", "dataset_id", "selected_ids_sha256", "manifests"},
            )
            self.assertNotIn("q-0", json.dumps(public))
            validated = validate_coverage_registry_bytes(
                (output / "registry.json").read_bytes()
            )
            self.assertEqual(validated, registry)
            self.assertEqual(
                validate_coverage_manifest_bytes(
                    manifest_path.read_bytes(), corpus_dir=corpus
                ),
                ("bright.biology", "q-0", ("doc-0.txt",)),
            )

    def test_analysis_reports_surfaced_and_retained_without_localization_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            bodies = {"doc-a.txt": "alpha evidence\n", "doc-b.txt": "beta evidence\n"}
            for name, body in bodies.items():
                (corpus / name).write_text(body, encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "dci.retrieval-coverage-manifest/v1",
                        "dataset_id": "bright.biology",
                        "query_id": "q-1",
                        "documents": [
                            {
                                "id": name,
                                "path": name,
                                "sha256": hashlib.sha256(body.encode()).hexdigest(),
                            }
                            for name, body in bodies.items()
                        ],
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            pi = root / "pi"
            package = pi / "package"
            agent = pi / "agent"
            package.mkdir(parents=True)
            agent.mkdir()
            run = root / "run"
            request = DciRunRequest(
                run_id="coverage-run",
                question="question",
                cwd=corpus,
                tools="read",
                timeout_seconds=None,
            )
            paths = DciPaths(
                repo_root=root,
                pi=DciPiPaths(repo_dir=pi, package_dir=package, agent_dir=agent),
                output_root=root,
            )
            with DciRunRecorder(
                output_dir=run,
                request=request,
                paths=paths,
                features=DciConversationFeatures(externalize_tool_results=True),
            ) as recorder:
                recorder.record_event(
                    {
                        "type": "tool_execution_start",
                        "toolCallId": "call-1",
                        "toolName": "read",
                        "args": {"path": "doc-a.txt"},
                    }
                )
                recorder.record_event(
                    {
                        "type": "tool_execution_end",
                        "toolCallId": "call-1",
                        "toolName": "read",
                        "args": {"path": "doc-a.txt"},
                        "isError": False,
                        "result": bodies["doc-a.txt"],
                    }
                )
                tool_message = {
                    "role": "toolResult",
                    "toolCallId": "call-1",
                    "toolName": "read",
                    "content": [{"type": "text", "text": bodies["doc-a.txt"]}],
                    "isError": False,
                }
                recorder.record_event({"type": "message_end", "message": tool_message})
                recorder.record_event(
                    {
                        "type": "provider_request_context",
                        "requestIndex": 1,
                        "model": None,
                        "runtimeContextManagement": None,
                        "messages": [tool_message, {"role": "user", "content": "doc-a.txt"}],
                        "payload": {},
                    }
                )
                recorder.finalize(status="completed", final_text="answer")

            record = analyze_coverage_run(
                run_dir=run,
                corpus_dir=corpus,
                manifest=json.loads(manifest.read_text(encoding="utf-8")),
            )

            self.assertEqual(record.coverage_microunits, 500_000)
            self.assertEqual(record.retained_coverage_microunits, 500_000)
            self.assertIsNone(record.localization_microunits)
            self.assertEqual(record.evidence_state, "observed")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
