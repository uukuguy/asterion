"""Bounded, digest-closed coordination for the DCI coverage experiment."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TextIO

from asterion.applications.dci_agent_lite.benchmark_instances import (
    DciBenchmarkInstance,
    select_benchmark_instance,
)
from asterion.applications.dci_agent_lite.benchmark_host import (
    coverage_execution_config_sha256,
)
from asterion.applications.dci_agent_lite.benchmark_source_lock import (
    resolve_benchmark_source_lock,
    write_benchmark_source_lock,
)
from asterion.applications.dci_agent_lite.operator_config import (
    DciOperatorConfig,
    load_operator_config,
)
from asterion.benchmarks.cli import BenchmarkCommandHost
from asterion.benchmarks.evidence import BenchmarkRunResult
from asterion.capability_packages.sources.base import CapabilityPackageSource
from asterion.capabilities.dci.implementation.operator_inputs import (
    DciBenchmarkOperatorInputs,
)
from asterion.capabilities.dci.implementation.evaluation.artifacts import (
    pathlight_trace_id,
)
from asterion.capabilities.dci.implementation.pathlight.coverage import (
    coverage_query_sha256,
    prepare_coverage_registry,
    validate_coverage_registry_bytes,
    validate_coverage_registry_root,
)
from asterion.capabilities.dci.implementation.pathlight.diagnosis import (
    DciCoverageDatasetObservation,
    DciCoverageExperimentObservation,
)
from asterion.capabilities.dci.implementation.pathlight.recovery import (
    read_completed_dci_run,
)
from asterion.capabilities.dci.implementation.research.trajectory_resolution import (
    public_resolution_projection,
)
from asterion.pathlight.flow import project_trace_flow
from asterion.pathlight._private_file import read_private_file, write_private_file
from asterion.pathlight.diagnosis import Proposal, read_diagnosis_bundle
from asterion.runtime.protocol import validate_run_request
from asterion.workflow_evidence.storage import read_workflow_observation_bundle


PLAN_FILENAME = "pathlight-coverage-experiment.json"
_PLAN_SCHEMA = "asterion.dci.pathlight.coverage-experiment/v1"
_AUTHORIZATION_SCHEMA = "asterion.dci.pathlight.coverage-experiment-authorization/v1"
_ERROR = "asterion-dci: command failed\n"
_MAX_DOCUMENT_BYTES = 1 << 20
_MAX_NATIVE_STATE_BYTES = 8 << 20
_MAX_AGENT_OPERATIONS = 50
_MAX_COST_MICROUSD = 5_000_000
_MAX_INFRASTRUCTURE_FAILURES = 2
_SOURCE_LOCK_FILENAME = "pathlight-coverage-source-lock.json"
_RECEIPT_SCHEMA = "asterion.dci.pathlight.coverage-experiment-receipt/v2"
_RUN_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_TASK_IDS = (
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
    "beir.scifact",
)


@dataclass(frozen=True, slots=True)
class _CommandResult:
    code: int
    output: dict[str, object]


@dataclass(frozen=True, slots=True)
class _Preflight:
    task: Mapping[str, object]
    host: BenchmarkCommandHost
    payloads: object
    resolved: object
    draft: object
    receipt_chain: tuple[dict[str, object], ...]
    authorized_cost_microusd: int


def main(
    arguments: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
    repo_root: Path,
    env_file: Path | None,
    environment: Mapping[str, str] | None,
    package_sources: Sequence[CapabilityPackageSource] | None = None,
    host_factory: Callable[..., BenchmarkCommandHost] | None = None,
) -> int:
    """Run one experiment command behind the existing provider-free route."""

    try:
        values = tuple(arguments)
        if not values:
            raise ValueError
        if values[0] == "prepare":
            output = _prepare(
                values[1:],
                repo_root=repo_root,
                env_file=env_file,
                environment=environment,
                package_sources=package_sources,
            )
        elif values[0] == "execute":
            result = _execute(
                values[1:],
                repo_root=repo_root,
                env_file=env_file,
                environment=environment,
                package_sources=package_sources,
                host_factory=host_factory,
            )
            stdout.write(
                json.dumps(result.output, sort_keys=True, separators=(",", ":")) + "\n"
            )
            return result.code
        elif values[0] == "status":
            output = _status(values[1:])
        else:
            raise ValueError
        stdout.write(json.dumps(output, sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    except BaseException:
        stderr.write(_ERROR)
        return 2


def _prepare(
    arguments: tuple[str, ...],
    *,
    repo_root: Path,
    env_file: Path | None,
    environment: Mapping[str, str] | None,
    package_sources: Sequence[CapabilityPackageSource] | None,
) -> dict[str, object]:
    options = _exact_options(
        arguments, {"--diagnosis-file", "--proposal-sha256", "--output-root"}
    )
    output_root = _operator_root(options["--output-root"])
    if any(output_root.iterdir()):
        raise ValueError
    diagnosis = read_diagnosis_bundle(_absolute_path(options["--diagnosis-file"]))
    proposal = _coverage_proposal(diagnosis.proposals, options["--proposal-sha256"])
    config = load_operator_config(
        repo_root,
        env_file=env_file,
        environment=environment,
    )
    staging_root = _create_staging_root(output_root)
    failed = False
    body: dict[str, object] | None = None
    try:
        (staging_root / "coverage").mkdir(mode=0o700)
        (staging_root / "receipts").mkdir(mode=0o700)
        (staging_root / "evidence").mkdir(mode=0o700)
        tasks: list[dict[str, object]] = []
        for task_id in _TASK_IDS:
            registry_root = staging_root / "coverage" / task_id
            registry = prepare_coverage_registry(
                dataset_id=task_id,
                dataset_path=config.benchmark_inputs.dataset_roots[task_id],
                corpus_dir=config.benchmark_inputs.corpus_roots[task_id],
                selected_count=10,
                output_root=registry_root,
            )
            tasks.append(
                {
                    "task_id": task_id,
                    "instance_selector": f"dci.{task_id}@1.0.0",
                    "case_limit": 10,
                    "max_cost_microusd": 1_000_000,
                    "registry_path": f"coverage/{task_id}/registry.json",
                    "registry_sha256": registry.sha256,
                    "selected_ids_sha256": registry.selected_ids_sha256,
                }
            )
        source_lock = resolve_benchmark_source_lock(
            select_benchmark_instance("dci.beir.scifact@1.0.0"),
            package_sources=package_sources,
        )
        source_lock_path = staging_root / _SOURCE_LOCK_FILENAME
        write_benchmark_source_lock(source_lock, source_lock_path)
        registry_set_sha256 = _digest(
            [
                {
                    "task_id": task["task_id"],
                    "registry_sha256": task["registry_sha256"],
                    "selected_ids_sha256": task["selected_ids_sha256"],
                }
                for task in tasks
            ]
        )
        body = {
            "schema": _PLAN_SCHEMA,
            "diagnosis_bundle_sha256": diagnosis.bundle_sha256,
            "proposal_sha256": proposal.proposal_sha256,
            "scope_sha256": proposal.scope_sha256,
            "variant_sha256": _domain_digest(
                "proposal-sole-variable",
                "trajectory-coverage-instrumentation-only",
            ),
            "registry_set_sha256": registry_set_sha256,
            "source_lock_path": _SOURCE_LOCK_FILENAME,
            "source_lock_sha256": _file_sha256(source_lock_path),
            "execution_config_sha256": coverage_execution_config_sha256(
                config.benchmark_inputs.private_environment
            ),
            "max_agent_operations": _MAX_AGENT_OPERATIONS,
            "max_cost_microusd": _MAX_COST_MICROUSD,
            "max_infrastructure_failures": _MAX_INFRASTRUCTURE_FAILURES,
            "execution_authorized": False,
            "tasks": tasks,
        }
        body["plan_sha256"] = _digest(body)
        write_private_file(staging_root / PLAN_FILENAME, _canonical_bytes(body))
        _read_plan(staging_root / PLAN_FILENAME)
        for task in tasks:
            task_id = str(task["task_id"])
            registry = validate_coverage_registry_root(
                staging_root / str(task["registry_path"]),
                corpus_dir=config.benchmark_inputs.corpus_roots[task_id],
                expected_dataset_id=task_id,
                expected_count=10,
            )
            if registry.sha256 != task["registry_sha256"]:
                raise ValueError
        _publish_staged_tree(output_root, staging_root)
    except BaseException:
        failed = True
    try:
        _cleanup_staging_tree(output_root, staging_root)
    except BaseException:
        failed = True
    if failed or body is None:
        raise ValueError
    return {
        "case_count": _MAX_AGENT_OPERATIONS,
        "max_cost_microusd": _MAX_COST_MICROUSD,
        "output_bundle_digest": body["plan_sha256"],
    }


def _execute(
    arguments: tuple[str, ...],
    *,
    repo_root: Path,
    env_file: Path | None,
    environment: Mapping[str, str] | None,
    package_sources: Sequence[CapabilityPackageSource] | None,
    host_factory: Callable[..., BenchmarkCommandHost] | None,
) -> _CommandResult:
    options = _exact_options(
        arguments, {"--plan-file", "--authorization-file", "--output-root"}
    )
    plan = _read_plan(_absolute_path(options["--plan-file"]))
    output_root = _operator_root(options["--output-root"])
    if _absolute_path(options["--plan-file"]).parent != output_root:
        raise ValueError
    authorization = _read_authorization(
        _absolute_path(options["--authorization-file"]), plan=plan, output_root=output_root
    )
    source_lock_path = output_root / str(plan["source_lock_path"])
    if _file_sha256(source_lock_path) != plan["source_lock_sha256"]:
        raise ValueError
    base_config = _execution_config(
        plan,
        output_root=output_root,
        repo_root=repo_root,
        env_file=env_file,
        environment=environment,
    )
    expected_execution_config = plan.get("execution_config_sha256")
    if (
        type(expected_execution_config) is not str
        or not hmac.compare_digest(
            coverage_execution_config_sha256(
                base_config.benchmark_inputs.private_environment
            ),
            expected_execution_config,
        )
    ):
        raise ValueError
    tasks = plan["tasks"]
    if type(tasks) is not list:
        raise ValueError
    preflights: list[_Preflight] = []
    infrastructure_failures = 0
    completed_before = 0
    for raw_task in tasks:
        if type(raw_task) is not dict:
            raise ValueError
        task_id = str(raw_task["task_id"])
        registry = validate_coverage_registry_root(
            output_root / str(raw_task["registry_path"]),
            corpus_dir=base_config.benchmark_inputs.corpus_roots[task_id],
            expected_dataset_id=task_id,
            expected_count=10,
        )
        if (
            registry.sha256 != raw_task["registry_sha256"]
            or registry.selected_ids_sha256 != raw_task["selected_ids_sha256"]
        ):
            raise ValueError
        receipt_chain = _read_receipt_chain(
            output_root / "receipts",
            plan=plan,
            task=raw_task,
            expected_authorization_sha256=str(authorization["authorization_sha256"]),
        )
        terminal = bool(
            receipt_chain and receipt_chain[-1]["benchmark_status"] == "completed"
        )
        if terminal and _revalidate_terminal_receipt(
            output_root=output_root,
            plan=plan,
            task=raw_task,
            receipt=receipt_chain[-1],
        ):
            completed_before += 1
        infrastructure_failures += sum(
            receipt["benchmark_status"] == "failed" for receipt in receipt_chain
        )
        remaining_cost_microusd = _remaining_task_budget(raw_task, receipt_chain)
        if remaining_cost_microusd == 0 and not terminal:
            raise ValueError
        authorized_cost_microusd = (
            int(raw_task["max_cost_microusd"])
            if terminal and remaining_cost_microusd == 0
            else remaining_cost_microusd
        )
        config = _config_with_amount(base_config, authorized_cost_microusd)
        instance = select_benchmark_instance(str(raw_task["instance_selector"]))
        host = _create_host(
            host_factory,
            instance=instance,
            config=config,
            package_sources=package_sources,
        )
        metadata = host.discover_metadata(
            application_ref=instance.application_ref,
            suite_ref=instance.suite_ref,
        )
        source_lock = host.resolve_source_lock(source_lock_path)
        payloads = host.open_selected_payloads(metadata, source_lock)
        resolved = host.resolve_application(
            payloads,
            application_ref=instance.application_ref,
            suite_ref=instance.suite_ref,
        )
        draft = host.create_plan(
            resolved,
            application_ref=instance.application_ref,
            suite_ref=instance.suite_ref,
            case_limit=10,
            execute=False,
            authorization=None,
            resume_run_id=None,
        )
        if getattr(draft, "case_limit", None) != 10:
            raise ValueError
        preflights.append(
            _Preflight(
                raw_task,
                host,
                payloads,
                resolved,
                draft,
                receipt_chain,
                authorized_cost_microusd,
            )
        )
    executed_cases = sum(
        _receipt_case_count(receipt)
        for preflight in preflights
        for receipt in preflight.receipt_chain
    )
    terminal_count = sum(
        bool(item.receipt_chain and item.receipt_chain[-1]["benchmark_status"] == "completed")
        for item in preflights
    )
    if completed_before == len(_TASK_IDS) or infrastructure_failures >= 2:
        raise ValueError
    if terminal_count == len(_TASK_IDS):
        return _CommandResult(
            1,
            _status_summary(
                plan, completed=completed_before, status="observation-invalid"
            ),
        )

    completed = completed_before
    for preflight in preflights:
        chain = preflight.receipt_chain
        if chain and chain[-1]["benchmark_status"] == "completed":
            continue
        if executed_cases + 10 > _MAX_AGENT_OPERATIONS:
            raise ValueError
        task = preflight.task
        instance = select_benchmark_instance(str(task["instance_selector"]))
        # Failed and cancelled benchmark run IDs are terminal in the evidence
        # store. Coordinator resume therefore skips completed task receipts and
        # starts a fresh immutable generation for the interrupted task.
        resume_run_id = None
        inner_authorization = preflight.host.authorize_execution(
            application_ref=instance.application_ref,
            suite_ref=instance.suite_ref,
            case_limit=10,
            evidence_root=output_root / "evidence" / str(task["task_id"]),
            resume_run_id=resume_run_id,
        )
        execution_plan = preflight.host.create_plan(
            preflight.resolved,
            application_ref=instance.application_ref,
            suite_ref=instance.suite_ref,
            case_limit=10,
            execute=True,
            authorization=inner_authorization,
            resume_run_id=resume_run_id,
        )
        run_id = getattr(execution_plan, "run_id", None)
        if type(run_id) is not str or not run_id:
            raise ValueError
        try:
            providers = preflight.host.load_selected_providers(
                preflight.payloads, inner_authorization
            )
            result = preflight.host.run(
                execution_plan,
                providers,
                evidence_root=output_root / "evidence" / str(task["task_id"]),
            )
            if not isinstance(result, BenchmarkRunResult):
                raise ValueError
            status = result.status
            case_count = sum(item.case_count for item in result.tasks)
            consumed_cost_microusd, cost_evidence = _result_cost_evidence(
                result,
                task_id=str(task["task_id"]),
                authorized_cost_microusd=preflight.authorized_cost_microusd,
            )
            if status == "completed" and case_count != 10:
                status = "failed"
            observation: DciCoverageDatasetObservation | None = None
            observation_status = "unavailable"
            if status == "completed":
                try:
                    observation = _seal_completed_native_task(
                        output_root=output_root,
                        plan=plan,
                        task=task,
                        run_id=run_id,
                    )
                    observation_status = "complete"
                except Exception:
                    observation_status = "invalid"
        except BaseException:
            status = "failed"
            # The provider boundary failed before returning trustworthy progress.
            # Charge the full ten-case scope so a retry can never exceed the
            # plan's fifty Agent-operation ceiling.
            case_count = 10
            consumed_cost_microusd = preflight.authorized_cost_microusd
            cost_evidence = "upper-bound"
            observation = None
            observation_status = "unavailable"
        _publish_receipt(
            output_root / "receipts",
            plan=plan,
            task=task,
            authorization=authorization,
            generation=len(chain),
            run_id=run_id,
            status=status,
            case_count=case_count,
            authorized_cost_microusd=preflight.authorized_cost_microusd,
            consumed_cost_microusd=consumed_cost_microusd,
            cost_evidence=cost_evidence,
            observation_status=observation_status,
            observation_evidence_sha256=(
                None if observation is None else observation.evidence_sha256
            ),
        )
        executed_cases += case_count
        if status == "completed" and observation_status == "complete":
            completed += 1
            continue
        if status == "completed":
            continue
        if status == "cancelled":
            return _CommandResult(
                130, _status_summary(plan, completed=completed, status="cancelled")
            )
        infrastructure_failures += 1
        if infrastructure_failures >= _MAX_INFRASTRUCTURE_FAILURES:
            return _CommandResult(
                1, _status_summary(plan, completed=completed, status="failed")
            )
    if completed == len(_TASK_IDS):
        return _CommandResult(
            0, _status_summary(plan, completed=completed, status="completed")
        )
    return _CommandResult(
        1, _status_summary(plan, completed=completed, status="partial")
    )


def _status(arguments: tuple[str, ...]) -> dict[str, object]:
    options = _exact_options(
        arguments, {"--plan-file", "--authorization-file", "--output-root"}
    )
    plan_path = _absolute_path(options["--plan-file"])
    if plan_path.parent != _operator_root(options["--output-root"]):
        raise ValueError
    plan = _read_plan(plan_path)
    authorization = _read_authorization(
        _absolute_path(options["--authorization-file"]), plan=plan, output_root=plan_path.parent
    )
    tasks = plan["tasks"]
    if type(tasks) is not list:
        raise ValueError
    completed = 0
    terminal_statuses: list[str] = []
    infrastructure_failures = 0
    for task in tasks:
        if type(task) is not dict:
            raise ValueError
        chain = _read_receipt_chain(
            plan_path.parent / "receipts",
            plan=plan,
            task=task,
            expected_authorization_sha256=str(authorization["authorization_sha256"]),
        )
        if chain:
            receipt = chain[-1]
            terminal_statuses.append(str(receipt["benchmark_status"]))
            if receipt["benchmark_status"] == "completed":
                completed += _revalidate_terminal_receipt(
                    output_root=plan_path.parent,
                    plan=plan,
                    task=task,
                    receipt=receipt,
                )
            infrastructure_failures += sum(
                item["benchmark_status"] == "failed" for item in chain
            )
    if completed == len(_TASK_IDS):
        status = "completed"
    elif terminal_statuses and terminal_statuses[-1] == "cancelled":
        status = "cancelled"
    elif infrastructure_failures >= 2:
        status = "failed"
    elif len(terminal_statuses) == len(_TASK_IDS) and all(
        terminal == "completed" for terminal in terminal_statuses
    ):
        status = "observation-invalid"
    elif terminal_statuses:
        status = "partial"
    else:
        status = "prepared"
    return _status_summary(plan, completed=completed, status=status)


def read_completed_coverage_experiment(
    *, plan_file: Path, authorization_file: Path, output_root: Path
) -> DciCoverageExperimentObservation:
    """Rebuild one completed coverage observation from its sealed native closure."""

    try:
        if (
            not isinstance(plan_file, Path)
            or not isinstance(authorization_file, Path)
            or not isinstance(output_root, Path)
        ):
            raise ValueError
        root = _operator_root(str(output_root))
        plan_path = _absolute_path(str(plan_file))
        authorization_path = _absolute_path(str(authorization_file))
        if plan_path.parent != root:
            raise ValueError
        plan = _read_plan(plan_path)
        authorization = _read_authorization(
            authorization_path, plan=plan, output_root=root
        )
        tasks = plan.get("tasks")
        if type(tasks) is not list or len(tasks) != len(_TASK_IDS):
            raise ValueError
        datasets: list[DciCoverageDatasetObservation] = []
        receipt_digests: list[str] = []
        consumed_cost = 0
        infrastructure_failures = 0
        agent_operations = 0
        for task in tasks:
            if type(task) is not dict:
                raise ValueError
            chain = _read_receipt_chain(
                root / "receipts",
                plan=plan,
                task=task,
                expected_authorization_sha256=str(
                    authorization["authorization_sha256"]
                ),
            )
            if (
                not chain
                or chain[-1].get("benchmark_status") != "completed"
                or chain[-1].get("observation_status") != "complete"
            ):
                raise ValueError
            receipt_digests.extend(str(receipt["receipt_sha256"]) for receipt in chain)
            consumed_cost += sum(_receipt_consumed_cost(receipt) for receipt in chain)
            infrastructure_failures += sum(
                receipt["benchmark_status"] == "failed" for receipt in chain
            )
            terminal = chain[-1]
            case_count = terminal.get("case_count")
            if type(case_count) is not int:
                raise ValueError
            agent_operations += case_count
            observation = _read_native_dataset_observation(
                output_root=root,
                plan=plan,
                task=task,
                receipt=terminal,
            )
            if observation.evidence_sha256 != terminal["observation_evidence_sha256"]:
                raise ValueError
            datasets.append(observation)
        if agent_operations != _MAX_AGENT_OPERATIONS:
            raise ValueError
        return DciCoverageExperimentObservation(
            plan_sha256=str(plan["plan_sha256"]),
            proposal_sha256=str(plan["proposal_sha256"]),
            scope_sha256=str(plan["scope_sha256"]),
            variant_sha256=str(plan["variant_sha256"]),
            registry_set_sha256=str(plan["registry_set_sha256"]),
            authorization_sha256=str(authorization["authorization_sha256"]),
            receipt_set_sha256=_domain_digest(
                "coverage-receipt-set", receipt_digests
            ),
            datasets=tuple(datasets),
            agent_operation_count=agent_operations,
            judge_operation_count=0,
            consumed_cost_microusd=consumed_cost,
            infrastructure_failure_count=infrastructure_failures,
        )
    except Exception:
        raise ValueError("coverage experiment evidence is invalid") from None


def _seal_completed_native_task(
    *,
    output_root: Path,
    plan: Mapping[str, object],
    task: Mapping[str, object],
    run_id: str,
) -> DciCoverageDatasetObservation:
    """Validate the native closure before a completed receipt can exist."""

    observation = _read_native_dataset_observation(
        output_root=output_root,
        plan=plan,
        task=task,
        receipt={"run_id": run_id, "receipt_sha256": "0" * 64},
    )
    if (
        observation.dataset_id != task.get("task_id")
        or observation.coverage_available_queries != 10
        or observation.coverage_total_queries != 10
        or observation.integrity_failure_count != 0
    ):
        raise ValueError
    return observation


def _revalidate_terminal_receipt(
    *,
    output_root: Path,
    plan: Mapping[str, object],
    task: Mapping[str, object],
    receipt: Mapping[str, object],
) -> bool:
    if receipt.get("benchmark_status") != "completed":
        return False
    try:
        observation = _seal_completed_native_task(
            output_root=output_root,
            plan=plan,
            task=task,
            run_id=str(receipt["run_id"]),
        )
    except Exception:
        return False
    return (
        receipt.get("observation_status") == "complete"
        and observation.evidence_sha256
        == receipt.get("observation_evidence_sha256")
    )


def _read_native_dataset_observation(
    *,
    output_root: Path,
    plan: Mapping[str, object],
    task: Mapping[str, object],
    receipt: Mapping[str, object],
) -> DciCoverageDatasetObservation:
    task_id = str(task["task_id"])
    evidence_root = _operator_root(str(output_root / "evidence" / task_id))
    outputs = _owned_evidence_directory(evidence_root / "outputs")
    run_id = receipt.get("run_id")
    if type(run_id) is not str:
        raise ValueError
    run_root = _owned_evidence_directory(outputs / run_id)
    if tuple(path.name for path in outputs.iterdir()) != (run_id,):
        raise ValueError
    authorities = tuple(run_root.iterdir())
    if len(authorities) != 1 or authorities[0].name != "authorized-full":
        raise ValueError
    authority_root = _owned_evidence_directory(authorities[0])
    native_roots = tuple(authority_root.iterdir())
    if (
        len(native_roots) != 2
        or any(not _is_sha256(path.name) for path in native_roots)
    ):
        raise ValueError
    candidates = tuple(
        path for path in native_roots if (path / "config.json").is_file()
    )
    if len(candidates) != 1:
        raise ValueError
    native_root = _owned_evidence_directory(candidates[0])
    _owned_evidence_directory(next(path for path in native_roots if path != native_root))
    recovered = read_completed_dci_run(native_root, task_id)
    if recovered.selected_count != 10 or recovered.total_count != 10:
        raise ValueError

    registry_path = output_root / str(task["registry_path"])
    registry_bytes = read_private_file(registry_path, _MAX_DOCUMENT_BYTES)
    registry = validate_coverage_registry_bytes(registry_bytes)
    if (
        registry.dataset_id != task_id
        or registry.selected_count != 10
        or registry.sha256 != task["registry_sha256"]
        or registry.selected_ids_sha256 != task["selected_ids_sha256"]
    ):
        raise ValueError
    expected_queries = {item.query_sha256 for item in registry.manifests}
    rows = _jsonl_private(native_root / "results.jsonl")
    if len(rows) != 10:
        raise ValueError

    coverage_any: list[int] = []
    coverage_mean: list[int] = []
    coverage_all: list[int] = []
    retained: list[int] = []
    tool_observations = 0
    surfaced_gold = 0
    model_calls = 0
    context_frames = 0
    missing_boundaries = 0
    evidence_parts: list[dict[str, object]] = []
    observed_queries: set[str] = set()
    for row in rows:
        query_id = row.get("query_id")
        generation = row.get("native_generation")
        if (
            type(query_id) is not str
            or not query_id
            or "/" in query_id
            or row.get("status") != "completed"
            or type(generation) is not str
            or not generation.startswith("native-generation-")
            or "/" in generation
        ):
            raise ValueError
        query_sha256 = coverage_query_sha256(query_id)
        if query_sha256 not in expected_queries or query_sha256 in observed_queries:
            raise ValueError
        observed_queries.add(query_sha256)
        query_root = _owned_evidence_directory(native_root / query_id)
        generation_root = _query_generation_root(query_root, generation)
        evidence = _json_native(generation_root / "trajectory-resolution.json")
        if type(evidence) is not dict:
            raise ValueError
        projection = public_resolution_projection(evidence)
        if (
            projection.get("schema")
            != "dci.trajectory-resolution-coverage-summary/v1"
            or projection.get("dataset_id") != task_id
            or projection.get("query_sha256") != query_sha256
        ):
            raise ValueError
        metrics = projection.get("metrics")
        counts = projection.get("counts")
        if type(metrics) is not dict or type(counts) is not dict:
            raise ValueError
        coverage = metrics.get("coverage")
        retained_metric = metrics.get("retained_coverage")
        if type(coverage) is not dict or type(retained_metric) is not dict:
            raise ValueError
        coverage_any.append(_microunits(coverage.get("any")))
        coverage_mean.append(_microunits(coverage.get("mean")))
        coverage_all.append(_microunits(coverage.get("all")))
        retained_value = retained_metric.get("value")
        if retained_value is not None:
            retained.append(_microunits(retained_value))
        tool_observations += _natural(counts.get("tool_observations"))
        surfaced_gold += _natural(counts.get("surfaced_gold_documents"))

        workflow = read_workflow_observation_bundle(
            generation_root / "workflow-evidence.json"
        )
        if len(workflow.records) != 1 or len(workflow.pathlight_traces) != 1:
            raise ValueError
        generation_state = _json_native(
            generation_root / "state.json", max_bytes=_MAX_NATIVE_STATE_BYTES
        )
        if type(generation_state) is not dict:
            raise ValueError
        attempts = generation_state.get("attempts")
        if type(attempts) is not list:
            raise ValueError
        _validate_workflow_case_binding(
            record=workflow.records[0],
            trace=workflow.pathlight_traces[0],
            trajectory=evidence,
            expected_dataset_id=task_id,
            expected_query_id=query_id,
            expected_generation=generation,
            generation_state=generation_state,
            workflow_run_id=_workflow_protocol_run_id(
                generation_root, attempt=len(attempts)
            ),
        )
        flow = project_trace_flow(workflow.pathlight_traces[0])
        model_calls += sum(node.get("kind") == "model-call" for node in flow)
        context_frames += sum(node.get("kind") == "context-frame" for node in flow)
        missing_boundaries += sum(bool(node.get("missing_evidence")) for node in flow)
        identity = evidence.get("identity")
        if type(identity) is not dict or not _is_sha256(identity.get("sha256")):
            raise ValueError
        evidence_parts.append(
            {
                "query_sha256": query_sha256,
                "resolution_sha256": identity["sha256"],
                "workflow_bundle_sha256": workflow.bundle_sha256,
            }
        )
    recovered_coverage = tuple(
        case.resolution_coverage_microunits for case in recovered.cases
    )
    if any(value is None for value in recovered_coverage):
        raise ValueError
    exact_recovered_coverage = tuple(
        value for value in recovered_coverage if value is not None
    )
    if (
        observed_queries != expected_queries
        or sorted(coverage_any) != sorted(exact_recovered_coverage)
    ):
        raise ValueError
    return DciCoverageDatasetObservation(
        dataset_id=task_id,
        coverage_available_queries=10,
        coverage_total_queries=10,
        coverage_median_any_microunits=_median(coverage_any),
        coverage_median_mean_microunits=_median(coverage_mean),
        coverage_median_all_microunits=_median(coverage_all),
        retained_available_queries=len(retained),
        retained_median_microunits=None if not retained else _median(retained),
        tool_observation_count=tool_observations,
        surfaced_gold_count=surfaced_gold,
        model_call_count=model_calls,
        context_frame_count=context_frames,
        missing_boundary_count=missing_boundaries,
        integrity_failure_count=0,
        evidence_sha256=_domain_digest(
            "coverage-dataset-observation",
            {
                "task_id": task_id,
                "plan_sha256": plan["plan_sha256"],
                "selected_ids_sha256": task["selected_ids_sha256"],
                "run_id_sha256": hashlib.sha256(run_id.encode("utf-8")).hexdigest(),
                "recovered_run_sha256": recovered.recovered_run_sha256,
                "registry_sha256": registry.sha256,
                "cases": sorted(evidence_parts, key=lambda item: str(item["query_sha256"])),
            },
        ),
    )


def _validate_workflow_case_binding(
    *,
    record: Mapping[str, object],
    trace: Mapping[str, object],
    trajectory: Mapping[str, object],
    expected_dataset_id: str,
    expected_query_id: str,
    expected_generation: str,
    generation_state: Mapping[str, object],
    workflow_run_id: str,
) -> None:
    run = trajectory.get("run")
    dataset = trajectory.get("dataset")
    attempts = generation_state.get("attempts")
    native_run_id = generation_state.get("run_id")
    if (
        type(run) is not dict
        or type(dataset) is not dict
        or type(attempts) is not list
        or not attempts
        or type(native_run_id) is not str
        or not native_run_id
        or expected_generation != f"native-generation-{len(attempts):04d}"
        or run.get("run_id") != native_run_id
        or run.get("attempt") != len(attempts)
        or dataset.get("dataset_id") != expected_dataset_id
        or dataset.get("query_id") != expected_query_id
        or record.get("terminal_status") != "completed"
        or type(workflow_run_id) is not str
        or not workflow_run_id
        or record.get("run_sha256")
        != hashlib.sha256(workflow_run_id.encode("utf-8")).hexdigest()
        or trace.get("trace_id")
        != pathlight_trace_id(workflow_run_id, attempt=len(attempts))
    ):
        raise ValueError


def _workflow_protocol_run_id(generation_root: Path, *, attempt: int) -> str:
    try:
        if type(attempt) is not int or attempt < 1:
            raise ValueError
        protocol = _owned_evidence_directory(generation_root / "protocol")
        request = _json_native(protocol / f"attempt-{attempt:04d}.request.json")
        if type(request) is not dict:
            raise ValueError
        validate_run_request(request)
        run_id = request.get("run_id")
        if type(run_id) is not str or not run_id:
            raise ValueError
        return run_id
    except (OSError, TypeError, ValueError):
        raise ValueError from None


def _jsonl_private(path: Path) -> tuple[dict[str, object], ...]:
    encoded = read_private_file(path, _MAX_DOCUMENT_BYTES)
    rows: list[dict[str, object]] = []
    for line in encoded.splitlines():
        if not line:
            raise ValueError
        value = json.loads(line, object_pairs_hook=_unique_object)
        if type(value) is not dict:
            raise ValueError
        rows.append(value)
    return tuple(rows)


def _owned_evidence_directory(path: Path) -> Path:
    metadata = path.stat(follow_symlinks=False)
    if (
        not path.is_absolute()
        or path != path.resolve()
        or path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) not in {0o700, 0o755}
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError
    return path


def _query_generation_root(query_root: Path, generation: str) -> Path:
    """Accept the fixed native case envelope without accepting arbitrary files."""

    expected_files = {
        "input_question.txt",
        "item.json",
        "reproduction-evidence.json",
        "result.json",
        "timing.json",
    }
    try:
        root = _owned_evidence_directory(query_root)
        if type(generation) is not str or not generation.startswith(
            "native-generation-"
        ):
            raise ValueError
        children = {path.name: path for path in root.iterdir()}
        if set(children) != expected_files | {generation}:
            raise ValueError
        for name in expected_files:
            path = children[name]
            metadata = path.stat(follow_symlinks=False)
            if (
                path.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.getuid()
            ):
                raise ValueError
        return _owned_evidence_directory(children[generation])
    except (OSError, TypeError, ValueError):
        raise ValueError from None


def _natural(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _microunits(value: object) -> int:
    if type(value) is not float or not 0.0 <= value <= 1.0:
        raise ValueError
    return int(round(value * 1_000_000))


def _median(values: Sequence[int]) -> int:
    if not values:
        raise ValueError
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return ordered[middle - 1] + (ordered[middle] - ordered[middle - 1]) // 2


def _execution_config(
    plan: Mapping[str, object],
    *,
    output_root: Path,
    repo_root: Path,
    env_file: Path | None,
    environment: Mapping[str, str] | None,
) -> DciOperatorConfig:
    base = load_operator_config(
        repo_root,
        env_file=env_file,
        environment=environment,
        amount=Decimal("1"),
    )
    tasks = plan.get("tasks")
    if type(tasks) is not list:
        raise ValueError
    coverage_roots = {
        str(task["task_id"]): output_root / str(task["registry_path"])
        for task in tasks
        if type(task) is dict
    }
    if tuple(sorted(coverage_roots)) != tuple(sorted(_TASK_IDS)):
        raise ValueError
    inputs = base.benchmark_inputs
    return DciOperatorConfig(
        repo_root=base.repo_root,
        benchmark_inputs=DciBenchmarkOperatorInputs(
            dataset_roots=inputs.dataset_roots,
            corpus_roots=inputs.corpus_roots,
            private_environment=inputs.private_environment,
            coverage_registry_roots=coverage_roots,
            amount=Decimal("1"),
        ),
        host_service_options=base.host_service_options,
    )


def _config_with_amount(
    config: DciOperatorConfig, authorized_cost_microusd: int
) -> DciOperatorConfig:
    if (
        type(authorized_cost_microusd) is not int
        or not 1 <= authorized_cost_microusd <= 1_000_000
    ):
        raise ValueError
    inputs = config.benchmark_inputs
    return DciOperatorConfig(
        repo_root=config.repo_root,
        benchmark_inputs=DciBenchmarkOperatorInputs(
            dataset_roots=inputs.dataset_roots,
            corpus_roots=inputs.corpus_roots,
            private_environment=inputs.private_environment,
            coverage_registry_roots=inputs.coverage_registry_roots,
            amount=Decimal(authorized_cost_microusd) / Decimal(1_000_000),
        ),
        host_service_options=config.host_service_options,
    )


def _result_cost_evidence(
    result: BenchmarkRunResult,
    *,
    task_id: str,
    authorized_cost_microusd: int,
) -> tuple[int, str]:
    matches = [task for task in result.tasks if task.task_id == task_id]
    if len(matches) != 1:
        raise ValueError
    artifacts = matches[0].artifact_ids
    authorized_artifact = f"coverage-authorized-microusd.{authorized_cost_microusd}"
    cost_artifacts = tuple(
        artifact for artifact in artifacts if artifact.startswith("coverage-")
    )
    if artifacts.count(authorized_artifact) != 1 or len(cost_artifacts) != 2:
        raise ValueError
    actual_prefix = "coverage-actual-microusd."
    upper_artifact = f"coverage-upper-microusd.{authorized_cost_microusd}"
    actual_values = [
        artifact.removeprefix(actual_prefix)
        for artifact in artifacts
        if artifact.startswith(actual_prefix)
    ]
    if len(actual_values) == 1 and upper_artifact not in artifacts:
        raw = actual_values[0]
        if not raw.isascii() or not raw.isdigit():
            raise ValueError
        consumed = int(raw)
        if str(consumed) != raw or not 0 <= consumed <= authorized_cost_microusd:
            raise ValueError
        return consumed, "actual"
    if not actual_values and artifacts.count(upper_artifact) == 1:
        return authorized_cost_microusd, "upper-bound"
    raise ValueError


def _remaining_task_budget(
    task: Mapping[str, object], chain: tuple[dict[str, object], ...]
) -> int:
    maximum = task.get("max_cost_microusd")
    if type(maximum) is not int or maximum != 1_000_000:
        raise ValueError
    consumed = sum(_receipt_consumed_cost(receipt) for receipt in chain)
    if not 0 <= consumed <= maximum:
        raise ValueError
    return maximum - consumed


def _receipt_consumed_cost(receipt: Mapping[str, object]) -> int:
    consumed = receipt.get("consumed_cost_microusd")
    if type(consumed) is not int:
        raise ValueError
    return consumed


def _receipt_case_count(receipt: Mapping[str, object]) -> int:
    count = receipt.get("case_count")
    if type(count) is not int:
        raise ValueError
    return count


def _create_host(
    factory: Callable[..., BenchmarkCommandHost] | None,
    *,
    instance: DciBenchmarkInstance,
    config: DciOperatorConfig,
    package_sources: Sequence[CapabilityPackageSource] | None,
) -> BenchmarkCommandHost:
    if factory is not None:
        return factory(
            instance=instance,
            operator_config=config,
            package_sources=package_sources,
        )
    from asterion.applications.dci_agent_lite.benchmark_host import DciBenchmarkHost

    return DciBenchmarkHost(
        instance=instance,
        operator_config=config,
        package_sources=package_sources,
    )


def _receipt_filename(task_id: str, generation: int) -> str:
    try:
        index = _TASK_IDS.index(task_id)
    except ValueError:
        raise ValueError from None
    if type(generation) is not int or not 0 <= generation <= 9999:
        raise ValueError
    return f"receipt-{index + 1}-{generation:04d}.json"


def _read_receipt_chain(
    root: Path,
    *,
    plan: Mapping[str, object],
    task: Mapping[str, object],
    expected_authorization_sha256: str,
) -> tuple[dict[str, object], ...]:
    _operator_root(str(root))
    task_id = str(task["task_id"])
    task_maximum = task.get("max_cost_microusd")
    if type(task_maximum) is not int or task_maximum != 1_000_000:
        raise ValueError
    index = _TASK_IDS.index(task_id) + 1
    allowed_name = re.compile(r"^receipt-[1-5]-[0-9]{4}\.json$")
    if any(
        not path.is_file() or allowed_name.fullmatch(path.name) is None
        for path in root.iterdir()
    ):
        raise ValueError
    names = sorted(
        path.name
        for path in root.iterdir()
        if path.name.startswith(f"receipt-{index}-")
    )
    chain: list[dict[str, object]] = []
    for generation, name in enumerate(names):
        if name != _receipt_filename(task_id, generation):
            raise ValueError
        value = _json_private(root / name)
        fields = {
            "schema",
            "generation",
            "task_id",
            "instance_selector",
            "plan_sha256",
            "proposal_sha256",
            "scope_sha256",
            "variant_sha256",
            "registry_sha256",
            "execution_config_sha256",
            "authorization_sha256",
            "run_id",
            "benchmark_status",
            "observation_status",
            "observation_evidence_sha256",
            "case_count",
            "authorized_cost_microusd",
            "consumed_cost_microusd",
            "cost_evidence",
            "receipt_sha256",
        }
        if type(value) is not dict or set(value) != fields:
            raise ValueError
        digest = value.pop("receipt_sha256", None)
        benchmark_status = value.get("benchmark_status")
        observation_status = value.get("observation_status")
        observation_digest = value.get("observation_evidence_sha256")
        case_count = value.get("case_count")
        authorized_cost = value.get("authorized_cost_microusd")
        consumed_cost = value.get("consumed_cost_microusd")
        cost_evidence = value.get("cost_evidence")
        if (
            value.get("schema") != _RECEIPT_SCHEMA
            or value.get("generation") != generation
            or value.get("task_id") != task_id
            or value.get("instance_selector") != task["instance_selector"]
            or value.get("plan_sha256") != plan["plan_sha256"]
            or value.get("proposal_sha256") != plan["proposal_sha256"]
            or value.get("scope_sha256") != plan["scope_sha256"]
            or value.get("variant_sha256") != plan["variant_sha256"]
            or value.get("registry_sha256") != task["registry_sha256"]
            or value.get("execution_config_sha256")
            != plan["execution_config_sha256"]
            or value.get("authorization_sha256") != expected_authorization_sha256
            or type(value.get("run_id")) is not str
            or _RUN_ID.fullmatch(str(value.get("run_id"))) is None
            or benchmark_status not in {"completed", "failed", "cancelled"}
            or observation_status not in {"complete", "invalid", "unavailable"}
            or (observation_status == "complete") != _is_sha256(observation_digest)
            or benchmark_status != "completed"
            and observation_status != "unavailable"
            or benchmark_status == "completed"
            and observation_status == "unavailable"
            or type(case_count) is not int
            or not 0 <= case_count <= 10
            or benchmark_status == "completed"
            and case_count != 10
            or type(authorized_cost) is not int
            or not 1 <= authorized_cost <= 1_000_000
            or type(consumed_cost) is not int
            or not 0 <= consumed_cost <= authorized_cost
            or cost_evidence not in {"actual", "upper-bound"}
            or cost_evidence == "upper-bound"
            and consumed_cost != authorized_cost
            or authorized_cost
            > task_maximum - sum(_receipt_consumed_cost(receipt) for receipt in chain)
            or not _is_sha256(digest)
            or not hmac.compare_digest(str(digest), _digest(value))
        ):
            raise ValueError
        if chain and chain[-1]["benchmark_status"] == "completed":
            raise ValueError
        value["receipt_sha256"] = digest
        chain.append(value)
    return tuple(chain)


def _publish_receipt(
    root: Path,
    *,
    plan: Mapping[str, object],
    task: Mapping[str, object],
    authorization: Mapping[str, object],
    generation: int,
    run_id: str,
    status: str,
    case_count: int,
    authorized_cost_microusd: int,
    consumed_cost_microusd: int,
    cost_evidence: str,
    observation_status: str = "unavailable",
    observation_evidence_sha256: str | None = None,
) -> None:
    if (
        _RUN_ID.fullmatch(run_id) is None
        or status not in {"completed", "failed", "cancelled"}
        or type(case_count) is not int
        or not 0 <= case_count <= 10
        or status == "completed"
        and case_count != 10
        or observation_status not in {"complete", "invalid", "unavailable"}
        or (observation_status == "complete")
        != _is_sha256(observation_evidence_sha256)
        or status != "completed"
        and observation_status != "unavailable"
        or status == "completed"
        and observation_status == "unavailable"
        or type(authorized_cost_microusd) is not int
        or not 1 <= authorized_cost_microusd <= 1_000_000
        or type(consumed_cost_microusd) is not int
        or not 0 <= consumed_cost_microusd <= authorized_cost_microusd
        or cost_evidence not in {"actual", "upper-bound"}
        or cost_evidence == "upper-bound"
        and consumed_cost_microusd != authorized_cost_microusd
    ):
        raise ValueError
    body: dict[str, object] = {
        "schema": _RECEIPT_SCHEMA,
        "generation": generation,
        "task_id": task["task_id"],
        "instance_selector": task["instance_selector"],
        "plan_sha256": plan["plan_sha256"],
        "proposal_sha256": plan["proposal_sha256"],
        "scope_sha256": plan["scope_sha256"],
        "variant_sha256": plan["variant_sha256"],
        "registry_sha256": task["registry_sha256"],
        "execution_config_sha256": plan["execution_config_sha256"],
        "authorization_sha256": authorization["authorization_sha256"],
        "run_id": run_id,
        "benchmark_status": status,
        "observation_status": observation_status,
        "observation_evidence_sha256": observation_evidence_sha256,
        "case_count": case_count,
        "authorized_cost_microusd": authorized_cost_microusd,
        "consumed_cost_microusd": consumed_cost_microusd,
        "cost_evidence": cost_evidence,
    }
    body["receipt_sha256"] = _digest(body)
    staging = _create_staging_root(root)
    name = _receipt_filename(str(task["task_id"]), generation)
    failed = False
    try:
        write_private_file(staging / name, _canonical_bytes(body))
        _publish_staged_outputs(root, staging, (name,))
    except BaseException:
        failed = True
    try:
        _cleanup_staging(root, staging, (name,))
    except BaseException:
        failed = True
    if failed:
        raise ValueError
    _read_receipt_chain(
        root,
        plan=plan,
        task=task,
        expected_authorization_sha256=str(authorization["authorization_sha256"]),
    )


def _status_summary(
    plan: Mapping[str, object], *, completed: int, status: str
) -> dict[str, object]:
    if (
        type(completed) is not int
        or not 0 <= completed <= len(_TASK_IDS)
        or status
        not in {
            "prepared",
            "partial",
            "completed",
            "failed",
            "cancelled",
            "observation-invalid",
        }
    ):
        raise ValueError
    return {
        "case_count": completed * 10,
        "completed_task_count": completed,
        "max_agent_operations": plan["max_agent_operations"],
        "max_cost_microusd": plan["max_cost_microusd"],
        "plan_sha256": plan["plan_sha256"],
        "proposal_sha256": plan["proposal_sha256"],
        "registry_set_sha256": plan["registry_set_sha256"],
        "scope_sha256": plan["scope_sha256"],
        "status": status,
    }


def _read_plan(path: Path) -> dict[str, object]:
    value = _json_private(path)
    required = {
        "schema",
        "diagnosis_bundle_sha256",
        "proposal_sha256",
        "scope_sha256",
        "variant_sha256",
        "registry_set_sha256",
        "source_lock_path",
        "source_lock_sha256",
        "execution_config_sha256",
        "max_agent_operations",
        "max_cost_microusd",
        "max_infrastructure_failures",
        "execution_authorized",
        "tasks",
        "plan_sha256",
    }
    if type(value) is not dict or set(value) != required:
        raise ValueError
    digest = value.pop("plan_sha256", None)
    if (
        value.get("schema") != _PLAN_SCHEMA
        or value.get("max_agent_operations") != _MAX_AGENT_OPERATIONS
        or value.get("max_cost_microusd") != _MAX_COST_MICROUSD
        or value.get("max_infrastructure_failures") != _MAX_INFRASTRUCTURE_FAILURES
        or value.get("execution_authorized") is not False
        or value.get("source_lock_path") != _SOURCE_LOCK_FILENAME
        or any(
            not _is_sha256(value.get(name))
            for name in (
                "diagnosis_bundle_sha256",
                "proposal_sha256",
                "scope_sha256",
                "variant_sha256",
                "registry_set_sha256",
                "source_lock_sha256",
                "execution_config_sha256",
            )
        )
        or not _is_sha256(digest)
        or not hmac.compare_digest(digest, _digest(value))
    ):
        raise ValueError
    tasks = value.get("tasks")
    task_fields = {
        "task_id",
        "instance_selector",
        "case_limit",
        "max_cost_microusd",
        "registry_path",
        "registry_sha256",
        "selected_ids_sha256",
    }
    if type(tasks) is not list or len(tasks) != len(_TASK_IDS):
        raise ValueError
    normalized_tasks: list[dict[str, object]] = []
    for index, raw_task in enumerate(tasks):
        task_id = _TASK_IDS[index]
        if (
            type(raw_task) is not dict
            or set(raw_task) != task_fields
            or raw_task.get("task_id") != task_id
            or raw_task.get("instance_selector") != f"dci.{task_id}@1.0.0"
            or raw_task.get("case_limit") != 10
            or raw_task.get("max_cost_microusd") != 1_000_000
            or raw_task.get("registry_path") != f"coverage/{task_id}/registry.json"
            or not _is_sha256(raw_task.get("registry_sha256"))
            or not _is_sha256(raw_task.get("selected_ids_sha256"))
        ):
            raise ValueError
        normalized_tasks.append(raw_task)
    if value["registry_set_sha256"] != _digest(
        [
            {
                "task_id": task["task_id"],
                "registry_sha256": task["registry_sha256"],
                "selected_ids_sha256": task["selected_ids_sha256"],
            }
            for task in normalized_tasks
        ]
    ):
        raise ValueError
    value["plan_sha256"] = digest
    return value


def _read_authorization(
    path: Path, *, plan: Mapping[str, object], output_root: Path
) -> dict[str, object]:
    value = _json_private(path)
    fields = {
        "schema",
        "plan_sha256",
        "proposal_sha256",
        "scope_sha256",
        "variant_sha256",
        "registry_set_sha256",
        "execution_config_sha256",
        "operator_root_sha256",
        "max_agent_operations",
        "max_cost_microusd",
        "max_infrastructure_failures",
        "execution_authorized",
        "operator_approval_sha256",
        "authorization_sha256",
    }
    if type(value) is not dict or set(value) != fields:
        raise ValueError
    digest = value.pop("authorization_sha256", None)
    if (
        value.get("schema") != _AUTHORIZATION_SCHEMA
        or value.get("plan_sha256") != plan["plan_sha256"]
        or value.get("proposal_sha256") != plan["proposal_sha256"]
        or value.get("scope_sha256") != plan["scope_sha256"]
        or value.get("variant_sha256") != plan["variant_sha256"]
        or value.get("registry_set_sha256") != plan["registry_set_sha256"]
        or value.get("execution_config_sha256")
        != plan["execution_config_sha256"]
        or value.get("operator_root_sha256")
        != _operator_root_binding_sha256(output_root)
        or value.get("max_agent_operations") != _MAX_AGENT_OPERATIONS
        or value.get("max_cost_microusd") != _MAX_COST_MICROUSD
        or value.get("max_infrastructure_failures") != _MAX_INFRASTRUCTURE_FAILURES
        or value.get("execution_authorized") is not True
        or not _is_sha256(value.get("operator_approval_sha256"))
        or not _is_sha256(digest)
        or not hmac.compare_digest(digest, _digest(value))
    ):
        raise ValueError
    value["authorization_sha256"] = digest
    return value


def _coverage_proposal(proposals: tuple[Proposal, ...], digest: str) -> Proposal:
    matches = [
        item for item in proposals if hmac.compare_digest(item.proposal_sha256, digest)
    ]
    if len(matches) != 1:
        raise ValueError
    proposal = matches[0]
    sole_variable = _domain_digest(
        "proposal-sole-variable", "trajectory-coverage-instrumentation-only"
    )
    expected = (
        _domain_digest(
            "proposal-change",
            {
                "change": "coverage-instrumentation",
                "sole_variable_sha256": sole_variable,
            },
        ),
        _domain_digest("proposal-success", {"trajectory_coverage_recorded": True}),
        _domain_digest("proposal-stop", {"infrastructure_failures": 2}),
        _domain_digest(
            "proposal-budget",
            {"agent_operations": 50, "max_cost_microusd": 5_000_000},
        ),
    )
    if (
        proposal.change_sha256,
        proposal.success_criteria_sha256,
        proposal.stop_criteria_sha256,
        proposal.budget_sha256,
    ) != expected:
        raise ValueError
    return proposal


def _exact_options(arguments: tuple[str, ...], names: set[str]) -> dict[str, str]:
    if len(arguments) != len(names) * 2:
        raise ValueError
    values: dict[str, str] = {}
    for index in range(0, len(arguments), 2):
        name, value = arguments[index : index + 2]
        if name not in names or name in values or not value:
            raise ValueError
        values[name] = value
    if set(values) != names:
        raise ValueError
    return values


def _absolute_path(value: str) -> Path:
    path = Path(value)
    if "\x00" in value or not path.is_absolute() or path != path.resolve():
        raise ValueError
    return path


def _operator_root(value: str) -> Path:
    from asterion.applications.dci_agent_lite.pathlight_cli import _operator_root

    return _operator_root(value)


def _operator_root_binding_sha256(root: Path) -> str:
    """Return a path-free identity for one validated private operator root."""

    try:
        validated = _operator_root(str(root))
        metadata = os.stat(validated, follow_symlinks=False)
        if metadata.st_dev < 0 or metadata.st_ino <= 0:
            raise ValueError
        return _domain_digest(
            "coverage-operator-root",
            {"device": metadata.st_dev, "inode": metadata.st_ino},
        )
    except (OSError, TypeError, ValueError):
        raise ValueError from None


def _create_staging_root(root: Path) -> Path:
    from asterion.applications.dci_agent_lite.pathlight_cli import (
        _create_staging_root,
    )

    return _create_staging_root(root)


def _publish_staged_tree(root: Path, staging: Path) -> None:
    from asterion.applications.dci_agent_lite.pathlight_cli import (
        _publish_staged_tree,
    )

    _publish_staged_tree(root, staging)


def _cleanup_staging_tree(root: Path, staging: Path) -> None:
    from asterion.applications.dci_agent_lite.pathlight_cli import (
        _cleanup_staging_tree,
    )

    _cleanup_staging_tree(root, staging)


def _publish_staged_outputs(root: Path, staging: Path, names: Sequence[str]) -> None:
    from asterion.applications.dci_agent_lite.pathlight_cli import (
        _publish_staged_outputs,
    )

    _publish_staged_outputs(root, staging, names)


def _cleanup_staging(root: Path, staging: Path, names: Sequence[str]) -> None:
    from asterion.applications.dci_agent_lite.pathlight_cli import _cleanup_staging

    _cleanup_staging(root, staging, names)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(read_private_file(path, _MAX_DOCUMENT_BYTES)).hexdigest()


def _json_private(path: Path) -> object:
    encoded = read_private_file(path, _MAX_DOCUMENT_BYTES)
    value = json.loads(encoded, object_pairs_hook=_unique_object)
    if encoded != _canonical_bytes(value):
        raise ValueError
    return value


def _json_native(path: Path, *, max_bytes: int = _MAX_DOCUMENT_BYTES) -> object:
    """Read one trusted native writer artifact without imposing its JSON layout."""

    try:
        return json.loads(
            read_private_file(path, max_bytes),
            object_pairs_hook=_unique_object,
        )
    except (OSError, TypeError, UnicodeError, ValueError, json.JSONDecodeError):
        raise ValueError from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _domain_digest(domain: str, value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "domain": f"asterion.dci.pathlight.diagnosis/{domain}/v1",
                "value": value,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = ("PLAN_FILENAME", "main")
