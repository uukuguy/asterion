"""Sequential generic benchmark execution."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from asterion.benchmarks.evidence import (
    BenchmarkEvidenceError,
    BenchmarkEvidenceStore,
    BenchmarkProgressEvent,
    BenchmarkRunResult,
    BenchmarkTaskResult,
)
from asterion.benchmarks.model import (
    BenchmarkTaskInvocation,
    BenchmarkTaskImplementation,
    BenchmarkTaskRequest,
    ResolvedBenchmarkPlan,
    ResolvedBenchmarkTask,
)
from asterion.runtime.host import CancellationSignal


OutputDirectoryFactory = Callable[[ResolvedBenchmarkPlan, ResolvedBenchmarkTask], Path]
_TASK_TERMINAL_PROGRESS = frozenset(
    {"task.started", "task.completed", "task.failed", "task.cancelled"}
)


@runtime_checkable
class BenchmarkTaskExecutor(Protocol):
    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult: ...


class BenchmarkRunner:
    """Run an already-resolved benchmark plan sequentially."""

    def __init__(self, *, output_directory_factory: OutputDirectoryFactory) -> None:
        self._output_directory_factory = output_directory_factory

    def run(
        self,
        plan: ResolvedBenchmarkPlan,
        *,
        executor: BenchmarkTaskExecutor,
        evidence: BenchmarkEvidenceStore,
        cancellation: CancellationSignal,
    ) -> BenchmarkRunResult:
        evidence.initialize(plan)
        completed = evidence.compatible_completed_task_results(plan)
        completed_by_id = frozenset(result.task_id for result in completed)
        results = list(completed)
        sequence = evidence.next_progress_sequence(plan)
        run_status = "completed"
        persisted_run = evidence.compatible_run_result(plan)
        if persisted_run is not None:
            evidence.finish_run(persisted_run)
            return persisted_run

        if len(completed) == len(plan.tasks):
            result = BenchmarkRunResult(status="completed", tasks=tuple(results))
            terminal_progress_status = evidence.terminal_progress_status(plan)
            if terminal_progress_status is None:
                evidence.append_progress(
                    BenchmarkProgressEvent(sequence=sequence, status="run.completed")
                )
            elif terminal_progress_status != "run.completed":
                raise BenchmarkEvidenceError("benchmark evidence resume is invalid")
            evidence.finish_run(result)
            return result

        if cancellation.cancelled:
            result = BenchmarkRunResult(status="cancelled", tasks=tuple(results))
            terminal_progress_status = evidence.terminal_progress_status(plan)
            if terminal_progress_status is None:
                evidence.append_progress(
                    BenchmarkProgressEvent(sequence=sequence, status="run.cancelled")
                )
            elif terminal_progress_status != "run.cancelled":
                raise BenchmarkEvidenceError("benchmark evidence resume is invalid")
            evidence.finish_run(result)
            return result

        evidence.append_progress(
            BenchmarkProgressEvent(sequence=sequence, status="run.started")
        )
        sequence += 1

        for task in plan.tasks:
            task_id = task.task.task_id
            if task_id in completed_by_id:
                continue
            if cancellation.cancelled:
                run_status = "cancelled"
                break

            task_result = self._execute_task(
                plan,
                task,
                executor=executor,
                evidence=evidence,
                cancellation=cancellation,
                next_sequence=sequence,
            )
            sequence += task_result.progress_count
            results.append(task_result.result)
            if task_result.result.status != "completed":
                run_status = task_result.result.status
                break

        run_result = BenchmarkRunResult(status=run_status, tasks=tuple(results))
        terminal_status = f"run.{run_status}"
        evidence.append_progress(
            BenchmarkProgressEvent(sequence=sequence, status=terminal_status)
        )
        evidence.finish_run(run_result)
        return run_result

    def _execute_task(
        self,
        plan: ResolvedBenchmarkPlan,
        task: ResolvedBenchmarkTask,
        *,
        executor: BenchmarkTaskExecutor,
        evidence: BenchmarkEvidenceStore,
        cancellation: CancellationSignal,
        next_sequence: int,
    ) -> _TaskExecutionResult:
        task_id = task.task.task_id
        evidence.start_task(task)
        evidence.append_progress(
            BenchmarkProgressEvent(
                sequence=next_sequence,
                status="task.started",
                task_id=task_id,
            )
        )
        progress_count = 1

        def append_progress(event: BenchmarkProgressEvent) -> None:
            nonlocal progress_count
            _validate_callback_progress(event)
            progress_count += 1
            evidence.append_progress(
                BenchmarkProgressEvent(
                    sequence=next_sequence + progress_count - 1,
                    status=event.status,
                    task_id=task_id,
                )
            )

        try:
            output_directory = self._output_directory_factory(plan, task)
            request = BenchmarkTaskRequest(
                run_id=plan.run_id,
                suite_ref=plan.suite.suite_ref,
                task_id=task_id,
                case_limit=plan.case_limit,
                output_directory=output_directory,
            )
            implementation = cast(
                BenchmarkTaskImplementation,
                task.binding.implementation,
            )
            invocation = implementation.build_invocation(request)
            if (
                not isinstance(invocation, BenchmarkTaskInvocation)
                or invocation.task_id != task_id
                or invocation.binding_id != task.binding.binding_id
            ):
                result = _failed_result(task_id)
            else:
                result = executor.execute(
                    invocation,
                    cancellation=cancellation,
                    on_progress=append_progress,
                )
            if result.task_id != task_id or result.case_count > plan.case_limit:
                result = _failed_result(task_id)
        except BenchmarkEvidenceError:
            raise
        except Exception:
            result = _failed_result(task_id)

        evidence.finish_task(result)
        return _TaskExecutionResult(result=result, progress_count=progress_count)


class _TaskExecutionResult:
    def __init__(self, *, result: BenchmarkTaskResult, progress_count: int) -> None:
        self.result = result
        self.progress_count = progress_count


def _failed_result(task_id: str) -> BenchmarkTaskResult:
    return BenchmarkTaskResult(task_id=task_id, status="failed", case_count=0)


def _validate_callback_progress(event: BenchmarkProgressEvent) -> None:
    if (
        not isinstance(event, BenchmarkProgressEvent)
        or not event.status.startswith("task.")
        or event.status.startswith("run.")
        or event.status in _TASK_TERMINAL_PROGRESS
    ):
        raise BenchmarkEvidenceError("benchmark progress event is invalid")


__all__ = (
    "BenchmarkRunner",
    "BenchmarkTaskExecutor",
    "OutputDirectoryFactory",
)
