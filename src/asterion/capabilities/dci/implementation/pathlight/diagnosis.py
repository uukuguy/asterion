"""Closed, deterministic differential diagnosis for recovered DCI batches.

The analyzer accepts only the six known paper-main cohorts.  It deliberately
retains aggregate identities and fixed-point measurements, never private case
text, paths, runtime configuration, or provider/model names.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from asterion.capabilities.dci.implementation.pathlight.conversion import (
    DciReferenceComparison,
    load_paper_reference,
    recovered_run_to_experiment,
)
from asterion.capabilities.dci.implementation.pathlight.recovery import (
    DciRecoveredCase,
    DciRecoveredRun,
    DciRecoveredVariant,
    validate_recovered_run,
)
from asterion.pathlight.diagnosis import DiagnosisBundle, Finding, Proposal
from asterion.pathlight.experiment import ExperimentBundle


_ERROR = "DCI diagnosis is invalid"
_MAX_INT = (1 << 63) - 1
_REQUIRED: dict[str, tuple[Literal["ir", "qa"], Literal["ndcg-at-10", "accuracy"], int]] = {
    "beir.scifact": ("ir", "ndcg-at-10", 300),
    "bright.biology": ("ir", "ndcg-at-10", 103),
    "bright.earth-science": ("ir", "ndcg-at-10", 116),
    "bright.economics": ("ir", "ndcg-at-10", 103),
    "bright.robotics": ("ir", "ndcg-at-10", 101),
    "qa.bamboogle": ("qa", "accuracy", 125),
}
_DATASET_ORDER = tuple(sorted(_REQUIRED))
_COMPONENTS = (
    "runtime",
    "model",
    "toolset",
    "prompt",
    "context",
    "metric",
)
_HYPOTHESIS_CODES = (
    "retrieval-scale-noise",
    "query-decomposition",
    "context-retention",
    "paper-method-difference",
)
_PROPOSAL_CODES = ("coverage-instrumentation", "retrieval-query-decomposition")
_MISSING_CODES = (
    "assembly-lineage",
    "package-lineage",
    "retrieval-coverage",
    "sealed-analysis-digest",
    "sealed-config-digest",
    "trace-graph",
)


class DciDiagnosisError(Exception):
    """A context-free trust-boundary failure for DCI diagnosis inputs."""


def _digest(domain: str, value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            {"domain": f"asterion.dci.pathlight.diagnosis/{domain}/v1", "value": value},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _checked(value: object) -> int:
    if type(value) is not int or value < 0 or value > _MAX_INT:
        raise ValueError
    return value


def _sum(values: tuple[int, ...]) -> int:
    total = 0
    for value in values:
        total += _checked(value)
        if total > _MAX_INT:
            raise ValueError
    return total


def _ratio_microunits(numerator: int, denominator: int) -> int:
    numerator, denominator = _checked(numerator), _checked(denominator)
    if denominator == 0 or numerator > denominator or numerator > _MAX_INT // 1_000_000:
        raise ValueError
    return numerator * 1_000_000 // denominator


def _median(values: tuple[int, ...]) -> int:
    """Return the lower integer midpoint (floor((a+b)/2)) for even samples."""

    if not values:
        raise ValueError
    ordered = tuple(sorted(_checked(value) for value in values))
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return ordered[middle - 1] + (ordered[middle] - ordered[middle - 1]) // 2


@dataclass(frozen=True, slots=True)
class DciWorkflowMetrics:
    """Integer-only aggregate metrics; even-sized medians round down."""

    zero_score_rate_microunits: int
    median_agent_total_tokens: int
    median_tool_call_count: int
    median_wall_time_ns: int
    median_tool_time_ns: int
    median_read_call_count: int
    median_grep_call_count: int
    median_question_word_count: int
    total_tool_error_count: int
    tool_time_share_microunits: int

    def to_mapping(self) -> dict[str, int]:
        return {
            "zero_score_rate_microunits": self.zero_score_rate_microunits,
            "median_agent_total_tokens": self.median_agent_total_tokens,
            "median_tool_call_count": self.median_tool_call_count,
            "median_wall_time_ns": self.median_wall_time_ns,
            "median_tool_time_ns": self.median_tool_time_ns,
            "median_read_call_count": self.median_read_call_count,
            "median_grep_call_count": self.median_grep_call_count,
            "median_question_word_count": self.median_question_word_count,
            "total_tool_error_count": self.total_tool_error_count,
            "tool_time_share_microunits": self.tool_time_share_microunits,
        }


@dataclass(frozen=True, slots=True)
class DciDatasetObservation:
    dataset_id: str
    metric_name: Literal["ndcg-at-10", "accuracy"]
    selected_count: int
    total_count: int
    failed_count: int
    corpus_file_count: int
    score_microunits: int
    reference_score_microunits: int
    reference_gap_microunits: int
    reference_status: Literal["reference-only"]
    aggregate_evaluation_sha256: str
    workflow_metrics: DciWorkflowMetrics

    def to_mapping(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "metric_name": self.metric_name,
            "selected_count": self.selected_count,
            "total_count": self.total_count,
            "failed_count": self.failed_count,
            "corpus_file_count": self.corpus_file_count,
            "score_microunits": self.score_microunits,
            "reference_score_microunits": self.reference_score_microunits,
            "reference_gap_microunits": self.reference_gap_microunits,
            "reference_status": self.reference_status,
            "aggregate_evaluation_sha256": self.aggregate_evaluation_sha256,
            "workflow_metrics": self.workflow_metrics.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class DciComponentComparison:
    dataset_id: str
    component: Literal["runtime", "model", "toolset", "prompt", "context", "metric"]
    relation_to_bright_biology: Literal["same", "different"]

    def to_mapping(self) -> dict[str, str]:
        return {
            "dataset_id": self.dataset_id,
            "component": self.component,
            "relation_to_bright_biology": self.relation_to_bright_biology,
        }


@dataclass(frozen=True, slots=True)
class DciProposalSummary:
    """A safe numeric description of one operator-authorized proposal only."""

    code: Literal["coverage-instrumentation", "retrieval-query-decomposition"]
    proposal_sha256: str
    requires_operator_authorization: bool
    execution_authorized: bool
    agent_operation_cap: int
    max_cost_microusd: int
    infrastructure_failure_stop: int | None
    prerequisite_proposal_sha256: str | None
    minimum_mean_ndcg_gain_microunits: int | None
    maximum_cost_or_time_increase_microunits: int | None

    def to_mapping(self) -> dict[str, object]:
        return {
            "code": self.code,
            "proposal_sha256": self.proposal_sha256,
            "requires_operator_authorization": self.requires_operator_authorization,
            "execution_authorized": self.execution_authorized,
            "agent_operation_cap": self.agent_operation_cap,
            "max_cost_microusd": self.max_cost_microusd,
            "infrastructure_failure_stop": self.infrastructure_failure_stop,
            "prerequisite_proposal_sha256": self.prerequisite_proposal_sha256,
            "minimum_mean_ndcg_gain_microunits": self.minimum_mean_ndcg_gain_microunits,
            "maximum_cost_or_time_increase_microunits": self.maximum_cost_or_time_increase_microunits,
        }


@dataclass(frozen=True, slots=True)
class DciDiagnosisReport:
    observations: tuple[DciDatasetObservation, ...]
    component_comparisons: tuple[DciComponentComparison, ...]
    findings: tuple[Finding, ...]
    missing_evidence: tuple[str, ...]
    hypothesis_codes: tuple[str, ...]
    proposals: tuple[DciProposalSummary, ...]
    aggregate_workflow_metrics: DciWorkflowMetrics
    diagnosis_bundle: DiagnosisBundle
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            tuple(item.dataset_id for item in self.observations) != _DATASET_ORDER
            or self.missing_evidence != tuple(sorted(self.missing_evidence))
            or self.hypothesis_codes != _HYPOTHESIS_CODES
            or tuple(item.code for item in self.proposals) != _PROPOSAL_CODES
            or any(item.execution_authorized or not item.requires_operator_authorization for item in self.proposals)
        ):
            raise ValueError("invalid diagnosis report")
        object.__setattr__(self, "report_sha256", _digest("report", self._unsigned_mapping()))

    @property
    def dataset_count(self) -> int:
        return len(self.observations)

    @property
    def total_case_count(self) -> int:
        return _sum(tuple(item.selected_count for item in self.observations))

    @property
    def reference_gaps_microunits(self) -> dict[str, int]:
        return {item.dataset_id: item.reference_gap_microunits for item in self.observations}

    @property
    def reference_status(self) -> dict[str, Literal["reference-only"]]:
        return {item.dataset_id: item.reference_status for item in self.observations}

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "schema": "asterion.dci.pathlight-diagnosis-report/v1",
            "observations": [item.to_mapping() for item in self.observations],
            "component_comparisons": [item.to_mapping() for item in self.component_comparisons],
            "findings": [item.to_mapping() for item in self.findings],
            "missing_evidence": list(self.missing_evidence),
            "hypothesis_codes": list(self.hypothesis_codes),
            "proposals": [item.to_mapping() for item in self.proposals],
            "aggregate_workflow_metrics": self.aggregate_workflow_metrics.to_mapping(),
            "diagnosis_bundle": self.diagnosis_bundle.to_mapping(),
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "report_sha256": self.report_sha256}


def diagnose_recommended_pack(runs: object) -> DciDiagnosisReport:
    """Diagnose exactly the six fixed recovered DCI cohorts without execution."""

    result: DciDiagnosisReport | None = None
    try:
        normalized = _validate_pack(runs)
        experiments = {dataset_id: recovered_run_to_experiment(run) for dataset_id, run in normalized.items()}
        references = {dataset_id: load_paper_reference(dataset_id) for dataset_id in _DATASET_ORDER}
        observations = tuple(
            _observation(dataset_id, normalized[dataset_id], experiments[dataset_id], references[dataset_id])
            for dataset_id in _DATASET_ORDER
        )
        aggregate_ids = {item.dataset_id: item.aggregate_evaluation_sha256 for item in observations}
        findings = _findings(observations, aggregate_ids)
        bundle, public_proposals = _diagnosis_bundle(experiments, aggregate_ids, findings)
        comparisons = _component_comparisons(normalized)
        result = DciDiagnosisReport(
            observations=observations,
            component_comparisons=comparisons,
            findings=tuple(sorted(findings, key=lambda item: item.finding_sha256)),
            missing_evidence=_MISSING_CODES,
            hypothesis_codes=_HYPOTHESIS_CODES,
            proposals=public_proposals,
            aggregate_workflow_metrics=_workflow_metrics(
                tuple(case for run in normalized.values() for case in run.cases)
            ),
            diagnosis_bundle=bundle,
        )
    except Exception:
        pass
    if result is None:
        raise DciDiagnosisError(_ERROR) from None
    return result


def _validate_pack(runs: object) -> dict[str, DciRecoveredRun]:
    if type(runs) is not tuple or len(runs) != len(_REQUIRED):
        raise ValueError
    normalized: dict[str, DciRecoveredRun] = {}
    for run in runs:
        if (
            type(run) is not DciRecoveredRun
            or type(run.variant) is not DciRecoveredVariant
            or type(run.cases) is not tuple
            or any(type(case) is not DciRecoveredCase for case in run.cases)
        ):
            raise ValueError
        mapping = run.to_mapping()
        raw_cases = mapping.get("cases")
        if type(mapping) is not dict or type(raw_cases) is not list:
            raise ValueError
        mapping["cases"] = sorted(
            raw_cases,
            key=lambda item: item["dataset_item_sha256"] if type(item) is dict else "",
        )
        recovered = validate_recovered_run(mapping)
        expected = _REQUIRED.get(recovered.dataset_id)
        if expected is None or (recovered.mode, recovered.metric_name, recovered.selected_count) != expected:
            raise ValueError
        if recovered.dataset_id in normalized:
            raise ValueError
        _validate_numeric_limits(recovered)
        normalized[recovered.dataset_id] = recovered
    if tuple(sorted(normalized)) != _DATASET_ORDER:
        raise ValueError
    return normalized


def _validate_numeric_limits(run: DciRecoveredRun) -> None:
    for value in (run.selected_count, run.total_count, run.failed_count, run.corpus_file_count):
        _checked(value)
    for case in run.cases:
        for value in (
            case.agent_total_tokens, case.overall_cost_microusd, case.wall_time_ns,
            case.tool_time_ns, case.tool_call_count, case.tool_error_count,
            case.read_call_count, case.grep_call_count, case.read_time_ns,
            case.grep_time_ns, case.question_word_count,
        ):
            _checked(value)
        if (
            case.wall_time_ns == 0
            or case.tool_time_ns > case.wall_time_ns
            or case.resolution_status != "not-available"
            or case.resolution_coverage_microunits is not None
        ):
            raise ValueError


def _observation(
    dataset_id: str,
    run: DciRecoveredRun,
    experiment: ExperimentBundle,
    reference: DciReferenceComparison,
) -> DciDatasetObservation:
    if reference.dataset_id != dataset_id or reference.metric_name != run.metric_name or reference.total_count != run.total_count:
        raise ValueError
    aggregates = tuple(
        item for item in experiment.evaluations
        if item.selected_count == run.selected_count and item.total_count == run.total_count
    )
    if len(aggregates) != 1 or aggregates[0].value_microunits != run.metric_value_microunits:
        raise ValueError
    gap = run.metric_value_microunits - reference.value_microunits
    if gap < -_MAX_INT or gap > _MAX_INT:
        raise ValueError
    return DciDatasetObservation(
        dataset_id, run.metric_name, run.selected_count, run.total_count, run.failed_count,
        run.corpus_file_count, run.metric_value_microunits, reference.value_microunits, gap,
        reference.comparison_status, aggregates[0].evaluation_sha256, _workflow_metrics(run.cases),
    )


def _workflow_metrics(cases: tuple[DciRecoveredCase, ...]) -> DciWorkflowMetrics:
    if not cases:
        raise ValueError
    def values(attribute: str) -> tuple[int, ...]:
        return tuple(getattr(case, attribute) for case in cases)

    zero_count = sum(case.metric_value_microunits == 0 for case in cases)
    wall = _sum(values("wall_time_ns"))
    tool = _sum(values("tool_time_ns"))
    return DciWorkflowMetrics(
        _ratio_microunits(zero_count, len(cases)),
        _median(values("agent_total_tokens")), _median(values("tool_call_count")),
        _median(values("wall_time_ns")), _median(values("tool_time_ns")),
        _median(values("read_call_count")), _median(values("grep_call_count")),
        _median(values("question_word_count")), _sum(values("tool_error_count")),
        _ratio_microunits(tool, wall),
    )


def _component_comparisons(runs: dict[str, DciRecoveredRun]) -> tuple[DciComponentComparison, ...]:
    baseline = runs["bright.biology"].variant
    attributes = {
        "runtime": "runtime_contract_sha256", "model": "model_sha256", "toolset": "toolset_sha256",
        "prompt": "prompt_contract_sha256", "context": "context_contract_sha256", "metric": "metric_contract_sha256",
    }
    return tuple(
        DciComponentComparison(
            dataset_id, component, "same" if getattr(runs[dataset_id].variant, attributes[component]) == getattr(baseline, attributes[component]) else "different"
        )
        for dataset_id in _DATASET_ORDER
        for component in _COMPONENTS
    )


def _finding(category: str, code: str, evidence: tuple[str, ...], counter: tuple[str, ...] = ()) -> Finding:
    return Finding(category, _digest("subject", code), tuple(sorted(evidence)), tuple(sorted(counter)), "confirmed" if category == "observed" else ("unknown" if category in {"missing-evidence", "not-comparable"} else "medium"), _digest("code", code))  # type: ignore[arg-type]


def _findings(observations: tuple[DciDatasetObservation, ...], aggregate_ids: dict[str, str]) -> tuple[Finding, ...]:
    observed = tuple(_finding("observed", f"observed:{item.dataset_id}", (item.aggregate_evaluation_sha256,)) for item in observations)
    by_code = {item.finding_code_sha256: item for item in observed}
    def observed_id(dataset_id: str) -> str:
        return by_code[_digest("code", f"observed:{dataset_id}")].finding_sha256
    missing = tuple(
        _finding("missing-evidence", f"missing:{code}", tuple(sorted(aggregate_ids.values())))
        for code in _MISSING_CODES
    )
    not_comparable = _finding("not-comparable", "not-comparable:paper-reference", (aggregate_ids["bright.biology"],))
    hypotheses = (
        _finding("hypothesis", "hypothesis:retrieval-scale-noise", (observed_id("bright.biology"), observed_id("bright.earth-science")), (not_comparable.finding_sha256,)),
        _finding("hypothesis", "hypothesis:query-decomposition", (observed_id("bright.biology"), observed_id("beir.scifact")), (not_comparable.finding_sha256,)),
        _finding("hypothesis", "hypothesis:context-retention", (observed_id("bright.biology"), missing[_MISSING_CODES.index("retrieval-coverage")].finding_sha256), (not_comparable.finding_sha256,)),
        _finding("hypothesis", "hypothesis:paper-method-difference", (observed_id("bright.biology"), not_comparable.finding_sha256), (missing[_MISSING_CODES.index("sealed-config-digest")].finding_sha256,)),
    )
    return (*observed, *missing, not_comparable, *hypotheses)


def _diagnosis_bundle(
    experiments: Mapping[str, ExperimentBundle],
    aggregate_ids: dict[str, str],
    findings: tuple[Finding, ...],
) -> tuple[DiagnosisBundle, tuple[DciProposalSummary, ...]]:
    hypothesis = {
        code: next(item for item in findings if item.finding_code_sha256 == _digest("code", f"hypothesis:{code}"))
        for code in _HYPOTHESIS_CODES
    }
    coverage = Proposal(
        hypothesis["context-retention"].finding_sha256,
        _digest("proposal-change", "coverage-instrumentation"), _digest("proposal-scope", {"bright_cases": 40, "scifact_cases": 10}),
        _digest("proposal-success", "trajectory-coverage-only"), _digest("proposal-stop", {"infrastructure_failures": 2}),
        _digest("proposal-budget", {"agent_operations": 50, "max_cost_microusd": 5_000_000}),
    )
    decomposition = Proposal(
        hypothesis["query-decomposition"].finding_sha256,
        _digest("proposal-change", "retrieval-query-decomposition"), _digest("proposal-scope", {"paired_agent_operations": 80}),
        _digest("proposal-success", {"mean_ndcg_gain_microunits": 50_000, "maximum_cost_or_time_increase_microunits": 250_000}),
        _digest("proposal-stop", "coverage-proposal-must-succeed"),
        _digest("proposal-budget", {"agent_operations": 80, "max_cost_microusd": 8_000_000}),
    )
    bundle = DiagnosisBundle.build(
        experiment_bundle_sha256s=tuple(experiments[key].bundle_sha256 for key in _DATASET_ORDER),
        evaluation_sha256s=tuple(aggregate_ids.values()), findings=findings, proposals=(coverage, decomposition),
    )
    summaries = (
        DciProposalSummary("coverage-instrumentation", coverage.proposal_sha256, True, False, 50, 5_000_000, 2, None, None, None),
        DciProposalSummary("retrieval-query-decomposition", decomposition.proposal_sha256, True, False, 80, 8_000_000, None, coverage.proposal_sha256, 50_000, 250_000),
    )
    return bundle, summaries


_CN_DATASETS = {
    "beir.scifact": "SciFact", "bright.biology": "Bright 生物学", "bright.earth-science": "Bright 地球科学",
    "bright.economics": "Bright 经济学", "bright.robotics": "Bright 机器人学", "qa.bamboogle": "Bamboogle",
}
_CN_METRICS = {"ndcg-at-10": "nDCG@10", "accuracy": "准确率"}
_CN_HYPOTHESES = {
    "retrieval-scale-noise": "大语料检索尺度噪声", "query-decomposition": "查询分解不足",
    "context-retention": "上下文保留不可见", "paper-method-difference": "论文方法差异",
}
_CN_PROPOSALS = {"coverage-instrumentation": "覆盖率观测", "retrieval-query-decomposition": "检索查询分解"}
_CN_MISSING = {
    "assembly-lineage": "装配谱系", "package-lineage": "包谱系", "retrieval-coverage": "检索覆盖率",
    "sealed-analysis-digest": "封存分析摘要", "sealed-config-digest": "封存配置摘要", "trace-graph": "轨迹图谱",
}


def render_chinese_diagnosis(report: object) -> str:
    """Render only fixed Chinese dictionaries plus safe numeric report fields."""

    if type(report) is not DciDiagnosisReport:
        raise DciDiagnosisError(_ERROR)
    try:
        checked = DciDiagnosisReport(
            report.observations, report.component_comparisons, report.findings, report.missing_evidence,
            report.hypothesis_codes, report.proposals, report.aggregate_workflow_metrics, report.diagnosis_bundle,
        )
        if checked.report_sha256 != report.report_sha256:
            raise ValueError
        lines = ["# DCI 差分诊断", "", "## 已证实事实", ""]
        for item in report.observations:
            lines.append(f"- {_CN_DATASETS[item.dataset_id]}：{_CN_METRICS[item.metric_name]} {item.score_microunits} 微单位；样本 {item.selected_count}/{item.total_count}；论文差值 {item.reference_gap_microunits} 微单位（仅参考）。")
        lines.extend(["", "## 待验证假设", ""])
        lines.extend(f"- {_CN_HYPOTHESES[code]}。" for code in report.hypothesis_codes)
        lines.extend(["", "## 反证与不可比较项", "", "- 论文数值仅作参考，当前变体不可视为完全可比。", "", "## 证据缺口", ""])
        lines.extend(f"- {_CN_MISSING[code]}" for code in report.missing_evidence)
        lines.extend(["", "## 最小受控实验", ""])
        for item in report.proposals:
            lines.append(f"- {_CN_PROPOSALS[item.code]}：最多 {item.agent_operation_cap} 次 Agent 操作，成本上限 {item.max_cost_microusd} 微美元；需运营者授权，当前未授权。")
        return "\n".join(lines) + "\n"
    except DciDiagnosisError:
        raise
    except Exception:
        raise DciDiagnosisError(_ERROR) from None
