"""Security and resume tests for private generic benchmark evidence."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from asterion.benchmarks.evidence import (
    BenchmarkEvidenceError,
    BenchmarkEvidenceStore,
    BenchmarkProgressEvent,
    BenchmarkRunResult,
    BenchmarkTaskResult,
    LocalPrivateBenchmarkEvidenceStore,
)
from asterion.benchmarks.model import (
    ApplicationRef,
    BenchmarkPlan,
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
    PlannedBenchmarkTask,
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


_PRIVATE_SENTINELS = (
    "PROMPT-BODY-SENTINEL",
    "ANSWER-BODY-SENTINEL",
    "CREDENTIAL-VALUE-SENTINEL",
    "RAW-OUTPUT-SENTINEL",
    "PRIVATE-PATH-SENTINEL",
)


class _TaskImplementation:
    def __init__(self, secret: str) -> None:
        self.secret = secret

    def build_invocation(
        self, request: BenchmarkTaskRequest
    ) -> BenchmarkTaskInvocation:
        return BenchmarkTaskInvocation(
            task_id=request.task_id,
            binding_id=f"{request.task_id}.binding",
            public_arguments=("synthetic",),
            private_payload={"credential": self.secret},
        )


class BenchmarkEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.temporary_root = Path(self._temporary.name)
        self.evidence_root = (
            self.temporary_root
            / _PRIVATE_SENTINELS[-1]
            / "evidence"
        )
        self.evidence_root.parent.mkdir(mode=0o700)
        self.plan = self._resolved_plan()
        self.store = LocalPrivateBenchmarkEvidenceStore(self.evidence_root)

    def _resolved_plan(
        self,
        *,
        application_id: str = "example.application",
        suite_id: str = "example.synthetic-suite",
        owner_package_id: str = "example.benchmark-package",
        support_package_id: str = "example.support-package",
        owner_digest: str = "a",
        support_digest: str = "b",
        owner_source: str = "example.benchmark-source",
        support_source: str = "example.support-source",
        task_ids: tuple[str, ...] = (
            "example.task-a",
            "example.task-b",
        ),
        case_limit: int = 4,
        run_id: str = "benchmark-run-001",
    ) -> ResolvedBenchmarkPlan:
        owner = CapabilityPackageRef(owner_package_id, "1.0.0")
        tasks = tuple(
            BenchmarkTaskManifest(
                task_id=task_id,
                capability=CapabilityRef(
                    f"example.capability-{index}",
                    "1.0.0",
                ),
                binding_id=f"example.binding-{index}",
                metric_contract_id="example.metric",
                result_contract_id="example.result",
                note=f"Synthetic task {index}.",
            )
            for index, task_id in enumerate(task_ids, start=1)
        )
        suite = BenchmarkSuiteManifest(
            suite_ref=BenchmarkSuiteRef(suite_id, "1.0.0"),
            owner_package=owner,
            tasks=tasks,
            artifact_media_types=("application/vnd.example.result+json",),
            default_case_limit=8,
            default_concurrency=1,
        )
        planned = tuple(
            PlannedBenchmarkTask(
                ordinal=index,
                task=task,
                capability=ResolvedCapability(
                    ref=task.capability,
                    source=(
                        self.temporary_root
                        / _PRIVATE_SENTINELS[-1]
                        / f"capability-{index}.json"
                    ),
                    manifest={
                        "capability_id": task.capability.capability_id,
                        "version": task.capability.version,
                    },
                ),
            )
            for index, task in enumerate(tasks, start=1)
        )
        locks = (
            CapabilitySourceLock(
                entries=(
                    CapabilitySourceLockEntry(
                        package_ref=owner,
                        payload_sha256=owner_digest * 64,
                        source_id=owner_source,
                    ),
                )
            ),
            CapabilitySourceLock(
                entries=(
                    CapabilitySourceLockEntry(
                        package_ref=CapabilityPackageRef(
                            support_package_id,
                            "1.0.0",
                        ),
                        payload_sha256=support_digest * 64,
                        source_id=support_source,
                    ),
                )
            ),
        )
        plan = BenchmarkPlan(
            run_id=run_id,
            application_ref=ApplicationRef(application_id, "1.0.0"),
            suite=suite,
            tasks=planned,
            case_limit=case_limit,
            package_locks=locks,
        )
        return ResolvedBenchmarkPlan(
            plan,
            tuple(
                ResolvedBenchmarkTask(
                    planned=task,
                    binding=BenchmarkTaskBinding(
                        owner_package=owner,
                        binding_id=task.task.binding_id,
                        implementation=_TaskImplementation(
                            _PRIVATE_SENTINELS[2]
                        ),
                    ),
                )
                for task in planned
            ),
        )

    def _finish_task(
        self,
        index: int,
        *,
        status: str = "completed",
        completed_cases: int = 4,
    ) -> None:
        task = self.plan.tasks[index]
        task_id = task.planned.task.task_id
        self.store.start_task(task)
        self.store.append_progress(
            BenchmarkProgressEvent(
                task_id=task_id,
                sequence=1,
                phase="executing",
                completed_cases=completed_cases,
                total_cases=4,
                content_digest="c" * 64,
                private_payload={
                    "prompt": _PRIVATE_SENTINELS[0],
                    "raw_output": _PRIVATE_SENTINELS[3],
                },
            )
        )
        self.store.finish_task(
            BenchmarkTaskResult(
                task_id=task_id,
                status=status,
                completed_cases=completed_cases,
                content_digests=("d" * 64,),
                private_payload={
                    "answer": _PRIVATE_SENTINELS[1],
                    "credential": _PRIVATE_SENTINELS[2],
                },
            )
        )

    @property
    def _run_root(self) -> Path:
        return self.evidence_root / self.plan.plan.run_id

    @property
    def _evidence_path(self) -> Path:
        return self._run_root / "evidence.json"

    def test_protocol_and_values_expose_the_planned_store_surface(self) -> None:
        self.assertIsInstance(self.store, BenchmarkEvidenceStore)
        progress = BenchmarkProgressEvent(
            task_id="example.task-a",
            sequence=1,
            phase="preparing",
            completed_cases=0,
            total_cases=4,
            content_digest=None,
            private_payload={"prompt": _PRIVATE_SENTINELS[0]},
        )
        task = BenchmarkTaskResult(
            task_id="example.task-a",
            status="completed",
            completed_cases=4,
            content_digests=("a" * 64,),
            private_payload={"answer": _PRIVATE_SENTINELS[1]},
        )
        run = BenchmarkRunResult(
            run_id="benchmark-run-001",
            status="completed",
            completed_task_ids=("example.task-a",),
            content_digests=("b" * 64,),
            private_payload={"raw_output": _PRIVATE_SENTINELS[3]},
        )

        for value in (progress, task, run):
            rendered = repr(value)
            for sentinel in _PRIVATE_SENTINELS:
                self.assertNotIn(sentinel, rendered)

    def test_every_created_directory_and_file_is_private_under_permissive_umask(
        self,
    ) -> None:
        previous_umask = os.umask(0)
        self.addCleanup(os.umask, previous_umask)

        self.store.initialize(self.plan)
        self._finish_task(0)

        self.assertEqual(
            stat.S_IMODE(self.evidence_root.stat().st_mode),
            0o700,
        )
        self.assertEqual(
            stat.S_IMODE(self._run_root.stat().st_mode),
            0o700,
        )
        members = tuple(self._run_root.iterdir())
        self.assertEqual(members, (self._evidence_path,))
        self.assertEqual(
            stat.S_IMODE(self._evidence_path.stat().st_mode),
            0o600,
        )
        self.assertTrue(stat.S_ISREG(self._evidence_path.stat().st_mode))
        self.assertEqual(self._evidence_path.stat().st_nlink, 1)

    def test_preexisting_symlinked_run_directory_is_rejected(self) -> None:
        self.evidence_root.mkdir(mode=0o700)
        outside = self.temporary_root / "outside"
        outside.mkdir(mode=0o700)
        self._run_root.symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(
            BenchmarkEvidenceError,
            "^benchmark evidence directory is unsafe$",
        ):
            self.store.initialize(self.plan)

        self.assertEqual(tuple(outside.iterdir()), ())

    def test_symlink_replacement_between_validation_and_write_is_rejected(
        self,
    ) -> None:
        self.store.initialize(self.plan)
        outside = self.temporary_root / "outside"
        outside.mkdir(mode=0o700)
        moved = self.evidence_root / "moved-run"
        real_replace = os.replace
        swapped = False

        def replace_after_swap(
            source: str,
            destination: str,
            *,
            src_dir_fd: int | None = None,
            dst_dir_fd: int | None = None,
        ) -> None:
            nonlocal swapped
            if not swapped:
                swapped = True
                self._run_root.rename(moved)
                self._run_root.symlink_to(
                    outside,
                    target_is_directory=True,
                )
            real_replace(
                source,
                destination,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
            )

        with (
            patch(
                "asterion.benchmarks.evidence.os.replace",
                side_effect=replace_after_swap,
            ),
            self.assertRaisesRegex(
                BenchmarkEvidenceError,
                "^benchmark evidence directory changed$",
            ),
        ):
            self.store.start_task(self.plan.tasks[0])

        self.assertTrue(swapped)
        self.assertEqual(tuple(outside.iterdir()), ())
        self.assertFalse((outside / "evidence.json").exists())
        self.assertTrue((moved / "evidence.json").is_file())

    def test_nonregular_or_multiply_linked_evidence_member_is_rejected(
        self,
    ) -> None:
        member_kinds = ["directory", "symlink", "hardlink"]
        if hasattr(os, "mkfifo"):
            member_kinds.append("fifo")

        for member_kind in member_kinds:
            with self.subTest(member_kind=member_kind):
                root = self.temporary_root / f"evidence-{member_kind}"
                run = root / self.plan.plan.run_id
                run.mkdir(parents=True, mode=0o700)
                root.chmod(0o700)
                run.chmod(0o700)
                member = run / "evidence.json"
                outside = self.temporary_root / f"outside-{member_kind}"
                if member_kind == "directory":
                    member.mkdir(mode=0o700)
                elif member_kind == "symlink":
                    outside.write_text("outside\n", encoding="utf-8")
                    member.symlink_to(outside)
                elif member_kind == "hardlink":
                    outside.write_text("{}\n", encoding="utf-8")
                    outside.chmod(0o600)
                    os.link(outside, member)
                else:
                    os.mkfifo(member, mode=0o600)

                store = LocalPrivateBenchmarkEvidenceStore(root)
                with self.assertRaisesRegex(
                    BenchmarkEvidenceError,
                    "^benchmark evidence file is unsafe$",
                ):
                    store.initialize(self.plan)

    def test_atomic_fsync_replace_stays_inside_the_opened_run_descriptor(
        self,
    ) -> None:
        real_replace = os.replace
        replacements: list[tuple[str, str, int | None, int | None]] = []
        real_fsync = os.fsync
        fsynced_modes: list[int] = []

        def recorded_replace(
            source: str,
            destination: str,
            *,
            src_dir_fd: int | None = None,
            dst_dir_fd: int | None = None,
        ) -> None:
            replacements.append(
                (source, destination, src_dir_fd, dst_dir_fd)
            )
            real_replace(
                source,
                destination,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
            )

        def recorded_fsync(descriptor: int) -> None:
            fsynced_modes.append(os.fstat(descriptor).st_mode)
            real_fsync(descriptor)

        with (
            patch(
                "asterion.benchmarks.evidence.os.replace",
                side_effect=recorded_replace,
            ),
            patch(
                "asterion.benchmarks.evidence.os.fsync",
                side_effect=recorded_fsync,
            ),
        ):
            self.store.initialize(self.plan)

        self.assertEqual(len(replacements), 1)
        source, destination, source_fd, destination_fd = replacements[0]
        self.assertTrue(source.startswith(".evidence."))
        self.assertEqual(destination, "evidence.json")
        self.assertIsNotNone(source_fd)
        self.assertEqual(source_fd, destination_fd)
        self.assertGreaterEqual(len(fsynced_modes), 2)
        self.assertTrue(any(stat.S_ISREG(mode) for mode in fsynced_modes))
        self.assertTrue(any(stat.S_ISDIR(mode) for mode in fsynced_modes))

    def test_only_allowlisted_descriptors_statuses_and_digests_are_serialized(
        self,
    ) -> None:
        self.store.initialize(self.plan)
        self._finish_task(0)
        self._finish_task(1)
        self.store.finish_run(
            BenchmarkRunResult(
                run_id=self.plan.plan.run_id,
                status="completed",
                completed_task_ids=tuple(
                    task.planned.task.task_id for task in self.plan.tasks
                ),
                content_digests=("e" * 64,),
                private_payload={
                    "prompt": _PRIVATE_SENTINELS[0],
                    "answer": _PRIVATE_SENTINELS[1],
                    "credential": _PRIVATE_SENTINELS[2],
                    "raw_output": _PRIVATE_SENTINELS[3],
                    "path": str(self.evidence_root),
                },
            )
        )

        serialized = self._evidence_path.read_text(encoding="utf-8")
        document = json.loads(serialized)
        for sentinel in _PRIVATE_SENTINELS:
            self.assertNotIn(sentinel, serialized)
        self.assertNotIn(str(self.evidence_root), serialized)
        self.assertEqual(
            set(document),
            {
                "schema",
                "run_id",
                "identity",
                "status",
                "tasks",
                "run_result",
            },
        )
        self.assertEqual(
            set(document["tasks"][0]),
            {
                "ordinal",
                "task_id",
                "status",
                "progress",
                "result",
            },
        )
        self.assertEqual(
            set(document["tasks"][0]["progress"][0]),
            {
                "sequence",
                "phase",
                "completed_cases",
                "total_cases",
                "content_digest",
            },
        )
        self.assertEqual(
            set(document["tasks"][0]["result"]),
            {
                "status",
                "completed_cases",
                "content_digests",
            },
        )

    def test_resume_accepts_only_the_exact_complete_plan_identity(self) -> None:
        self.store.initialize(self.plan)
        self._finish_task(0)
        self._finish_task(1)
        completed_ids = tuple(
            task.planned.task.task_id for task in self.plan.tasks
        )
        self.store.finish_run(
            BenchmarkRunResult(
                run_id=self.plan.plan.run_id,
                status="completed",
                completed_task_ids=completed_ids,
                content_digests=("e" * 64,),
                private_payload=None,
            )
        )

        self.assertEqual(
            self.store.compatible_completed_tasks(self.plan),
            frozenset(completed_ids),
        )
        self.store.initialize(self.plan)

        changed_plans = {
            "application ref": self._resolved_plan(
                application_id="example.other-application"
            ),
            "suite ref": self._resolved_plan(
                suite_id="example.other-suite"
            ),
            "package refs": self._resolved_plan(
                support_package_id="example.other-support"
            ),
            "payload digests": self._resolved_plan(
                support_digest="f"
            ),
            "source locks": self._resolved_plan(
                support_source="example.other-source"
            ),
            "ordered task ids": self._resolved_plan(
                task_ids=("example.task-b", "example.task-a")
            ),
            "case limit": self._resolved_plan(case_limit=3),
        }
        for name, changed in changed_plans.items():
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(
                    BenchmarkEvidenceError,
                    "^benchmark evidence is incompatible$",
                ),
            ):
                self.store.compatible_completed_tasks(changed)

    def test_resume_accepts_a_valid_partial_run_and_returns_only_completed_tasks(
        self,
    ) -> None:
        self.store.initialize(self.plan)
        self._finish_task(0)
        self.store.start_task(self.plan.tasks[1])

        self.assertEqual(
            self.store.compatible_completed_tasks(self.plan),
            frozenset({"example.task-a"}),
        )

    def test_each_store_stays_bound_to_its_selected_run_in_a_shared_root(
        self,
    ) -> None:
        other_plan = self._resolved_plan(run_id="benchmark-run-002")
        other_store = LocalPrivateBenchmarkEvidenceStore(self.evidence_root)
        self.store.initialize(self.plan)
        other_store.initialize(other_plan)

        self.store.start_task(self.plan.tasks[0])
        other_store.start_task(other_plan.tasks[0])

        first = json.loads(
            (
                self.evidence_root
                / self.plan.plan.run_id
                / "evidence.json"
            ).read_text(encoding="utf-8")
        )
        second = json.loads(
            (
                self.evidence_root
                / other_plan.plan.run_id
                / "evidence.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(first["tasks"][0]["status"], "running")
        self.assertEqual(second["tasks"][0]["status"], "running")

        resumed = LocalPrivateBenchmarkEvidenceStore(self.evidence_root)
        self.assertEqual(
            resumed.compatible_completed_tasks(self.plan),
            frozenset(),
        )
        resumed.append_progress(
            BenchmarkProgressEvent(
                task_id=self.plan.tasks[0].planned.task.task_id,
                sequence=1,
                phase="executing",
                completed_cases=1,
                total_cases=4,
                content_digest=None,
                private_payload=None,
            )
        )

    def test_rebinding_a_store_is_rejected_before_another_run_is_created(
        self,
    ) -> None:
        other_plan = self._resolved_plan(run_id="benchmark-run-002")
        self.store.initialize(self.plan)

        with self.assertRaisesRegex(
            BenchmarkEvidenceError,
            "^benchmark evidence run identity is ambiguous$",
        ):
            self.store.initialize(other_plan)

        self.assertFalse(
            (self.evidence_root / other_plan.plan.run_id).exists()
        )

    def test_resume_rejects_missing_incomplete_corrupt_or_extended_evidence(
        self,
    ) -> None:
        missing_root = self.temporary_root / "missing-evidence"
        with self.assertRaisesRegex(
            BenchmarkEvidenceError,
            "^benchmark evidence is unavailable$",
        ):
            LocalPrivateBenchmarkEvidenceStore(
                missing_root
            ).compatible_completed_tasks(self.plan)

        self.store.initialize(self.plan)
        valid = json.loads(self._evidence_path.read_text(encoding="utf-8"))
        corrupt_documents: dict[str, str] = {
            "invalid json": "{not-json}\n",
            "missing identity member": json.dumps(
                {
                    **valid,
                    "identity": {
                        key: value
                        for key, value in valid["identity"].items()
                        if key != "source_locks"
                    },
                }
            ),
            "completed without result": json.dumps(
                {
                    **valid,
                    "status": "running",
                    "tasks": [
                        {
                            **valid["tasks"][0],
                            "status": "completed",
                            "result": None,
                        },
                        valid["tasks"][1],
                    ],
                }
            ),
            "result regresses progress": json.dumps(
                {
                    **valid,
                    "status": "running",
                    "tasks": [
                        {
                            **valid["tasks"][0],
                            "status": "completed",
                            "progress": [
                                {
                                    "sequence": 1,
                                    "phase": "executing",
                                    "completed_cases": 3,
                                    "total_cases": 4,
                                    "content_digest": None,
                                }
                            ],
                            "result": {
                                "status": "completed",
                                "completed_cases": 2,
                                "content_digests": [],
                            },
                        },
                        valid["tasks"][1],
                    ],
                }
            ),
            "unknown private-looking member": json.dumps(
                {
                    **valid,
                    "prompt": _PRIVATE_SENTINELS[0],
                }
            ),
        }

        for name, serialized in corrupt_documents.items():
            with self.subTest(name=name):
                self._evidence_path.write_text(
                    serialized + ("" if serialized.endswith("\n") else "\n"),
                    encoding="utf-8",
                )
                self._evidence_path.chmod(0o600)
                with self.assertRaisesRegex(
                    BenchmarkEvidenceError,
                    "^benchmark evidence is invalid$",
                ):
                    self.store.compatible_completed_tasks(self.plan)

        del valid["identity"]["case_limit"]
        self._evidence_path.write_text(
            json.dumps(valid) + "\n",
            encoding="utf-8",
        )
        self._evidence_path.chmod(0o600)
        with self.assertRaisesRegex(
            BenchmarkEvidenceError,
            "^benchmark evidence is invalid$",
        ):
            self.store.initialize(self.plan)

    def test_lifecycle_rejects_noncontiguous_or_mismatched_updates(self) -> None:
        self.store.initialize(self.plan)
        first = self.plan.tasks[0]
        first_id = first.planned.task.task_id
        self.store.start_task(first)

        invalid_progress = (
            BenchmarkProgressEvent(
                task_id=first_id,
                sequence=2,
                phase="executing",
                completed_cases=1,
                total_cases=4,
                content_digest=None,
                private_payload=None,
            ),
            BenchmarkProgressEvent(
                task_id=self.plan.tasks[1].planned.task.task_id,
                sequence=1,
                phase="executing",
                completed_cases=1,
                total_cases=4,
                content_digest=None,
                private_payload=None,
            ),
        )
        for event in invalid_progress:
            with (
                self.subTest(event=event),
                self.assertRaises(BenchmarkEvidenceError),
            ):
                self.store.append_progress(event)

        self.store.append_progress(
            replace(invalid_progress[0], sequence=1)
        )
        with self.assertRaises(BenchmarkEvidenceError):
            self.store.finish_task(
                BenchmarkTaskResult(
                    task_id=self.plan.tasks[1].planned.task.task_id,
                    status="completed",
                    completed_cases=4,
                    content_digests=(),
                    private_payload=None,
                )
            )

        self.store.finish_task(
            BenchmarkTaskResult(
                task_id=first_id,
                status="failed",
                completed_cases=1,
                content_digests=(),
                private_payload=None,
            )
        )
        with self.assertRaises(BenchmarkEvidenceError):
            self.store.start_task(self.plan.tasks[1])
        with self.assertRaises(BenchmarkEvidenceError):
            self.store.finish_run(
                BenchmarkRunResult(
                    run_id=self.plan.plan.run_id,
                    status="cancelled",
                    completed_task_ids=(),
                    content_digests=(),
                    private_payload=None,
                )
            )
        self.store.finish_run(
            BenchmarkRunResult(
                run_id=self.plan.plan.run_id,
                status="failed",
                completed_task_ids=(),
                content_digests=(),
                private_payload=None,
            )
        )
        with self.assertRaises(BenchmarkEvidenceError):
            self.store.start_task(first)


if __name__ == "__main__":
    unittest.main()
