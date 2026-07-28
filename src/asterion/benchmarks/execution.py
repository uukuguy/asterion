"""Sequential execution for fully resolved benchmark plans."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from asterion.benchmarks.evidence import (
    BenchmarkEvidenceStore,
    BenchmarkProgressEvent,
    BenchmarkRunResult,
    BenchmarkTaskResult,
)
from asterion.benchmarks.model import (
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
    ResolvedBenchmarkPlan,
    ResolvedBenchmarkTask,
)
from asterion.runtime.host import CancellationSignal


class BenchmarkExecutionError(RuntimeError):
    """Stable private-payload-free benchmark execution failure."""


@runtime_checkable
class BenchmarkTaskExecutor(Protocol):
    """Injected execution boundary for one already-resolved task."""

    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult: ...


class BenchmarkRunner:
    """Run exact task bindings once, sequentially, and fail closed."""

    def run(
        self,
        plan: ResolvedBenchmarkPlan,
        *,
        executor: BenchmarkTaskExecutor,
        evidence: BenchmarkEvidenceStore,
        cancellation: CancellationSignal,
    ) -> BenchmarkRunResult:
        if not isinstance(plan, ResolvedBenchmarkPlan):
            raise BenchmarkExecutionError("benchmark execution plan is invalid")
        if not isinstance(executor, BenchmarkTaskExecutor):
            raise BenchmarkExecutionError("benchmark task executor is invalid")
        if not isinstance(evidence, BenchmarkEvidenceStore):
            raise BenchmarkExecutionError("benchmark evidence store is invalid")
        if not _is_cancellation_signal(cancellation):
            raise BenchmarkExecutionError("benchmark cancellation signal is invalid")

        evidence.initialize(plan)
        completed = evidence.compatible_completed_tasks(plan)
        ordered_task_ids = tuple(task.planned.task.task_id for task in plan.tasks)
        _validate_completed_prefix(completed, ordered_task_ids)
        completed_ids = [
            task_id for task_id in ordered_task_ids if task_id in completed
        ]
        if len(completed_ids) == len(ordered_task_ids):
            return _run_result(
                plan,
                status="completed",
                completed_task_ids=completed_ids,
                content_digests=(),
            )

        run_status = "completed"
        run_digests: list[str] = []
        for task in plan.tasks:
            task_id = task.planned.task.task_id
            if task_id in completed:
                continue
            if cancellation.cancelled:
                run_status = "cancelled"
                break

            invocation = _build_invocation(plan, task)
            evidence.start_task(task)
            expected_sequence = 1

            def record_progress(event: BenchmarkProgressEvent) -> None:
                nonlocal expected_sequence
                if (
                    not isinstance(event, BenchmarkProgressEvent)
                    or event.task_id != task_id
                    or event.sequence != expected_sequence
                    or event.total_cases != plan.plan.case_limit
                ):
                    raise BenchmarkExecutionError("benchmark task progress is invalid")
                evidence.append_progress(event)
                expected_sequence += 1

            try:
                result = executor.execute(
                    invocation,
                    cancellation=cancellation,
                    on_progress=record_progress,
                )
                if (
                    not isinstance(result, BenchmarkTaskResult)
                    or result.task_id != task_id
                    or result.completed_cases > plan.plan.case_limit
                ):
                    raise BenchmarkExecutionError("benchmark task result is invalid")
            except KeyboardInterrupt:
                result = _exception_result(task_id, status="cancelled")
            except Exception:
                result = _exception_result(task_id, status="failed")

            evidence.finish_task(result)
            if result.status == "completed":
                completed_ids.append(task_id)
                run_digests.extend(result.content_digests)
                if cancellation.cancelled:
                    run_status = "cancelled"
                    break
                continue
            run_status = result.status
            break

        result = _run_result(
            plan,
            status=run_status,
            completed_task_ids=completed_ids,
            content_digests=run_digests,
        )
        evidence.finish_run(result)
        return result


def _build_invocation(
    plan: ResolvedBenchmarkPlan,
    task: ResolvedBenchmarkTask,
) -> BenchmarkTaskInvocation:
    task_id = task.planned.task.task_id
    request = BenchmarkTaskRequest(
        run_id=plan.plan.run_id,
        suite_ref=plan.plan.suite.suite_ref,
        task_id=task_id,
        case_limit=plan.plan.case_limit,
        output_directory=Path(plan.plan.run_id) / task_id,
    )
    try:
        invocation = task.binding.implementation.build_invocation(request)
    except Exception:
        raise BenchmarkExecutionError("benchmark task invocation failed") from None
    if (
        not isinstance(invocation, BenchmarkTaskInvocation)
        or invocation.task_id != task_id
        or invocation.binding_id != task.binding.binding_id
    ):
        raise BenchmarkExecutionError("benchmark task invocation is invalid")
    return invocation


def _exception_result(
    task_id: str,
    *,
    status: str,
) -> BenchmarkTaskResult:
    return BenchmarkTaskResult(
        task_id=task_id,
        status=status,
        completed_cases=0,
        content_digests=(),
        private_payload={
            "failure_class": ("interrupted" if status == "cancelled" else "executor")
        },
    )


def _run_result(
    plan: ResolvedBenchmarkPlan,
    *,
    status: str,
    completed_task_ids: list[str],
    content_digests: tuple[str, ...] | list[str],
) -> BenchmarkRunResult:
    return BenchmarkRunResult(
        run_id=plan.plan.run_id,
        status=status,
        completed_task_ids=tuple(completed_task_ids),
        content_digests=tuple(content_digests),
        private_payload={"failure_class": None},
    )


def _validate_completed_prefix(
    completed: object,
    ordered_task_ids: tuple[str, ...],
) -> None:
    if not isinstance(completed, frozenset):
        raise BenchmarkExecutionError("benchmark resume evidence is invalid")
    completed_prefix = ordered_task_ids[: len(completed)]
    if completed != frozenset(completed_prefix):
        raise BenchmarkExecutionError("benchmark resume evidence is invalid")


def _is_cancellation_signal(value: object) -> bool:
    try:
        return isinstance(value.cancelled, bool)
    except Exception:
        return False
