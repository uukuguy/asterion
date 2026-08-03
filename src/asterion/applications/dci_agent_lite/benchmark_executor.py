"""DCI executors implementing Asterion's generic benchmark task protocol."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import stat
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import replace
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, Never

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
from asterion.capabilities.dci.implementation.datasets import (
    load_beir_benchmark_rows_bytes,
    load_benchmark_rows_bytes,
    load_bright_benchmark_rows_bytes,
)
from asterion.capabilities.dci.implementation.evaluation.benchmark import (
    BenchmarkRequest,
    BenchmarkResult,
    run_benchmark_async,
)
from asterion.capabilities.dci.implementation.evaluation.artifacts import (
    DciConversationFeatures,
)
from asterion.capabilities.dci.implementation.evaluation.judge import JudgeConfig
from asterion.capabilities.dci.implementation.pathlight.coverage import (
    validate_coverage_registry_root,
)
from asterion.capabilities.dci.implementation.reproduction.paper_benchmarks import (
    canonical_sha256,
    read_paper_benchmark_dataset,
    resolve_paper_benchmark,
    resolve_paper_experiment_scope,
)
from asterion.capabilities.dci.implementation.research.experiment_profiles import (
    authorize_full_execution,
    authorized_scope_output_root,
    cancel_full_execution_authorization_snapshot,
    cancel_full_execution_authorization,
    consumed_full_execution_authorization_snapshot,
    resolve_experiment_profile,
)
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
    "qa.musique": ("qa.musique", "main", 2417),
    "qa.nq": ("qa.nq", "main", 3610),
    "qa.triviaqa": ("qa.triviaqa", "main", 11313),
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
_COVERAGE_TASK_ORDER = (
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
    "beir.scifact",
)
_COVERAGE_TASK_IDS = frozenset(_COVERAGE_TASK_ORDER)
_COVERAGE_EFFECTIVE_TOOLS = "read,grep"
_DEFAULT_EXPERIMENT_PROFILE = "asterion-safe/pi"
_FULL_SCOPE_BY_TASK = {
    "beir.scifact": "beir.scifact.main.full",
    "bright.biology": "bright.biology.main.full",
    "bright.earth-science": "bright.earth-science.main.full",
    "bright.economics": "bright.economics.main.full",
    "bright.robotics": "bright.robotics.main.full",
    "qa.bamboogle.paper-full125": "qa.bamboogle.main.full",
}
_UPSTREAM_EXPERIMENT_PROFILE = (
    "upstream-github/271f37e71f053bf0c99c05ce6d2fb53b841d922e/pi"
)
_EXPERIMENT_PROFILES = {
    _DEFAULT_EXPERIMENT_PROFILE,
    _UPSTREAM_EXPERIMENT_PROFILE,
}


def _coverage_execution_config_sha256(
    runtime_options: DciRuntimeOptions,
    *,
    executor_profile: str,
    experiment_profile: str,
) -> str:
    """Digest exact effective settings for the fixed coverage experiment."""

    if (
        type(runtime_options) is not DciRuntimeOptions
        or type(executor_profile) is not str
        or not executor_profile
        or experiment_profile not in _EXPERIMENT_PROFILES
    ):
        _fail()
    value = {
        "schema": "asterion.dci.coverage-execution-config/v1",
        "executor_profile": executor_profile,
        "experiment_profile": experiment_profile,
        "runtime": runtime_options.runtime,
        "provider": runtime_options.provider,
        "model": runtime_options.model,
        "tools": _COVERAGE_EFFECTIVE_TOOLS,
        "timeout_seconds": runtime_options.timeout_seconds,
        "runtime_context_level": runtime_options.runtime_context_level,
        "thinking_level": runtime_options.thinking_level,
        "node_max_old_space_size_mb": runtime_options.node_max_old_space_size_mb,
        "keep_session": runtime_options.keep_session,
        "extra_args": list(runtime_options.extra_args),
        "authentication_mode": runtime_options.authentication_mode,
        "tasks": [
            {
                "task_id": task_id,
                "mode": _REAL_TASK_MODES[task_id],
                "max_turns": _REAL_TASK_EXECUTION[task_id][0],
                "max_concurrency": _REAL_TASK_EXECUTION[task_id][1],
                "max_native_attempts": _REAL_TASK_NATIVE_ATTEMPTS[task_id],
                "case_limit": 10,
                "externalize_tool_results": True,
                "judge_operations": 0,
            }
            for task_id in _COVERAGE_TASK_ORDER
        ],
    }
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
        judge_connectivity_probe: Callable[[JudgeConfig], None] | None = None,
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
            or judge_connectivity_probe is not None
            and not callable(judge_connectivity_probe)
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
        self._judge_connectivity_probe = judge_connectivity_probe

    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult:
        payload: DciBenchmarkInvocationPayload | None = None
        request: BenchmarkRequest | None = None
        try:
            payload = _real_payload(invocation, cancellation, on_progress)
            mode = _REAL_TASK_MODES.get(invocation.task_id, "qa")
            coverage_registry = payload.coverage_registry
            if coverage_registry is not None and (
                mode != "ir" or invocation.task_id not in _COVERAGE_TASK_IDS
            ):
                _fail()
            judge_config = (
                JudgeConfig(api_key=None)
                if coverage_registry is not None
                else self._judge_config
            )
            self._readiness_probe(
                payload,
                self._paths,
                self._runtime_options,
                judge_config,
            )
            on_progress(
                BenchmarkProgressEvent(
                    sequence=1,
                    status="task.real.readiness.completed",
                    task_id=invocation.task_id,
                )
            )
            if mode == "qa" and self._judge_connectivity_probe is not None:
                self._judge_connectivity_probe(judge_config)
            if cancellation.cancelled:
                return _cancelled(invocation.task_id)
            max_turns, max_concurrency = _REAL_TASK_EXECUTION.get(
                invocation.task_id,
                (self._max_turns, 1),
            )
            if payload.case_limit > 50:
                max_concurrency = 2
            request = BenchmarkRequest(
                dataset=payload.dataset,
                output_root=payload.output_directory,
                cwd=self._paths.repo_root,
                judge_config=judge_config,
                runtime_options=replace(
                    self._runtime_options,
                    tools=_COVERAGE_EFFECTIVE_TOOLS,
                ),
                limit=payload.case_limit,
                mode=mode,
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
                conversation_features=(
                    DciConversationFeatures(externalize_tool_results=True)
                    if coverage_registry is not None
                    else None
                ),
                resume_policy="compatible",
                coverage_registry=coverage_registry,
            )
            on_progress(
                BenchmarkProgressEvent(
                    sequence=2,
                    status="task.real.authorization.started",
                    task_id=invocation.task_id,
                )
            )
            request = _authorize_full_request(request, payload, invocation.task_id)
            on_progress(
                BenchmarkProgressEvent(
                    sequence=3,
                    status="task.real.authorization.completed",
                    task_id=invocation.task_id,
                )
            )
            on_progress(
                BenchmarkProgressEvent(
                    sequence=4,
                    status="task.real.started",
                    task_id=invocation.task_id,
                )
            )
            if cancellation.cancelled:
                return _cancelled(
                    invocation.task_id,
                    artifact_ids=_unused_coverage_budget_artifacts(request, payload),
                )
            native = asyncio.run(
                _run_cancellable(
                    self._benchmark_runner,
                    request,
                    paths=self._paths,
                    cancellation=cancellation,
                )
            )
            if native is None:
                return _cancelled(
                    invocation.task_id,
                    artifact_ids=_coverage_budget_artifacts(request, payload),
                )
            if not isinstance(native, BenchmarkResult):
                _fail()
            budget_artifacts = _coverage_budget_artifacts(request, payload)
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
                    artifact_ids=budget_artifacts,
                )
            on_progress(
                BenchmarkProgressEvent(
                    sequence=5,
                    status="task.real.completed",
                    task_id=invocation.task_id,
                )
            )
            return BenchmarkTaskResult(
                task_id=invocation.task_id,
                status="completed",
                case_count=total,
                artifact_ids=tuple(
                    sorted((f"{invocation.task_id}.native-result", *budget_artifacts))
                ),
            )
        except DciBenchmarkExecutorError:
            failed_result = _failed_coverage_execution(invocation, payload, request)
            if failed_result is not None:
                return failed_result
            raise
        except asyncio.CancelledError:
            return _cancelled(
                invocation.task_id
                if isinstance(invocation, BenchmarkTaskInvocation)
                else "qa.bamboogle.github-sample50"
            )
        except Exception:
            failed_result = _failed_coverage_execution(invocation, payload, request)
            if failed_result is not None:
                return failed_result
            _fail()


def _failed_coverage_execution(
    invocation: object,
    payload: DciBenchmarkInvocationPayload | None,
    request: BenchmarkRequest | None,
) -> BenchmarkTaskResult | None:
    if (
        not isinstance(invocation, BenchmarkTaskInvocation)
        or payload is None
        or payload.coverage_registry is None
        or request is None
        or request.full_execution_authorization is None
        or payload.amount is None
    ):
        return None
    authorized = _cost_microusd(payload.amount)
    try:
        receipt = cancel_full_execution_authorization_snapshot(
            request.full_execution_authorization
        )
        ledger = receipt.get("ledger")
        if type(ledger) is not dict:
            raise ValueError
        actual = ledger.get("actual_cost_usd")
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            raise ValueError
        consumed = _cost_microusd(Decimal(str(actual)))
        if consumed > authorized:
            raise ValueError
        artifacts = tuple(
            sorted(
                (
                    f"coverage-actual-microusd.{consumed}",
                    f"coverage-authorized-microusd.{authorized}",
                )
            )
        )
    except Exception:
        artifacts = (
            f"coverage-authorized-microusd.{authorized}",
            f"coverage-upper-microusd.{authorized}",
        )
    return BenchmarkTaskResult(
        task_id=invocation.task_id,
        status="failed",
        case_count=0,
        artifact_ids=artifacts,
    )


def _authorize_full_request(
    request: BenchmarkRequest,
    payload: DciBenchmarkInvocationPayload,
    task_id: str,
) -> BenchmarkRequest:
    """Issue one in-process, budget-bound capability for supported full scopes."""

    scope_id = _FULL_SCOPE_BY_TASK.get(task_id)
    coverage_case10 = (
        payload.coverage_registry is not None
        and task_id in _COVERAGE_TASK_IDS
        and payload.case_limit == 10
    )
    if scope_id is None or payload.case_limit <= 50 and not coverage_case10:
        return request
    if (
        payload.amount is None
        or payload.amount <= 0
        or coverage_case10
        and payload.amount > Decimal("1")
    ):
        _fail()
    scope = resolve_paper_experiment_scope(scope_id)
    if not coverage_case10 and payload.case_limit != scope.selection_count:
        _fail()
    benchmark = resolve_paper_benchmark(scope.dataset_id)
    raw, binding = read_paper_benchmark_dataset(payload.dataset, benchmark)
    selected_ids_sha256 = scope.selected_ids_sha256
    if coverage_case10:
        if benchmark.dataset_id.startswith("bright."):
            rows = load_bright_benchmark_rows_bytes(
                raw, expected_count=benchmark.source_count
            )
        elif benchmark.dataset_id.startswith("beir."):
            rows = load_beir_benchmark_rows_bytes(
                raw, expected_count=benchmark.source_count
            )
        else:
            rows = load_benchmark_rows_bytes(raw)
        if len(rows) < payload.case_limit:
            _fail()
        selected_rows = rows[: payload.case_limit]
        registry_path = payload.coverage_registry
        if not isinstance(registry_path, Path):
            _fail()
        registry = validate_coverage_registry_root(
            registry_path,
            corpus_dir=payload.corpus,
            expected_dataset_id=task_id,
            expected_count=payload.case_limit,
        )
        if registry.selected_ids_sha256 != canonical_sha256(
            tuple(row.query_id for row in selected_rows)
        ):
            _fail()
        selected_ids_sha256 = canonical_sha256(
            tuple(sorted(row.query_id for row in selected_rows))
        )
    profile = resolve_experiment_profile(_DEFAULT_EXPERIMENT_PROFILE)
    judge_operations = (
        payload.case_limit if request.mode == "qa" else int(not coverage_case10)
    )
    # The authorization ledger reserves an operation's full upper bound before
    # it starts, then replaces that reservation with its actual spend.  A
    # per-operation bound equal to the total envelope therefore makes a
    # sequential batch fail after its first case, even when that case was
    # inexpensive.  Ten reservation slots preserve the finite total budget
    # while leaving normal DeepSeek/Pi operations ample headroom.
    operation_limit = float(payload.amount) / 10
    authority = authorize_full_execution(
        profile=profile,
        scope_ids=(scope_id,),
        dataset_input_bindings=(binding,),
        bounded_selected_ids_sha256=(selected_ids_sha256,),
        selected_query_counts=(payload.case_limit,),
        planned_agent_operations=payload.case_limit,
        planned_judge_operations=(payload.case_limit if request.mode == "qa" else 0),
        output_root=payload.output_directory.parent / "authorized-full",
        max_agent_operations=payload.case_limit,
        max_judge_operations=judge_operations,
        max_cost_usd=float(payload.amount),
        max_agent_cost_per_operation_usd=operation_limit,
        max_judge_cost_per_operation_usd=operation_limit,
        invocation_authorized=True,
    )
    return replace(
        request,
        output_root=authorized_scope_output_root(authority, scope_id),
        full_execution_authorization=authority,
        experiment_scope_id=scope_id,
        dataset_input_binding=binding,
    )


def _coverage_budget_artifacts(
    request: BenchmarkRequest,
    payload: DciBenchmarkInvocationPayload,
) -> tuple[str, ...]:
    """Return body-free bounded cost evidence for one coverage task."""

    authority = request.full_execution_authorization
    if payload.coverage_registry is None or authority is None or payload.amount is None:
        return ()
    authorized = _cost_microusd(payload.amount)
    try:
        receipt = consumed_full_execution_authorization_snapshot(authority)
        ledger = receipt.get("ledger")
        if type(ledger) is not dict:
            raise ValueError
        actual = ledger.get("actual_cost_usd")
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            raise ValueError
        consumed = _cost_microusd(Decimal(str(actual)))
        if consumed > authorized:
            raise ValueError
        return tuple(
            sorted(
                (
                    f"coverage-actual-microusd.{consumed}",
                    f"coverage-authorized-microusd.{authorized}",
                )
            )
        )
    except Exception:
        try:
            cancel_full_execution_authorization(authority)
        except Exception:
            pass
        return (
            f"coverage-authorized-microusd.{authorized}",
            f"coverage-upper-microusd.{authorized}",
        )


def _unused_coverage_budget_artifacts(
    request: BenchmarkRequest,
    payload: DciBenchmarkInvocationPayload,
) -> tuple[str, ...]:
    authority = request.full_execution_authorization
    if payload.coverage_registry is None or authority is None or payload.amount is None:
        return ()
    try:
        cancel_full_execution_authorization(authority)
    except Exception:
        pass
    authorized = _cost_microusd(payload.amount)
    return tuple(
        sorted(
            (
                "coverage-actual-microusd.0",
                f"coverage-authorized-microusd.{authorized}",
            )
        )
    )


def _cost_microusd(amount: Decimal) -> int:
    value = (amount * Decimal(1_000_000)).to_integral_value(rounding=ROUND_CEILING)
    if value < 0 or value > 1_000_000:
        raise ValueError
    return int(value)


def _real_payload(
    invocation: object,
    cancellation: object,
    on_progress: object,
) -> DciBenchmarkInvocationPayload:
    if not isinstance(invocation, BenchmarkTaskInvocation):
        _fail()
    task_id = invocation.task_id
    contract = _REAL_TASK_CONTRACTS.get(task_id)
    if (
        contract is None
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
        or payload.coverage_registry is not None
        and (
            not isinstance(payload.coverage_registry, Path)
            or not payload.coverage_registry.is_absolute()
        )
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
        or payload.coverage_registry is None
        and not judge_config.api_key
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


def verify_judge_connectivity(config: JudgeConfig) -> None:
    """Verify configured Judge credentials without sending benchmark content."""

    if not isinstance(config, JudgeConfig) or not config.api_key:
        _fail()
    request = urllib.request.Request(
        config.base_url.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {config.api_key}"},
    )
    try:
        with urllib.request.urlopen(
            request, timeout=min(config.timeout_seconds, 15)
        ) as response:
            if response.status < 200 or response.status >= 300:
                _fail()
    except (OSError, ValueError, urllib.error.HTTPError):
        _fail()


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


def _cancelled(
    task_id: str, *, artifact_ids: tuple[str, ...] = ()
) -> BenchmarkTaskResult:
    return BenchmarkTaskResult(
        task_id=task_id,
        status="cancelled",
        case_count=0,
        artifact_ids=artifact_ids,
    )


def _fail() -> Never:
    raise DciBenchmarkExecutorError("DCI benchmark execution is invalid") from None


__all__ = (
    "DciBenchmarkExecutorError",
    "LocalDciBenchmarkExecutor",
    "RealDciBenchmarkExecutor",
)
