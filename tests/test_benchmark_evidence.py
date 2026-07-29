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
    BenchmarkEvidenceError,
    BenchmarkProgressEvent,
    BenchmarkRunResult,
    BenchmarkTaskResult,
    LocalPrivateBenchmarkEvidenceStore,
)
from asterion.benchmarks.model import (
    ApplicationRef,
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
    ResolvedBenchmarkPlan,
    ResolvedBenchmarkTask,
    ResolvedCapability,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages import (
    BenchmarkSuiteManifest,
    BenchmarkSuiteRef,
    BenchmarkTaskBinding,
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
                store = LocalPrivateBenchmarkEvidenceStore(root)
                store.prepare_run(plan())
                store.write_progress(
                    plan(),
                    BenchmarkProgressEvent(
                        sequence=1,
                        status="task.started",
                        task_id="example.alpha",
                    ),
                )
                store.write_task_result(
                    plan(),
                    BenchmarkTaskResult(
                        task_id="example.alpha",
                        status="completed",
                        case_count=3,
                        artifact_ids=("artifact.alpha",),
                    ),
                )
                store.write_run_result(
                    plan(),
                    BenchmarkRunResult(
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

    def test_rejects_symlink_and_nonregular_roots_runs_and_members_redacted(self) -> None:
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
                LocalPrivateBenchmarkEvidenceStore(root_link).prepare_run(plan())

            root = temp / "evidence"
            store = LocalPrivateBenchmarkEvidenceStore(root)
            store.prepare_run(plan())
            run = root / "runs" / "run-001"
            for path in (run / "manifest.json", run / "progress"):
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()
                os.symlink(target, path)
                with self.subTest(member=path.name):
                    with self.assertRaises(BenchmarkEvidenceError) as context:
                        store.resume_completed_run(plan())
                    self.assertNotIn("SECRET", repr(context.exception))
                path.unlink()
                if path.name == "progress":
                    path.mkdir(mode=0o700)
                else:
                    path.write_text("{}", encoding="utf-8")

            result = run / "result.json"
            result.mkdir()
            with self.assertRaises(BenchmarkEvidenceError):
                store.resume_completed_run(plan())

    def test_atomic_write_rejects_validation_to_replace_race_redacted(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            store = LocalPrivateBenchmarkEvidenceStore(root)
            store.prepare_run(plan())
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
                store.write_run_result(
                    plan(),
                    BenchmarkRunResult(
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
                    ),
                )
            self.assertNotIn("SECRET-RACE", repr(context.exception))

    def test_resume_requires_exact_completed_closure(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir) / "evidence"
            store = LocalPrivateBenchmarkEvidenceStore(root)
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
            store.prepare_run(plan())
            with self.assertRaises(BenchmarkEvidenceError):
                store.resume_completed_run(plan())
            store.write_run_result(plan(), result)

            self.assertEqual(store.resume_completed_run(plan()), result)

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
                        store.resume_completed_run(changed)

            result_path = root / "runs" / "run-001" / "result.json"
            result_path.write_text("{", encoding="utf-8")
            with self.assertRaises(BenchmarkEvidenceError):
                store.resume_completed_run(plan())

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
    LocalPrivateBenchmarkEvidenceStore(Path("/private/SECRET-FD")).prepare_run(object())
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
        binding=BenchmarkTaskBinding(
            owner_package=PACKAGE_REF,
            binding_id=task.binding_id,
            implementation=Implementation(),
        ),
    )


class Implementation:
    def build_invocation(
        self,
        request: BenchmarkTaskRequest,
    ) -> BenchmarkTaskInvocation:
        del request
        raise AssertionError("SECRET-IMPLEMENTATION-CALLED")


if __name__ == "__main__":
    unittest.main()
