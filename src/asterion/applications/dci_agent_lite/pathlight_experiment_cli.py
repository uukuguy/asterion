"""Bounded, digest-closed coordination for the DCI coverage experiment."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
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
from asterion.capabilities.dci.implementation.pathlight.coverage import (
    prepare_coverage_registry,
    validate_coverage_registry_root,
)
from asterion.pathlight._private_file import read_private_file, write_private_file
from asterion.pathlight.diagnosis import Proposal, read_diagnosis_bundle


PLAN_FILENAME = "pathlight-coverage-experiment.json"
_PLAN_SCHEMA = "asterion.dci.pathlight.coverage-experiment/v1"
_AUTHORIZATION_SCHEMA = "asterion.dci.pathlight.coverage-experiment-authorization/v1"
_ERROR = "asterion-dci: command failed\n"
_MAX_DOCUMENT_BYTES = 1 << 20
_MAX_AGENT_OPERATIONS = 50
_MAX_COST_MICROUSD = 5_000_000
_MAX_INFRASTRUCTURE_FAILURES = 2
_SOURCE_LOCK_FILENAME = "pathlight-coverage-source-lock.json"
_RECEIPT_SCHEMA = "asterion.dci.pathlight.coverage-experiment-receipt/v1"
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
        _absolute_path(options["--authorization-file"]), plan=plan
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
            output_root / "receipts", plan=plan, task=raw_task
        )
        if receipt_chain and receipt_chain[-1]["status"] == "completed":
            completed_before += 1
        infrastructure_failures += sum(
            receipt["status"] == "failed" for receipt in receipt_chain
        )
        remaining_cost_microusd = _remaining_task_budget(raw_task, receipt_chain)
        completed_task = bool(
            receipt_chain and receipt_chain[-1]["status"] == "completed"
        )
        if remaining_cost_microusd == 0 and not completed_task:
            raise ValueError
        authorized_cost_microusd = (
            int(raw_task["max_cost_microusd"])
            if completed_task and remaining_cost_microusd == 0
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
    if completed_before == len(_TASK_IDS) or infrastructure_failures >= 2:
        raise ValueError

    completed = completed_before
    for preflight in preflights:
        chain = preflight.receipt_chain
        if chain and chain[-1]["status"] == "completed":
            continue
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
        except BaseException:
            status = "failed"
            case_count = 0
            consumed_cost_microusd = preflight.authorized_cost_microusd
            cost_evidence = "upper-bound"
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
        )
        if status == "completed":
            completed += 1
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
    options = _exact_options(arguments, {"--plan-file", "--output-root"})
    plan_path = _absolute_path(options["--plan-file"])
    if plan_path.parent != _operator_root(options["--output-root"]):
        raise ValueError
    plan = _read_plan(plan_path)
    tasks = plan["tasks"]
    if type(tasks) is not list:
        raise ValueError
    completed = 0
    terminal_statuses: list[str] = []
    infrastructure_failures = 0
    for task in tasks:
        if type(task) is not dict:
            raise ValueError
        chain = _read_receipt_chain(plan_path.parent / "receipts", plan=plan, task=task)
        if chain:
            terminal_statuses.append(str(chain[-1]["status"]))
            completed += chain[-1]["status"] == "completed"
            infrastructure_failures += sum(
                receipt["status"] == "failed" for receipt in chain
            )
    if completed == len(_TASK_IDS):
        status = "completed"
    elif terminal_statuses and terminal_statuses[-1] == "cancelled":
        status = "cancelled"
    elif infrastructure_failures >= 2:
        status = "failed"
    elif terminal_statuses:
        status = "partial"
    else:
        status = "prepared"
    return _status_summary(plan, completed=completed, status=status)


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
            "status",
            "case_count",
            "authorized_cost_microusd",
            "consumed_cost_microusd",
            "cost_evidence",
            "receipt_sha256",
        }
        if type(value) is not dict or set(value) != fields:
            raise ValueError
        digest = value.pop("receipt_sha256", None)
        status = value.get("status")
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
            or not _is_sha256(value.get("authorization_sha256"))
            or type(value.get("run_id")) is not str
            or _RUN_ID.fullmatch(str(value.get("run_id"))) is None
            or status not in {"completed", "failed", "cancelled"}
            or type(case_count) is not int
            or not 0 <= case_count <= 10
            or status == "completed"
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
        if chain and chain[-1]["status"] == "completed":
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
) -> None:
    if (
        _RUN_ID.fullmatch(run_id) is None
        or status not in {"completed", "failed", "cancelled"}
        or type(case_count) is not int
        or not 0 <= case_count <= 10
        or status == "completed"
        and case_count != 10
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
        "status": status,
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
    _read_receipt_chain(root, plan=plan, task=task)


def _status_summary(
    plan: Mapping[str, object], *, completed: int, status: str
) -> dict[str, object]:
    if (
        type(completed) is not int
        or not 0 <= completed <= len(_TASK_IDS)
        or status not in {"prepared", "partial", "completed", "failed", "cancelled"}
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


def _read_authorization(path: Path, *, plan: Mapping[str, object]) -> dict[str, object]:
    value = _json_private(path)
    fields = {
        "schema",
        "plan_sha256",
        "proposal_sha256",
        "scope_sha256",
        "variant_sha256",
        "registry_set_sha256",
        "execution_config_sha256",
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
