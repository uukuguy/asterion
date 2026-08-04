"""Provider-free Bright A/B evidence projection.

The receipt is deliberately not an evidence source here.  Callers provide the
validated receipt chain together with the native runs re-read by Task 6; this
module derives every case score and every aggregate from those native runs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from asterion.capabilities.dci.implementation.pathlight.conversion import load_paper_reference
from asterion.capabilities.dci.implementation.pathlight.recovery import DciRecoveredRun
from asterion.pathlight.diagnosis import DiagnosisBundle
from asterion.pathlight.evaluation import EvaluationBundle, EvaluationRecord, MetricContract
from asterion.pathlight.experiment import (
    CaseTrial,
    DatasetSnapshot,
    EvaluatorContract,
    ExperimentBundle,
    ExperimentPlan,
    Variant,
)
from asterion.pathlight.optimization import (
    Decision,
    OptimizationBundle,
    OptimizationCriteria,
    OptimizationTrial,
    TrialHistory,
)
from asterion.pathlight._private_file import read_private_file
from asterion.workflow_evidence import read_workflow_observation_bundle
from asterion.capabilities.dci.implementation.pathlight.recovery import _domain_digest


_DATASETS = (
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
)
BRIGHT_OPTIMIZATION_CRITERIA = OptimizationCriteria(50_000, 250_000, 250_000)


class DciBrightOptimizationError(Exception):
    """A body-free DCI Bright finalization failure."""


def _digest(value: object) -> str:
    return hashlib.sha256(
        (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()


def _evaluation_bundle_digest(metric: MetricContract, evaluations: Sequence[EvaluationRecord]) -> str:
    return hashlib.sha256(json.dumps(
        {"schema": "asterion.pathlight-evaluations/v1", "metric_contracts": [metric.to_mapping()], "evaluations": [value.to_mapping() for value in evaluations]},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class BrightNativeBatch:
    """A receipt-bound native batch, after Task 6 re-read it from disk."""

    dataset_id: str
    variant_role: str
    receipt: Mapping[str, object]
    recovered_run: DciRecoveredRun | None
    workflow_bundle_sha256s: tuple[str, ...]
    native_root: Path | None = None


@dataclass(frozen=True, slots=True)
class BrightOptimizationClosure:
    experiment: ExperimentBundle
    evaluations: EvaluationBundle
    optimization: OptimizationBundle
    diagnosis: DiagnosisBundle
    evidence_gaps: tuple[str, ...]
    dataset_item_sha256s_by_dataset: tuple[tuple[str, tuple[str, ...]], ...] = ()


def read_native_case_lineage(native_root: Path, expected_dataset_id: str) -> dict[str, str]:
    """Read the private result-row -> native workflow trace join.

    Query identifiers never escape this function.  The benchmark's authoritative
    layout is ``<query_id>/<native_generation>/workflow-evidence.json`` (not an
    assumed positional directory), so a reordered result file cannot remap a
    score to a different trace.
    """

    try:
        if not isinstance(native_root, Path) or not native_root.is_absolute() or expected_dataset_id not in _DATASETS:
            raise ValueError
        run = DciRecoveredRun  # force only the safe reader below to establish the native root
        del run
        # Recovery validates artifact digests, result schema/status and exactly
        # the 10 case identities before any workflow file is considered.
        from asterion.capabilities.dci.implementation.pathlight.recovery import read_completed_dci_run
        recovered = read_completed_dci_run(native_root, expected_dataset_id)
        encoded = read_private_file(native_root / "results.jsonl", 1 << 20)
        lines = tuple(line for line in encoded.splitlines() if line)
        if len(lines) != 10:
            raise ValueError
        rows = tuple(json.loads(line) for line in lines)
        if any(type(row) is not dict for row in rows):
            raise ValueError
        query_ids: list[str] = []
        for row in rows:
            assert type(row) is dict
            query_id, status, generation = row.get("query_id"), row.get("status"), row.get("native_generation")
            if type(query_id) is not str or not query_id or "/" in query_id or query_id in {".", ".."} or status != "completed" or type(generation) is not str or not generation.startswith("native-generation-") or "/" in generation:
                raise ValueError
            query_ids.append(query_id)
        if tuple(query_ids) != tuple(sorted(query_ids)) or len(set(query_ids)) != 10:
            raise ValueError
        recovered_items = {case.dataset_item_sha256 for case in recovered.cases if case.run_status == "completed"}
        if len(recovered_items) != 10:
            raise ValueError
        result: dict[str, str] = {}
        for row in rows:
            assert type(row) is dict
            query_id = row["query_id"]
            generation = row["native_generation"]
            assert type(query_id) is str and type(generation) is str
            item = _domain_digest("query-id", query_id)
            workflow_path = native_root / query_id / generation / "workflow-evidence.json"
            bundle = read_workflow_observation_bundle(workflow_path)
            if len(bundle.records) != 1 or len(bundle.pathlight_traces) != 1:
                raise ValueError
            record, trace = bundle.records[0], bundle.pathlight_traces[0]
            if record.get("terminal_status") != "completed" or type(trace.get("trace_sha256")) is not str:
                raise ValueError
            trace_sha256 = trace["trace_sha256"]
            if not isinstance(trace_sha256, str):
                raise ValueError
            if len(trace_sha256) != 64 or item in result or trace_sha256 in result.values():
                raise ValueError
            result[item] = trace_sha256
        if set(result) != recovered_items:
            raise ValueError
        return result
    except Exception:
        raise DciBrightOptimizationError("DCI Bright optimization finalization is invalid") from None


def finalize_bright_optimization(
    *,
    plan: Mapping[str, object],
    authorization: Mapping[str, object],
    receipts: Sequence[Mapping[str, object]],
    native_batches: Sequence[BrightNativeBatch],
    diagnosis: DiagnosisBundle,
) -> BrightOptimizationClosure:
    """Derive the immutable 40-item paired Bright closure from native evidence.

    Any missing or invalid batch becomes an incomplete history.  It is never
    converted into a synthetic score or silently removed from the denominator.
    """

    try:
        _validate_inputs(plan, authorization, receipts, native_batches, diagnosis)
        variants = _variants(str(plan["baseline_query_plan_sha256"]), str(plan["candidate_query_plan_sha256"]))
        by_dataset_selected = _selected_by_dataset(plan)
        selected = tuple(sorted(_scoped_item(dataset, item) for dataset, values in by_dataset_selected.items() for item in values))
        by_task = {(batch.dataset_id, batch.variant_role): batch for batch in native_batches}
        datasets = _datasets(by_task)
        composite = DatasetSnapshot(
            _digest({"contract": "bright-40/v1"}),
            _digest({"dataset_snapshot_sha256s": [item.dataset_snapshot_sha256 for item in datasets]}),
            40,
            "1.0.0",
        )
        metric = MetricContract("ndcg-at-10", "microunits", True, "1.0.0")
        evaluator = EvaluatorContract(
            metric.metric_contract_sha256, "recovered", _digest("bright-native-evaluator"),
            _digest("bright-native-input"), _digest("bright-native-output"), _digest("bright-native-failure"), "1.0.0",
        )
        plan_value = ExperimentPlan(
            composite.dataset_snapshot_sha256,
            _digest({"selected_case_sha256s": selected}),
            variants["baseline"].variant_sha256,
            (variants["candidate"].variant_sha256,),
            _digest({"assignment": "paired", "selected_case_sha256s": selected}),
            (evaluator.evaluator_contract_sha256,),
            str(plan["budget_sha256"]), str(plan["stop_criteria_sha256"]),
            str(authorization["authorization_sha256"]),
        )
        records, cases, trials, gaps = _case_projection(
            by_task, by_dataset_selected, variants, plan_value, composite, metric
        )
        aggregate = _dataset_aggregates(by_task, datasets, metric)
        experiment = ExperimentBundle.build(
            datasets=(*datasets, composite), evaluators=(evaluator,), variants=tuple(variants.values()),
            plans=(plan_value,), trials=cases, evaluations=(*records, *aggregate),
        )
        all_evaluations = tuple(sorted((*records, *aggregate), key=lambda value: value.evaluation_sha256))
        evaluations = EvaluationBundle(
            (metric,), all_evaluations,
            _evaluation_bundle_digest(metric, all_evaluations),
        )
        history = (
            TrialHistory.build(
                experiment_plan=plan_value, baseline_variant=variants["baseline"], candidate_variant=variants["candidate"],
                trials=trials, evaluations=records, expected_dataset_item_sha256s=selected,
            ) if records else _incomplete_history(plan_value, variants, selected, trials, metric)
        )
        decision = Decision.derive(
            proposal_sha256=str(plan["proposal_sha256"]), finding_sha256=str(plan["finding_sha256"]),
            history=history, criteria=BRIGHT_OPTIMIZATION_CRITERIA,
            operator_approval_sha256=str(authorization["operator_approval_sha256"]),
        )
        diagnosis = DiagnosisBundle.build(
            experiment_bundle_sha256s=(*diagnosis.experiment_bundle_sha256s, experiment.bundle_sha256),
            evaluation_sha256s=(*diagnosis.evaluation_sha256s, *(item.evaluation_sha256 for item in all_evaluations)),
            findings=diagnosis.findings, proposals=diagnosis.proposals,
        )
        traces = tuple(sorted({case.trace_sha256 for case in cases}))
        optimization = OptimizationBundle.build(
            experiment_bundle_sha256s=(experiment.bundle_sha256,), evaluation_bundle_sha256s=(evaluations.bundle_sha256,),
            diagnosis_bundle_sha256s=(diagnosis.bundle_sha256,), trace_sha256s=traces,
            trials=trials, histories=(history,), decisions=(decision,),
        )
        return BrightOptimizationClosure(
            experiment, evaluations, optimization, diagnosis, tuple(sorted(gaps)),
            tuple((dataset, tuple(_scoped_item(dataset, item) for item in by_dataset_selected[dataset])) for dataset in _DATASETS),
        )
    except Exception:
        raise DciBrightOptimizationError("DCI Bright optimization finalization is invalid") from None


def render_bright_optimization_chinese(closure: BrightOptimizationClosure) -> str:
    """Render only aggregate, public-safe Bright decision context in Chinese."""

    history = closure.optimization.histories[0]
    decision = closure.optimization.decisions[0]
    rows: list[str] = [
        "# Bright 查询分解优化诊断",
        "",
        "范围：40 条基线 + 40 条候选；每个数据集固定 10 个相同条目。",
        f"Decision：{decision.result}（{decision.reason}）。",
        "本报告描述已注册比较，不主张查询分解导致任何结果。",
        "",
        "## 数据集结果",
    ]
    by_dataset: dict[str, dict[str, list[int]]] = {name: {"baseline": [], "candidate": []} for name in _DATASETS}
    # Dataset identity is held only in public data object ordering; report omits case identities.
    for trial in closure.optimization.trials:
        for dataset_id, index in dict(closure.dataset_item_sha256s_by_dataset).items():
            if trial.dataset_item_sha256 in index and trial.status == "completed":
                evaluation = next(value for value in closure.evaluations.evaluations if value.evaluation_sha256 == trial.evaluation_sha256)
                assert evaluation.value_microunits is not None
                by_dataset[dataset_id][trial.variant_role].append(evaluation.value_microunits)
    for dataset_id in _DATASETS:
        baseline = by_dataset[dataset_id]["baseline"]
        candidate = by_dataset[dataset_id]["candidate"]
        if len(baseline) == len(candidate) == 10:
            left, right = sum(baseline) // 10, sum(candidate) // 10
            rows.append(f"- {dataset_id}：baseline {left}，candidate {right}，delta {right - left} 微单位。")
        else:
            rows.append(f"- {dataset_id}：证据不完整，未计算比较均值。")
    rows.extend([
        "", "## 成本与时间",
        f"- baseline 成本 {history.baseline_agent_cost_microusd} 微美元；candidate 成本 {history.candidate_agent_cost_microusd} 微美元；增幅 {history.cost_increase_microunits} 微单位。",
        f"- baseline 时间 {history.baseline_elapsed_ns} ns；candidate 时间 {history.candidate_elapsed_ns} ns；增幅 {history.time_increase_microunits} 微单位。",
        f"- 状态计数：baseline 完成/失败/取消 {history.baseline_completed_count}/{history.baseline_failed_count}/{history.baseline_cancelled_count}；candidate 完成/失败/取消 {history.candidate_completed_count}/{history.candidate_failed_count}/{history.candidate_cancelled_count}。",
        "", "## 证据限制与下一步",
        "- 每个 completed case 已由私有 native case-lineage reader 将 canonical result row、opaque dataset item 与唯一 workflow trace 闭合；原始 query identifier 不会出现在报告中。",
        f"- 证据缺口：{', '.join(closure.evidence_gaps) if closure.evidence_gaps else '无额外缺口'}。",
        "- 历史 full Bright 分数仅为论文来源的 reference-only 背景，配置、范围与本次 4×10 实验不同，不能作为论文复现或可比较结果。",
        "- 最小下一步：为工作流公开协议增加经验证的 case item/evaluation lineage 后，再执行同一预注册范围的独立复核。",
    ])
    for dataset_id in _DATASETS:
        reference = load_paper_reference(dataset_id)
        rows.append(f"- 论文背景 {dataset_id}：nDCG@10 {reference.value_microunits} 微单位（reference-only，非可比）。")
    return "\n".join(rows) + "\n"


def _validate_inputs(plan: Mapping[str, object], authorization: Mapping[str, object], receipts: Sequence[Mapping[str, object]], batches: Sequence[BrightNativeBatch], diagnosis: DiagnosisBundle) -> None:
    required_plan = {"plan_sha256", "proposal_sha256", "finding_sha256", "budget_sha256", "stop_criteria_sha256", "baseline_query_plan_sha256", "candidate_query_plan_sha256", "tasks"}
    if not isinstance(plan, Mapping) or not required_plan.issubset(plan) or not isinstance(authorization, Mapping) or type(diagnosis) is not DiagnosisBundle:
        raise ValueError
    if len(receipts) > 8 or len(batches) != len(receipts):
        raise ValueError
    tasks = plan["tasks"]
    if type(tasks) is not list or len(tasks) != 8:
        raise ValueError
    expected = {(dataset, role) for dataset in _DATASETS for role in ("baseline", "candidate")}
    if {(batch.dataset_id, batch.variant_role) for batch in batches} != {(str(receipt.get("task_id", "")).rsplit(".", 1)[0], str(receipt.get("task_id", "")).rsplit(".", 1)[-1]) for receipt in receipts}:
        raise ValueError
    if any((batch.dataset_id, batch.variant_role) not in expected for batch in batches):
        raise ValueError


def _selected_by_dataset(plan: Mapping[str, object]) -> dict[str, tuple[str, ...]]:
    tasks = plan["tasks"]
    assert type(tasks) is list
    result: dict[str, tuple[str, ...]] = {}
    for dataset_id in _DATASETS:
        matching = [task for task in tasks if type(task) is dict and task.get("dataset_id") == dataset_id]
        if len(matching) != 2 or {task.get("variant_role") for task in matching} != {"baseline", "candidate"}:
            raise ValueError
        baseline = next(task for task in matching if task["variant_role"] == "baseline")
        candidate = next(task for task in matching if task["variant_role"] == "candidate")
        items = baseline.get("selected_case_sha256s")
        if type(items) is not list or items != candidate.get("selected_case_sha256s") or len(items) != 10 or any(type(item) is not str or len(item) != 64 for item in items):
            raise ValueError
        result[dataset_id] = tuple(sorted(items))
    values = tuple(item for items in result.values() for item in items)
    if len(values) != 40:
        raise ValueError
    return result


def _variants(baseline_prompt: str, candidate_prompt: str) -> dict[str, Variant]:
    common = {name: _digest(f"asterion-safe/pi:{name}") for name in ("assembly", "package-set", "implementation", "runtime", "model", "toolset", "policy")}
    def make(prompt: str) -> Variant:
        return Variant(common["assembly"], common["package-set"], common["implementation"], common["runtime"], common["model"], common["toolset"], prompt, common["policy"], _digest({"schema": "asterion.dci.pathlight.query-plan-change/v1", "query_plan_sha256": prompt}))
    value = {"baseline": make(baseline_prompt), "candidate": make(candidate_prompt)}
    if value["baseline"].variant_sha256 == value["candidate"].variant_sha256:
        raise ValueError
    return value


def _datasets(batches: Mapping[tuple[str, str], BrightNativeBatch]) -> tuple[DatasetSnapshot, ...]:
    result: list[DatasetSnapshot] = []
    for dataset_id in _DATASETS:
        runs = []
        for role in ("baseline", "candidate"):
            batch = batches.get((dataset_id, role))
            runs.append(None if batch is None else batch.recovered_run)
        usable = [run for run in runs if run is not None]
        content = usable[0].dataset_snapshot_sha256 if usable else _digest({"missing": dataset_id})
        if any(run.dataset_snapshot_sha256 != content for run in usable):
            raise ValueError
        result.append(DatasetSnapshot(_digest({"dataset_id": dataset_id, "contract": "bright/v1"}), _digest({"native": content}), 10, "1.0.0"))
    return tuple(sorted(result, key=lambda item: item.dataset_snapshot_sha256))


def _case_projection(batches: Mapping[tuple[str, str], BrightNativeBatch], selected_by_dataset: Mapping[str, tuple[str, ...]], variants: Mapping[str, Variant], plan: ExperimentPlan, composite: DatasetSnapshot, metric: MetricContract) -> tuple[tuple[EvaluationRecord, ...], tuple[CaseTrial, ...], tuple[OptimizationTrial, ...], set[str]]:
    records: list[EvaluationRecord] = []
    cases: list[CaseTrial] = []
    trials: list[OptimizationTrial] = []
    gaps: set[str] = set()
    for dataset_id in _DATASETS:
        for role in ("baseline", "candidate"):
            batch = batches.get((dataset_id, role))
            if batch is None or batch.recovered_run is None or batch.receipt.get("native_evidence_state") != "complete":
                gaps.add("missing-native-evidence")
                for raw_item in selected_by_dataset[dataset_id]:
                    item = _scoped_item(dataset_id, raw_item)
                    unavailable_trace = _digest({"unavailable-native-case": plan.experiment_plan_sha256, "dataset_item_sha256": item, "variant_role": role})
                    case_trial = CaseTrial(plan.experiment_plan_sha256, item, variants[role].variant_sha256, unavailable_trace, (), "missing", ("trace-graph",))
                    cases.append(case_trial)
                    trials.append(OptimizationTrial(plan.experiment_plan_sha256, case_trial.case_trial_sha256, item, role, variants[role].variant_sha256, None, None, "failed", "mapping", 0, 0, 0, 0))
                continue
            run = batch.recovered_run
            if run.metric_name != "ndcg-at-10" or run.selected_count != 10 or len(run.cases) != 10:
                raise ValueError
            expected_raw_items = selected_by_dataset[dataset_id]
            cases_by_item = {case.dataset_item_sha256: case for case in run.cases}
            if set(cases_by_item) != set(expected_raw_items):
                raise ValueError
            if batch.native_root is None:
                gaps.add("missing-native-case-lineage")
                continue
            native_traces = read_native_case_lineage(batch.native_root, dataset_id)
            if set(native_traces) != set(expected_raw_items):
                raise ValueError
            receipt = batch.receipt
            values = _allocate(_receipt_int(receipt, "cost_microusd"), expected_raw_items), _allocate(_receipt_int(receipt, "input_tokens"), expected_raw_items), _allocate(_receipt_int(receipt, "output_tokens"), expected_raw_items), _allocate(_receipt_int(receipt, "elapsed_ns"), expected_raw_items)
            for raw_item, cost, input_tokens, output_tokens, elapsed in zip(expected_raw_items, *values, strict=True):
                item = _scoped_item(dataset_id, raw_item)
                case = cases_by_item[raw_item]
                trace = native_traces[raw_item]
                evaluation = EvaluationRecord(trace, metric.metric_contract_sha256, composite.dataset_snapshot_sha256, plan.scope_sha256, case.metric_value_microunits, 1, 1, "recovered")
                case_trial = CaseTrial(plan.experiment_plan_sha256, item, variants[role].variant_sha256, trace, (evaluation.evaluation_sha256,), "observed", tuple(sorted(set(run.missing_evidence) - {"model-request-boundary", "compaction-request-only"})))
                records.append(evaluation)
                cases.append(case_trial)
                trials.append(OptimizationTrial(plan.experiment_plan_sha256, case_trial.case_trial_sha256, item, role, variants[role].variant_sha256, trace, evaluation.evaluation_sha256, "completed", None, cost, input_tokens, output_tokens, elapsed))
            if not batch.workflow_bundle_sha256s:
                gaps.add("missing-workflow-bundle")
    return tuple(records), tuple(cases), tuple(trials), gaps


def _incomplete_history(plan: ExperimentPlan, variants: Mapping[str, Variant], selected: tuple[str, ...], trials: Sequence[OptimizationTrial], metric: MetricContract) -> TrialHistory:
    roles = {role: tuple(sorted(trial.optimization_trial_sha256 for trial in trials if trial.variant_role == role)) for role in ("baseline", "candidate")}
    return TrialHistory(
        plan.experiment_plan_sha256, variants["baseline"].variant_sha256, variants["candidate"].variant_sha256,
        plan.dataset_snapshot_sha256, plan.scope_sha256, metric.metric_contract_sha256, plan.evaluator_contract_sha256s[0],
        plan.assignment_sha256, plan.stop_criteria_sha256, plan.budget_sha256, selected,
        roles["baseline"], roles["candidate"],
        0, len(roles["baseline"]), 0, 0, len(roles["candidate"]), 0,
        None, None, None, 0, 0, None, 0, 0, 0, 0, 0, 0, None, "incomplete",
    )


def _allocate(total: int, items: tuple[str, ...]) -> tuple[int, ...]:
    if type(total) is not int or total < 0 or len(items) != 10:
        raise ValueError
    quotient, remainder = divmod(total, len(items))
    return tuple(quotient + int(index < remainder) for index in range(len(items)))


def _scoped_item(dataset_id: str, item: str) -> str:
    return _digest({"dataset_id": dataset_id, "selected_case_sha256": item})


def _receipt_int(receipt: Mapping[str, object], name: str) -> int:
    value = receipt.get(name)
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _dataset_aggregates(batches: Mapping[tuple[str, str], BrightNativeBatch], datasets: tuple[DatasetSnapshot, ...], metric: MetricContract) -> tuple[EvaluationRecord, ...]:
    result: list[EvaluationRecord] = []
    dataset_by_native = {dataset.content_sha256: dataset for dataset in datasets}
    for batch in batches.values():
        run = batch.recovered_run
        if run is None:
            continue
        dataset = dataset_by_native.get(_digest({"native": run.dataset_snapshot_sha256}))
        if dataset is None:
            raise ValueError
        result.append(EvaluationRecord(_digest({"aggregate": run.recovered_run_sha256}), metric.metric_contract_sha256, dataset.dataset_snapshot_sha256, _digest({"dataset": batch.dataset_id}), run.metric_value_microunits, 10, 10, "recovered"))
    return tuple(result)


__all__ = (
    "BRIGHT_OPTIMIZATION_CRITERIA", "BrightNativeBatch", "BrightOptimizationClosure",
    "DciBrightOptimizationError", "finalize_bright_optimization", "render_bright_optimization_chinese",
)
