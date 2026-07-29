from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.benchmarks.evidence import (
    BenchmarkEvidenceStore,
    BenchmarkEvidenceError,
    BenchmarkProgressEvent,
    BenchmarkRunResult,
    BenchmarkTaskResult,
    LocalPrivateBenchmarkEvidenceStore,
)
from asterion.benchmarks.model import (
    ApplicationRef,
    ResolvedBenchmarkPlan,
    ResolvedBenchmarkTask,
    ResolvedCapability,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages import (
    BenchmarkSuiteManifest,
    BenchmarkSuiteRef,
    BenchmarkTaskManifest,
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
)


APPLICATION_REF = ApplicationRef("example.application", "1.0.0")
SUITE_REF = BenchmarkSuiteRef("example.suite", "1.0.0")
PACKAGE_REF = CapabilityPackageRef("example.package", "1.0.0")
ALPHA_REF = CapabilityRef("example.alpha", "1.0.0")
BETA_REF = CapabilityRef("example.beta", "1.0.0")


class BenchmarkEvidenceTests(unittest.TestCase):
    def test_private_store_creates_private_layout_under_permissive_umask(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            old_umask = os.umask(0)
            try:
                p = plan()
                store = LocalPrivateBenchmarkEvidenceStore(root)
                self.assertIsInstance(store, BenchmarkEvidenceStore)
                store.initialize(p)
                alpha = BenchmarkTaskResult(
                    task_id="example.alpha",
                    status="completed",
                    case_count=3,
                    artifact_ids=("artifact.alpha",),
                )
                beta = BenchmarkTaskResult(
                    task_id="example.beta",
                    status="completed",
                    case_count=3,
                )
                store.start_task(p.tasks[0])
                store.append_progress(
                    BenchmarkProgressEvent(
                        sequence=1,
                        status="task.started",
                        task_id="example.alpha",
                    ),
                )
                store.finish_task(alpha)
                store.start_task(p.tasks[1])
                store.finish_task(beta)
                finish_run_with_terminal(
                    store,
                    p,
                    BenchmarkRunResult(
                        status="completed",
                        tasks=(alpha, beta),
                    ),
                )
            finally:
                os.umask(old_umask)

            run = root / "runs" / "run-001"
            paths = (
                root,
                root / "runs",
                run,
                run / "progress",
                run / "tasks",
                run / "tasks" / "example.alpha",
            )
            for directory in paths:
                with self.subTest(directory=directory.name):
                    self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            files = (
                run / "manifest.json",
                run / "progress" / "000001.json",
                run / "tasks" / "example.alpha" / "result.json",
                run / "result.json",
            )
            for file in files:
                with self.subTest(file=file.name):
                    self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
                    self.assertNotIn("SECRET", file.read_text(encoding="utf-8"))

    def test_rejects_symlink_and_nonregular_roots_runs_and_members_redacted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            temp = Path(temp_dir)
            target = temp / "target"
            target.mkdir()
            root_link = temp / "root-link"
            try:
                os.symlink(target, root_link)
            except OSError as error:
                self.skipTest(f"symlink unavailable: {error}")

            with self.assertRaises(BenchmarkEvidenceError):
                LocalPrivateBenchmarkEvidenceStore(root_link).initialize(plan())

            root = temp / "evidence"
            store = LocalPrivateBenchmarkEvidenceStore(root)
            p = plan()
            store.initialize(p)
            run = root / "runs" / "run-001"
            for path in (run / "manifest.json", run / "progress"):
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()
                os.symlink(target, path)
                with self.subTest(member=path.name):
                    with self.assertRaises(BenchmarkEvidenceError) as context:
                        store.compatible_completed_tasks(p)
                    self.assertNotIn("SECRET", repr(context.exception))
                path.unlink()
                if path.name == "progress":
                    path.mkdir(mode=0o700)
                else:
                    path.write_text("{}", encoding="utf-8")

            result = run / "result.json"
            result.mkdir()
            with self.assertRaises(BenchmarkEvidenceError):
                store.compatible_completed_tasks(p)

    def test_atomic_write_rejects_validation_to_replace_race_redacted(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            store = LocalPrivateBenchmarkEvidenceStore(root)
            p = plan()
            store.initialize(p)
            result = BenchmarkRunResult(
                status="completed",
                tasks=(
                    BenchmarkTaskResult(
                        task_id="example.alpha",
                        status="completed",
                        case_count=1,
                    ),
                    BenchmarkTaskResult(
                        task_id="example.beta",
                        status="completed",
                        case_count=1,
                    ),
                ),
            )
            for task_result, task in zip(result.tasks, p.tasks, strict=True):
                store.start_task(task)
                store.finish_task(task_result)
            store.append_progress(
                BenchmarkProgressEvent(
                    sequence=store.next_progress_sequence(p),
                    status="run.completed",
                )
            )
            original_replace = os.replace

            def raced_replace(
                src: str,
                dst: str,
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                original_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
                fd = os.open(
                    dst,
                    os.O_WRONLY | os.O_TRUNC,
                    dir_fd=dst_dir_fd,
                )
                try:
                    os.write(fd, b'{"status":"completed","secret":"SECRET-RACE"}')
                    os.fsync(fd)
                finally:
                    os.close(fd)

            with (
                patch.object(os, "replace", raced_replace),
                self.assertRaises(BenchmarkEvidenceError) as context,
            ):
                store.finish_run(result)
            self.assertNotIn("SECRET-RACE", repr(context.exception))

    def test_resume_requires_exact_completed_closure(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            store = LocalPrivateBenchmarkEvidenceStore(root)
            p = plan()
            result = BenchmarkRunResult(
                status="completed",
                tasks=(
                    BenchmarkTaskResult(
                        task_id="example.alpha",
                        status="completed",
                        case_count=3,
                    ),
                    BenchmarkTaskResult(
                        task_id="example.beta",
                        status="completed",
                        case_count=3,
                    ),
                ),
            )
            store.initialize(p)
            with self.assertRaises(BenchmarkEvidenceError):
                store.finish_run(result)
            for task_result, task in zip(result.tasks, p.tasks, strict=True):
                store.start_task(task)
                store.finish_task(task_result)
            finish_run_with_terminal(store, p, result)

            self.assertEqual(
                store.compatible_completed_tasks(p),
                frozenset(("example.alpha", "example.beta")),
            )

            cases = (
                plan(application_ref=ApplicationRef("other.application", "1.0.0")),
                plan(suite_ref=BenchmarkSuiteRef("other.suite", "1.0.0")),
                plan(case_limit=2),
                plan(package_digest="b" * 64),
                plan(task_ids=("example.beta", "example.alpha")),
            )
            for changed in cases:
                with self.subTest(run_id=changed.run_id, case_limit=changed.case_limit):
                    with self.assertRaises(BenchmarkEvidenceError):
                        store.compatible_completed_tasks(changed)

            result_path = root / "runs" / "run-001" / "result.json"
            result_path.write_text("{", encoding="utf-8")
            with self.assertRaises(BenchmarkEvidenceError):
                store.compatible_completed_tasks(p)

    def test_compatible_resume_returns_only_completed_ordered_prefix(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            store = LocalPrivateBenchmarkEvidenceStore(root)
            p = plan()
            store.initialize(p)
            store.start_task(p.tasks[0])
            store.finish_task(
                BenchmarkTaskResult(
                    task_id="example.alpha",
                    status="completed",
                    case_count=2,
                )
            )
            self.assertEqual(
                store.compatible_completed_tasks(p),
                frozenset(("example.alpha",)),
            )

            resumed = LocalPrivateBenchmarkEvidenceStore(root)
            resumed.initialize(p)
            self.assertEqual(
                resumed.compatible_completed_tasks(p),
                frozenset(("example.alpha",)),
            )
            with self.assertRaises(BenchmarkEvidenceError):
                resumed.start_task(p.tasks[0])
            resumed.start_task(p.tasks[1])
            resumed.finish_task(
                BenchmarkTaskResult(
                    task_id="example.beta",
                    status="completed",
                    case_count=2,
                )
            )

    def test_compatible_completed_task_results_returns_exact_persisted_prefix(
        self,
    ) -> None:
        from asterion.benchmarks import BenchmarkEvidenceStore as ExportedStore

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            p = plan()
            store = LocalPrivateBenchmarkEvidenceStore(root)
            self.assertIs(BenchmarkEvidenceStore, ExportedStore)
            self.assertIsInstance(store, BenchmarkEvidenceStore)
            store.initialize(p)

            alpha = BenchmarkTaskResult(
                task_id="example.alpha",
                status="completed",
                case_count=2,
                artifact_ids=("artifact.alpha",),
            )
            beta = BenchmarkTaskResult(
                task_id="example.beta",
                status="completed",
                case_count=1,
                artifact_ids=("artifact.beta",),
            )
            store.start_task(p.tasks[0])
            store.finish_task(alpha)
            self.assertEqual(
                store.compatible_completed_task_results(p),
                (alpha,),
            )

            store.start_task(p.tasks[1])
            store.finish_task(beta)
            finish_run_with_terminal(
                store,
                p,
                BenchmarkRunResult(status="completed", tasks=(alpha, beta)),
            )

            resumed = LocalPrivateBenchmarkEvidenceStore(root)
            self.assertEqual(
                resumed.compatible_completed_task_results(p),
                (alpha, beta),
            )

    def test_next_progress_sequence_is_descriptor_validated_for_resume(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            p = plan()
            store = LocalPrivateBenchmarkEvidenceStore(root)
            store.initialize(p)
            store.append_progress(
                BenchmarkProgressEvent(sequence=1, status="run.started")
            )
            store.start_task(p.tasks[0])
            store.append_progress(
                BenchmarkProgressEvent(
                    sequence=2,
                    status="task.started",
                    task_id="example.alpha",
                )
            )
            store.finish_task(
                BenchmarkTaskResult(
                    task_id="example.alpha",
                    status="completed",
                    case_count=1,
                )
            )

            resumed = LocalPrivateBenchmarkEvidenceStore(root)
            resumed.initialize(p)
            self.assertEqual(resumed.next_progress_sequence(p), 3)

            with self.assertRaises(BenchmarkEvidenceError):
                resumed.next_progress_sequence(plan(case_limit=2))

    def test_initialize_existing_run_rejects_before_repairing_missing_or_corrupt_closure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            for name, manifest_body in (
                ("missing", None),
                ("corrupt", "{"),
            ):
                with self.subTest(name=name):
                    root = Path(temp_dir) / name
                    run = root / "runs" / "run-001"
                    run.mkdir(parents=True, mode=0o700)
                    if manifest_body is not None:
                        (run / "manifest.json").write_text(
                            manifest_body,
                            encoding="utf-8",
                        )

                    with self.assertRaises(BenchmarkEvidenceError):
                        LocalPrivateBenchmarkEvidenceStore(root).initialize(plan())

                    self.assertFalse((run / "progress").exists())
                    self.assertFalse((run / "tasks").exists())
                    if manifest_body is None:
                        self.assertFalse((run / "manifest.json").exists())

    def test_compatible_resume_rejects_existing_run_with_bad_or_missing_members(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            p = plan()
            root = Path(temp_dir) / "evidence"
            store = LocalPrivateBenchmarkEvidenceStore(root)
            store.initialize(p)

            cases = (
                ("missing-progress", lambda run: (run / "progress").rmdir()),
                (
                    "gapped-progress",
                    lambda run: (run / "progress" / "000002.json").write_text(
                        '{"sequence":2,"status":"run.gapped"}',
                        encoding="utf-8",
                    ),
                ),
                (
                    "unknown-task-progress",
                    lambda run: (run / "progress" / "000001.json").write_text(
                        '{"sequence":1,"status":"task.started","task_id":"example.missing"}',
                        encoding="utf-8",
                    ),
                ),
            )
            for case_name, mutate in cases:
                with self.subTest(case=case_name):
                    copy_root = Path(temp_dir) / f"copy-{case_name}"
                    copy_store = LocalPrivateBenchmarkEvidenceStore(copy_root)
                    copy_store.initialize(p)
                    copy_run = copy_root / "runs" / "run-001"
                    mutate(copy_run)
                    with self.assertRaises(BenchmarkEvidenceError):
                        copy_store.compatible_completed_tasks(p)

    def test_finish_run_rejects_persisted_task_result_mismatch(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            p = plan()
            store = LocalPrivateBenchmarkEvidenceStore(root)
            store.initialize(p)
            alpha = BenchmarkTaskResult(
                task_id="example.alpha",
                status="completed",
                case_count=1,
                artifact_ids=("artifact.alpha",),
            )
            beta = BenchmarkTaskResult(
                task_id="example.beta",
                status="completed",
                case_count=1,
            )
            store.start_task(p.tasks[0])
            store.finish_task(alpha)
            result_path = (
                root / "runs" / "run-001" / "tasks" / "example.alpha" / "result.json"
            )
            result_path.write_text(
                '{"artifact_ids":[],"case_count":1,"status":"completed","task_id":"example.alpha"}',
                encoding="utf-8",
            )
            store.start_task(p.tasks[1])
            store.finish_task(beta)

            with self.assertRaises(BenchmarkEvidenceError):
                store.finish_run(
                    BenchmarkRunResult(status="completed", tasks=(alpha, beta))
                )

    def test_append_progress_is_live_and_bound_to_active_task(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            p = plan()
            store = LocalPrivateBenchmarkEvidenceStore(root)
            store.initialize(p)
            with self.assertRaises(BenchmarkEvidenceError):
                store.append_progress(
                    BenchmarkProgressEvent(
                        sequence=1,
                        status="task.started",
                        task_id="example.alpha",
                    )
                )
            store.append_progress(
                BenchmarkProgressEvent(sequence=1, status="run.started")
            )
            store.start_task(p.tasks[0])
            with self.assertRaises(BenchmarkEvidenceError):
                store.append_progress(
                    BenchmarkProgressEvent(
                        sequence=2,
                        status="task.started",
                        task_id="example.beta",
                    )
                )
            store.append_progress(
                BenchmarkProgressEvent(sequence=2, status="task.running")
            )
            store.append_progress(
                BenchmarkProgressEvent(
                    sequence=3,
                    status="task.running",
                    task_id="example.alpha",
                )
            )
            alpha = BenchmarkTaskResult(
                task_id="example.alpha",
                status="completed",
                case_count=1,
            )
            beta = BenchmarkTaskResult(
                task_id="example.beta",
                status="completed",
                case_count=1,
            )
            store.finish_task(alpha)
            store.start_task(p.tasks[1])
            store.finish_task(beta)
            finish_run_with_terminal(
                store,
                p,
                BenchmarkRunResult(status="completed", tasks=(alpha, beta)),
            )

            with self.assertRaises(BenchmarkEvidenceError):
                store.append_progress(
                    BenchmarkProgressEvent(sequence=5, status="run.done")
                )

    def test_start_task_requires_exact_planned_task_object(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            p = plan()
            forged_same_identity = plan().tasks[0]
            store = LocalPrivateBenchmarkEvidenceStore(root)
            store.initialize(p)

            with self.assertRaises(BenchmarkEvidenceError):
                store.start_task(forged_same_identity)

            store.start_task(p.tasks[0])

    def test_task_lifecycle_is_once_ordered_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            store = LocalPrivateBenchmarkEvidenceStore(root)
            p = plan()
            store.initialize(p)
            with self.assertRaises(BenchmarkEvidenceError):
                store.start_task(p.tasks[1])
            store.start_task(p.tasks[0])
            with self.assertRaises(BenchmarkEvidenceError):
                store.start_task(p.tasks[1])
            with self.assertRaises(BenchmarkEvidenceError):
                store.finish_task(
                    BenchmarkTaskResult(
                        task_id="example.alpha",
                        status="completed",
                        case_count=4,
                    )
                )
            store.finish_task(
                BenchmarkTaskResult(
                    task_id="example.alpha",
                    status="completed",
                    case_count=3,
                )
            )
            with self.assertRaises(BenchmarkEvidenceError):
                store.finish_task(
                    BenchmarkTaskResult(
                        task_id="example.alpha",
                        status="completed",
                        case_count=3,
                    )
                )

    def test_progress_sequences_are_contiguous_known_and_never_overwritten(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            store = LocalPrivateBenchmarkEvidenceStore(root)
            p = plan()
            store.initialize(p)
            store.append_progress(
                BenchmarkProgressEvent(sequence=1, status="run.started")
            )
            with self.assertRaises(BenchmarkEvidenceError):
                store.append_progress(
                    BenchmarkProgressEvent(sequence=1, status="run.repeat")
                )
            with self.assertRaises(BenchmarkEvidenceError):
                store.append_progress(
                    BenchmarkProgressEvent(
                        sequence=2,
                        status="task.started",
                        task_id="example.missing",
                    )
                )
            store.append_progress(
                BenchmarkProgressEvent(sequence=2, status="run.ready")
            )

    def test_failed_and_cancelled_run_results_use_ordered_prefix_closure(self) -> None:
        failed = BenchmarkRunResult(
            status="failed",
            tasks=(
                BenchmarkTaskResult(
                    task_id="example.alpha",
                    status="failed",
                    case_count=1,
                ),
            ),
        )
        cancelled_before_task = BenchmarkRunResult(status="cancelled", tasks=())
        cancelled_mid_task = BenchmarkRunResult(
            status="cancelled",
            tasks=(
                BenchmarkTaskResult(
                    task_id="example.alpha",
                    status="cancelled",
                    case_count=1,
                ),
            ),
        )
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            for result in (failed, cancelled_before_task, cancelled_mid_task):
                with self.subTest(status=result.status, tasks=len(result.tasks)):
                    root = (
                        Path(temp_dir) / f"evidence-{result.status}-{len(result.tasks)}"
                    )
                    store = LocalPrivateBenchmarkEvidenceStore(root)
                    p = plan()
                    store.initialize(p)
                    for task_result, task in zip(result.tasks, p.tasks, strict=False):
                        store.start_task(task)
                        store.finish_task(task_result)
                    finish_run_with_terminal(store, p, result)

            invalid = BenchmarkRunResult(
                status="failed",
                tasks=(
                    BenchmarkTaskResult(
                        task_id="example.alpha",
                        status="completed",
                        case_count=1,
                    ),
                ),
            )
            store = LocalPrivateBenchmarkEvidenceStore(Path(temp_dir) / "invalid")
            store.initialize(plan())
            with self.assertRaises(BenchmarkEvidenceError):
                store.finish_run(invalid)

    def test_finish_run_is_idempotent_only_for_exact_persisted_terminal_result(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            p = plan()
            store = LocalPrivateBenchmarkEvidenceStore(root)
            store.initialize(p)
            alpha = BenchmarkTaskResult(
                task_id="example.alpha",
                status="completed",
                case_count=1,
            )
            beta = BenchmarkTaskResult(
                task_id="example.beta",
                status="completed",
                case_count=1,
            )
            result = BenchmarkRunResult(status="completed", tasks=(alpha, beta))
            store.start_task(p.tasks[0])
            store.finish_task(alpha)
            store.start_task(p.tasks[1])
            store.finish_task(beta)
            finish_run_with_terminal(store, p, result)

            resumed = LocalPrivateBenchmarkEvidenceStore(root)
            resumed.initialize(p)
            self.assertEqual(resumed.compatible_run_result(p), result)
            resumed.finish_run(result)
            with self.assertRaises(BenchmarkEvidenceError):
                resumed.finish_run(BenchmarkRunResult(status="cancelled", tasks=()))

    def test_compatible_run_result_distinguishes_completed_prefix_without_terminal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            p = plan()
            store = LocalPrivateBenchmarkEvidenceStore(root)
            store.initialize(p)
            alpha = BenchmarkTaskResult(
                task_id="example.alpha",
                status="completed",
                case_count=1,
            )
            beta = BenchmarkTaskResult(
                task_id="example.beta",
                status="completed",
                case_count=1,
            )
            store.start_task(p.tasks[0])
            store.finish_task(alpha)
            store.start_task(p.tasks[1])
            store.finish_task(beta)

            resumed = LocalPrivateBenchmarkEvidenceStore(root)
            resumed.initialize(p)
            self.assertIsNone(resumed.compatible_run_result(p))

    def test_terminal_run_result_requires_exact_final_matching_progress(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            for name, progress_bodies in (
                ("missing", ()),
                (
                    "duplicate",
                    (
                        '{"sequence":1,"status":"run.completed"}',
                        '{"sequence":2,"status":"run.completed"}',
                    ),
                ),
                (
                    "nonfinal",
                    (
                        '{"sequence":1,"status":"run.completed"}',
                        '{"sequence":2,"status":"run.ready"}',
                    ),
                ),
                ("mismatched", ('{"sequence":1,"status":"run.failed"}',)),
            ):
                with self.subTest(name=name):
                    root = Path(temp_dir) / name
                    p = plan()
                    store = LocalPrivateBenchmarkEvidenceStore(root)
                    store.initialize(p)
                    alpha = BenchmarkTaskResult(
                        task_id="example.alpha",
                        status="completed",
                        case_count=1,
                    )
                    beta = BenchmarkTaskResult(
                        task_id="example.beta",
                        status="completed",
                        case_count=1,
                    )
                    store.start_task(p.tasks[0])
                    store.finish_task(alpha)
                    store.start_task(p.tasks[1])
                    store.finish_task(beta)
                    run = root / "runs" / "run-001"
                    (run / "result.json").write_text(
                        (
                            '{"status":"completed","tasks":['
                            '{"artifact_ids":[],"case_count":1,'
                            '"status":"completed","task_id":"example.alpha"},'
                            '{"artifact_ids":[],"case_count":1,'
                            '"status":"completed","task_id":"example.beta"}]}'
                        ),
                        encoding="utf-8",
                    )
                    progress = run / "progress"
                    for index, body in enumerate(progress_bodies, start=1):
                        (progress / f"{index:06d}.json").write_text(
                            body,
                            encoding="utf-8",
                        )

                    resumed = LocalPrivateBenchmarkEvidenceStore(root)
                    with self.assertRaises(BenchmarkEvidenceError):
                        resumed.initialize(p)

    def test_finish_run_requires_matching_final_terminal_progress(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            p = plan()
            store = LocalPrivateBenchmarkEvidenceStore(root)
            store.initialize(p)
            alpha = BenchmarkTaskResult(
                task_id="example.alpha",
                status="completed",
                case_count=1,
            )
            beta = BenchmarkTaskResult(
                task_id="example.beta",
                status="completed",
                case_count=1,
            )
            store.start_task(p.tasks[0])
            store.finish_task(alpha)
            store.start_task(p.tasks[1])
            store.finish_task(beta)

            with self.assertRaises(BenchmarkEvidenceError):
                store.finish_run(
                    BenchmarkRunResult(status="completed", tasks=(alpha, beta))
                )

    def test_noncompleted_task_result_allows_one_run_terminal_progress_only(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            p = plan()
            store = LocalPrivateBenchmarkEvidenceStore(root)
            store.initialize(p)
            store.append_progress(
                BenchmarkProgressEvent(sequence=1, status="run.started")
            )
            store.start_task(p.tasks[0])
            store.finish_task(
                BenchmarkTaskResult(
                    task_id="example.alpha",
                    status="failed",
                    case_count=1,
                )
            )
            store.append_progress(
                BenchmarkProgressEvent(sequence=2, status="run.failed")
            )
            with self.assertRaises(BenchmarkEvidenceError):
                store.start_task(p.tasks[1])
            store.finish_run(
                BenchmarkRunResult(
                    status="failed",
                    tasks=(
                        BenchmarkTaskResult(
                            task_id="example.alpha",
                            status="failed",
                            case_count=1,
                        ),
                    ),
                )
            )
            with self.assertRaises(BenchmarkEvidenceError):
                store.append_progress(
                    BenchmarkProgressEvent(sequence=3, status="run.failed")
                )

    def test_noncompleted_task_result_without_run_result_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            store = LocalPrivateBenchmarkEvidenceStore(root)
            p = plan()
            store.initialize(p)
            store.start_task(p.tasks[0])
            store.finish_task(
                BenchmarkTaskResult(
                    task_id="example.alpha",
                    status="failed",
                    case_count=1,
                )
            )

            resumed = LocalPrivateBenchmarkEvidenceStore(root)
            with self.assertRaises(BenchmarkEvidenceError):
                resumed.compatible_completed_tasks(p)

    def test_strict_json_rejects_duplicate_unknown_missing_and_nonfinite_values(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            store = LocalPrivateBenchmarkEvidenceStore(root)
            p = plan()
            store.initialize(p)
            run = root / "runs" / "run-001"
            cases = (
                '{"status":"completed","status":"completed","tasks":[]}',
                '{"status":"completed","tasks":[],"extra":true}',
                '{"status":"completed"}',
                '{"status":NaN,"tasks":[]}',
            )
            for body in cases:
                with self.subTest(body=body):
                    (run / "result.json").write_text(body, encoding="utf-8")
                    with self.assertRaises(BenchmarkEvidenceError):
                        store.compatible_completed_tasks(p)

    def test_atomic_write_cleans_only_created_temp_and_requires_fsync(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            store = LocalPrivateBenchmarkEvidenceStore(root)
            p = plan()
            store.initialize(p)
            run = root / "runs" / "run-001"
            existing_temp = run / ".result.json.tmp-fixed"
            existing_temp.write_text("KEEP", encoding="utf-8")

            class FixedUuid:
                hex = "fixed"

            store.append_progress(
                BenchmarkProgressEvent(sequence=1, status="run.cancelled")
            )
            with (
                patch(
                    "asterion.benchmarks.evidence.uuid.uuid4", return_value=FixedUuid()
                ),
                self.assertRaises(BenchmarkEvidenceError),
            ):
                store.finish_run(BenchmarkRunResult(status="cancelled", tasks=()))
            self.assertEqual(existing_temp.read_text(encoding="utf-8"), "KEEP")

            def failed_fsync(fd: int) -> None:
                del fd
                raise OSError("SECRET-FSYNC")

            with (
                patch.object(os, "fsync", failed_fsync),
                self.assertRaises(BenchmarkEvidenceError) as context,
            ):
                store.append_progress(
                    BenchmarkProgressEvent(sequence=1, status="run.started")
                )
            self.assertNotIn("SECRET-FSYNC", repr(context.exception))

    def test_public_values_are_frozen_closed_and_body_free(self) -> None:
        event = BenchmarkProgressEvent(
            sequence=1,
            status="task.completed",
            task_id="example.alpha",
        )
        task = BenchmarkTaskResult(
            task_id="example.alpha",
            status="completed",
            case_count=1,
            artifact_ids=("artifact.alpha",),
        )
        result = BenchmarkRunResult(status="completed", tasks=(task,))

        with self.assertRaises(Exception):
            setattr(event, "status", "failed")
        self.assertNotIn("SECRET", repr(result))

        invalid = (
            lambda: BenchmarkProgressEvent(
                sequence=0,
                status="task.started",
                task_id="example.alpha",
            ),
            lambda: BenchmarkProgressEvent(
                sequence=1,
                status="SECRET-status",
                task_id="example.alpha",
            ),
            lambda: BenchmarkTaskResult(
                task_id="example.alpha",
                status="completed",
                case_count=1,
                artifact_ids=("SECRET-output",),
            ),
            lambda: BenchmarkRunResult(status="running", tasks=(task,)),
        )
        for factory in invalid:
            with self.subTest(factory=factory):
                with self.assertRaises(BenchmarkEvidenceError) as context:
                    factory()
                self.assertNotIn("SECRET", repr(context.exception))

    def test_unsupported_fd_platform_imports_but_public_api_fails_closed(self) -> None:
        script = """
import os
import sys
from pathlib import Path

mode, name = sys.argv[1:3]
if mode == "missing":
    if hasattr(os, name):
        delattr(os, name)
else:
    setattr(os, name, frozenset())

from asterion.benchmarks.evidence import (
    BenchmarkEvidenceError,
    LocalPrivateBenchmarkEvidenceStore,
)

try:
    LocalPrivateBenchmarkEvidenceStore(Path("/private/SECRET-FD")).initialize(object())
except BenchmarkEvidenceError as error:
    rendered = repr(error)
    assert error.__cause__ is None
    assert error.__suppress_context__
    assert "SECRET-FD" not in rendered
    assert name not in rendered
else:
    raise AssertionError("evidence store did not fail closed")
"""
        for mode, name in (
            ("missing", "O_DIRECTORY"),
            ("missing", "O_NOFOLLOW"),
            ("missing", "O_CLOEXEC"),
            ("unsupported", "supports_dir_fd"),
            ("unsupported", "supports_fd"),
        ):
            with self.subTest(name):
                result = subprocess.run(
                    [sys.executable, "-c", script, mode, name],
                    cwd=Path.cwd(),
                    env={**os.environ, "PYTHONPATH": str(Path.cwd() / "src")},
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def plan(
    *,
    application_ref: ApplicationRef = APPLICATION_REF,
    suite_ref: BenchmarkSuiteRef = SUITE_REF,
    case_limit: int = 3,
    package_digest: str = "a" * 64,
    task_ids: tuple[str, ...] = ("example.alpha", "example.beta"),
) -> ResolvedBenchmarkPlan:
    suite = BenchmarkSuiteManifest(
        suite_ref=suite_ref,
        owner_package=PACKAGE_REF,
        tasks=tuple(task_manifest(task_id) for task_id in task_ids),
        artifact_media_types=("application/json",),
        default_case_limit=10,
        default_concurrency=1,
    )
    return ResolvedBenchmarkPlan(
        run_id="run-001",
        application_ref=application_ref,
        suite=suite,
        tasks=tuple(
            resolved_task(index, task)
            for index, task in enumerate(suite.tasks, start=1)
        ),
        case_limit=case_limit,
        package_locks=(
            CapabilitySourceLock(
                entries=(
                    CapabilitySourceLockEntry(
                        package_ref=PACKAGE_REF,
                        payload_sha256=package_digest,
                        source_id="example.package.local-directory",
                    ),
                )
            ),
        ),
    )


def task_manifest(task_id: str) -> BenchmarkTaskManifest:
    return BenchmarkTaskManifest(
        task_id=task_id,
        capability=ALPHA_REF if task_id == "example.alpha" else BETA_REF,
        binding_id=task_id,
        metric_contract_id="example.metric",
        result_contract_id="example.result",
        note="SECRET-PROMPT-BODY",
    )


def resolved_task(ordinal: int, task: BenchmarkTaskManifest) -> ResolvedBenchmarkTask:
    return ResolvedBenchmarkTask(
        ordinal=ordinal,
        task=task,
        capability=ResolvedCapability(
            ref=task.capability,
            manifest={
                "capability_id": task.capability.capability_id,
                "version": task.capability.version,
                "prompt": "SECRET-PROMPT-BODY",
            },
        ),
    )


def finish_run_with_terminal(
    store: LocalPrivateBenchmarkEvidenceStore,
    p: ResolvedBenchmarkPlan,
    result: BenchmarkRunResult,
) -> None:
    store.append_progress(
        BenchmarkProgressEvent(
            sequence=store.next_progress_sequence(p),
            status=f"run.{result.status}",
        )
    )
    store.finish_run(result)


if __name__ == "__main__":
    unittest.main()
