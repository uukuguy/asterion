"""DCI executors implementing Asterion's generic benchmark task protocol."""

from __future__ import annotations

from collections.abc import Callable

from asterion.benchmarks import (
    BenchmarkProgressEvent,
    BenchmarkTaskExecutor,
    BenchmarkTaskInvocation,
    BenchmarkTaskResult,
)
from asterion.capabilities.dci.implementation.benchmark_bindings import (
    DciBenchmarkInvocationPayload,
)
from asterion.runtime.host import CancellationSignal


class DciBenchmarkExecutorError(ValueError):
    """Raised when a DCI task invocation is not executable."""


class LocalDciBenchmarkExecutor(BenchmarkTaskExecutor):
    """Validate real bindings and complete deterministically without providers."""

    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult:
        try:
            if (
                not isinstance(invocation, BenchmarkTaskInvocation)
                or not isinstance(
                    invocation.private_payload,
                    DciBenchmarkInvocationPayload,
                )
                or not callable(on_progress)
                or not hasattr(cancellation, "cancelled")
            ):
                _fail()
            payload = invocation.private_payload
            if (
                payload.case_limit < 1
                or payload.max_concurrency != 1
                or payload.resume_policy != "compatible"
                or not payload.dataset.is_absolute()
                or not payload.corpus.is_absolute()
                or not payload.output_directory.is_absolute()
            ):
                _fail()
            if cancellation.cancelled:
                return BenchmarkTaskResult(
                    task_id=invocation.task_id,
                    status="cancelled",
                    case_count=0,
                )
            on_progress(
                BenchmarkProgressEvent(
                    sequence=1,
                    status="task.fixture.validated",
                    task_id=invocation.task_id,
                )
            )
            if cancellation.cancelled:
                return BenchmarkTaskResult(
                    task_id=invocation.task_id,
                    status="cancelled",
                    case_count=0,
                )
            return BenchmarkTaskResult(
                task_id=invocation.task_id,
                status="completed",
                case_count=payload.case_limit,
                artifact_ids=(f"{invocation.task_id}.fixture-result",),
            )
        except DciBenchmarkExecutorError:
            raise
        except Exception:
            _fail()


def _fail() -> None:
    raise DciBenchmarkExecutorError("DCI benchmark execution is invalid") from None


__all__ = (
    "DciBenchmarkExecutorError",
    "LocalDciBenchmarkExecutor",
)
