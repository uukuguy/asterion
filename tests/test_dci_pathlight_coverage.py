from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.capabilities.dci.implementation.pathlight import coverage as coverage_module
from asterion.capabilities.dci.implementation.pathlight.coverage import (
    DciCoverageError,
    analyze_coverage_run,
    coverage_query_sha256,
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
from asterion.capabilities.dci.implementation.research.trajectory_resolution import (
    TrajectoryAnalysisConfig,
    analyze_trajectory_resolution,
    public_resolution_projection,
    validate_public_resolution_summary,
)


def _bright_source_row(query_id: str, document: str) -> dict[str, object]:
    return {
        "query_id": query_id,
        "query": "query",
        "answer": "answer",
        "excluded_ids": ["excluded.txt"],
        "gold_ids": [document],
        "gold_ids_long": [document],
        "id": f"source-{query_id}",
        "reasoning": "reasoning",
    }


class DciPathlightCoverageRegistryTests(unittest.TestCase):
    def test_registry_accepts_the_exact_beir_and_bright_source_shapes(self) -> None:
        cases = (
            (
                "beir.scifact",
                {
                    "query_id": "q-beir",
                    "query": "query",
                    "answer": "",
                    "gold_ids": ["doc.txt"],
                },
            ),
            (
                "bright.biology",
                {
                    "query_id": 7,
                    "query": "query",
                    "answer": "answer",
                    "excluded_ids": ["excluded.txt"],
                    "gold_ids": ["doc.txt"],
                    "gold_ids_long": ["doc.txt"],
                    "id": "bright-source-id",
                    "reasoning": "reasoning",
                },
            ),
        )
        for dataset_id, row in cases:
            with self.subTest(dataset_id=dataset_id), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                dataset = root / "dataset.jsonl"
                dataset.write_text(json.dumps(row) + "\n", encoding="utf-8")
                corpus = root / "corpus"
                corpus.mkdir()
                (corpus / "doc.txt").write_text("body\n", encoding="utf-8")

                registry = prepare_coverage_registry(
                    dataset_id=dataset_id,
                    dataset_path=dataset,
                    corpus_dir=corpus,
                    selected_count=1,
                    output_root=root / "coverage",
                )

                self.assertEqual(registry.selected_count, 1)

    def test_registry_preserves_exact_source_paths_with_colliding_basenames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "dataset.jsonl"
            rows = [
                _bright_source_row("q-1", "source-a/doc.txt"),
                _bright_source_row("q-2", "source-b/doc.txt"),
            ]
            dataset.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            corpus = root / "corpus"
            corpus.mkdir()
            for source in ("source-a", "source-b"):
                (corpus / source).mkdir()
                (corpus / source / "doc.txt").write_text(
                    f"{source} body\n", encoding="utf-8"
                )

            registry = prepare_coverage_registry(
                dataset_id="bright.earth-science",
                dataset_path=dataset,
                corpus_dir=corpus,
                selected_count=2,
                output_root=root / "coverage",
            )

            observed_ids = []
            observed_paths = []
            for ref in registry.manifests:
                manifest = json.loads(
                    (root / "coverage" / ref.relative_path).read_text(encoding="utf-8")
                )
                observed_ids.append(manifest["documents"][0]["id"])
                observed_paths.append(manifest["documents"][0]["path"])
            self.assertEqual(observed_ids, ["source-a/doc.txt", "source-b/doc.txt"])
            self.assertEqual(observed_paths, observed_ids)

    def test_atomic_publish_does_not_replace_concurrently_created_directory(self) -> None:
        publisher = getattr(coverage_module, "_publish_directory_no_replace", None)
        self.assertIsNotNone(publisher, "atomic no-replace publish primitive is missing")
        assert callable(publisher)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            staging = parent / ".coverage.staging-fixture"
            destination = parent / "coverage"
            staging.mkdir(mode=0o700)
            (staging / "registry.json").write_text("staged", encoding="utf-8")
            create = threading.Event()
            created = threading.Event()

            def create_hostile_destination() -> None:
                create.wait()
                destination.mkdir(mode=0o700)
                (destination / "hostile.txt").write_text("hostile", encoding="utf-8")
                created.set()

            worker = threading.Thread(target=create_hostile_destination)
            worker.start()
            parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                create.set()
                self.assertTrue(created.wait(timeout=5))
                with self.assertRaises(DciCoverageError):
                    publisher(parent_fd, staging.name, destination.name)
            finally:
                os.close(parent_fd)
                worker.join(timeout=5)

            self.assertEqual(
                (destination / "hostile.txt").read_text(encoding="utf-8"), "hostile"
            )
            self.assertTrue((staging / "registry.json").is_file())

    def test_registry_publish_race_preserves_hostile_target_and_cleans_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "dataset.jsonl"
            dataset.write_text(
                json.dumps(_bright_source_row("q-1", "doc.txt"))
                + "\n",
                encoding="utf-8",
            )
            corpus = root / "corpus"
            corpus.mkdir()
            (corpus / "doc.txt").write_text("body\n", encoding="utf-8")
            output = root / "coverage"
            real_publisher = getattr(
                coverage_module, "_publish_directory_no_replace", None
            )

            def create_destination_then_publish(
                parent_fd: int, staging_name: str, output_name: str
            ) -> None:
                os.mkdir(output_name, 0o700, dir_fd=parent_fd)
                target_fd = os.open(
                    output_name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=parent_fd
                )
                try:
                    hostile_fd = os.open(
                        "hostile.txt",
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=target_fd,
                    )
                    os.write(hostile_fd, b"hostile")
                    os.close(hostile_fd)
                finally:
                    os.close(target_fd)
                if not callable(real_publisher):
                    raise AssertionError("atomic publisher is missing")
                real_publisher(parent_fd, staging_name, output_name)

            with patch.object(
                coverage_module,
                "_publish_directory_no_replace",
                side_effect=create_destination_then_publish,
                create=True,
            ):
                with self.assertRaises(DciCoverageError):
                    prepare_coverage_registry(
                        dataset_id="bright.biology",
                        dataset_path=dataset,
                        corpus_dir=corpus,
                        selected_count=1,
                        output_root=output,
                    )

            self.assertEqual(
                (output / "hostile.txt").read_text(encoding="utf-8"), "hostile"
            )
            self.assertFalse(
                any(path.name.startswith(".coverage.staging-") for path in root.iterdir())
            )

    def test_registry_binds_source_order_rows_without_evidence_spans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "dataset.jsonl"
            rows = [
                _bright_source_row(f"q-{index}", f"doc-{index}.txt")
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
            self.assertEqual(
                registry.manifests[0].query_sha256,
                coverage_query_sha256("q-0"),
            )
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
            query_id = "QUERY_SENTINEL_6"
            bodies = {
                "DOCUMENT_SENTINEL_A.txt": "alpha evidence\n",
                "DOCUMENT_SENTINEL_B.txt": "beta evidence\n",
            }
            for name, body in bodies.items():
                (corpus / name).write_text(body, encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "dci.retrieval-coverage-manifest/v1",
                        "dataset_id": "bright.biology",
                        "query_id": query_id,
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
                        "args": {"path": "DOCUMENT_SENTINEL_A.txt"},
                    }
                )
                recorder.record_event(
                    {
                        "type": "tool_execution_end",
                        "toolCallId": "call-1",
                        "toolName": "read",
                        "args": {"path": "DOCUMENT_SENTINEL_A.txt"},
                        "isError": False,
                        "result": bodies["DOCUMENT_SENTINEL_A.txt"],
                    }
                )
                tool_message = {
                    "role": "toolResult",
                    "toolCallId": "call-1",
                    "toolName": "read",
                    "content": [
                        {"type": "text", "text": bodies["DOCUMENT_SENTINEL_A.txt"]}
                    ],
                    "isError": False,
                }
                recorder.record_event({"type": "message_end", "message": tool_message})
                recorder.record_event(
                    {
                        "type": "provider_request_context",
                        "requestIndex": 1,
                        "model": None,
                        "runtimeContextManagement": None,
                        "messages": [
                            tool_message,
                            {"role": "user", "content": "DOCUMENT_SENTINEL_A.txt"},
                        ],
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

            manifest_mapping = json.loads(manifest.read_text(encoding="utf-8"))
            evidence = analyze_trajectory_resolution(
                run_dir=run,
                attempt=1,
                corpus_dir=corpus,
                config=TrajectoryAnalysisConfig(segment_characters=4096),
                gold_manifest_bytes=(
                    json.dumps(manifest_mapping, sort_keys=True, separators=(",", ":"))
                    + "\n"
                ).encode(),
            )
            public = public_resolution_projection(evidence)
            validated = validate_public_resolution_summary(public)
            serialized = json.dumps(validated, sort_keys=True)

            self.assertEqual(
                public["schema"], "dci.trajectory-resolution-coverage-summary/v1"
            )
            self.assertEqual(
                set(public),
                {
                    "schema",
                    "identity_sha256",
                    "dataset_id",
                    "query_sha256",
                    "metrics",
                    "counts",
                },
            )
            self.assertEqual(record.query_sha256, public["query_sha256"])
            for sentinel in (query_id, *bodies, *bodies.values()):
                with self.subTest(sentinel=sentinel):
                    self.assertNotIn(sentinel, serialized)
                    self.assertNotIn(sentinel, repr(record))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
