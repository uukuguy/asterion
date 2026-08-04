from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import traceback
import unittest
from collections.abc import ItemsView, Iterator, Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from asterion.pathlight import TraceEvent, TraceGraph
import asterion.workflow_evidence as workflow_evidence
from asterion.workflow_evidence import (
    WorkflowObservationBundle,
    WorkflowEvidenceError,
    read_workflow_observation_bundle,
    validate_workflow_observation_bundle,
    write_workflow_observation_bundle,
)

SENTINEL_MAPPING_ERROR = "SENTINEL_PRIVATE_MAPPING_ERROR"


class _HostileMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        del key
        raise RuntimeError(SENTINEL_MAPPING_ERROR)

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError(SENTINEL_MAPPING_ERROR)

    def __len__(self) -> int:
        raise RuntimeError(SENTINEL_MAPPING_ERROR)

    def items(self) -> ItemsView[str, object]:
        raise RuntimeError(SENTINEL_MAPPING_ERROR)


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


def _rich_pathlight_trace() -> dict[str, object]:
    return TraceGraph.build(
        "00000000-0000-4000-8000-000000000002",
        (
            TraceEvent.start(
                "00000000-0000-4000-8000-000000000002",
                "00000000-0000-4000-8000-000000000002",
                None,
                1,
                "context-frame",
                attributes={
                    "frame_index": 1,
                    "segment_count": 0,
                    "observation_sha256": "a" * 64,
                },
            ),
            TraceEvent.complete(
                "00000000-0000-4000-8000-000000000002",
                "00000000-0000-4000-8000-000000000002",
                2,
                kind="context-frame",
            ),
        ),
    ).to_mapping()


def _rehash_record(record: dict[str, object]) -> None:
    graph = dict(record)
    graph.pop("graph_sha256")
    record["graph_sha256"] = hashlib.sha256(
        json.dumps(graph, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _rehash_bundle(document: dict[str, object]) -> None:
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


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_compatible(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _json_compatible(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_compatible(item) for item in value]
    return value


def _failure_record(run_id: str) -> dict[str, object]:
    return {
        "schema": "asterion.workflow-observation/v1",
        "run_id": run_id,
        "input_digest": "b" * 64,
        "status": "failed",
        "failure_class": "runtime-invocation-failed",
    }


def _mutated_bundle_path(root: Path, mutation: str) -> Path:
    path = root / "workflow-evidence.json"
    trace = _completed_pathlight_trace()
    write_workflow_observation_bundle(
        path, (_completed_record(),), pathlight_traces=(trace,)
    )
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
        _rehash_bundle(document)
    elif mutation == "duplicate-trace":
        document["pathlight_traces"].append(document["pathlight_traces"][0])
        _rehash_bundle(document)
    elif mutation == "tool-private-field":
        record = document["records"][0]
        record["tools"] = [
            {
                "name": "search",
                "calls": 1,
                "errors": 0,
                "prompt": "SECRET-WORKFLOW-PROMPT",
            }
        ]
        _rehash_record(record)
        _rehash_bundle(document)
    elif mutation == "tool-bool-count":
        record = document["records"][0]
        record["tools"] = [{"name": "search", "calls": True, "errors": 0}]
        _rehash_record(record)
        _rehash_bundle(document)
    elif mutation == "usage-bool":
        record = document["records"][0]
        record["usage"] = {"input_tokens": True, "output_tokens": 0}
        _rehash_record(record)
        _rehash_bundle(document)
    elif mutation == "artifact-private-field":
        record = document["records"][0]
        record["artifacts"] = [
            {
                "artifact_id": "answer",
                "sha256": "a" * 64,
                "raw_payload": "SECRET-WORKFLOW-ANSWER",
            }
        ]
        _rehash_record(record)
        _rehash_bundle(document)
    elif mutation == "unknown-field":
        document["private_sentinel"] = "SECRET-WORKFLOW-EVIDENCE"
    else:
        raise AssertionError(f"unknown mutation: {mutation}")
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class WorkflowEvidenceStorageTests(unittest.TestCase):
    def _assert_source_invalid(
        self, path: Path, *, sentinel: str = "SENTINEL_PRIVATE_SOURCE"
    ) -> None:
        try:
            read_workflow_observation_bundle(path)
        except Exception as error:
            raised = error
        else:
            self.fail("invalid workflow observation source was accepted")
        rendered = "".join(traceback.format_exception(raised))
        self.assertIsInstance(raised, WorkflowEvidenceError)
        self.assertEqual(str(raised), "workflow observation source is invalid")
        self.assertIsNone(raised.__cause__)
        self.assertTrue(raised.__suppress_context__)
        self.assertNotIn(sentinel, rendered)
        self.assertNotIn(str(path), rendered)

    def test_builds_the_same_validated_bundle_without_a_path(self) -> None:
        builder = getattr(
            workflow_evidence, "build_workflow_observation_bundle", None
        )
        mapping_reader = getattr(
            workflow_evidence, "read_workflow_observation_bundle_mapping", None
        )
        self.assertIsNotNone(builder)
        self.assertIsNotNone(mapping_reader)
        assert builder is not None and mapping_reader is not None
        trace = _completed_pathlight_trace()

        mapping = builder(
            (_completed_record(),),
            pathlight_traces=(trace,),
        )
        bundle = mapping_reader(mapping)

        self.assertEqual(
            mapping["schema"], "asterion.workflow-observation-bundle/v1"
        )
        self.assertEqual(bundle.bundle_sha256, mapping["bundle_sha256"])
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory).resolve() / "workflow-evidence.json"
            write_workflow_observation_bundle(
                target,
                (_completed_record(),),
                pathlight_traces=(trace,),
            )
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")), mapping
            )

    def test_rich_trace_round_trips_without_losing_safe_observation_attributes(
        self,
    ) -> None:
        trace = _rich_pathlight_trace()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "workflow-evidence.json"
            write_workflow_observation_bundle(
                path,
                (_completed_record(),),
                pathlight_traces=(trace,),
            )

            bundle = read_workflow_observation_bundle(path)

        self.assertEqual(
            bundle.pathlight_traces[0]["events"][0]["attributes"],
            {
                "frame_index": 1,
                "segment_count": 0,
                "observation_sha256": "a" * 64,
            },
        )

    def test_reader_accepts_only_exact_safe_bundle_basenames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            canonical = root / "workflow-evidence.json"
            write_workflow_observation_bundle(canonical, (_completed_record(),))
            offline = root / "workflow-evidence.provider-calls.offline.json"
            canonical.rename(offline)

            self.assertEqual(
                read_workflow_observation_bundle(offline).records[0]["run_sha256"],
                _text_digest("run-1"),
            )

            for basename in (
                "renamed-offline.json",
                "workflow-evidence.provider-calls.offline.json.bak",
                "other.json",
            ):
                with self.subTest(basename=basename):
                    candidate = root / basename
                    candidate.write_bytes(offline.read_bytes())
                    with self.assertRaisesRegex(
                        WorkflowEvidenceError,
                        "^workflow observation source is invalid$",
                    ):
                        read_workflow_observation_bundle(candidate)

    def test_reader_projects_completed_record_identifiers_as_sha256(self) -> None:
        run_id = "/private/SECRET-RUN"
        tool_name = "/private/SECRET-TOOL"
        artifact_id = "/private/SECRET-ARTIFACT"
        record = _completed_record()
        record["run_id"] = run_id
        record["tools"] = [{"name": tool_name, "calls": 1, "errors": 0}]
        record["artifacts"] = [{"artifact_id": artifact_id, "sha256": "c" * 64}]
        _rehash_record(record)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "workflow-evidence.json"
            write_workflow_observation_bundle(path, (record,))

            bundle = read_workflow_observation_bundle(path)

        summary = _json_compatible(bundle.records[0])
        self.assertEqual(
            summary,
            {
                "schema": "asterion.pathlight-workflow-summary/v1",
                "source_graph_sha256": record["graph_sha256"],
                "run_sha256": _text_digest(run_id),
                "input_sha256": record["input_digest"],
                "terminal_status": "completed",
                "tools": [
                    {"tool_sha256": _text_digest(tool_name), "calls": 1, "errors": 0}
                ],
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "artifacts": [
                    {
                        "artifact_id_sha256": _text_digest(artifact_id),
                        "sha256": "c" * 64,
                    }
                ],
            },
        )
        rendered = json.dumps(summary, sort_keys=True)
        for raw_value in (run_id, tool_name, artifact_id):
            self.assertNotIn(raw_value, rendered)
            self.assertNotIn(raw_value, repr(bundle))

    def test_reader_projects_failure_record_identifiers_as_sha256(self) -> None:
        run_id = "/private/SECRET-FAILED-RUN"
        record = _failure_record(run_id)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "workflow-evidence.json"
            write_workflow_observation_bundle(path, (record,))

            bundle = read_workflow_observation_bundle(path)

        summary = _json_compatible(bundle.records[0])
        self.assertEqual(
            summary,
            {
                "schema": "asterion.pathlight-workflow-summary/v1",
                "source_graph_sha256": hashlib.sha256(
                    json.dumps(record, sort_keys=True, separators=(",", ":")).encode(
                        "utf-8"
                    )
                ).hexdigest(),
                "run_sha256": _text_digest(run_id),
                "input_sha256": "b" * 64,
                "terminal_status": "failed",
                "failure_class": "runtime-invocation-failed",
            },
        )
        self.assertNotIn(run_id, json.dumps(summary, sort_keys=True))
        self.assertNotIn(run_id, repr(bundle))

    def test_reader_accepts_exact_public_safe_nested_record_entries(self) -> None:
        record = _completed_record()
        record["tools"] = [{"name": "search", "calls": 1, "errors": 0}]
        record["usage"] = {"input_tokens": 3, "output_tokens": 2}
        record["artifacts"] = [{"artifact_id": "answer", "sha256": "a" * 64}]
        _rehash_record(record)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "workflow-evidence.json"
            write_workflow_observation_bundle(path, (record,))

            bundle = read_workflow_observation_bundle(path)

        self.assertEqual(
            bundle.records[0]["tools"],
            ({"tool_sha256": _text_digest("search"), "calls": 1, "errors": 0},),
        )
        usage = bundle.records[0]["usage"]
        artifacts = bundle.records[0]["artifacts"]
        assert isinstance(usage, Mapping)
        assert isinstance(artifacts, tuple)
        artifact = artifacts[0]
        assert isinstance(artifact, Mapping)
        self.assertEqual(usage["input_tokens"], 3)
        self.assertEqual(
            artifact["artifact_id_sha256"],
            _text_digest("answer"),
        )

    def test_reader_rejects_private_or_invalid_nested_record_values(self) -> None:
        mutations = (
            "tool-private-field",
            "tool-bool-count",
            "usage-bool",
            "artifact-private-field",
        )
        for mutation in mutations:
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as directory,
            ):
                with self.assertRaises(WorkflowEvidenceError):
                    read_workflow_observation_bundle(
                        _mutated_bundle_path(Path(directory).resolve(), mutation)
                    )

    def test_reader_rejects_ancestor_symlink_and_final_replacement(self) -> None:
        with (
            self.subTest("ancestor-symlink"),
            tempfile.TemporaryDirectory() as directory,
        ):
            root = Path(directory).resolve()
            target = root / "target"
            target.mkdir()
            write_workflow_observation_bundle(
                target / "workflow-evidence.json", (_completed_record(),)
            )
            (root / "ancestor").symlink_to(target, target_is_directory=True)

            with self.assertRaises(WorkflowEvidenceError):
                read_workflow_observation_bundle(
                    root / "ancestor" / "workflow-evidence.json"
                )

        with (
            self.subTest("final-replacement"),
            tempfile.TemporaryDirectory() as directory,
        ):
            root = Path(directory).resolve()
            path = root / "workflow-evidence.json"
            replacement = root / "replacement.json"
            write_workflow_observation_bundle(path, (_completed_record(),))
            replacement.write_bytes(path.read_bytes())
            original_open = os.open

            def replace_before_final_open(
                name: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                if name == "workflow-evidence.json" and dir_fd is not None:
                    path.rename(root / "original.json")
                    path.symlink_to(replacement)
                return original_open(name, flags, mode, dir_fd=dir_fd)

            with (
                patch(
                    "asterion.workflow_evidence.storage.os.open",
                    side_effect=replace_before_final_open,
                ),
                self.assertRaises(WorkflowEvidenceError),
            ):
                read_workflow_observation_bundle(path)

    def test_reader_opens_every_component_nofollow_and_nonblocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            nested = root / "one" / "two"
            nested.mkdir(parents=True)
            path = nested / "workflow-evidence.json"
            write_workflow_observation_bundle(path, (_completed_record(),))
            original_open = os.open
            opened_flags: list[int] = []

            def record_open(
                name: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                opened_flags.append(flags)
                return original_open(name, flags, mode, dir_fd=dir_fd)

            with patch(
                "asterion.workflow_evidence.storage.os.open", side_effect=record_open
            ):
                read_workflow_observation_bundle(path)

        self.assertGreaterEqual(len(opened_flags), 4)
        self.assertTrue(all(flags & os.O_NOFOLLOW for flags in opened_flags))
        self.assertTrue(all(flags & os.O_NONBLOCK for flags in opened_flags))

    def test_reader_rejects_file_type_owner_mode_and_size_drift(self) -> None:
        module = __import__(
            "asterion.workflow_evidence.storage", fromlist=["_read_bundle_document"]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()

            fifo = root / "fifo" / "workflow-evidence.json"
            fifo.parent.mkdir()
            os.mkfifo(fifo, 0o600)
            original_open = os.open

            def guard_fifo_open(
                name: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                if name == fifo.name and dir_fd is not None and not flags & os.O_NONBLOCK:
                    raise OSError("SENTINEL_PRIVATE_SOURCE")
                return original_open(name, flags, mode, dir_fd=dir_fd)

            with self.subTest(case="fifo"), patch.object(
                module.os, "open", side_effect=guard_fifo_open
            ):
                self._assert_source_invalid(fifo)

            for case in ("symlink", "directory", "wrong-mode"):
                with self.subTest(case=case):
                    child = root / case
                    child.mkdir()
                    path = child / "workflow-evidence.json"
                    if case == "symlink":
                        backing = child / "SENTINEL_PRIVATE_SOURCE"
                        write_workflow_observation_bundle(
                            backing.with_name("workflow-evidence.json"),
                            (_completed_record(),),
                        )
                        target = child / "valid-source.json"
                        path.rename(target)
                        path.symlink_to(target.name)
                    elif case == "directory":
                        path.mkdir(mode=0o600)
                    else:
                        write_workflow_observation_bundle(path, (_completed_record(),))
                        path.chmod(0o640)
                    self._assert_source_invalid(path)

            owner_path = root / "owner" / "workflow-evidence.json"
            owner_path.parent.mkdir()
            write_workflow_observation_bundle(owner_path, (_completed_record(),))
            real_fstat = os.fstat

            def foreign_owner(descriptor: int):
                metadata = real_fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    return metadata
                return SimpleNamespace(
                    st_mode=metadata.st_mode,
                    st_uid=os.geteuid() + 1,
                    st_dev=metadata.st_dev,
                    st_ino=metadata.st_ino,
                    st_size=metadata.st_size,
                    st_mtime_ns=metadata.st_mtime_ns,
                )

            with self.subTest(case="foreign-owner"), patch.object(
                module.os, "fstat", side_effect=foreign_owner
            ):
                self._assert_source_invalid(owner_path)

            oversized_path = root / "oversized" / "workflow-evidence.json"
            oversized_path.parent.mkdir()
            write_workflow_observation_bundle(oversized_path, (_completed_record(),))

            def oversized(descriptor: int):
                metadata = real_fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    return metadata
                return SimpleNamespace(
                    st_mode=metadata.st_mode,
                    st_uid=metadata.st_uid,
                    st_dev=metadata.st_dev,
                    st_ino=metadata.st_ino,
                    st_size=64 * 1024 * 1024 + 1,
                    st_mtime_ns=metadata.st_mtime_ns,
                )

            with self.subTest(case="oversized"), patch.object(
                module.os, "fstat", side_effect=oversized
            ), patch.object(module.os, "pread") as pread:
                self._assert_source_invalid(oversized_path)
            pread.assert_not_called()

    def test_reader_requires_stable_exact_bounded_held_fd_read(self) -> None:
        module = __import__(
            "asterion.workflow_evidence.storage", fromlist=["_read_bundle_document"]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "workflow-evidence.json"
            write_workflow_observation_bundle(path, (_completed_record(),))
            source_size = path.stat().st_size
            real_fstat = os.fstat
            real_pread = os.pread
            calls: list[tuple[int, int]] = []

            def bounded_pread(descriptor: int, count: int, offset: int) -> bytes:
                calls.append((count, offset))
                return real_pread(descriptor, count, offset)

            with self.subTest(case="bounded-valid"), patch.object(
                module.os, "pread", side_effect=bounded_pread
            ):
                read_workflow_observation_bundle(path)
            self.assertTrue(calls)
            self.assertTrue(all(0 < count <= 1024 * 1024 for count, _ in calls))
            self.assertEqual(calls[-1], (1, source_size))

            regular_fstat_calls = 0

            def replacement_metadata(descriptor: int):
                nonlocal regular_fstat_calls
                metadata = real_fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    return metadata
                regular_fstat_calls += 1
                if regular_fstat_calls == 1:
                    return metadata
                return SimpleNamespace(
                    st_mode=metadata.st_mode,
                    st_uid=metadata.st_uid,
                    st_dev=metadata.st_dev,
                    st_ino=metadata.st_ino + 1,
                    st_size=metadata.st_size,
                    st_mtime_ns=metadata.st_mtime_ns,
                )

            with self.subTest(case="replacement"), patch.object(
                module.os, "fstat", side_effect=replacement_metadata
            ):
                self._assert_source_invalid(path)

            with self.subTest(case="missing-bytes"), patch.object(
                module.os, "pread", return_value=b""
            ):
                self._assert_source_invalid(path)

            def extra_byte(descriptor: int, count: int, offset: int) -> bytes:
                if offset == source_size:
                    return b"x"
                return real_pread(descriptor, count, offset)

            with self.subTest(case="extra-bytes"), patch.object(
                module.os, "pread", side_effect=extra_byte
            ):
                self._assert_source_invalid(path)

            mutated = False

            def mutate_during_read(descriptor: int, count: int, offset: int) -> bytes:
                nonlocal mutated
                chunk = real_pread(descriptor, count, offset)
                if not mutated:
                    mutated = True
                    metadata = path.stat()
                    os.utime(
                        path,
                        ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000),
                    )
                return chunk

            with self.subTest(case="mutation"), patch.object(
                module.os, "pread", side_effect=mutate_during_read
            ):
                self._assert_source_invalid(path)

    def test_reader_rejects_duplicate_json_keys_with_fixed_unchained_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "workflow-evidence.json"
            path.write_text(
                '{"schema":"SENTINEL_PRIVATE_SOURCE","schema":"duplicate"}',
                encoding="utf-8",
            )
            path.chmod(0o600)

            self._assert_source_invalid(path)

    def test_reads_written_bundle_as_immutable_validated_value(self) -> None:
        trace = _completed_pathlight_trace()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "workflow-evidence.json"
            write_workflow_observation_bundle(
                path,
                (_completed_record(),),
                pathlight_traces=(trace,),
            )

            bundle = read_workflow_observation_bundle(path)

            validate_workflow_observation_bundle(bundle)

            self.assertEqual(
                bundle.bundle_sha256,
                json.loads(path.read_text(encoding="utf-8"))["bundle_sha256"],
            )
            self.assertEqual(
                bundle.pathlight_traces[0]["trace_sha256"],
                trace["trace_sha256"],
            )
            self.assertEqual(
                bundle.records[0]["schema"],
                "asterion.pathlight-workflow-summary/v1",
            )
            with self.assertRaises(TypeError):
                bundle.pathlight_traces[0]["trace_id"] = "mutated"  # type: ignore[index]
            self.assertIsInstance(bundle.pathlight_traces[0]["events"], tuple)
            with self.assertRaises(TypeError):
                bundle.records[0]["usage"]["input_tokens"] = 1  # type: ignore[index]

    def test_bundle_projection_digest_rejects_forged_typed_values(self) -> None:
        trace = _completed_pathlight_trace()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "workflow-evidence.json"
            write_workflow_observation_bundle(
                path, (_completed_record(),), pathlight_traces=(trace,)
            )
            bundle = read_workflow_observation_bundle(path)
            tampered_record = dict(bundle.records[0])
            tampered_record["run_sha256"] = "SENTINEL_PRIVATE"

            with self.assertRaises(WorkflowEvidenceError):
                WorkflowObservationBundle(
                    records=(tampered_record,),
                    pathlight_traces=bundle.pathlight_traces,
                    bundle_sha256=bundle.bundle_sha256,
                    projection_sha256=bundle.projection_sha256,
                )
            with self.assertRaises(WorkflowEvidenceError):
                WorkflowObservationBundle(
                    records=bundle.records,
                    pathlight_traces=bundle.pathlight_traces,
                    bundle_sha256=bundle.bundle_sha256,
                    projection_sha256="0" * 64,
                )

            incomplete = object.__new__(WorkflowObservationBundle)
            with self.assertRaises(WorkflowEvidenceError):
                validate_workflow_observation_bundle(incomplete)

    def test_bundle_normalizes_hostile_mapping_failures_without_leaking_text(
        self,
    ) -> None:
        hostile = _HostileMapping()
        calls = (
            lambda: WorkflowObservationBundle(
                records=(hostile,),
                pathlight_traces=(),
                bundle_sha256="0" * 64,
                projection_sha256="0" * 64,
            ),
            lambda: WorkflowObservationBundle(
                records=(),
                pathlight_traces=(hostile,),
                bundle_sha256="0" * 64,
                projection_sha256="0" * 64,
            ),
        )
        forged = object.__new__(WorkflowObservationBundle)
        object.__setattr__(forged, "records", (hostile,))
        object.__setattr__(forged, "pathlight_traces", ())
        object.__setattr__(forged, "bundle_sha256", "0" * 64)
        object.__setattr__(forged, "projection_sha256", "0" * 64)

        for call in (*calls, lambda: validate_workflow_observation_bundle(forged)):
            with (
                self.subTest(call=call),
                self.assertRaises(WorkflowEvidenceError) as raised,
            ):
                call()
            self.assertNotIn(SENTINEL_MAPPING_ERROR, str(raised.exception))
            self.assertTrue(raised.exception.__suppress_context__)

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
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as directory,
            ):
                with self.assertRaises(WorkflowEvidenceError):
                    read_workflow_observation_bundle(
                        _mutated_bundle_path(Path(directory).resolve(), mutation)
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
            for target_name in (
                "other.json",
                "workflow-evidence.provider-calls.offline.json",
            ):
                with self.subTest(target_name=target_name), self.assertRaises(
                    ValueError
                ):
                    write_workflow_observation_bundle(
                        root / target_name, (_completed_record(),)
                    )

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
        events = trace["events"]
        assert isinstance(events, list)
        event = events[0]
        assert isinstance(event, dict)
        event["attributes"] = {"content_length": 1}
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
