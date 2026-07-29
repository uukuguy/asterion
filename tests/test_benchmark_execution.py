from __future__ import annotations

import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from asterion.benchmarks.evidence import (
    BenchmarkEvidenceError,
    BenchmarkEvidenceStore,
    BenchmarkProgressEvent,
    BenchmarkRunResult,
    BenchmarkTaskResult,
    LocalPrivateBenchmarkEvidenceStore,
)
from asterion.benchmarks.execution import (
    BenchmarkRunner,
    BenchmarkTaskExecutor,
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
from asterion.runtime.host import CancellationSignal


APPLICATION_REF = ApplicationRef("example.application", "1.0.0")
SUITE_REF = BenchmarkSuiteRef("example.suite", "1.0.0")
PACKAGE_REF = CapabilityPackageRef("example.package", "1.0.0")
ALPHA_REF = CapabilityRef("example.alpha", "1.0.0")
BETA_REF = CapabilityRef("example.beta", "1.0.0")
GAMMA_REF = CapabilityRef("example.gamma", "1.0.0")


class BenchmarkExecutionTests(unittest.TestCase):
    def test_tasks_execute_once_and_sequentially(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            calls: list[tuple[str, str]] = []
            p = plan(
                task_ids=("example.alpha", "example.beta", "example.gamma"),
                build_log=calls,
            )
            output_factory = RecordingOutputFactory(Path(temp_dir) / "outputs")
            executor = RecordingExecutor(calls)
            evidence = LocalPrivateBenchmarkEvidenceStore(Path(temp_dir) / "evidence")

            result = BenchmarkRunner(output_directory_factory=output_factory).run(
                p,
                executor=executor,
                evidence=evidence,
                cancellation=ManualCancellation(),
            )

        self.assertEqual(
            calls,
            [
                ("build", "example.alpha"),
                ("execute", "example.alpha"),
                ("build", "example.beta"),
                ("execute", "example.beta"),
                ("build", "example.gamma"),
                ("execute", "example.gamma"),
            ],
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(
            tuple(task.task_id for task in result.tasks),
            ("example.alpha", "example.beta", "example.gamma"),
        )
        self.assertEqual(
            tuple(
                output_factory.output_directory_for(task)
                for _plan, task in output_factory.requests
            ),
            (
                Path(temp_dir) / "outputs" / "example.alpha",
                Path(temp_dir) / "outputs" / "example.beta",
                Path(temp_dir) / "outputs" / "example.gamma",
            ),
        )
        self.assertIsInstance(executor, BenchmarkTaskExecutor)

    def test_resume_skips_exact_completed_prefix_and_returns_full_result(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            p = plan()
            root = Path(temp_dir) / "evidence"
            original = LocalPrivateBenchmarkEvidenceStore(root)
            original.initialize(p)
            alpha = BenchmarkTaskResult(
                task_id="example.alpha",
                status="completed",
                case_count=2,
                artifact_ids=("artifact.alpha",),
            )
            original.start_task(p.tasks[0])
            original.finish_task(alpha)

            calls: list[tuple[str, str]] = []
            p = plan(build_log=calls)
            resumed = LocalPrivateBenchmarkEvidenceStore(root)
            result = BenchmarkRunner(
                output_directory_factory=RecordingOutputFactory(
                    Path(temp_dir) / "outputs"
                ),
            ).run(
                p,
                executor=RecordingExecutor(calls),
                evidence=resumed,
                cancellation=ManualCancellation(),
            )

        self.assertEqual(
            calls,
            [("build", "example.beta"), ("execute", "example.beta")],
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.tasks[0], alpha)
        self.assertEqual(
            tuple(task.task_id for task in result.tasks),
            ("example.alpha", "example.beta"),
        )

    def test_partial_resume_continues_existing_progress_sequence(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            p = plan()
            root = Path(temp_dir) / "evidence"
            original = LocalPrivateBenchmarkEvidenceStore(root)
            original.initialize(p)
            original.append_progress(
                BenchmarkProgressEvent(sequence=1, status="run.started")
            )
            original.start_task(p.tasks[0])
            original.append_progress(
                BenchmarkProgressEvent(
                    sequence=2,
                    status="task.started",
                    task_id="example.alpha",
                )
            )
            alpha = BenchmarkTaskResult(
                task_id="example.alpha",
                status="completed",
                case_count=2,
                artifact_ids=("artifact.alpha",),
            )
            original.finish_task(alpha)

            calls: list[tuple[str, str]] = []
            evidence = RecordingEvidence(LocalPrivateBenchmarkEvidenceStore(root))
            result = BenchmarkRunner(
                output_directory_factory=RecordingOutputFactory(
                    Path(temp_dir) / "outputs"
                ),
            ).run(
                plan(build_log=calls),
                executor=VerboseExecutor(),
                evidence=evidence,
                cancellation=ManualCancellation(),
            )

        progress = [
            event
            for kind, event in evidence.events
            if kind == "progress" and event is not None
        ]
        self.assertEqual([event.sequence for event in progress], [3, 4, 5, 6])
        self.assertEqual(
            [(event.status, event.task_id) for event in progress],
            [
                ("run.started", None),
                ("task.started", "example.beta"),
                ("task.note", "example.beta"),
                ("run.completed", None),
            ],
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.tasks[0], alpha)

    def test_resume_completed_run_returns_exact_persisted_result_without_execution(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            p = plan()
            root = Path(temp_dir) / "evidence"
            original = LocalPrivateBenchmarkEvidenceStore(root)
            original.initialize(p)
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
            original.start_task(p.tasks[0])
            original.finish_task(alpha)
            original.start_task(p.tasks[1])
            original.finish_task(beta)
            expected = BenchmarkRunResult(status="completed", tasks=(alpha, beta))
            original.finish_run(expected)

            calls: list[tuple[str, str]] = []
            result = BenchmarkRunner(
                output_directory_factory=RecordingOutputFactory(
                    Path(temp_dir) / "outputs"
                ),
            ).run(
                p,
                executor=RecordingExecutor(calls),
                evidence=LocalPrivateBenchmarkEvidenceStore(root),
                cancellation=ManualCancellation(),
            )

        self.assertEqual(result, expected)
        self.assertEqual(calls, [])

    def test_full_completed_prefix_without_run_result_emits_terminal_progress(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            p = plan()
            root = Path(temp_dir) / "evidence"
            original = LocalPrivateBenchmarkEvidenceStore(root)
            original.initialize(p)
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
            original.start_task(p.tasks[0])
            original.finish_task(alpha)
            original.start_task(p.tasks[1])
            original.finish_task(beta)

            evidence = RecordingEvidence(LocalPrivateBenchmarkEvidenceStore(root))
            result = BenchmarkRunner(
                output_directory_factory=RecordingOutputFactory(
                    Path(temp_dir) / "outputs"
                ),
            ).run(
                p,
                executor=ForbiddenExecutor(),
                evidence=evidence,
                cancellation=ManualCancellation(),
            )

        self.assertEqual(
            [
                event
                for kind, event in evidence.events
                if kind == "progress" and event is not None
            ],
            [BenchmarkProgressEvent(sequence=1, status="run.completed")],
        )
        self.assertEqual(
            result,
            BenchmarkRunResult(status="completed", tasks=(alpha, beta)),
        )

    def test_full_resume_does_not_swallow_evidence_finish_failure(self) -> None:
        p = plan()
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

        with self.assertRaisesRegex(
            BenchmarkEvidenceError,
            "benchmark evidence is invalid",
        ):
            BenchmarkRunner(
                output_directory_factory=lambda _plan, _task: Path.cwd()
            ).run(
                p,
                executor=FixedResultExecutor(result.tasks[0]),
                evidence=FailingCompletedEvidence(result),
                cancellation=ManualCancellation(),
            )

    def test_first_task_failure_prevents_later_tasks(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            calls: list[tuple[str, str]] = []
            result = BenchmarkRunner(
                output_directory_factory=RecordingOutputFactory(
                    Path(temp_dir) / "outputs"
                ),
            ).run(
                plan(build_log=calls),
                executor=RecordingExecutor(calls, statuses={"example.alpha": "failed"}),
                evidence=LocalPrivateBenchmarkEvidenceStore(
                    Path(temp_dir) / "evidence"
                ),
                cancellation=ManualCancellation(),
            )

        self.assertEqual(
            calls,
            [("build", "example.alpha"), ("execute", "example.alpha")],
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(
            result.tasks,
            (
                BenchmarkTaskResult(
                    task_id="example.alpha", status="failed", case_count=3
                ),
            ),
        )

    def test_pre_task_cancellation_starts_nothing(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            calls: list[tuple[str, str]] = []
            evidence = RecordingEvidence(
                LocalPrivateBenchmarkEvidenceStore(Path(temp_dir) / "evidence")
            )
            result = BenchmarkRunner(
                output_directory_factory=RecordingOutputFactory(
                    Path(temp_dir) / "outputs"
                ),
            ).run(
                plan(),
                executor=RecordingExecutor(calls),
                evidence=evidence,
                cancellation=ManualCancellation(cancelled=True),
            )

        self.assertEqual(calls, [])
        self.assertEqual(
            evidence.events,
            [
                ("initialize", None),
                (
                    "progress",
                    BenchmarkProgressEvent(sequence=1, status="run.cancelled"),
                ),
                ("finish_run", None),
            ],
        )
        self.assertEqual(result, BenchmarkRunResult(status="cancelled", tasks=()))

    def test_mid_task_cancellation_reaches_executor_and_stops_later_tasks(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            calls: list[tuple[str, str]] = []
            cancellation = ManualCancellation()
            result = BenchmarkRunner(
                output_directory_factory=RecordingOutputFactory(
                    Path(temp_dir) / "outputs"
                ),
            ).run(
                plan(build_log=calls),
                executor=CancellingExecutor(calls, cancellation),
                evidence=LocalPrivateBenchmarkEvidenceStore(
                    Path(temp_dir) / "evidence"
                ),
                cancellation=cancellation,
            )

        self.assertEqual(
            calls,
            [
                ("build", "example.alpha"),
                ("execute", "example.alpha"),
                ("cancelled-seen", "example.alpha"),
            ],
        )
        self.assertEqual(
            result,
            BenchmarkRunResult(
                status="cancelled",
                tasks=(
                    BenchmarkTaskResult(
                        task_id="example.alpha",
                        status="cancelled",
                        case_count=1,
                    ),
                ),
            ),
        )

    def test_runner_controlled_progress_sequences_are_contiguous_and_terminal_once(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            evidence = RecordingEvidence(
                LocalPrivateBenchmarkEvidenceStore(Path(temp_dir) / "evidence")
            )
            result = BenchmarkRunner(
                output_directory_factory=RecordingOutputFactory(
                    Path(temp_dir) / "outputs"
                ),
            ).run(
                plan(),
                executor=VerboseExecutor(),
                evidence=evidence,
                cancellation=ManualCancellation(),
            )

        progress = [
            event
            for kind, event in evidence.events
            if kind == "progress" and event is not None
        ]
        self.assertEqual([event.sequence for event in progress], [1, 2, 3, 4, 5, 6])
        self.assertEqual(
            [(event.status, event.task_id) for event in progress],
            [
                ("run.started", None),
                ("task.started", "example.alpha"),
                ("task.note", "example.alpha"),
                ("task.started", "example.beta"),
                ("task.note", "example.beta"),
                ("run.completed", None),
            ],
        )
        self.assertEqual(
            [kind for kind, _ in evidence.events].count("finish_task"),
            2,
        )
        self.assertEqual(
            [kind for kind, _ in evidence.events].count("finish_run"),
            1,
        )
        self.assertEqual(result.status, "completed")

    def test_failed_and_cancelled_runs_emit_one_terminal_progress_event(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            for status in ("failed", "cancelled"):
                with self.subTest(status=status):
                    root = Path(temp_dir) / status
                    evidence = RecordingEvidence(
                        LocalPrivateBenchmarkEvidenceStore(root / "evidence")
                    )
                    calls: list[tuple[str, str]] = []
                    result = BenchmarkRunner(
                        output_directory_factory=RecordingOutputFactory(
                            root / "outputs"
                        ),
                    ).run(
                        plan(build_log=calls),
                        executor=RecordingExecutor(
                            calls,
                            statuses={"example.alpha": status},
                        ),
                        evidence=evidence,
                        cancellation=ManualCancellation(),
                    )

                    terminal = [
                        event
                        for kind, event in evidence.events
                        if kind == "progress"
                        and event is not None
                        and event.status.startswith("run.")
                    ]
                    self.assertEqual(
                        [event.status for event in terminal],
                        ["run.started", f"run.{status}"],
                    )
                    self.assertEqual(result.status, status)

    def test_executor_exception_becomes_redacted_failed_result(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            calls: list[tuple[str, str]] = []
            result = BenchmarkRunner(
                output_directory_factory=RecordingOutputFactory(
                    Path(temp_dir) / "outputs"
                ),
            ).run(
                plan(build_log=calls),
                executor=ExplodingExecutor(calls),
                evidence=LocalPrivateBenchmarkEvidenceStore(
                    Path(temp_dir) / "evidence"
                ),
                cancellation=ManualCancellation(),
            )

        self.assertEqual(
            calls,
            [("build", "example.alpha"), ("execute", "example.alpha")],
        )
        self.assertEqual(
            result,
            BenchmarkRunResult(
                status="failed",
                tasks=(
                    BenchmarkTaskResult(
                        task_id="example.alpha",
                        status="failed",
                        case_count=0,
                    ),
                ),
            ),
        )
        self.assertNotIn("SECRET-EXECUTOR", repr(result))

    def test_implementation_exception_becomes_redacted_failed_result(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            calls: list[tuple[str, str]] = []
            result = BenchmarkRunner(
                output_directory_factory=RecordingOutputFactory(
                    Path(temp_dir) / "outputs"
                ),
            ).run(
                plan(
                    build_log=calls,
                    implementation_factory=lambda task_id, log: ExplodingImplementation(
                        task_id,
                        log,
                    ),
                ),
                executor=RecordingExecutor(calls),
                evidence=LocalPrivateBenchmarkEvidenceStore(
                    Path(temp_dir) / "evidence"
                ),
                cancellation=ManualCancellation(),
            )

        self.assertEqual(calls, [("build", "example.alpha")])
        self.assertEqual(
            result,
            BenchmarkRunResult(
                status="failed",
                tasks=(
                    BenchmarkTaskResult(
                        task_id="example.alpha",
                        status="failed",
                        case_count=0,
                    ),
                ),
            ),
        )
        self.assertNotIn("SECRET-IMPLEMENTATION", repr(result))

    def test_invocation_identity_is_validated_before_executor_runs(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            cases = (
                ("example.beta", "example.alpha"),
                ("example.alpha", "example.beta"),
            )
            for invocation_task_id, binding_id in cases:
                with self.subTest(
                    invocation_task_id=invocation_task_id,
                    binding_id=binding_id,
                ):
                    calls: list[tuple[str, str]] = []
                    result = BenchmarkRunner(
                        output_directory_factory=RecordingOutputFactory(
                            Path(temp_dir) / invocation_task_id / "outputs"
                        ),
                    ).run(
                        plan(
                            build_log=calls,
                            implementation_factory=lambda task_id, log: (
                                WrongInvocationImplementation(
                                    task_id,
                                    log,
                                    invocation_task_id=invocation_task_id,
                                    binding_id=binding_id,
                                )
                            ),
                        ),
                        executor=ForbiddenExecutor(),
                        evidence=LocalPrivateBenchmarkEvidenceStore(
                            Path(temp_dir) / invocation_task_id / "evidence"
                        ),
                        cancellation=ManualCancellation(),
                    )

                    self.assertEqual(calls, [("build", "example.alpha")])
                    self.assertEqual(
                        result,
                        BenchmarkRunResult(
                            status="failed",
                            tasks=(
                                BenchmarkTaskResult(
                                    task_id="example.alpha",
                                    status="failed",
                                    case_count=0,
                                ),
                            ),
                        ),
                    )

    def test_callback_progress_is_task_scoped_and_nonterminal(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            evidence = RecordingEvidence(
                LocalPrivateBenchmarkEvidenceStore(Path(temp_dir) / "evidence")
            )
            result = BenchmarkRunner(
                output_directory_factory=RecordingOutputFactory(
                    Path(temp_dir) / "outputs"
                ),
            ).run(
                plan(),
                executor=WrongTaskProgressExecutor(),
                evidence=evidence,
                cancellation=ManualCancellation(),
            )

        progress = [
            event
            for kind, event in evidence.events
            if kind == "progress" and event is not None
        ]
        self.assertIn(
            BenchmarkProgressEvent(
                sequence=3,
                status="task.note",
                task_id="example.alpha",
            ),
            progress,
        )
        self.assertEqual(result.status, "completed")

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            with self.assertRaises(BenchmarkEvidenceError):
                BenchmarkRunner(
                    output_directory_factory=RecordingOutputFactory(
                        Path(temp_dir) / "outputs"
                    ),
                ).run(
                    plan(),
                    executor=ForbiddenProgressExecutor("run.completed"),
                    evidence=LocalPrivateBenchmarkEvidenceStore(
                        Path(temp_dir) / "evidence"
                    ),
                    cancellation=ManualCancellation(),
                )

    def test_callback_evidence_failure_is_not_swallowed_as_task_failure(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            with self.assertRaises(BenchmarkEvidenceError):
                BenchmarkRunner(
                    output_directory_factory=RecordingOutputFactory(
                        Path(temp_dir) / "outputs"
                    ),
                ).run(
                    plan(),
                    executor=VerboseExecutor(),
                    evidence=FailingProgressEvidence(
                        LocalPrivateBenchmarkEvidenceStore(Path(temp_dir) / "evidence"),
                    ),
                    cancellation=ManualCancellation(),
                )

    def test_result_task_identity_and_case_count_are_bound_to_plan(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            for returned, expected in (
                (
                    BenchmarkTaskResult(
                        task_id="example.beta",
                        status="completed",
                        case_count=1,
                    ),
                    BenchmarkRunResult(
                        status="failed",
                        tasks=(
                            BenchmarkTaskResult(
                                task_id="example.alpha",
                                status="failed",
                                case_count=0,
                            ),
                        ),
                    ),
                ),
                (
                    BenchmarkTaskResult(
                        task_id="example.alpha",
                        status="completed",
                        case_count=4,
                    ),
                    BenchmarkRunResult(
                        status="failed",
                        tasks=(
                            BenchmarkTaskResult(
                                task_id="example.alpha",
                                status="failed",
                                case_count=0,
                            ),
                        ),
                    ),
                ),
            ):
                with self.subTest(returned=returned):
                    root = Path(temp_dir) / returned.task_id.replace(".", "-")
                    result = BenchmarkRunner(
                        output_directory_factory=RecordingOutputFactory(
                            root / "outputs"
                        ),
                    ).run(
                        plan(),
                        executor=FixedResultExecutor(returned),
                        evidence=LocalPrivateBenchmarkEvidenceStore(root / "evidence"),
                        cancellation=ManualCancellation(),
                    )
                    self.assertEqual(result, expected)

    def test_runner_does_not_discover_authorize_retry_or_start_services(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            calls: list[tuple[str, str]] = []
            result = BenchmarkRunner(
                output_directory_factory=RecordingOutputFactory(
                    Path(temp_dir) / "outputs"
                ),
            ).run(
                plan(build_log=calls),
                executor=RecordingExecutor(calls, statuses={"example.alpha": "failed"}),
                evidence=LocalPrivateBenchmarkEvidenceStore(
                    Path(temp_dir) / "evidence"
                ),
                cancellation=HostileCancellation(),
            )

        self.assertEqual(result.status, "failed")
        self.assertEqual(
            calls,
            [("build", "example.alpha"), ("execute", "example.alpha")],
        )


def plan(
    *,
    task_ids: tuple[str, ...] = ("example.alpha", "example.beta"),
    build_log: list[tuple[str, str]] | None = None,
    implementation_factory: (
        Callable[[str, list[tuple[str, str]]], object] | None
    ) = None,
) -> ResolvedBenchmarkPlan:
    suite = BenchmarkSuiteManifest(
        suite_ref=SUITE_REF,
        owner_package=PACKAGE_REF,
        tasks=tuple(task_manifest(task_id) for task_id in task_ids),
        artifact_media_types=("application/json",),
        default_case_limit=10,
        default_concurrency=1,
    )
    log: list[tuple[str, str]] = build_log if build_log is not None else []
    factory = implementation_factory or (
        lambda task_id, task_log: RecordingImplementation(task_id, task_log)
    )
    return ResolvedBenchmarkPlan(
        run_id="run-001",
        application_ref=APPLICATION_REF,
        suite=suite,
        tasks=tuple(
            resolved_task(index, task, factory(task.task_id, log))
            for index, task in enumerate(suite.tasks, start=1)
        ),
        case_limit=3,
        package_locks=(
            CapabilitySourceLock(
                entries=(
                    CapabilitySourceLockEntry(
                        package_ref=PACKAGE_REF,
                        payload_sha256="a" * 64,
                        source_id="example.package.local-directory",
                    ),
                )
            ),
        ),
    )


def task_manifest(task_id: str) -> BenchmarkTaskManifest:
    capability = {
        "example.alpha": ALPHA_REF,
        "example.beta": BETA_REF,
        "example.gamma": GAMMA_REF,
    }[task_id]
    return BenchmarkTaskManifest(
        task_id=task_id,
        capability=capability,
        binding_id=task_id,
        metric_contract_id="example.metric",
        result_contract_id="example.result",
        note="SECRET-PROMPT-BODY",
    )


def resolved_task(
    ordinal: int,
    task: BenchmarkTaskManifest,
    implementation: object,
) -> ResolvedBenchmarkTask:
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
            implementation=implementation,
        ),
    )


class RecordingImplementation:
    def __init__(self, task_id: str, log: list[tuple[str, str]]) -> None:
        self._task_id = task_id
        self._log = log

    def build_invocation(
        self,
        request: BenchmarkTaskRequest,
    ) -> BenchmarkTaskInvocation:
        self._log.append(("build", request.task_id))
        return BenchmarkTaskInvocation(
            task_id=self._task_id,
            binding_id=self._task_id,
            public_arguments=(request.task_id,),
            private_payload={"request": request},
        )


class ExplodingImplementation:
    def __init__(self, task_id: str, log: list[tuple[str, str]]) -> None:
        self._task_id = task_id
        self._log = log

    def build_invocation(
        self,
        request: BenchmarkTaskRequest,
    ) -> BenchmarkTaskInvocation:
        del request
        self._log.append(("build", self._task_id))
        raise RuntimeError("SECRET-IMPLEMENTATION-FAILURE")


class WrongInvocationImplementation:
    def __init__(
        self,
        task_id: str,
        log: list[tuple[str, str]],
        *,
        invocation_task_id: str,
        binding_id: str,
    ) -> None:
        self._task_id = task_id
        self._log = log
        self._invocation_task_id = invocation_task_id
        self._binding_id = binding_id

    def build_invocation(
        self,
        request: BenchmarkTaskRequest,
    ) -> BenchmarkTaskInvocation:
        self._log.append(("build", request.task_id))
        return BenchmarkTaskInvocation(
            task_id=self._invocation_task_id,
            binding_id=self._binding_id,
            public_arguments=(self._task_id,),
            private_payload={"request": request},
        )


class RecordingExecutor:
    def __init__(
        self,
        calls: list[tuple[str, str]],
        *,
        statuses: dict[str, str] | None = None,
    ) -> None:
        self._calls = calls
        self._statuses = statuses or {}

    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult:
        del cancellation, on_progress
        self._calls.append(("execute", invocation.task_id))
        return BenchmarkTaskResult(
            task_id=invocation.task_id,
            status=self._statuses.get(invocation.task_id, "completed"),
            case_count=3,
        )


class VerboseExecutor:
    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult:
        del cancellation
        on_progress(
            BenchmarkProgressEvent(
                sequence=999,
                status="task.note",
                task_id=invocation.task_id,
            )
        )
        return BenchmarkTaskResult(
            task_id=invocation.task_id,
            status="completed",
            case_count=3,
        )


class CancellingExecutor:
    def __init__(
        self,
        calls: list[tuple[str, str]],
        cancellation: ManualCancellation,
    ) -> None:
        self._calls = calls
        self._cancellation = cancellation

    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult:
        del on_progress
        self._calls.append(("execute", invocation.task_id))
        self._cancellation.cancel()
        if cancellation.cancelled:
            self._calls.append(("cancelled-seen", invocation.task_id))
        return BenchmarkTaskResult(
            task_id=invocation.task_id,
            status="cancelled",
            case_count=1,
        )


class ExplodingExecutor:
    def __init__(self, calls: list[tuple[str, str]]) -> None:
        self._calls = calls

    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult:
        del cancellation, on_progress
        self._calls.append(("execute", invocation.task_id))
        raise RuntimeError("SECRET-EXECUTOR-FAILURE")


class FixedResultExecutor:
    def __init__(self, result: BenchmarkTaskResult) -> None:
        self._result = result

    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult:
        del invocation, cancellation, on_progress
        return self._result


class ForbiddenExecutor:
    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult:
        del invocation, cancellation, on_progress
        raise AssertionError("executor must not run")


class WrongTaskProgressExecutor:
    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult:
        del cancellation
        on_progress(
            BenchmarkProgressEvent(
                sequence=999,
                status="task.note",
                task_id="example.beta",
            )
        )
        return BenchmarkTaskResult(
            task_id=invocation.task_id,
            status="completed",
            case_count=3,
        )


class ForbiddenProgressExecutor:
    def __init__(self, status: str) -> None:
        self._status = status

    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult:
        del cancellation
        on_progress(
            BenchmarkProgressEvent(
                sequence=999,
                status=self._status,
                task_id=invocation.task_id,
            )
        )
        return BenchmarkTaskResult(
            task_id=invocation.task_id,
            status="completed",
            case_count=3,
        )


class RecordingOutputFactory:
    def __init__(self, root: Path) -> None:
        self._root = root
        self.requests: list[tuple[ResolvedBenchmarkPlan, ResolvedBenchmarkTask]] = []

    def __call__(
        self,
        plan: ResolvedBenchmarkPlan,
        task: ResolvedBenchmarkTask,
    ) -> Path:
        self.requests.append((plan, task))
        return self.output_directory_for(task)

    def output_directory_for(self, task: ResolvedBenchmarkTask) -> Path:
        return self._root / task.task.task_id


class RecordingEvidence:
    def __init__(self, delegate: BenchmarkEvidenceStore) -> None:
        self._delegate = delegate
        self.events: list[tuple[str, BenchmarkProgressEvent | None]] = []

    def initialize(self, plan: ResolvedBenchmarkPlan) -> None:
        self.events.append(("initialize", None))
        self._delegate.initialize(plan)

    def start_task(self, task: ResolvedBenchmarkTask) -> None:
        self.events.append(("start_task", None))
        self._delegate.start_task(task)

    def append_progress(self, event: BenchmarkProgressEvent) -> None:
        self.events.append(("progress", event))
        self._delegate.append_progress(event)

    def finish_task(self, result: BenchmarkTaskResult) -> None:
        self.events.append(("finish_task", None))
        self._delegate.finish_task(result)

    def finish_run(self, result: BenchmarkRunResult) -> None:
        self.events.append(("finish_run", None))
        self._delegate.finish_run(result)

    def compatible_completed_tasks(
        self,
        plan: ResolvedBenchmarkPlan,
    ) -> frozenset[str]:
        return self._delegate.compatible_completed_tasks(plan)

    def compatible_completed_task_results(
        self,
        plan: ResolvedBenchmarkPlan,
    ) -> tuple[BenchmarkTaskResult, ...]:
        return self._delegate.compatible_completed_task_results(plan)

    def compatible_run_result(
        self,
        plan: ResolvedBenchmarkPlan,
    ) -> BenchmarkRunResult | None:
        return self._delegate.compatible_run_result(plan)

    def next_progress_sequence(self, plan: ResolvedBenchmarkPlan) -> int:
        return self._delegate.next_progress_sequence(plan)


class FailingCompletedEvidence:
    def __init__(self, result: BenchmarkRunResult) -> None:
        self._result = result

    def initialize(self, plan: ResolvedBenchmarkPlan) -> None:
        del plan

    def start_task(self, task: ResolvedBenchmarkTask) -> None:
        del task

    def append_progress(self, event: BenchmarkProgressEvent) -> None:
        del event

    def finish_task(self, result: BenchmarkTaskResult) -> None:
        del result

    def finish_run(self, result: BenchmarkRunResult) -> None:
        del result
        raise BenchmarkEvidenceError("benchmark evidence is invalid")

    def compatible_completed_tasks(
        self,
        plan: ResolvedBenchmarkPlan,
    ) -> frozenset[str]:
        del plan
        return frozenset(task.task_id for task in self._result.tasks)

    def compatible_completed_task_results(
        self,
        plan: ResolvedBenchmarkPlan,
    ) -> tuple[BenchmarkTaskResult, ...]:
        del plan
        return self._result.tasks

    def compatible_run_result(
        self,
        plan: ResolvedBenchmarkPlan,
    ) -> BenchmarkRunResult | None:
        del plan
        return self._result

    def next_progress_sequence(self, plan: ResolvedBenchmarkPlan) -> int:
        del plan
        return 1


class FailingProgressEvidence(RecordingEvidence):
    def append_progress(self, event: BenchmarkProgressEvent) -> None:
        if event.status == "task.note":
            raise BenchmarkEvidenceError("benchmark progress event is invalid")
        super().append_progress(event)


class ManualCancellation:
    def __init__(self, *, cancelled: bool = False) -> None:
        self._cancelled = cancelled

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


class HostileCancellation:
    @property
    def cancelled(self) -> bool:
        return False

    def discover_packages(self) -> None:
        raise AssertionError("runner must not discover packages")

    def authorize(self) -> None:
        raise AssertionError("runner must not authorize")

    def start_services(self) -> None:
        raise AssertionError("runner must not start services")


if __name__ == "__main__":
    unittest.main()
