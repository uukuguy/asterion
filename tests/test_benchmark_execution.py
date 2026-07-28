"""Sequential benchmark execution and real process-tree cancellation tests."""

from __future__ import annotations

import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.applications.selection import ApplicationSelector
from asterion.benchmarks.evidence import (
    BenchmarkEvidenceStore,
    BenchmarkProgressEvent,
    BenchmarkRunResult,
    BenchmarkTaskResult,
)
from asterion.benchmarks.execution import (
    BenchmarkRunner,
    BenchmarkTaskExecutor,
)
from asterion.benchmarks.model import (
    BenchmarkPlan,
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
    PlannedBenchmarkTask,
    ResolvedBenchmarkPlan,
    ResolvedBenchmarkTask,
    ResolvedCapability,
)
from asterion.benchmarks.process import (
    AuthorizedProcessTaskExecutor,
    AuthorizedProcessTaskPlan,
    ProcessExecutionDetails,
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


_PRIVATE_EXCEPTION = "EXECUTOR-EXCEPTION-PRIVATE-SENTINEL"
_PRIVATE_ENVIRONMENT = "INHERITED-ENVIRONMENT-PRIVATE-SENTINEL"
_HELPER = Path(__file__).parent / "fixtures" / "helpers" / "benchmark_process_tree.py"


class _MutableCancellation:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled


class _FileCancellation:
    def __init__(self, path: Path) -> None:
        self.path = path

    @property
    def cancelled(self) -> bool:
        return self.path.exists()


class _TaskImplementation:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def build_invocation(
        self, request: BenchmarkTaskRequest
    ) -> BenchmarkTaskInvocation:
        self.calls.append(f"build:{request.task_id}")
        return BenchmarkTaskInvocation(
            task_id=request.task_id,
            binding_id=f"{request.task_id}.binding",
            public_arguments=("synthetic",),
            private_payload={"request": request},
        )


class _MemoryEvidence:
    def __init__(
        self,
        calls: list[str],
        *,
        completed: frozenset[str] = frozenset(),
    ) -> None:
        self.calls = calls
        self.completed = completed
        self.progress: list[BenchmarkProgressEvent] = []
        self.task_results: list[BenchmarkTaskResult] = []
        self.run_results: list[BenchmarkRunResult] = []
        self.compatibility_checks = 0

    def initialize(self, plan: ResolvedBenchmarkPlan) -> None:
        self.calls.append("evidence:initialize")

    def start_task(self, task: ResolvedBenchmarkTask) -> None:
        task_id = task.planned.task.task_id
        self.calls.append(f"evidence:start:{task_id}")

    def append_progress(self, event: BenchmarkProgressEvent) -> None:
        self.calls.append(f"evidence:progress:{event.task_id}:{event.sequence}")
        self.progress.append(event)

    def finish_task(self, result: BenchmarkTaskResult) -> None:
        self.calls.append(f"evidence:finish:{result.task_id}:{result.status}")
        self.task_results.append(result)

    def finish_run(self, result: BenchmarkRunResult) -> None:
        self.calls.append(f"evidence:run:{result.status}")
        self.run_results.append(result)

    def compatible_completed_tasks(self, plan: ResolvedBenchmarkPlan) -> frozenset[str]:
        self.compatibility_checks += 1
        self.calls.append("evidence:compatible")
        return self.completed


class _RecordingExecutor:
    def __init__(
        self,
        calls: list[str],
        *,
        statuses: dict[str, str] | None = None,
        cancellation: _MutableCancellation | None = None,
        fail_task: str | None = None,
    ) -> None:
        self.calls = calls
        self.statuses = {} if statuses is None else statuses
        self.cancellation = cancellation
        self.fail_task = fail_task
        self.attempts: list[str] = []

    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: _MutableCancellation,
        on_progress,
    ) -> BenchmarkTaskResult:
        task_id = invocation.task_id
        self.attempts.append(task_id)
        self.calls.append(f"executor:start:{task_id}")
        if task_id == self.fail_task:
            raise RuntimeError(_PRIVATE_EXCEPTION)
        for sequence, phase, completed in (
            (1, "preparing", 0),
            (2, "executing", 1),
        ):
            on_progress(
                BenchmarkProgressEvent(
                    task_id=task_id,
                    sequence=sequence,
                    phase=phase,
                    completed_cases=completed,
                    total_cases=2,
                    content_digest=None,
                    private_payload=None,
                )
            )
        status = self.statuses.get(task_id, "completed")
        if status == "cancelled" and self.cancellation is not None:
            self.cancellation.cancelled = True
        self.calls.append(f"executor:end:{task_id}")
        return BenchmarkTaskResult(
            task_id=task_id,
            status=status,
            completed_cases=2 if status == "completed" else 1,
            content_digests=((task_id.encode().hex() * 64)[:64],)
            if status == "completed"
            else (),
            private_payload=None,
        )


class BenchmarkExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.calls: list[str] = []
        self.plan = self._plan()

    def _plan(
        self,
        task_ids: tuple[str, ...] = (
            "example.task-a",
            "example.task-b",
            "example.task-c",
        ),
    ) -> ResolvedBenchmarkPlan:
        owner = CapabilityPackageRef("example.benchmarks", "1.0.0")
        manifests = tuple(
            BenchmarkTaskManifest(
                task_id=task_id,
                capability=CapabilityRef(
                    f"example.capability-{index}",
                    "1.0.0",
                ),
                binding_id=f"{task_id}.binding",
                metric_contract_id="example.metric",
                result_contract_id="example.result",
                note=f"Synthetic task {index}.",
            )
            for index, task_id in enumerate(task_ids, start=1)
        )
        suite = BenchmarkSuiteManifest(
            suite_ref=BenchmarkSuiteRef("example.suite", "1.0.0"),
            owner_package=owner,
            tasks=manifests,
            artifact_media_types=("application/vnd.example.result+json",),
            default_case_limit=2,
            default_concurrency=1,
        )
        planned = tuple(
            PlannedBenchmarkTask(
                ordinal=index,
                task=manifest,
                capability=ResolvedCapability(
                    ref=manifest.capability,
                    source=self.root / f"capability-{index}.json",
                    manifest={
                        "capability_id": manifest.capability.capability_id,
                        "version": manifest.capability.version,
                    },
                ),
            )
            for index, manifest in enumerate(manifests, start=1)
        )
        plan = BenchmarkPlan(
            run_id="example-run",
            application_ref=ApplicationSelector(
                "example.application",
                "1.0.0",
            ),
            suite=suite,
            tasks=planned,
            case_limit=2,
            package_locks=(
                CapabilitySourceLock(
                    entries=(
                        CapabilitySourceLockEntry(
                            package_ref=owner,
                            payload_sha256="a" * 64,
                            source_id="example.source",
                        ),
                    )
                ),
            ),
        )
        return ResolvedBenchmarkPlan(
            plan,
            tuple(
                ResolvedBenchmarkTask(
                    planned=task,
                    binding=BenchmarkTaskBinding(
                        owner_package=owner,
                        binding_id=task.task.binding_id,
                        implementation=_TaskImplementation(self.calls),
                    ),
                )
                for task in planned
            ),
        )

    def test_protocols_and_sequential_execution_boundary(self) -> None:
        evidence = _MemoryEvidence(self.calls)
        executor = _RecordingExecutor(self.calls)

        result = BenchmarkRunner().run(
            self.plan,
            executor=executor,
            evidence=evidence,
            cancellation=_MutableCancellation(),
        )

        self.assertIsInstance(executor, BenchmarkTaskExecutor)
        self.assertIsInstance(evidence, BenchmarkEvidenceStore)
        self.assertEqual(result.status, "completed")
        self.assertEqual(
            executor.attempts,
            [
                "example.task-a",
                "example.task-b",
                "example.task-c",
            ],
        )
        for task_id in executor.attempts:
            task_calls = [
                f"build:{task_id}",
                f"evidence:start:{task_id}",
                f"executor:start:{task_id}",
                f"evidence:progress:{task_id}:1",
                f"evidence:progress:{task_id}:2",
                f"executor:end:{task_id}",
                f"evidence:finish:{task_id}:completed",
            ]
            positions = [self.calls.index(call) for call in task_calls]
            self.assertEqual(positions, sorted(positions))
        self.assertLess(
            self.calls.index("evidence:finish:example.task-a:completed"),
            self.calls.index("executor:start:example.task-b"),
        )
        self.assertEqual(
            [event.sequence for event in evidence.progress],
            [1, 2, 1, 2, 1, 2],
        )
        self.assertEqual(len(evidence.task_results), 3)
        self.assertEqual(len(evidence.run_results), 1)
        self.assertIs(evidence.run_results[0], result)

    def test_resume_skips_only_compatible_completed_tasks(self) -> None:
        evidence = _MemoryEvidence(
            self.calls,
            completed=frozenset({"example.task-a"}),
        )
        executor = _RecordingExecutor(self.calls)

        result = BenchmarkRunner().run(
            self.plan,
            executor=executor,
            evidence=evidence,
            cancellation=_MutableCancellation(),
        )

        self.assertEqual(
            executor.attempts,
            ["example.task-b", "example.task-c"],
        )
        self.assertEqual(evidence.compatibility_checks, 1)
        self.assertEqual(
            result.completed_task_ids,
            (
                "example.task-a",
                "example.task-b",
                "example.task-c",
            ),
        )

    def test_first_failure_stops_later_tasks(self) -> None:
        evidence = _MemoryEvidence(self.calls)
        executor = _RecordingExecutor(
            self.calls,
            statuses={"example.task-b": "failed"},
        )

        result = BenchmarkRunner().run(
            self.plan,
            executor=executor,
            evidence=evidence,
            cancellation=_MutableCancellation(),
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(
            executor.attempts,
            ["example.task-a", "example.task-b"],
        )
        self.assertEqual(
            [task.status for task in evidence.task_results],
            ["completed", "failed"],
        )

    def test_pre_task_cancellation_starts_nothing(self) -> None:
        evidence = _MemoryEvidence(self.calls)
        executor = _RecordingExecutor(self.calls)

        result = BenchmarkRunner().run(
            self.plan,
            executor=executor,
            evidence=evidence,
            cancellation=_MutableCancellation(cancelled=True),
        )

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(executor.attempts, [])
        self.assertFalse(any(call.startswith("build:") for call in self.calls))
        self.assertFalse(any(call.startswith("evidence:start:") for call in self.calls))
        self.assertEqual(len(evidence.run_results), 1)

    def test_mid_task_cancellation_reaches_executor_and_stops_later_tasks(
        self,
    ) -> None:
        cancellation = _MutableCancellation()
        evidence = _MemoryEvidence(self.calls)
        executor = _RecordingExecutor(
            self.calls,
            statuses={"example.task-a": "cancelled"},
            cancellation=cancellation,
        )

        result = BenchmarkRunner().run(
            self.plan,
            executor=executor,
            evidence=evidence,
            cancellation=cancellation,
        )

        self.assertTrue(cancellation.cancelled)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(executor.attempts, ["example.task-a"])
        self.assertEqual(evidence.task_results[0].status, "cancelled")

    def test_executor_exception_becomes_one_redacted_failed_result(
        self,
    ) -> None:
        evidence = _MemoryEvidence(self.calls)
        executor = _RecordingExecutor(
            self.calls,
            fail_task="example.task-a",
        )

        result = BenchmarkRunner().run(
            self.plan,
            executor=executor,
            evidence=evidence,
            cancellation=_MutableCancellation(),
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(evidence.task_results), 1)
        self.assertEqual(evidence.task_results[0].status, "failed")
        self.assertEqual(len(evidence.run_results), 1)
        rendered = repr((evidence.task_results, result))
        self.assertNotIn(_PRIVATE_EXCEPTION, rendered)
        self.assertNotIn(
            _PRIVATE_EXCEPTION,
            str(evidence.task_results[0].private_payload),
        )

    def test_complete_resume_returns_without_retrying_or_reopening_terminal(
        self,
    ) -> None:
        completed = frozenset(task.planned.task.task_id for task in self.plan.tasks)
        evidence = _MemoryEvidence(self.calls, completed=completed)
        executor = _RecordingExecutor(self.calls)

        result = BenchmarkRunner().run(
            self.plan,
            executor=executor,
            evidence=evidence,
            cancellation=_MutableCancellation(),
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(executor.attempts, [])
        self.assertEqual(evidence.run_results, [])


@unittest.skipUnless(os.name == "posix", "process groups require POSIX")
class AuthorizedProcessTaskExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _invocation(
        self,
        plan: AuthorizedProcessTaskPlan,
    ) -> BenchmarkTaskInvocation:
        return BenchmarkTaskInvocation(
            task_id="example.process-task",
            binding_id="example.process-binding",
            public_arguments=("synthetic",),
            private_payload=plan,
        )

    def test_process_plan_is_immutable_and_snapshots_environment(self) -> None:
        argv = [sys.executable, "-c", "raise SystemExit(0)"]
        environment = {"EXAMPLE_VALUE": "before"}
        plan = AuthorizedProcessTaskPlan(
            argv=argv,
            cwd=self.root,
            environment=environment,
            deadline_seconds=2.0,
            output_limit_bytes=128,
            case_limit=1,
            termination_grace_seconds=0.1,
        )
        argv.append("after")
        environment["EXAMPLE_VALUE"] = "after"

        self.assertEqual(
            plan.argv,
            (sys.executable, "-c", "raise SystemExit(0)"),
        )
        self.assertEqual(dict(plan.environment), {"EXAMPLE_VALUE": "before"})
        with self.assertRaises((AttributeError, TypeError)):
            plan.environment["OTHER"] = "value"

    def test_direct_process_uses_clean_environment_and_bounded_output(
        self,
    ) -> None:
        plan = AuthorizedProcessTaskPlan(
            argv=(
                sys.executable,
                "-c",
                (
                    "import os,sys;"
                    "sys.stdout.write("
                    "os.environ.get('INJECTED','missing')+'|'+"
                    "os.environ.get('INHERITED','missing')+'|'+'x'*4096)"
                ),
            ),
            cwd=self.root,
            environment={"INJECTED": "present"},
            deadline_seconds=2.0,
            output_limit_bytes=64,
            case_limit=3,
            termination_grace_seconds=0.1,
        )
        progress: list[BenchmarkProgressEvent] = []

        with patch.dict(
            os.environ,
            {"INHERITED": _PRIVATE_ENVIRONMENT},
            clear=False,
        ):
            result = AuthorizedProcessTaskExecutor().execute(
                self._invocation(plan),
                cancellation=_MutableCancellation(),
                on_progress=progress.append,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.completed_cases, 3)
        self.assertEqual([event.sequence for event in progress], [1, 2, 3])
        details = result.private_payload
        self.assertIsInstance(details, ProcessExecutionDetails)
        assert isinstance(details, ProcessExecutionDetails)
        self.assertLessEqual(len(details.stdout), 64)
        self.assertTrue(details.stdout.startswith(b"present|missing|"))
        self.assertTrue(details.stdout_truncated)
        self.assertNotIn(_PRIVATE_ENVIRONMENT.encode(), details.stdout)
        self.assertEqual(details.exit_code, 0)

    def test_deadline_stops_the_process_group_and_returns_failed(self) -> None:
        plan = AuthorizedProcessTaskPlan(
            argv=(sys.executable, "-c", "import time;time.sleep(60)"),
            cwd=self.root,
            environment={},
            deadline_seconds=0.05,
            output_limit_bytes=64,
            case_limit=1,
            termination_grace_seconds=0.05,
        )

        result = AuthorizedProcessTaskExecutor().execute(
            self._invocation(plan),
            cancellation=_MutableCancellation(),
            on_progress=lambda event: None,
        )

        self.assertEqual(result.status, "failed")
        details = result.private_payload
        self.assertIsInstance(details, ProcessExecutionDetails)
        assert isinstance(details, ProcessExecutionDetails)
        self.assertEqual(details.failure_class, "deadline")

    def test_cancellation_terminates_and_reaps_the_real_process_tree(
        self,
    ) -> None:
        pid_file = self.root / "public-pids.txt"
        plan = AuthorizedProcessTaskPlan(
            argv=(sys.executable, str(_HELPER), str(pid_file)),
            cwd=self.root,
            environment={},
            deadline_seconds=5.0,
            output_limit_bytes=64,
            case_limit=1,
            termination_grace_seconds=0.1,
        )
        recorded_pids: tuple[int, ...] = ()
        try:
            result = AuthorizedProcessTaskExecutor().execute(
                self._invocation(plan),
                cancellation=_FileCancellation(pid_file),
                on_progress=lambda event: None,
            )
            self.assertEqual(result.status, "cancelled")
            recorded_pids = tuple(
                int(value)
                for value in pid_file.read_text(encoding="utf-8").splitlines()
            )
            self.assertEqual(len(recorded_pids), 2)
            deadline = time.monotonic() + 2.0
            while (
                any(_pid_exists(pid) for pid in recorded_pids)
                and time.monotonic() < deadline
            ):
                time.sleep(0.02)
            self.assertFalse(
                any(_pid_exists(pid) for pid in recorded_pids),
                "process-tree PID survived executor cancellation",
            )
        finally:
            for pid in recorded_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


if __name__ == "__main__":
    unittest.main()
