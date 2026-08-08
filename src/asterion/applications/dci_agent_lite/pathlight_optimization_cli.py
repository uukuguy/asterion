"""Private, provider-free preparation for the bounded Bright A/B trial.

This module deliberately stops before benchmark execution.  A plan is useful
evidence, never authority: an operator must provide a separate, root-bound
authorization document before a later execution coordinator may load a
provider.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import TextIO, cast

from asterion.applications.dci_agent_lite.benchmark_instances import (
    select_benchmark_instance,
)
from asterion.applications.dci_agent_lite.benchmark_source_lock import (
    resolve_benchmark_source_lock,
    write_benchmark_source_lock,
)
from asterion.applications.dci_agent_lite.benchmark_host import (
    optimization_execution_config_sha256,
)
from asterion.applications.dci_agent_lite.benchmark_instances import (
    DciBenchmarkInstance,
)
from asterion.benchmarks.cli import BenchmarkCommandHost
from asterion.benchmarks.evidence import BenchmarkRunResult
from asterion.capability_packages.sources.base import CapabilityPackageSource
from asterion.capabilities.dci.implementation.operator_inputs import DciBenchmarkOperatorInputs
from asterion.applications.dci_agent_lite.operator_config import (
    DciOperatorConfig,
    load_operator_config,
)
from asterion.capabilities.dci.implementation.pathlight.diagnosis import (
    AUTHORIZATION_GATE_REPORT_FILENAME,
    DCI_DIAGNOSIS_REPORT_FILENAME,
    authorization_gate_report_mapping,
    read_authorization_gate_report,
    read_dci_diagnosis_report,
)
from asterion.capabilities.dci.implementation.pathlight.recovery import (
    _domain_digest as _recovery_digest,
    read_completed_dci_run,
)
from asterion.capabilities.dci.implementation.pathlight.conversion import (
    recovered_run_to_evaluation_bundle,
    recovered_run_to_experiment,
)
from asterion.capabilities.dci.implementation.pathlight.optimization import (
    BrightNativeBatch,
    finalize_bright_optimization,
    render_bright_optimization_chinese,
)
from asterion.capabilities.dci.implementation.research.query_planning import (
    BASELINE_QUERY_PLAN,
    DECOMPOSED_QUERY_PLAN,
    materialize_query_planning_prompt,
    query_planning_contract_sha256,
    resolve_query_planning_contract,
)
from asterion.capabilities.dci.implementation.datasets import (
    load_bright_benchmark_rows_bytes,
)
from asterion.pathlight._private_file import read_private_file, write_private_file
from asterion.pathlight.diagnosis import Proposal, read_diagnosis_bundle
from asterion.pathlight.diagnosis import write_diagnosis_bundle
from asterion.pathlight.evaluation import write_evaluation_bundle
from asterion.pathlight.experiment import Variant
from asterion.pathlight.experiment import write_experiment_bundle
from asterion.pathlight.optimization import write_optimization_bundle
from asterion.workflow_evidence import read_workflow_observation_bundle


PLAN_FILENAME = "pathlight-bright-optimization.json"
_PLAN_SCHEMA = "asterion.dci.pathlight.bright-optimization-plan/v1"
_AUTHORIZATION_SCHEMA = "asterion.dci.pathlight.bright-optimization-authorization/v1"
_SELECTION_SCHEMA = "asterion.dci.pathlight.bright-selected-cases/v1"
_SOURCE_LOCK_FILENAME = "pathlight-bright-optimization-source-lock.json"
_RECEIPT_SCHEMA = "asterion.dci.pathlight.bright-optimization-receipt/v1"
_ERROR = "asterion-dci: command failed\n"
_MAX_DOCUMENT_BYTES = 1 << 20
_MAX_AGENT_OPERATIONS = 80
_MAX_JUDGE_OPERATIONS = 0
_MAX_COST_MICROUSD = 16_000_000
_TASK_MAX_COST_MICROUSD = 2_000_000
_MAX_INFRASTRUCTURE_FAILURES = 2
_MAX_NATIVE_ATTEMPTS = 1
_DATASETS = (
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
)
_ROLES = ("baseline", "candidate")
_RECEIPT_NAME = re.compile(r"^receipt-[1-8]-0000\.json$")
_RUN_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_EXECUTION_LEASE_NAME = ".pathlight-bright-optimization.execution.lock"
_RECOVERY_DOCUMENTS = (
    "config.json", "batch-state.json", "summary.json", "analysis.json", "results.jsonl",
)


def main(
    arguments: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
    repo_root: Path,
    env_file: Path | None,
    environment: Mapping[str, str] | None,
    package_sources: Sequence[object] | None = None,
    host_factory: Callable[..., object] | None = None,
) -> int:
    """Run the bounded Bright optimization coordinator."""

    try:
        values = tuple(arguments)
        if not values:
            raise ValueError
        if values[0] == "prepare":
            # Preparation intentionally cannot read dotenv files.
            result = _prepare(
                values[1:],
                repo_root=repo_root,
                environment=environment,
                package_sources=package_sources,
            )
        elif values[0] == "status":
            result = _status(values[1:])
        elif values[0] == "finalize":
            result = _finalize(values[1:])
        elif values[0] in {"execute", "resume"}:
            command = _execute(
                values[1:],
                repo_root=repo_root,
                env_file=env_file,
                environment=environment,
                package_sources=package_sources,
                host_factory=host_factory,
            )
            stdout.write(json.dumps(command[1], sort_keys=True, separators=(",", ":")) + "\n")
            return command[0]
        else:
            raise ValueError
        stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    except BaseException:
        stderr.write(_ERROR)
        return 2


def read_optimization_plan(path: Path) -> dict[str, object]:
    """Read an exact inactive private plan, without creating authority."""

    return _read_plan(path)


def read_optimization_authorization(
    path: Path, *, plan: Mapping[str, object]
) -> dict[str, object]:
    """Read one strict operator authorization bound to an exact plan/root."""

    return _read_authorization(path, plan=plan)


def _prepare(
    arguments: tuple[str, ...],
    *,
    repo_root: Path,
    environment: Mapping[str, str] | None,
    package_sources: Sequence[object] | None,
) -> dict[str, object]:
    options = _optional_options(
        arguments,
        required={
            "--diagnosis-file",
            "--diagnosis-report-file",
            "--gate-report-file",
            "--proposal-sha256",
            "--output-root",
        },
        optional={
            "--coverage-registry-root",
        },
    )
    output_root = _operator_root(options["--output-root"])
    if any(output_root.iterdir()):
        raise ValueError
    diagnosis_path = _absolute_path(options["--diagnosis-file"])
    report_path = _diagnosis_report_path(options["--diagnosis-report-file"])
    gate_path = _gate_report_path(options["--gate-report-file"])
    if diagnosis_path.parent != report_path.parent or report_path.parent != gate_path.parent:
        raise ValueError
    diagnosis = read_diagnosis_bundle(diagnosis_path)
    report = read_dci_diagnosis_report(report_path)
    proposal = _query_decomposition_proposal(
        diagnosis, options["--proposal-sha256"]
    )
    gate = read_authorization_gate_report(gate_path)
    expected_gate = authorization_gate_report_mapping(report)
    if (
        report.diagnosis_bundle != diagnosis
        or gate["diagnosis_bundle_sha256"] != diagnosis.bundle_sha256
        or gate["query_proposal_sha256"] != proposal.proposal_sha256
        or gate["query_scope_sha256"] != proposal.scope_sha256
        or gate != expected_gate
    ):
        raise ValueError
    # Passing a non-existent explicit path prevents load_operator_config from
    # falling back to ``repo_root/.env``.  Only caller-supplied environment is
    # consumed, and no provider is constructed on this path.
    coverage_registry_root = (
        None
        if "--coverage-registry-root" not in options
        else _operator_root(options["--coverage-registry-root"])
    )
    config = load_operator_config(
        repo_root,
        env_file=Path(repo_root).resolve() / ".pathlight-no-dotenv",
        environment=environment,
        max_native_attempts=_MAX_NATIVE_ATTEMPTS,
    )
    staging = _create_staging_root(output_root)
    body: dict[str, object] | None = None
    failed = False
    try:
        (staging / "selections").mkdir(mode=0o700)
        (staging / "prompts").mkdir(mode=0o700)
        (staging / "receipts").mkdir(mode=0o700)
        (staging / "evidence").mkdir(mode=0o700)
        selections = _prepare_selections(staging, config, coverage_registry_root)
        source_lock = resolve_benchmark_source_lock(
            select_benchmark_instance("dci.bright.biology@1.0.0"),
            package_sources=package_sources,  # type: ignore[arg-type]
        )
        source_lock_path = staging / _SOURCE_LOCK_FILENAME
        write_benchmark_source_lock(source_lock, source_lock_path)
        candidate_prompt = materialize_query_planning_prompt(
            DECOMPOSED_QUERY_PLAN, staging / "prompts"
        )
        baseline_contract = resolve_query_planning_contract(BASELINE_QUERY_PLAN)
        candidate_contract = resolve_query_planning_contract(DECOMPOSED_QUERY_PLAN)
        baseline_digest = query_planning_contract_sha256(baseline_contract)
        candidate_digest = query_planning_contract_sha256(candidate_contract)
        if hmac.compare_digest(baseline_digest, candidate_digest):
            raise ValueError
        baseline_variant, candidate_variant = _optimization_variants(
            baseline_digest, candidate_digest
        )
        baseline_config = optimization_execution_config_sha256(
            config.benchmark_inputs.private_environment, baseline_contract
        )
        candidate_config = optimization_execution_config_sha256(
            config.benchmark_inputs.private_environment, candidate_contract
        )
        if hmac.compare_digest(baseline_config, candidate_config):
            raise ValueError
        tasks = _tasks(
            selections,
            baseline_digest,
            candidate_digest,
            baseline_variant.variant_sha256,
            candidate_variant.variant_sha256,
            baseline_config,
            candidate_config,
        )
        output_stat = os.stat(output_root, follow_symlinks=False)
        body = {
            "schema": _PLAN_SCHEMA,
            "diagnosis_bundle_sha256": diagnosis.bundle_sha256,
            "authorization_gate_report_sha256": gate["gate_report_sha256"],
            "proposal_sha256": proposal.proposal_sha256,
            "finding_sha256": proposal.finding_sha256,
            "scope_sha256": proposal.scope_sha256,
            "success_criteria_sha256": proposal.success_criteria_sha256,
            "stop_criteria_sha256": proposal.stop_criteria_sha256,
            "budget_sha256": proposal.budget_sha256,
            "source_lock_path": _SOURCE_LOCK_FILENAME,
            "source_lock_sha256": _file_sha256(source_lock_path),
            "selected_case_scope_sha256": _selected_scope(selections),
            "baseline_query_plan_sha256": baseline_digest,
            "candidate_query_plan_sha256": candidate_digest,
            "baseline_variant_sha256": baseline_variant.variant_sha256,
            "candidate_variant_sha256": candidate_variant.variant_sha256,
            "baseline_execution_config_sha256": baseline_config,
            "candidate_execution_config_sha256": candidate_config,
            "candidate_prompt_path": str(candidate_prompt.relative_to(staging)),
            "output_root_device": output_stat.st_dev,
            "output_root_inode": output_stat.st_ino,
            "max_agent_operations": _MAX_AGENT_OPERATIONS,
            "max_judge_operations": _MAX_JUDGE_OPERATIONS,
            "max_cost_microusd": _MAX_COST_MICROUSD,
            "max_infrastructure_failures": _MAX_INFRASTRUCTURE_FAILURES,
            "max_native_attempts": _MAX_NATIVE_ATTEMPTS,
            "execution_authorized": False,
            "tasks": tasks,
        }
        body["plan_sha256"] = _digest(body)
        write_private_file(staging / PLAN_FILENAME, _canonical_bytes(body))
        _read_plan(staging / PLAN_FILENAME)
        _validate_prepared_closure(staging, body, config)
        _publish_staged_tree(output_root, staging)
    except BaseException:
        failed = True
    try:
        _cleanup_staging_tree(output_root, staging)
    except BaseException:
        failed = True
    if failed or body is None:
        raise ValueError
    return {
        "dataset_count": len(_DATASETS),
        "case_count": 40,
        "max_agent_operations": _MAX_AGENT_OPERATIONS,
        "max_judge_operations": _MAX_JUDGE_OPERATIONS,
        "max_cost_microusd": _MAX_COST_MICROUSD,
        "output_bundle_digest": body["plan_sha256"],
    }


def _prepare_selections(root: Path, config: DciOperatorConfig, coverage_registry_root: Path | None = None) -> dict[str, dict[str, object]]:
    selections: dict[str, dict[str, object]] = {}
    for dataset_id in _DATASETS:
        source = _read_source(Path(config.benchmark_inputs.dataset_roots[dataset_id]))
        rows = load_bright_benchmark_rows_bytes(source)
        if coverage_registry_root is None:
            cases = tuple(sorted((_recovery_digest("query-id", row.query_id) for row in rows)))[:10]
        else:
            registry_root = coverage_registry_root / "coverage" / dataset_id
            registry = json.loads((registry_root / "registry.json").read_text(encoding="utf-8"))
            selected = {
                json.loads((registry_root / item["path"]).read_text(encoding="utf-8"))["query_id"]
                for item in registry["manifests"]
            }
            cases = tuple(sorted(_recovery_digest("query-id", row.query_id) for row in rows if row.query_id in selected))
        if len(cases) != 10 or len(set(cases)) != 10:
            raise ValueError
        value: dict[str, object] = {
            "schema": _SELECTION_SCHEMA,
            "dataset_id": dataset_id,
            "dataset_source_sha256": hashlib.sha256(source).hexdigest(),
            "selected_case_sha256s": list(cases),
        }
        value["selected_ids_sha256"] = _digest(value["selected_case_sha256s"])
        value["selection_sha256"] = _digest(value)
        path = root / "selections" / f"{dataset_id}.json"
        write_private_file(path, _canonical_bytes(value))
        selections[dataset_id] = value
    return selections


def _tasks(
    selections: Mapping[str, Mapping[str, object]],
    baseline_digest: str,
    candidate_digest: str,
    baseline_variant: str,
    candidate_variant: str,
    baseline_config: str,
    candidate_config: str,
) -> list[dict[str, object]]:
    tasks: list[dict[str, object]] = []
    for dataset_id in _DATASETS:
        selection = selections[dataset_id]
        for role in _ROLES:
            tasks.append(
                {
                    "task_id": f"{dataset_id}.{role}",
                    "dataset_id": dataset_id,
                    "instance_selector": f"dci.{dataset_id}@1.0.0",
                    "variant_role": role,
                    "query_plan_sha256": baseline_digest if role == "baseline" else candidate_digest,
                    "variant_sha256": baseline_variant if role == "baseline" else candidate_variant,
                    "execution_config_sha256": baseline_config if role == "baseline" else candidate_config,
                    "selection_path": f"selections/{dataset_id}.json",
                    "selection_sha256": selection["selection_sha256"],
                    "selected_ids_sha256": selection["selected_ids_sha256"],
                    "selected_case_sha256s": selection["selected_case_sha256s"],
                    "case_limit": 10,
                    "native_attempt_limit": _MAX_NATIVE_ATTEMPTS,
                    "max_judge_operations": _MAX_JUDGE_OPERATIONS,
                    "max_cost_microusd": _TASK_MAX_COST_MICROUSD,
                    "evidence_path": f"evidence/{dataset_id}/{role}",
                    "receipt_path": f"receipts/{dataset_id}.{role}",
                }
            )
    return tasks


def _optimization_variants(
    baseline_query_plan_sha256: str, candidate_query_plan_sha256: str
) -> tuple[Variant, Variant]:
    """Return the two generic Variant identities for the sole query-plan axis."""

    common = {
        "assembly_sha256": _digest("asterion-safe/pi:assembly"),
        "package_set_sha256": _digest("asterion-safe/pi:package-set"),
        "implementation_sha256": _digest("asterion-safe/pi:implementation"),
        "runtime_sha256": _digest("asterion-safe/pi:runtime"),
        "model_sha256": _digest("asterion-safe/pi:model"),
        "toolset_sha256": _digest("asterion-safe/pi:toolset"),
        "policy_sha256": _digest("asterion-safe/pi:policy"),
    }

    def build(query_plan_sha256: str) -> Variant:
        return Variant(
            **common,
            prompt_contract_sha256=query_plan_sha256,
            change_sha256=_digest(
                {
                    "schema": "asterion.dci.pathlight.query-plan-change/v1",
                    "query_plan_sha256": query_plan_sha256,
                }
            ),
        )

    baseline, candidate = build(baseline_query_plan_sha256), build(candidate_query_plan_sha256)
    baseline_mapping = baseline.to_mapping()
    candidate_mapping = candidate.to_mapping()
    differences = {
        name
        for name in baseline_mapping
        if baseline_mapping[name] != candidate_mapping[name]
    }
    if differences != {"prompt_contract_sha256", "change_sha256", "variant_sha256"}:
        raise ValueError
    return baseline, candidate


def _validate_prepared_closure(root: Path, plan: Mapping[str, object], config: DciOperatorConfig) -> None:
    if _file_sha256(root / str(plan["source_lock_path"])) != plan["source_lock_sha256"]:
        raise ValueError
    prompt = root / str(plan["candidate_prompt_path"])
    if prompt.name == "" or not prompt.is_file() or stat.S_IMODE(os.stat(prompt, follow_symlinks=False).st_mode) != 0o400:
        raise ValueError
    selections: dict[str, dict[str, object]] = {}
    for dataset_id in _DATASETS:
        value = _json_private(root / "selections" / f"{dataset_id}.json")
        if not isinstance(value, dict) or _selection(value) != value:
            raise ValueError
        # Read the source again only to detect mutation before publication.
        if hashlib.sha256(_read_source(Path(config.benchmark_inputs.dataset_roots[dataset_id]))).hexdigest() != value["dataset_source_sha256"]:
            raise ValueError
        selections[dataset_id] = value
    if _selected_scope(selections) != plan["selected_case_scope_sha256"]:
        raise ValueError


def _execute(
    arguments: tuple[str, ...],
    *,
    repo_root: Path,
    env_file: Path | None,
    environment: Mapping[str, str] | None,
    package_sources: Sequence[object] | None,
    host_factory: Callable[..., object] | None,
) -> tuple[int, dict[str, object]]:
    """Run one execution coordinator while exclusively owning its plan root."""

    options = _optional_options(
        arguments,
        required={"--plan-file", "--output-root"},
        optional={"--authorization-file"},
    )
    output_root = _operator_root(options["--output-root"])
    with _execution_lease(output_root):
        return _execute_unlocked(
            arguments,
            repo_root=repo_root,
            env_file=env_file,
            environment=environment,
            package_sources=package_sources,
            host_factory=host_factory,
        )


def _execute_unlocked(
    arguments: tuple[str, ...],
    *,
    repo_root: Path,
    env_file: Path | None,
    environment: Mapping[str, str] | None,
    package_sources: Sequence[object] | None,
    host_factory: Callable[..., object] | None,
) -> tuple[int, dict[str, object]]:
    """Preflight the complete immutable tree, then execute one foreground pass.

    The intentionally two-phase structure means a malformed later task can
    never cause an earlier task to load a provider.  A receipt is terminal for
    its task; resume only considers the remaining never-started tasks.
    """

    options = _optional_options(
        arguments,
        required={"--plan-file", "--output-root"},
        optional={"--authorization-file"},
    )
    plan_path = _absolute_path(options["--plan-file"])
    output_root = _operator_root(options["--output-root"])
    if plan_path.parent != output_root:
        raise ValueError
    plan = _read_plan(plan_path)
    authorization = _execution_authorization(
        options, plan=plan, output_root=output_root, environment=environment
    )
    _validate_execution_root(output_root, plan)
    receipts = _read_receipt_chain(
        output_root / "receipts", plan=plan,
        authorization_sha256=str(authorization["authorization_sha256"]),
    )
    tasks = plan["tasks"]
    if type(tasks) is not list:
        raise ValueError
    if len(receipts) == len(tasks):
        return 0, _receipt_status(plan, receipts)
    if sum(item["failure_category"] in _INFRASTRUCTURE_FAILURES for item in receipts) >= _MAX_INFRASTRUCTURE_FAILURES:
        return 1, _receipt_status(plan, receipts)
    config = load_operator_config(
        repo_root,
        env_file=env_file,
        environment=environment,
        max_native_attempts=_MAX_NATIVE_ATTEMPTS,
    )
    _validate_execution_tree(output_root, plan, config)
    global_maximum = plan.get("max_cost_microusd")
    if type(global_maximum) is not int:
        raise ValueError

    prepared: list[tuple[Mapping[str, object], BenchmarkCommandHost, object, object, object]] = []
    completed = {str(receipt["task_id"]) for receipt in receipts}
    # All provider-free host resolution is completed for every remaining task
    # before any provider is constructed.
    for task in tasks:
        if type(task) is not dict:
            raise ValueError
        if str(task["task_id"]) in completed:
            continue
        maximum = task.get("max_cost_microusd")
        if type(maximum) is not int:
            raise ValueError
        global_remaining = global_maximum - sum(
            _receipt_int(receipt, "cost_microusd") for receipt in receipts
        )
        if not 1 <= global_remaining <= global_maximum:
            raise ValueError
        instance = select_benchmark_instance(str(task["instance_selector"]))
        host = _create_host(
            host_factory, instance=instance,
            config=_config_with_amount(config, min(maximum, global_remaining)), package_sources=package_sources,
            task=task, output_root=output_root, plan=plan,
        )
        metadata = host.discover_metadata(
            application_ref=instance.application_ref, suite_ref=instance.suite_ref
        )
        source_lock = host.resolve_source_lock(output_root / str(plan["source_lock_path"]))
        payloads = host.open_selected_payloads(metadata, source_lock)
        resolved = host.resolve_application(
            payloads, application_ref=instance.application_ref, suite_ref=instance.suite_ref
        )
        draft = host.create_plan(
            resolved, application_ref=instance.application_ref, suite_ref=instance.suite_ref,
            case_limit=10, execute=False, authorization=None, resume_run_id=None,
        )
        if getattr(draft, "case_limit", None) != 10:
            raise ValueError
        prepared.append((task, host, payloads, resolved, draft))

    infrastructure_failures = sum(
        item["failure_category"] in _INFRASTRUCTURE_FAILURES for item in receipts
    )
    for task, host, payloads, resolved, _draft in prepared:
        instance = select_benchmark_instance(str(task["instance_selector"]))
        evidence_root = output_root / str(task["evidence_path"])
        recovered = _restore_quarantined_completed_evidence(
            output_root, evidence_root, str(task["task_id"]), str(task["dataset_id"]),
        )
        if recovered is not None:
            receipt = _publish_receipt(
                output_root / "receipts", plan=plan, authorization=authorization,
                task=task, receipts=receipts, run_id=recovered[0], status="completed",
                completed_case_count=10, cost_microusd=int(task["max_cost_microusd"]),
                cost_source="conservative", elapsed_ns=0, failure_category="none",
                native=recovered[1],
            )
            receipts = (*receipts, receipt)
            continue
        # Planning can create a native run manifest before a provider is
        # loaded.  A later retry must preserve that incomplete evidence and
        # continue, rather than treating its own recoverable residue as a
        # permanent execution blocker.
        _quarantine_unknown_evidence(output_root, evidence_root, str(task["task_id"]))
        _fresh_evidence_root(evidence_root)
        authorization_claim = host.authorize_execution(
            application_ref=instance.application_ref, suite_ref=instance.suite_ref,
            case_limit=10, evidence_root=evidence_root, resume_run_id=None,
        )
        execution_plan = host.create_plan(
            resolved, application_ref=instance.application_ref, suite_ref=instance.suite_ref,
            case_limit=10, execute=True, authorization=authorization_claim, resume_run_id=None,
        )
        run_id = getattr(execution_plan, "run_id", None)
        if type(run_id) is not str or _RUN_ID.fullmatch(run_id) is None:
            raise ValueError
        started = time.monotonic_ns()
        try:
            providers = host.load_selected_providers(payloads, authorization_claim)
            result = host.run(execution_plan, providers, evidence_root=evidence_root)
            status, cases, category = _result_terminal(
                result, task_id=str(task["dataset_id"]), evidence_root=evidence_root
            )
            maximum = task.get("max_cost_microusd")
            if type(maximum) is not int:
                raise ValueError
            cost, source = (
                (maximum, "conservative") if status != "completed"
                else _result_cost(result, task_id=str(task["dataset_id"]), maximum=maximum)
            )
        except KeyboardInterrupt:
            status, cases, category = "cancelled", 0, "cancelled"
            maximum = task.get("max_cost_microusd")
            if type(maximum) is not int:
                raise ValueError
            cost, source = maximum, "conservative"
        except BaseException as error:
            category = _infrastructure_failure_category(error)
            if category is None:
                _quarantine_unknown_evidence(output_root, evidence_root, str(task["task_id"]))
                raise ValueError from None
            status, cases = "failed", 0
            maximum = task.get("max_cost_microusd")
            if type(maximum) is not int:
                raise ValueError
            cost, source = maximum, "conservative"
        elapsed_ns = time.monotonic_ns() - started
        native = _native_receipt_projection(evidence_root, str(task["dataset_id"]), expected_case_count=cases) if status == "completed" else None
        if status == "completed" and native is None:
            category = "observation-invalid"
        receipt = _publish_receipt(
            output_root / "receipts", plan=plan, authorization=authorization, task=task,
            receipts=receipts, run_id=run_id, status=status, completed_case_count=cases,
            cost_microusd=cost, cost_source=source, elapsed_ns=elapsed_ns,
            failure_category=category, native=native,
        )
        receipts = (*receipts, receipt)
        if category in _INFRASTRUCTURE_FAILURES:
            infrastructure_failures += 1
            if infrastructure_failures >= _MAX_INFRASTRUCTURE_FAILURES:
                return 1, _receipt_status(plan, receipts)
        if status == "cancelled":
            return 130, _receipt_status(plan, receipts)
    return (0 if len(receipts) == len(tasks) else 1), _receipt_status(plan, receipts)


_INFRASTRUCTURE_FAILURES = frozenset({"authorization", "network", "rate-limit", "timeout", "host-service"})


@contextmanager
def _execution_lease(root: Path):
    """Make a plan root single-writer without persisting execution authority."""

    import fcntl

    path = root / _EXECUTION_LEASE_NAME
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
        0o600,
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
            raise ValueError
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError from None
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _validate_execution_root(root: Path, plan: Mapping[str, object]) -> None:
    metadata = os.stat(root, follow_symlinks=False)
    if (
        root.is_symlink() or not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_dev, metadata.st_ino) != (plan["output_root_device"], plan["output_root_inode"])
    ):
        raise ValueError
    _private_directory(root / "receipts")


def _validate_execution_tree(root: Path, plan: Mapping[str, object], config: DciOperatorConfig) -> None:
    _validate_plan_tree(root, plan)
    if _file_sha256(root / str(plan["source_lock_path"])) != plan["source_lock_sha256"]:
        raise ValueError
    for role, contract_id in (("baseline", BASELINE_QUERY_PLAN), ("candidate", DECOMPOSED_QUERY_PLAN)):
        contract = resolve_query_planning_contract(contract_id)
        if query_planning_contract_sha256(contract) != plan[f"{role}_query_plan_sha256"]:
            raise ValueError
        if optimization_execution_config_sha256(config.benchmark_inputs.private_environment, contract) != plan[f"{role}_execution_config_sha256"]:
            raise ValueError
    for dataset in _DATASETS:
        raw_selection = _json_private(root / "selections" / f"{dataset}.json")
        if type(raw_selection) is not dict:
            raise ValueError
        selection = _selection(raw_selection)
        source = _read_source(Path(config.benchmark_inputs.dataset_roots[dataset]))
        rows = load_bright_benchmark_rows_bytes(source)
        # The prepared selection is sealed into the plan and may deliberately
        # come from the preceding coverage experiment instead of the lexical
        # first ten source rows.  Execution must re-check source identity and
        # membership, but must not silently replace that selected cohort with
        # a different default cohort.
        available = frozenset(_recovery_digest("query-id", row.query_id) for row in rows)
        if (
            hashlib.sha256(source).hexdigest() != selection["dataset_source_sha256"]
            or any(case not in available for case in selection["selected_case_sha256s"])
        ):
            raise ValueError


def _fresh_evidence_root(path: Path) -> None:
    # Evidence is product-private and task-unique.  A pre-created tree could
    # smuggle compatible generic-run state into a new coordinator task.
    if path.exists() or path.is_symlink():
        raise ValueError
    path.mkdir(parents=True, mode=0o700)
    _private_directory(path)


def _quarantine_unknown_evidence(output_root: Path, evidence_root: Path, task_id: str) -> None:
    """Preserve unknown provider writes without wedging a later explicit resume."""
    if not evidence_root.exists():
        return
    quarantine = output_root / "evidence-quarantine"
    if not quarantine.exists():
        quarantine.mkdir(mode=0o700)
    _private_directory(quarantine)
    digest = _digest({"task": task_id, "root": str(evidence_root)})
    target = quarantine / f"{digest}.unknown"
    if target.exists() or target.is_symlink():
        raise ValueError
    os.rename(evidence_root, target)


def _restore_quarantined_completed_evidence(
    output_root: Path, evidence_root: Path, task_id: str, dataset_id: str,
) -> tuple[str, dict[str, object]] | None:
    """Adopt only a fully revalidated task previously quarantined by this plan."""

    target = output_root / "evidence-quarantine" / f"{_digest({'task': task_id, 'root': str(evidence_root)})}.unknown"
    if not target.exists():
        return None
    native = _native_receipt_projection(target, dataset_id)
    if native is None or evidence_root.exists():
        return None
    runs = tuple(sorted((target / "runs").iterdir(), key=lambda item: item.name))
    if len(runs) != 1 or not runs[0].is_dir() or runs[0].is_symlink() or _RUN_ID.fullmatch(runs[0].name) is None:
        return None
    os.rename(target, evidence_root)
    return runs[0].name, native


def _config_with_amount(config: DciOperatorConfig, cost_microusd: int) -> DciOperatorConfig:
    """Bind the real DCI payload to the remaining exact task/global ceiling."""
    if type(cost_microusd) is not int or not 1 <= cost_microusd <= _TASK_MAX_COST_MICROUSD:
        raise ValueError
    inputs = config.benchmark_inputs
    return DciOperatorConfig(
        repo_root=config.repo_root,
        benchmark_inputs=DciBenchmarkOperatorInputs(
            dataset_roots=inputs.dataset_roots,
            corpus_roots=inputs.corpus_roots,
            private_environment=inputs.private_environment,
            coverage_registry_roots=inputs.coverage_registry_roots,
            amount=Decimal(cost_microusd) / Decimal(1_000_000),
        ),
        host_service_options=config.host_service_options,
        max_native_attempts=_MAX_NATIVE_ATTEMPTS,
    )


def _create_host(
    factory: Callable[..., object] | None,
    *,
    instance: DciBenchmarkInstance,
    config: DciOperatorConfig,
    package_sources: Sequence[object] | None,
    task: Mapping[str, object],
    output_root: Path,
    plan: Mapping[str, object],
) -> BenchmarkCommandHost:
    role = task.get("variant_role")
    if role not in _ROLES:
        raise ValueError
    contract = resolve_query_planning_contract(
        BASELINE_QUERY_PLAN if role == "baseline" else DECOMPOSED_QUERY_PLAN
    )
    prompt = None if role == "baseline" else output_root / str(plan["candidate_prompt_path"])
    if factory is not None:
        candidate = factory(
            instance=instance, operator_config=config, package_sources=package_sources,
            query_planning_contract=contract, query_planning_prompt_file=prompt, task=task,
        )
        if not isinstance(candidate, BenchmarkCommandHost):
            raise ValueError
        return candidate
    from asterion.applications.dci_agent_lite.benchmark_host import DciBenchmarkHost
    return DciBenchmarkHost(
        instance=instance, operator_config=config,
        package_sources=cast(Sequence[CapabilityPackageSource] | None, package_sources),
        query_planning_contract=contract, query_planning_prompt_file=prompt,
    )


def _result_terminal(
    result: object, *, task_id: str, evidence_root: Path | None = None
) -> tuple[str, int, str]:
    if not isinstance(result, BenchmarkRunResult):
        raise ValueError
    matches = [item for item in result.tasks if item.task_id == task_id]
    if len(matches) != 1:
        raise ValueError
    task = matches[0]
    if result.status == "cancelled" or task.status == "cancelled":
        return "cancelled", 0, "cancelled"
    if result.status == "failed" or task.status == "failed":
        category = _native_failure_category(evidence_root, task_id)
        if category is None:
            raise ValueError
        return "failed", min(task.case_count, 10), category
    if result.status != "completed" or task.status != "completed" or task.case_count != 10:
        raise ValueError
    return "completed", 10, "none"


def _native_failure_category(evidence_root: Path | None, task_id: str) -> str | None:
    """Classify a failed native task from persisted progress, never its text."""

    if evidence_root is None or not (evidence_root / "runs").exists():
        # Legacy host-shaped test doubles have no generic evidence store.  The
        # production DCI host always has one and takes the strict branch below.
        return "model-business"
    try:
        paths = tuple(sorted(evidence_root.glob("runs/*/progress/*.json")))
        observations = []
        for path in paths:
            value = json.loads(
                read_private_file(path, _MAX_DOCUMENT_BYTES), object_pairs_hook=_unique_object
            )
            if type(value) is dict and value.get("status") == "task.failure-observed" and value.get("task_id") == task_id:
                observations.append(value.get("failure_class"))
        if len(observations) != 1:
            raise ValueError
        native = observations[0]
        mapping = {
            "authorization": "authorization", "network": "network",
            "rate-limit": "rate-limit", "timeout": "timeout",
            "model-refusal": "model-business", "evaluation": "model-business",
            "parsing": "model-business", "tool-protocol": "model-business",
        }
        return mapping.get(native) if isinstance(native, str) else None
    except Exception:
        return None


def _result_cost(result: object, *, task_id: str, maximum: int) -> tuple[int, str]:
    if not isinstance(result, BenchmarkRunResult) or maximum != _TASK_MAX_COST_MICROUSD:
        raise ValueError
    matches = [item for item in result.tasks if item.task_id == task_id]
    if len(matches) != 1:
        raise ValueError
    artifacts = matches[0].artifact_ids
    if tuple(artifacts) == (f"{task_id}.native-result",):
        # Bright A/B execution is selected from a previously sealed coverage
        # cohort; it is not itself a coverage collection run.  The native
        # executor therefore emits its result artifact, not coverage-ledger
        # artifacts.  Keep the plan's exact ceiling as conservative cost
        # evidence instead of turning a completed task into a host failure.
        return maximum, "conservative"
    authorized = [item for item in artifacts if item.startswith("coverage-authorized-microusd.")]
    actual = [item.removeprefix("coverage-actual-microusd.") for item in artifacts if item.startswith("coverage-actual-microusd.")]
    upper = [item for item in artifacts if item.startswith("coverage-upper-microusd.")]
    if authorized != [f"coverage-authorized-microusd.{maximum}"]:
        raise ValueError
    if len(actual) == 1 and not upper and actual[0].isdigit() and str(int(actual[0])) == actual[0]:
        value = int(actual[0])
        if 0 <= value <= maximum:
            return value, "actual"
    if not actual and upper == [f"coverage-upper-microusd.{maximum}"]:
        return maximum, "conservative"
    raise ValueError


def _infrastructure_failure_category(error: BaseException) -> str | None:
    name = type(error).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if "rate" in name or "throttle" in name:
        return "rate-limit"
    if "network" in name or "connection" in name:
        return "network"
    if "authoriz" in name:
        return "authorization"
    if "host" in name or "service" in name:
        return "host-service"
    return None


def _native_receipt_projection(
    evidence_root: Path, expected_dataset_id: str, *, expected_case_count: int = 10,
) -> dict[str, object] | None:
    """Return a digest-only receipt projection from one completed native run.

    This is deliberately a reader, rather than a claim made by the benchmark
    result.  It accepts exactly the one output tree a fresh task root may own
    and reuses the existing recovery and workflow evidence validators.
    """

    try:
        outputs = evidence_root / "outputs"
        _private_directory(evidence_root)
        native_root = _native_output_root(outputs, expected_dataset_id)
        recovered = read_completed_dci_run(native_root, expected_dataset_id)
        if recovered.selected_count != expected_case_count or recovered.total_count != expected_case_count:
            raise ValueError
        experiment = recovered_run_to_experiment(recovered)
        evaluations = recovered_run_to_evaluation_bundle(recovered)
        workflow_paths = tuple(sorted(native_root.rglob("workflow-evidence.json")))
        if not workflow_paths or any(path.is_symlink() for path in workflow_paths):
            raise ValueError
        bundles = tuple(read_workflow_observation_bundle(path) for path in workflow_paths)
        workflow_digests = tuple(sorted(bundle.bundle_sha256 for bundle in bundles))
        if len(set(workflow_digests)) != len(workflow_digests):
            raise ValueError
        input_tokens = 0
        output_tokens = 0
        record_count = 0
        run_identities: set[str] = set()
        input_identities: set[str] = set()
        source_identities: set[str] = set()
        for bundle in bundles:
            for record in bundle.records:
                if record.get("terminal_status") != "completed":
                    raise ValueError
                run_identity = record.get("run_sha256")
                input_identity = record.get("input_sha256")
                source_identity = record.get("source_graph_sha256")
                if (
                    not _is_sha256(run_identity) or not _is_sha256(input_identity)
                    or not _is_sha256(source_identity)
                    or run_identity in run_identities
                    or input_identity in input_identities
                    or source_identity in source_identities
                ):
                    raise ValueError
                assert isinstance(run_identity, str)
                assert isinstance(input_identity, str)
                assert isinstance(source_identity, str)
                run_identities.add(run_identity)
                input_identities.add(input_identity)
                source_identities.add(source_identity)
                usage = record.get("usage")
                if not isinstance(usage, Mapping):
                    raise ValueError
                input_value = usage.get("input_tokens")
                output_value = usage.get("output_tokens")
                if (
                    type(input_value) is not int or input_value < 0
                    or type(output_value) is not int or output_value < 0
                ):
                    raise ValueError
                input_tokens += input_value
                output_tokens += output_value
                record_count += 1
        if (
            record_count != expected_case_count
            or len(run_identities) != expected_case_count
            or len(input_identities) != expected_case_count
            or len(source_identities) != expected_case_count
            # Native totals include the provider's billable/context accounting;
            # workflow records expose the structured call payload accounting.
            # The latter can be lower, but can never exceed the former.
            or input_tokens + output_tokens
            > sum(case.agent_total_tokens for case in recovered.cases)
        ):
            raise ValueError
        return {
            "recovered_run_sha256": recovered.recovered_run_sha256,
            "experiment_bundle_sha256": experiment.bundle_sha256,
            "evaluation_bundle_sha256": evaluations.bundle_sha256,
            "workflow_bundle_set_sha256": _digest({"workflow_bundle_sha256s": workflow_digests}),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
    except Exception:
        return None


def _receipt_filename(index: int) -> str:
    if type(index) is not int or not 0 <= index < 8:
        raise ValueError
    return f"receipt-{index + 1}-0000.json"


def _read_receipt_chain(
    root: Path, *, plan: Mapping[str, object], authorization_sha256: str | None = None,
) -> tuple[dict[str, object], ...]:
    _private_directory(root)
    paths = tuple(sorted(root.iterdir(), key=lambda item: item.name))
    if any(not path.is_file() or _RECEIPT_NAME.fullmatch(path.name) is None for path in paths):
        raise ValueError
    tasks = plan.get("tasks")
    if type(tasks) is not list or len(paths) > len(tasks):
        raise ValueError
    chain: list[dict[str, object]] = []
    for index, path in enumerate(paths):
        if path.name != _receipt_filename(index):
            raise ValueError
        value = _json_private(path)
        expected = {
            "schema", "task_id", "plan_sha256", "authorization_sha256", "previous_receipt_sha256",
            "run_id_sha256", "status", "completed_case_count", "cost_microusd", "cost_source",
            "input_tokens", "output_tokens", "total_tokens", "elapsed_ns",
            "recovered_run_sha256", "experiment_bundle_sha256", "evaluation_bundle_sha256",
            "workflow_bundle_set_sha256", "failure_category", "native_evidence_state", "receipt_sha256",
        }
        if type(value) is not dict or set(value) != expected:
            raise ValueError
        digest = value.pop("receipt_sha256")
        task = tasks[index]
        previous = None if not chain else chain[-1]["receipt_sha256"]
        if (
            type(task) is not dict or value.get("schema") != _RECEIPT_SCHEMA
            or value.get("task_id") != task.get("task_id")
            or value.get("plan_sha256") != plan.get("plan_sha256")
            or not _is_sha256(value.get("authorization_sha256"))
            or authorization_sha256 is not None and value.get("authorization_sha256") != authorization_sha256
            or authorization_sha256 is None and chain and value.get("authorization_sha256") != chain[0]["authorization_sha256"]
            or value.get("previous_receipt_sha256") != previous
            or not _is_sha256(value.get("run_id_sha256"))
            or value.get("status") not in {"completed", "failed", "cancelled"}
            or type(value.get("completed_case_count")) is not int or not 0 <= value["completed_case_count"] <= 10
            or value["status"] == "completed" and value["completed_case_count"] != 10
            or type(value.get("cost_microusd")) is not int or not 0 <= value["cost_microusd"] <= int(task["max_cost_microusd"])
            or value.get("cost_source") not in {"actual", "conservative"}
            or value["cost_source"] == "conservative" and value["cost_microusd"] != task["max_cost_microusd"]
            or type(value.get("elapsed_ns")) is not int or value["elapsed_ns"] < 0
            or value.get("failure_category") not in {"none", "model-business", "cancelled", "observation-invalid", *_INFRASTRUCTURE_FAILURES}
            or not _is_sha256(digest) or not hmac.compare_digest(str(digest), _digest(value))
        ):
            raise ValueError
        native_fields = (
            "recovered_run_sha256", "experiment_bundle_sha256", "evaluation_bundle_sha256",
            "workflow_bundle_set_sha256", "input_tokens", "output_tokens", "total_tokens",
        )
        state = value.get("native_evidence_state")
        if state == "complete":
            if (
                value["status"] != "completed" or value["failure_category"] != "none"
                or any(not _is_sha256(value.get(name)) for name in native_fields[:4])
                or any(type(value.get(name)) is not int or value[name] < 0 for name in native_fields[4:])
                or value["total_tokens"] != value["input_tokens"] + value["output_tokens"]
            ):
                raise ValueError
            evidence_path = task.get("evidence_path") if type(task) is dict else None
            if type(evidence_path) is not str:
                raise ValueError
            observed = _native_receipt_projection(
                root.parent / evidence_path, str(task["dataset_id"]),
                expected_case_count=value["completed_case_count"],
            )
            if observed is None or any(value[name] != observed[name] for name in native_fields):
                raise ValueError
        elif state == "invalid":
            if value["status"] != "completed" or value["failure_category"] != "observation-invalid" or any(value[name] is not None for name in native_fields):
                raise ValueError
        elif state == "unavailable":
            if value["status"] == "completed" or value["failure_category"] not in {"model-business", "cancelled", *_INFRASTRUCTURE_FAILURES} or any(value[name] is not None for name in native_fields):
                raise ValueError
        else:
            raise ValueError
        value["receipt_sha256"] = digest
        chain.append(value)
    return tuple(chain)


def _publish_receipt(
    root: Path, *, plan: Mapping[str, object], authorization: Mapping[str, object], task: Mapping[str, object],
    receipts: tuple[dict[str, object], ...], run_id: str, status: str, completed_case_count: int,
    cost_microusd: int, cost_source: str, elapsed_ns: int, failure_category: str,
    native: Mapping[str, object] | None,
) -> dict[str, object]:
    index = len(receipts)
    tasks = plan["tasks"]
    if type(tasks) is not list or tasks[index] != task or status not in {"completed", "failed", "cancelled"}:
        raise ValueError
    body: dict[str, object] = {
        "schema": _RECEIPT_SCHEMA, "task_id": task["task_id"], "plan_sha256": plan["plan_sha256"],
        "authorization_sha256": authorization["authorization_sha256"],
        "previous_receipt_sha256": None if not receipts else receipts[-1]["receipt_sha256"],
        "run_id_sha256": _digest({"run-id": run_id}), "status": status,
        "completed_case_count": completed_case_count, "cost_microusd": cost_microusd,
        "cost_source": cost_source, "elapsed_ns": elapsed_ns,
        "failure_category": failure_category,
    }
    native_fields = (
        "recovered_run_sha256", "experiment_bundle_sha256", "evaluation_bundle_sha256",
        "workflow_bundle_set_sha256", "input_tokens", "output_tokens", "total_tokens",
    )
    if native is not None and status == "completed" and failure_category == "none":
        if set(native) != set(native_fields):
            raise ValueError
        body.update(native)
        body["native_evidence_state"] = "complete"
    else:
        body.update({name: None for name in native_fields})
        body["native_evidence_state"] = "invalid" if failure_category == "observation-invalid" else "unavailable"
    body["receipt_sha256"] = _digest(body)
    name = _receipt_filename(index)
    # Exclusive create is the append-only publication point.  A collision,
    # including an attacker-created nonregular child, is never overwritten.
    write_private_file(root / name, _canonical_bytes(body))
    return _read_receipt_chain(root, plan=plan)[-1]


def _receipt_status(plan: Mapping[str, object], receipts: tuple[dict[str, object], ...]) -> dict[str, object]:
    infra = sum(item["failure_category"] in _INFRASTRUCTURE_FAILURES for item in receipts)
    complete = sum(_receipt_int(item, "completed_case_count") for item in receipts)
    if len(receipts) == 8:
        status = "completed" if all(item["status"] == "completed" for item in receipts) else "terminal"
    elif receipts and receipts[-1]["status"] == "cancelled":
        status = "cancelled"
    elif infra >= _MAX_INFRASTRUCTURE_FAILURES:
        status = "failed"
    elif receipts:
        status = "partial"
    else:
        status = "prepared"
    return {
        "status": status, "completed_agent_operations": complete, "completed_judge_operations": 0,
        "consumed_cost_microusd": sum(_receipt_int(item, "cost_microusd") for item in receipts),
        "infrastructure_failure_count": infra, "max_agent_operations": plan["max_agent_operations"],
        "max_judge_operations": plan["max_judge_operations"], "max_cost_microusd": plan["max_cost_microusd"],
        "plan_sha256": plan["plan_sha256"],
    }


def _receipt_int(receipt: Mapping[str, object], name: str) -> int:
    value = receipt.get(name)
    if type(value) is not int:
        raise ValueError
    return value


def _finalize(arguments: tuple[str, ...]) -> dict[str, object]:
    """Re-read native evidence and publish one provider-free finalization."""

    options = _optional_options(
        arguments,
        required={"--plan-file", "--diagnosis-file", "--output-root"},
        optional={"--authorization-file"},
    )
    plan_path = _absolute_path(options["--plan-file"])
    output_root = _operator_root(options["--output-root"])
    if plan_path.parent != output_root:
        raise ValueError
    plan = _read_plan(plan_path)
    authorization = _execution_authorization(
        options, plan=plan, output_root=output_root, environment=None
    )
    _validate_execution_root(output_root, plan)
    receipts = _read_receipt_chain(
        output_root / "receipts", plan=plan,
        authorization_sha256=str(authorization["authorization_sha256"]),
    )
    diagnosis = read_diagnosis_bundle(_absolute_path(options["--diagnosis-file"]))
    if diagnosis.bundle_sha256 != plan["diagnosis_bundle_sha256"]:
        raise ValueError
    tasks = plan.get("tasks")
    if type(tasks) is not list or len(tasks) != 8:
        raise ValueError
    batches: list[BrightNativeBatch] = []
    for receipt, task in zip(receipts, tasks):
        if type(task) is not dict:
            raise ValueError
        evidence_root = output_root / str(task["evidence_path"])
        native_root = _native_root(evidence_root, str(task["dataset_id"])) if receipt["native_evidence_state"] == "complete" else None
        recovered = read_completed_dci_run(native_root, str(task["dataset_id"])) if native_root is not None else None
        bundles = _workflow_bundle_sha256s(native_root) if native_root is not None else ()
        if native_root is not None and _digest({"workflow_bundle_sha256s": list(bundles)}) != receipt["workflow_bundle_set_sha256"]:
            raise ValueError
        batches.append(BrightNativeBatch(str(task["dataset_id"]), str(task["variant_role"]), receipt, recovered, bundles, native_root))
    closure = finalize_bright_optimization(
        plan=plan, authorization=authorization, receipts=receipts, native_batches=batches, diagnosis=diagnosis,
    )
    report = render_bright_optimization_chinese(closure)
    _publish_finalization(output_root, closure, report)
    return {
        "experiment_bundle_sha256": closure.experiment.bundle_sha256,
        "evaluation_bundle_sha256": closure.evaluations.bundle_sha256,
        "optimization_bundle_sha256": closure.optimization.bundle_sha256,
        "diagnosis_bundle_sha256": closure.diagnosis.bundle_sha256,
        "decision": closure.optimization.decisions[0].result,
        "reason": closure.optimization.decisions[0].reason,
    }


def _native_root(evidence_root: Path, expected_dataset_id: str) -> Path:
    _private_directory(evidence_root)
    return _native_output_root(evidence_root / "outputs", expected_dataset_id)


def _native_output_root(outputs: Path, expected_dataset_id: str) -> Path:
    """Locate one budget-authorized native result without trusting a path hint."""

    _owned_readonly_directory(outputs)
    runs = tuple(sorted(outputs.iterdir(), key=lambda item: item.name))
    if len(runs) != 1 or not runs[0].is_dir() or runs[0].is_symlink():
        raise ValueError
    children = tuple(sorted(runs[0].iterdir(), key=lambda item: item.name))
    if (
        len(children) == 1 and children[0].name == expected_dataset_id
        and children[0].is_dir() and not children[0].is_symlink()
    ):
        return children[0]
    authorized = children
    if (
        len(authorized) != 1 or authorized[0].name != "authorized-full"
        or not authorized[0].is_dir() or authorized[0].is_symlink()
    ):
        raise ValueError
    roots = tuple(sorted(authorized[0].iterdir(), key=lambda item: item.name))
    completed = tuple(
        root for root in roots
        if (
            _is_sha256(root.name) and root.is_dir() and not root.is_symlink()
            and all((root / name).is_file() and not (root / name).is_symlink() for name in _RECOVERY_DOCUMENTS)
        )
    )
    if (
        len(completed) != 1
    ):
        raise ValueError
    return completed[0]


def _workflow_bundle_sha256s(native_root: Path) -> tuple[str, ...]:
    paths = tuple(sorted(native_root.rglob("workflow-evidence.json")))
    if not paths or any(path.is_symlink() for path in paths):
        raise ValueError
    values = tuple(sorted(read_workflow_observation_bundle(path).bundle_sha256 for path in paths))
    if len(values) != len(set(values)):
        raise ValueError
    return values


def _publish_finalization(output_root: Path, closure: object, report: str) -> None:
    """Stage all five values, reject conflicts first, then exclusively publish."""

    from asterion.capabilities.dci.implementation.pathlight.optimization import BrightOptimizationClosure
    if type(closure) is not BrightOptimizationClosure or type(report) is not str:
        raise ValueError
    staging = _create_staging_root(output_root)
    try:
        write_experiment_bundle(closure.experiment, staging / "pathlight-experiment.json")
        write_evaluation_bundle(
            staging / "pathlight-evaluations.json",
            closure.evaluations.evaluations,
            closure.evaluations.metric_contracts,
        )
        write_optimization_bundle(staging / "pathlight-optimization.json", closure.optimization)
        write_diagnosis_bundle(closure.diagnosis, staging / "pathlight-diagnosis.json")
        write_private_file(staging / "pathlight-bright-optimization.zh-CN.md", report.encode("utf-8"))
        names = tuple(sorted(path.name for path in staging.iterdir()))
        if names != (
            "pathlight-bright-optimization.zh-CN.md", "pathlight-diagnosis.json", "pathlight-evaluations.json",
            "pathlight-experiment.json", "pathlight-optimization.json",
        ):
            raise ValueError
        for name in names:
            current = output_root / name
            staged = staging / name
            if current.exists() or current.is_symlink():
                if read_private_file(current, _MAX_DOCUMENT_BYTES) != read_private_file(staged, _MAX_DOCUMENT_BYTES):
                    raise ValueError
        # Publish only missing outputs through the descriptor-relative,
        # inode-guarded link transaction shared by the public Pathlight CLI.
        # A publication fault rolls back every link it created, preserving any
        # pre-existing byte-identical outputs and leaving no partial closure.
        missing = tuple(name for name in names if not (output_root / name).exists())
        if missing:
            from asterion.applications.dci_agent_lite.pathlight_cli import _publish_staged_outputs
            _publish_staged_outputs(output_root, staging, missing)
    finally:
        try:
            _cleanup_staging_tree(output_root, staging)
        except Exception as cleanup_error:
            # A transient cleanup failure must not strand private staging
            # evidence.  Retry once before surfacing the original failure;
            # the cleanup primitive remains descriptor-relative and refuses
            # anything it no longer owns.
            try:
                _cleanup_staging_tree(output_root, staging)
            except Exception:
                pass
            raise cleanup_error


def _status(arguments: tuple[str, ...]) -> dict[str, object]:
    options = _exact_options(arguments, {"--plan-file", "--output-root"})
    plan_path = _absolute_path(options["--plan-file"])
    output_root = _operator_root(options["--output-root"])
    if plan_path.parent != output_root:
        raise ValueError
    plan = _read_plan(plan_path)
    root_metadata = os.stat(output_root, follow_symlinks=False)
    if (
        (root_metadata.st_dev, root_metadata.st_ino)
        != (plan["output_root_device"], plan["output_root_inode"])
    ):
        raise ValueError
    receipts = output_root / "receipts"
    return _receipt_status(plan, _read_receipt_chain(receipts, plan=plan))


def _read_plan(path: Path) -> dict[str, object]:
    value = _json_private(path)
    fields = {
        "schema", "diagnosis_bundle_sha256", "authorization_gate_report_sha256", "proposal_sha256", "finding_sha256", "scope_sha256",
        "success_criteria_sha256", "stop_criteria_sha256", "budget_sha256", "source_lock_path",
        "source_lock_sha256", "selected_case_scope_sha256", "baseline_query_plan_sha256",
        "candidate_query_plan_sha256", "baseline_variant_sha256", "candidate_variant_sha256",
        "baseline_execution_config_sha256", "candidate_execution_config_sha256",
        "candidate_prompt_path", "output_root_device", "output_root_inode",
        "max_agent_operations", "max_judge_operations", "max_cost_microusd", "max_infrastructure_failures",
        "max_native_attempts", "execution_authorized", "tasks", "plan_sha256",
    }
    if type(value) is not dict or set(value) != fields:
        raise ValueError
    digest = value.pop("plan_sha256", None)
    root_device = value.get("output_root_device")
    root_inode = value.get("output_root_inode")
    hashes = (
        "diagnosis_bundle_sha256", "authorization_gate_report_sha256", "proposal_sha256", "finding_sha256", "scope_sha256",
        "success_criteria_sha256", "stop_criteria_sha256", "budget_sha256", "source_lock_sha256",
        "selected_case_scope_sha256", "baseline_query_plan_sha256", "candidate_query_plan_sha256",
        "baseline_variant_sha256", "candidate_variant_sha256",
        "baseline_execution_config_sha256", "candidate_execution_config_sha256",
    )
    if (
        value.get("schema") != _PLAN_SCHEMA
        or any(not _is_sha256(value.get(name)) for name in hashes)
        or value.get("source_lock_path") != _SOURCE_LOCK_FILENAME
        or value.get("candidate_prompt_path") != _candidate_prompt_relative()
        or type(root_device) is not int or root_device < 0
        or type(root_inode) is not int or root_inode < 0
        or value.get("max_agent_operations") != _MAX_AGENT_OPERATIONS
        or value.get("max_judge_operations") != _MAX_JUDGE_OPERATIONS
        or value.get("max_cost_microusd") != _MAX_COST_MICROUSD
        or value.get("max_infrastructure_failures") != _MAX_INFRASTRUCTURE_FAILURES
        or value.get("max_native_attempts") != _MAX_NATIVE_ATTEMPTS
        or value.get("execution_authorized") is not False
        or hmac.compare_digest(str(value["baseline_query_plan_sha256"]), str(value["candidate_query_plan_sha256"]))
        or hmac.compare_digest(str(value["baseline_variant_sha256"]), str(value["candidate_variant_sha256"]))
        or hmac.compare_digest(str(value["baseline_execution_config_sha256"]), str(value["candidate_execution_config_sha256"]))
        or not _is_sha256(digest) or not hmac.compare_digest(str(digest), _digest(value))
    ):
        raise ValueError
    _validate_tasks(value["tasks"], value)
    value["plan_sha256"] = digest
    _validate_plan_tree(path.parent, value)
    return value


def _read_authorization(path: Path, *, plan: Mapping[str, object]) -> dict[str, object]:
    canonical_plan = _read_plan_mapping(plan)
    value = _json_private(path)
    fields = {
        "schema", "plan_sha256", "diagnosis_bundle_sha256", "authorization_gate_report_sha256", "proposal_sha256", "finding_sha256", "scope_sha256",
        "source_lock_sha256", "selected_case_scope_sha256", "baseline_query_plan_sha256", "candidate_query_plan_sha256",
        "baseline_variant_sha256", "candidate_variant_sha256", "baseline_execution_config_sha256", "candidate_execution_config_sha256",
        "output_root_device", "output_root_inode", "max_agent_operations", "max_judge_operations", "max_cost_microusd",
        "max_infrastructure_failures", "max_native_attempts", "execution_authorized", "operator_approval_sha256", "authorization_sha256",
    }
    if type(value) is not dict or set(value) != fields:
        raise ValueError
    digest = value.pop("authorization_sha256", None)
    bound = (
        "plan_sha256", "diagnosis_bundle_sha256", "authorization_gate_report_sha256", "proposal_sha256", "finding_sha256", "scope_sha256",
        "source_lock_sha256", "selected_case_scope_sha256", "baseline_query_plan_sha256", "candidate_query_plan_sha256",
        "baseline_variant_sha256", "candidate_variant_sha256", "baseline_execution_config_sha256", "candidate_execution_config_sha256",
        "output_root_device", "output_root_inode", "max_agent_operations", "max_judge_operations", "max_cost_microusd",
        "max_infrastructure_failures", "max_native_attempts",
    )
    if (
        value.get("schema") != _AUTHORIZATION_SCHEMA
        or any(value.get(name) != canonical_plan[name] for name in bound)
        or value.get("execution_authorized") is not True
        or not _is_sha256(value.get("operator_approval_sha256"))
        or not _is_sha256(digest)
        or not hmac.compare_digest(str(digest), _digest(value))
    ):
        raise ValueError
    value["authorization_sha256"] = digest
    return value


def _execution_authorization(
    options: Mapping[str, str], *, plan: Mapping[str, object], output_root: Path,
    environment: Mapping[str, str] | None,
) -> dict[str, object]:
    if "--authorization-file" in options:
        return _read_authorization(_absolute_path(options["--authorization-file"]), plan=plan)
    source = os.environ if environment is None else environment
    if source.get("ASTERION_DCI_REQUIRE_EXECUTION_AUTHORIZATION", "") == "1":
        raise ValueError
    metadata = os.stat(output_root, follow_symlinks=False)
    return {
        "authorization_sha256": _digest(
            {
                "development": True,
                "plan_sha256": plan["plan_sha256"],
                "device": metadata.st_dev,
                "inode": metadata.st_ino,
            }
        )
    }


def _read_plan_mapping(value: Mapping[str, object]) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError
    encoded = _canonical_bytes(value)
    decoded = json.loads(encoded)
    # The in-memory plan is accepted only if it has the exact persisted shape.
    temporary = dict(decoded)
    _validate_plan_value(temporary)
    return temporary


def _validate_plan_value(value: dict[str, object]) -> None:
    # Shared reader logic without an unsafe temporary file.
    fields = set(value)
    if "plan_sha256" not in fields:
        raise ValueError
    digest = value.pop("plan_sha256")
    try:
        root_device = value.get("output_root_device")
        root_inode = value.get("output_root_inode")
        hashes = (
            "diagnosis_bundle_sha256", "authorization_gate_report_sha256", "proposal_sha256", "finding_sha256", "scope_sha256",
            "success_criteria_sha256", "stop_criteria_sha256", "budget_sha256", "source_lock_sha256",
            "selected_case_scope_sha256", "baseline_query_plan_sha256", "candidate_query_plan_sha256",
            "baseline_variant_sha256", "candidate_variant_sha256",
            "baseline_execution_config_sha256", "candidate_execution_config_sha256",
        )
        if (
            set(value) != {
                "schema", "diagnosis_bundle_sha256", "authorization_gate_report_sha256", "proposal_sha256", "finding_sha256", "scope_sha256",
                "success_criteria_sha256", "stop_criteria_sha256", "budget_sha256", "source_lock_path",
                "source_lock_sha256", "selected_case_scope_sha256", "baseline_query_plan_sha256",
                "candidate_query_plan_sha256", "baseline_variant_sha256", "candidate_variant_sha256",
                "baseline_execution_config_sha256", "candidate_execution_config_sha256",
                "candidate_prompt_path", "output_root_device", "output_root_inode",
                "max_agent_operations", "max_judge_operations", "max_cost_microusd", "max_infrastructure_failures",
                "max_native_attempts", "execution_authorized", "tasks",
            }
            or value.get("schema") != _PLAN_SCHEMA
            or any(not _is_sha256(value.get(name)) for name in hashes)
            or value.get("source_lock_path") != _SOURCE_LOCK_FILENAME
            or value.get("candidate_prompt_path") != _candidate_prompt_relative()
            or type(root_device) is not int or root_device < 0
            or type(root_inode) is not int or root_inode < 0
            or value.get("max_agent_operations") != _MAX_AGENT_OPERATIONS
            or value.get("max_judge_operations") != _MAX_JUDGE_OPERATIONS
            or value.get("max_cost_microusd") != _MAX_COST_MICROUSD
            or value.get("max_infrastructure_failures") != _MAX_INFRASTRUCTURE_FAILURES
            or value.get("max_native_attempts") != _MAX_NATIVE_ATTEMPTS
            or value.get("execution_authorized") is not False
            or hmac.compare_digest(str(value["baseline_query_plan_sha256"]), str(value["candidate_query_plan_sha256"]))
            or hmac.compare_digest(str(value["baseline_variant_sha256"]), str(value["candidate_variant_sha256"]))
            or hmac.compare_digest(str(value["baseline_execution_config_sha256"]), str(value["candidate_execution_config_sha256"]))
            or not _is_sha256(digest)
            or not hmac.compare_digest(str(digest), _digest(value))
        ):
            raise ValueError
        _validate_tasks(value.get("tasks"), value)
    finally:
        value["plan_sha256"] = digest


def _validate_tasks(raw: object, plan: Mapping[str, object]) -> None:
    fields = {
        "task_id", "dataset_id", "instance_selector", "variant_role", "query_plan_sha256", "variant_sha256",
        "execution_config_sha256", "selection_path",
        "selection_sha256", "selected_ids_sha256", "selected_case_sha256s", "case_limit", "native_attempt_limit",
        "max_judge_operations", "max_cost_microusd", "evidence_path", "receipt_path",
    }
    if type(raw) is not list or len(raw) != 8:
        raise ValueError
    expected: list[tuple[str, str]] = [(dataset, role) for dataset in _DATASETS for role in _ROLES]
    for item, (dataset_id, role) in zip(raw, expected, strict=True):
        if (
            type(item) is not dict or set(item) != fields
            or item.get("task_id") != f"{dataset_id}.{role}"
            or item.get("dataset_id") != dataset_id
            or item.get("instance_selector") != f"dci.{dataset_id}@1.0.0"
            or item.get("variant_role") != role
            or item.get("query_plan_sha256") != plan[f"{role}_query_plan_sha256"]
            or item.get("variant_sha256") != plan[f"{role}_variant_sha256"]
            or item.get("execution_config_sha256") != plan[f"{role}_execution_config_sha256"]
            or item.get("selection_path") != f"selections/{dataset_id}.json"
            or not _is_sha256(item.get("selection_sha256"))
            or not _is_sha256(item.get("selected_ids_sha256"))
            or type(item.get("selected_case_sha256s")) is not list
            or len(item["selected_case_sha256s"]) != 10
            or item["selected_case_sha256s"] != sorted(item["selected_case_sha256s"])
            or len(set(item["selected_case_sha256s"])) != 10
            or any(not _is_sha256(value) for value in item["selected_case_sha256s"])
            or item.get("case_limit") != 10 or item.get("native_attempt_limit") != 1
            or item.get("max_judge_operations") != 0 or item.get("max_cost_microusd") != _TASK_MAX_COST_MICROUSD
            or item.get("evidence_path") != f"evidence/{dataset_id}/{role}"
            or item.get("receipt_path") != f"receipts/{dataset_id}.{role}"
        ):
            raise ValueError


def _validate_plan_tree(root: Path, plan: Mapping[str, object]) -> None:
    """Close an immutable plan over its published private children."""

    _private_directory(root)
    if _file_sha256(root / str(plan["source_lock_path"])) != plan["source_lock_sha256"]:
        raise ValueError
    from asterion.capabilities.dci.implementation.research.query_planning import (
        validate_materialized_query_planning_prompt,
    )

    validate_materialized_query_planning_prompt(
        DECOMPOSED_QUERY_PLAN, root / str(plan["candidate_prompt_path"])
    )
    selections: dict[str, dict[str, object]] = {}
    for dataset in _DATASETS:
        raw = _json_private(root / "selections" / f"{dataset}.json")
        if type(raw) is not dict:
            raise ValueError
        selections[dataset] = _selection(raw)
    if _selected_scope(selections) != plan["selected_case_scope_sha256"]:
        raise ValueError
    tasks = plan.get("tasks")
    if type(tasks) is not list:
        raise ValueError
    for task in tasks:
        if type(task) is not dict:
            raise ValueError
        dataset_id = task.get("dataset_id")
        if type(dataset_id) is not str:
            raise ValueError
        selection = selections.get(dataset_id)
        if selection is None or any(
            task[name] != selection[name]
            for name in ("selection_sha256", "selected_ids_sha256", "selected_case_sha256s")
        ):
            raise ValueError


def _query_decomposition_proposal(diagnosis: object, digest: str) -> Proposal:
    proposals = getattr(diagnosis, "proposals", None)
    findings = getattr(diagnosis, "findings", None)
    if type(proposals) is not tuple or type(findings) is not tuple:
        raise ValueError
    matches = [proposal for proposal in proposals if hmac.compare_digest(proposal.proposal_sha256, digest)]
    if len(matches) != 1:
        raise ValueError
    proposal = matches[0]
    sole = _diagnosis_digest("proposal-sole-variable", "retrieval-query-planning")
    expected = (
        _diagnosis_digest("proposal-change", {"change": "retrieval-query-decomposition", "sole_variable_sha256": sole}),
        _diagnosis_digest("proposal-success", {"mean_ndcg_gain_microunits": 50_000, "maximum_cost_or_time_increase_microunits": 250_000}),
        _diagnosis_digest("proposal-budget", {"agent_operations": 80, "max_cost_microusd": 16_000_000}),
    )
    coverage = _coverage_proposal(proposals)
    expected_stop = _diagnosis_digest(
        "proposal-stop", {"prerequisite_proposal_sha256": coverage.proposal_sha256}
    )
    if (
        proposal.finding_sha256 not in {item.finding_sha256 for item in findings}
        or coverage.finding_sha256 not in {item.finding_sha256 for item in findings}
        or (proposal.change_sha256, proposal.success_criteria_sha256, proposal.budget_sha256) != expected
        or proposal.stop_criteria_sha256 != expected_stop
    ):
        raise ValueError
    return proposal


def _coverage_proposal(proposals: tuple[Proposal, ...]) -> Proposal:
    sole = _diagnosis_digest(
        "proposal-sole-variable", "trajectory-coverage-instrumentation-only"
    )
    expected = (
        _diagnosis_digest("proposal-change", {"change": "coverage-instrumentation", "sole_variable_sha256": sole}),
        _diagnosis_digest("proposal-success", {"trajectory_coverage_recorded": True}),
        _diagnosis_digest("proposal-stop", {"infrastructure_failures": 2}),
        _diagnosis_digest("proposal-budget", {"agent_operations": 50, "max_cost_microusd": 5_000_000}),
    )
    matches = [
        proposal for proposal in proposals
        if (proposal.change_sha256, proposal.success_criteria_sha256, proposal.stop_criteria_sha256, proposal.budget_sha256) == expected
    ]
    if len(matches) != 1:
        raise ValueError
    return matches[0]


def _selection(value: Mapping[str, object]) -> dict[str, object]:
    fields = {"schema", "dataset_id", "dataset_source_sha256", "selected_case_sha256s", "selected_ids_sha256", "selection_sha256"}
    if type(value) is not dict or set(value) != fields or value.get("schema") != _SELECTION_SCHEMA:
        raise ValueError
    dataset_id = value.get("dataset_id")
    cases = value.get("selected_case_sha256s")
    digest = value.get("selection_sha256")
    unsigned = {key: item for key, item in value.items() if key != "selection_sha256"}
    if (
        dataset_id not in _DATASETS or not _is_sha256(value.get("dataset_source_sha256"))
        or type(cases) is not list or len(cases) != 10 or cases != sorted(cases) or len(set(cases)) != 10
        or any(not _is_sha256(item) for item in cases)
        or value.get("selected_ids_sha256") != _digest(cases)
        or not _is_sha256(digest) or not hmac.compare_digest(str(digest), _digest(unsigned))
    ):
        raise ValueError
    return dict(value)


def _selected_scope(selections: Mapping[str, Mapping[str, object]]) -> str:
    return _digest([
        {"dataset_id": dataset, "selected_case_sha256s": selections[dataset]["selected_case_sha256s"]}
        for dataset in _DATASETS
    ])


def _proposal_scope(selections: Mapping[str, Mapping[str, object]]) -> str:
    scopes = tuple(
        (
            dataset,
            _diagnosis_digest(
                "proposal-dataset-case-scope",
                {"dataset_id": dataset, "case_sha256s": selections[dataset]["selected_case_sha256s"]},
            ),
        )
        for dataset in _DATASETS
    )
    by_dataset = dict(scopes)
    return _diagnosis_digest(
        "proposal-case-scope",
        {
            "datasets": [
                {
                    "dataset_id": dataset,
                    "case_count": 10,
                    "case_scope_sha256": by_dataset[dataset],
                    "role": "bright-target",
                }
                for dataset in _DATASETS
            ],
            "purpose": "paired-bright",
            "total_case_count": 40,
        },
    )


def _candidate_prompt_relative() -> str:
    contract = resolve_query_planning_contract(DECOMPOSED_QUERY_PLAN)
    return f"prompts/query-planning-{query_planning_contract_sha256(contract)}.txt"


def _read_source(path: Path) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_DOCUMENT_BYTES:
            raise ValueError
        data = os.read(descriptor, _MAX_DOCUMENT_BYTES + 1)
        after = os.fstat(descriptor)
        if len(data) > _MAX_DOCUMENT_BYTES or (before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size):
            raise ValueError
        return data
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _json_private(path: Path) -> object:
    try:
        encoded = read_private_file(path, _MAX_DOCUMENT_BYTES)
        value = json.loads(encoded, object_pairs_hook=_unique_object)
        if encoded != _canonical_bytes(value):
            raise ValueError
        return value
    except Exception:
        raise ValueError from None


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(read_private_file(path, _MAX_DOCUMENT_BYTES)).hexdigest()


def _private_directory(path: Path) -> None:
    metadata = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700 or metadata.st_uid != os.getuid() or path.is_symlink():
        raise ValueError


def _owned_readonly_directory(path: Path) -> None:
    """Accept native output roots that expose names but cannot be modified."""

    metadata = os.stat(path, follow_symlinks=False)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or path.is_symlink()
    ):
        raise ValueError


def _absolute_path(value: str) -> Path:
    path = Path(value)
    if type(value) is not str or "\x00" in value or not path.is_absolute() or path != path.resolve():
        raise ValueError
    return path


def _gate_report_path(value: str) -> Path:
    path = _absolute_path(value)
    if path.name != AUTHORIZATION_GATE_REPORT_FILENAME:
        raise ValueError
    return path


def _diagnosis_report_path(value: str) -> Path:
    path = _absolute_path(value)
    if path.name != DCI_DIAGNOSIS_REPORT_FILENAME:
        raise ValueError
    return path


def _operator_root(value: str) -> Path:
    from asterion.applications.dci_agent_lite.pathlight_cli import _operator_root as validate
    return validate(value)


def _create_staging_root(root: Path) -> Path:
    from asterion.applications.dci_agent_lite.pathlight_cli import _create_staging_root as create
    return create(root)


def _publish_staged_tree(root: Path, staging: Path) -> None:
    from asterion.applications.dci_agent_lite.pathlight_cli import _publish_staged_tree as publish
    publish(root, staging)


def _cleanup_staging_tree(root: Path, staging: Path) -> None:
    from asterion.applications.dci_agent_lite.pathlight_cli import _cleanup_staging_tree as cleanup
    cleanup(root, staging)


def _exact_options(arguments: tuple[str, ...], names: set[str]) -> dict[str, str]:
    if len(arguments) != len(names) * 2:
        raise ValueError
    values: dict[str, str] = {}
    for index in range(0, len(arguments), 2):
        name, value = arguments[index:index + 2]
        if type(name) is not str or type(value) is not str or name not in names or name in values or not value:
            raise ValueError
        values[name] = value
    if set(values) != names:
        raise ValueError
    return values


def _optional_options(
    arguments: tuple[str, ...], *, required: set[str], optional: set[str]
) -> dict[str, str]:
    if len(arguments) % 2:
        raise ValueError
    values: dict[str, str] = {}
    for index in range(0, len(arguments), 2):
        name, value = arguments[index], arguments[index + 1]
        if (
            type(name) is not str
            or type(value) is not str
            or name not in required | optional
            or name in values
            or not value
        ):
            raise ValueError
        values[name] = value
    if not required.issubset(values):
        raise ValueError
    return values


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _diagnosis_digest(domain: str, value: object) -> str:
    return hashlib.sha256(json.dumps({"domain": f"asterion.dci.pathlight.diagnosis/{domain}/v1", "value": value}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


__all__ = ("PLAN_FILENAME", "main", "read_optimization_authorization", "read_optimization_plan")
