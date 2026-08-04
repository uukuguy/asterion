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
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

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
from asterion.pathlight.experiment import Variant


PLAN_FILENAME = "pathlight-bright-optimization.json"
_PLAN_SCHEMA = "asterion.dci.pathlight.bright-optimization-plan/v1"
_AUTHORIZATION_SCHEMA = "asterion.dci.pathlight.bright-optimization-authorization/v1"
_SELECTION_SCHEMA = "asterion.dci.pathlight.bright-selected-cases/v1"
_SOURCE_LOCK_FILENAME = "pathlight-bright-optimization-source-lock.json"
_ERROR = "asterion-dci: command failed\n"
_MAX_DOCUMENT_BYTES = 1 << 20
_MAX_AGENT_OPERATIONS = 80
_MAX_JUDGE_OPERATIONS = 0
_MAX_COST_MICROUSD = 8_000_000
_MAX_INFRASTRUCTURE_FAILURES = 2
_MAX_NATIVE_ATTEMPTS = 1
_DATASETS = (
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
)
_ROLES = ("baseline", "candidate")


def main(
    arguments: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
    repo_root: Path,
    env_file: Path | None,
    environment: Mapping[str, str] | None,
    package_sources: Sequence[object] | None = None,
) -> int:
    """Run only a provider-free Bright optimization command."""

    del env_file  # Preparation is intentionally unable to read dotenv files.
    try:
        values = tuple(arguments)
        if not values:
            raise ValueError
        if values[0] == "prepare":
            result = _prepare(
                values[1:],
                repo_root=repo_root,
                environment=environment,
                package_sources=package_sources,
            )
        elif values[0] == "status":
            result = _status(values[1:])
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
    options = _exact_options(
        arguments,
        {
            "--diagnosis-file",
            "--diagnosis-report-file",
            "--gate-report-file",
            "--proposal-sha256",
            "--output-root",
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
        selections = _prepare_selections(staging, config)
        if proposal.scope_sha256 != _proposal_scope(selections):
            raise ValueError
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


def _prepare_selections(root: Path, config: DciOperatorConfig) -> dict[str, dict[str, object]]:
    selections: dict[str, dict[str, object]] = {}
    for dataset_id in _DATASETS:
        source = _read_source(Path(config.benchmark_inputs.dataset_roots[dataset_id]))
        rows = load_bright_benchmark_rows_bytes(source)
        cases = tuple(sorted((_recovery_digest("query-id", row.query_id) for row in rows)))[:10]
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
                    "max_cost_microusd": 1_000_000,
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
    _private_directory(receipts)
    if any(receipts.iterdir()):
        raise ValueError
    return {
        "status": "prepared",
        "completed_agent_operations": 0,
        "completed_judge_operations": 0,
        "consumed_cost_microusd": 0,
        "infrastructure_failure_count": 0,
        "max_agent_operations": _MAX_AGENT_OPERATIONS,
        "max_judge_operations": _MAX_JUDGE_OPERATIONS,
        "max_cost_microusd": _MAX_COST_MICROUSD,
        "plan_sha256": plan["plan_sha256"],
    }


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
            or item.get("max_judge_operations") != 0 or item.get("max_cost_microusd") != 1_000_000
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
        _diagnosis_digest("proposal-budget", {"agent_operations": 80, "max_cost_microusd": 8_000_000}),
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
