"""DCI executors implementing Asterion's generic benchmark task protocol."""

from __future__ import annotations

import asyncio
import inspect
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from asterion.benchmarks import (
    BenchmarkProgressEvent,
    BenchmarkTaskExecutor,
    BenchmarkTaskInvocation,
    BenchmarkTaskResult,
)
from asterion.capabilities.dci.implementation.benchmark_bindings import (
    DciBenchmarkInvocationPayload,
)
from asterion.capabilities.dci.implementation.config import (
    DciPaths,
    DciRuntimeOptions,
)
from asterion.capabilities.dci.implementation.evaluation.benchmark import (
    BenchmarkRequest,
    BenchmarkResult,
    run_benchmark_async,
)
from asterion.capabilities.dci.implementation.evaluation.judge import JudgeConfig
from asterion.capabilities.dci.implementation.runtime.pi_rpc import (
    resolve_node_bin,
)
from asterion.runtime.host import CancellationSignal

_REAL_TASK_CONTRACTS = {
    "bcplus.level3": ("bcplus.level3", "github-level3", 830),
    "bcplus.main": ("bcplus.openai", "main", 830),
    "beir.arguana": ("beir.arguana", "paper-main", 1406),
    "beir.scifact": ("beir.scifact", "paper-main", 300),
    "bright.biology": ("bright.biology", "main", 103),
    "bright.earth-science": ("bright.earth-science", "main", 116),
    "bright.economics": ("bright.economics", "main", 103),
    "bright.robotics": ("bright.robotics", "main", 101),
    "qa.2wikimultihopqa": ("qa.2wikimultihopqa", "main", 12576),
    "qa.hotpotqa": ("qa.hotpotqa", "main", 7405),
    "qa.bamboogle.github-sample50": ("qa.bamboogle", "github-sample50", 50),
    "qa.bamboogle.paper-full125": ("qa.bamboogle", "paper-full125", 125),
}
_REAL_TASK_EXECUTION = {
    "bcplus.level3": (300, 10),
    "bcplus.main": (100, 10),
    "beir.arguana": (300, 10),
    "beir.scifact": (300, 10),
    "bright.biology": (300, 10),
    "bright.earth-science": (300, 10),
    "bright.economics": (300, 10),
    "bright.robotics": (300, 10),
}
_REAL_TASK_NATIVE_ATTEMPTS = {
    "beir.scifact": 3,
    "bright.biology": 3,
    "bright.earth-science": 3,
    "bright.economics": 3,
    "bright.robotics": 3,
}
_REAL_TASK_MODES = {
    "beir.arguana": "ir",
    "beir.scifact": "ir",
    "bright.biology": "ir",
    "bright.earth-science": "ir",
    "bright.economics": "ir",
    "bright.robotics": "ir",
}
_DEFAULT_EXPERIMENT_PROFILE = "asterion-safe/pi"
_UPSTREAM_EXPERIMENT_PROFILE = (
    "upstream-github/271f37e71f053bf0c99c05ce6d2fb53b841d922e/pi"
)
_EXPERIMENT_PROFILES = {
    _DEFAULT_EXPERIMENT_PROFILE,
    _UPSTREAM_EXPERIMENT_PROFILE,
}


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


class RealDciBenchmarkExecutor(BenchmarkTaskExecutor):
    """Translate one bounded real DCI task into the existing Agent/Judge engine."""

    def __init__(
        self,
        *,
        paths: DciPaths,
        runtime_options: DciRuntimeOptions,
        judge_config: JudgeConfig,
        experiment_profile: str = _DEFAULT_EXPERIMENT_PROFILE,
        max_turns: int = 100,
        benchmark_runner: Callable[..., Any] = run_benchmark_async,
        readiness_probe: Callable[..., None] | None = None,
    ) -> None:
        if (
            not isinstance(paths, DciPaths)
            or not isinstance(runtime_options, DciRuntimeOptions)
            or not isinstance(judge_config, JudgeConfig)
            or experiment_profile not in _EXPERIMENT_PROFILES
            or type(max_turns) is not int
            or max_turns < 1
            or not callable(benchmark_runner)
            or readiness_probe is not None
            and not callable(readiness_probe)
        ):
            _fail()
        self._paths = paths
        self._runtime_options = runtime_options
        self._judge_config = judge_config
        self._experiment_profile = experiment_profile
        self._max_turns = max_turns
        self._benchmark_runner = benchmark_runner
        self._readiness_probe = (
            _default_readiness_probe if readiness_probe is None else readiness_probe
        )

    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult:
        try:
            payload = _real_payload(invocation, cancellation, on_progress)
            self._readiness_probe(
                payload,
                self._paths,
                self._runtime_options,
                self._judge_config,
            )
            if cancellation.cancelled:
                return _cancelled(invocation.task_id)
            max_turns, max_concurrency = _REAL_TASK_EXECUTION.get(
                invocation.task_id,
                (self._max_turns, 1),
            )
            request = BenchmarkRequest(
                dataset=payload.dataset,
                output_root=payload.output_directory,
                cwd=self._paths.repo_root,
                judge_config=self._judge_config,
                runtime_options=self._runtime_options,
                limit=payload.case_limit,
                mode=_REAL_TASK_MODES.get(invocation.task_id, "qa"),
                profile=self._experiment_profile,
                dataset_profile=(
                    invocation.task_id
                    if invocation.task_id in _REAL_TASK_MODES
                    else None
                ),
                corpus=payload.corpus,
                max_concurrency=max_concurrency,
                max_turns=max_turns,
                max_native_attempts=_REAL_TASK_NATIVE_ATTEMPTS.get(
                    invocation.task_id, 2
                ),
                resume_policy="compatible",
            )
            on_progress(
                BenchmarkProgressEvent(
                    sequence=1,
                    status="task.real.started",
                    task_id=invocation.task_id,
                )
            )
            if cancellation.cancelled:
                return _cancelled(invocation.task_id)
            native = asyncio.run(
                _run_cancellable(
                    self._benchmark_runner,
                    request,
                    paths=self._paths,
                    cancellation=cancellation,
                )
            )
            if native is None:
                return _cancelled(invocation.task_id)
            if not isinstance(native, BenchmarkResult):
                _fail()
            total = native.counts.get("total")
            failed = native.counts.get("failed")
            if (
                type(total) is not int
                or type(failed) is not int
                or total != payload.case_limit
                or failed != 0
            ):
                return BenchmarkTaskResult(
                    task_id=invocation.task_id,
                    status="failed",
                    case_count=total if type(total) is int and total >= 0 else 0,
                )
            on_progress(
                BenchmarkProgressEvent(
                    sequence=2,
                    status="task.real.completed",
                    task_id=invocation.task_id,
                )
            )
            return BenchmarkTaskResult(
                task_id=invocation.task_id,
                status="completed",
                case_count=total,
                artifact_ids=(f"{invocation.task_id}.native-result",),
            )
        except DciBenchmarkExecutorError:
            raise
        except asyncio.CancelledError:
            return _cancelled(
                invocation.task_id
                if isinstance(invocation, BenchmarkTaskInvocation)
                else "qa.bamboogle.github-sample50"
            )
        except Exception:
            _fail()


def _real_payload(
    invocation: object,
    cancellation: object,
    on_progress: object,
) -> DciBenchmarkInvocationPayload:
    task_id = invocation.task_id if isinstance(invocation, BenchmarkTaskInvocation) else None
    contract = _REAL_TASK_CONTRACTS.get(task_id)
    if (
        not isinstance(invocation, BenchmarkTaskInvocation)
        or contract is None
        or invocation.binding_id != invocation.task_id
        or not isinstance(invocation.private_payload, DciBenchmarkInvocationPayload)
        or not callable(on_progress)
        or not hasattr(cancellation, "cancelled")
    ):
        _fail()
    payload = invocation.private_payload
    profile_id, selection_variant, max_case_limit = contract
    if (
        payload.profile_id != profile_id
        or payload.selection_variant != selection_variant
        or type(payload.case_limit) is not int
        or not 1 <= payload.case_limit <= max_case_limit
        or payload.max_concurrency != 1
        or payload.resume_policy != "compatible"
        or payload.runtime_context_level not in {None, "level3"}
        or not all(
            path.is_absolute()
            for path in (
                payload.dataset,
                payload.corpus,
                payload.output_directory,
            )
        )
    ):
        _fail()
    return payload


async def _run_cancellable(
    runner: Callable[..., Any],
    request: BenchmarkRequest,
    *,
    paths: DciPaths,
    cancellation: CancellationSignal,
) -> BenchmarkResult | None:
    async def invoke() -> BenchmarkResult:
        value = runner(request, paths=paths)
        if inspect.isawaitable(value):
            value = await value
        return value

    async def wait_for_cancel() -> None:
        while not cancellation.cancelled:
            await asyncio.sleep(0.01)

    task = asyncio.create_task(invoke())
    watcher = asyncio.create_task(wait_for_cancel())
    done, _pending = await asyncio.wait(
        (task, watcher),
        return_when=asyncio.FIRST_COMPLETED,
    )
    if watcher in done:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return None
    watcher.cancel()
    await asyncio.gather(watcher, return_exceptions=True)
    return task.result()


def _default_readiness_probe(
    payload: DciBenchmarkInvocationPayload,
    paths: DciPaths,
    runtime_options: DciRuntimeOptions,
    judge_config: JudgeConfig,
) -> None:
    if (
        not _regular_nonsymlink(payload.dataset)
        or not _directory_nonsymlink(payload.corpus)
        or _bounded_jsonl_count(payload.dataset, payload.case_limit)
        < payload.case_limit
        or not judge_config.api_key
        or not runtime_options.provider
        or not runtime_options.model
        or not _directory_nonsymlink(paths.pi.repo_dir)
        or not _directory_nonsymlink(paths.pi.package_dir)
        or not _regular_nonsymlink(paths.pi.package_dir / "package.json")
        or not _regular_nonsymlink(paths.pi.package_dir / "dist" / "cli.js")
        or not _directory_nonsymlink(paths.pi.agent_dir)
        or not (
            _regular_nonsymlink(paths.pi.agent_dir / "auth.json")
            or bool(payload.private_environment.get("OPENAI_API_KEY", "").strip())
        )
    ):
        _fail()
    resolve_node_bin(payload.private_environment)


def _bounded_jsonl_count(path: Path, required: int) -> int:
    count = 0
    with path.open("rb") as stream:
        for line in stream:
            if line.strip():
                count += 1
                if count >= required:
                    break
    return count


def _regular_nonsymlink(path: Path) -> bool:
    if _has_symlink_component(path):
        return False
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) and not stat.S_ISLNK(mode)


def _directory_nonsymlink(path: Path) -> bool:
    if _has_symlink_component(path):
        return False
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return False
    return stat.S_ISDIR(mode) and not stat.S_ISLNK(mode)


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if current.is_symlink():
            return True
    return False


def _cancelled(task_id: str) -> BenchmarkTaskResult:
    return BenchmarkTaskResult(
        task_id=task_id,
        status="cancelled",
        case_count=0,
    )


def _fail() -> None:
    raise DciBenchmarkExecutorError("DCI benchmark execution is invalid") from None


__all__ = (
    "DciBenchmarkExecutorError",
    "LocalDciBenchmarkExecutor",
    "RealDciBenchmarkExecutor",
)
