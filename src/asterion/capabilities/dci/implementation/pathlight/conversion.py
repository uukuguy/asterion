"""Public-safe conversion of recovered DCI evidence to Pathlight experiments."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from asterion.capabilities.dci.implementation.pathlight.recovery import (
    DciRecoveredCase,
    DciRecoveredRun,
    DciRecoveredVariant,
)
from asterion.capabilities.dci.implementation.reproduction import reproduction
from asterion.capabilities.dci.implementation.reproduction.paper_benchmarks import (
    canonical_sha256,
    resolve_paper_benchmark,
)
from asterion.pathlight.evaluation import EvaluationRecord
from asterion.pathlight.experiment import (
    CaseTrial,
    DatasetSnapshot,
    EvaluatorContract,
    ExperimentBundle,
    ExperimentPlan,
    Variant,
)


_TARGET_ID = "paper.2605.05242v1/dci-agent-cc/main"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECOVERY_MISSING = frozenset({"sealed-analysis-digest", "sealed-config-digest"})
_LINEAGE_MISSING = frozenset({"assembly-lineage", "package-lineage", "trace-graph"})


class DciConversionError(Exception):
    """A context-free DCI-to-Pathlight trust-boundary failure."""


@dataclass(frozen=True, slots=True)
class DciReferenceComparison:
    """One published paper number, explicitly unsuitable as a candidate result."""

    dataset_id: str
    metric_name: Literal["accuracy", "ndcg-at-10"]
    value_microunits: int
    total_count: int
    target_id: str
    target_sha256: str
    provenance_sha256: str
    comparison_status: Literal["reference-only"] = "reference-only"

    def to_mapping(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "metric_name": self.metric_name,
            "value_microunits": self.value_microunits,
            "total_count": self.total_count,
            "target_id": self.target_id,
            "target_sha256": self.target_sha256,
            "provenance_sha256": self.provenance_sha256,
            "comparison_status": self.comparison_status,
        }


def load_paper_reference(dataset_id: str) -> DciReferenceComparison:
    """Load one exact DCI-Agent-CC paper number without creating a candidate."""

    result: DciReferenceComparison | None = None
    failed = False
    try:
        result = _load_paper_reference(dataset_id)
    except Exception:
        failed = True
    if failed or result is None:
        raise DciConversionError("DCI Pathlight conversion is invalid")
    return result


def recovered_run_to_experiment(run: DciRecoveredRun) -> ExperimentBundle:
    """Build the complete recovered Pathlight closure for one DCI batch."""

    result: ExperimentBundle | None = None
    failed = False
    try:
        cases = _validate_recovered_run(run)
        dataset = DatasetSnapshot(
            dataset_contract_sha256=_project(
                "dataset-contract/v1", {"dataset_id": run.dataset_id, "mode": run.mode}
            ),
            content_sha256=_project("dataset-content/v1", run.dataset_snapshot_sha256),
            total_count=run.total_count,
            snapshot_version="1.0.0",
        )
        evaluator = _evaluator(run)
        variant = _variant(run)
        selected_item_set = tuple(case.dataset_item_sha256 for case in cases)
        aggregate_scope = _project("selected-item-set/v1", selected_item_set)
        plan = ExperimentPlan(
            dataset_snapshot_sha256=dataset.dataset_snapshot_sha256,
            scope_sha256=aggregate_scope,
            baseline_variant_sha256=variant.variant_sha256,
            candidate_variant_sha256s=(),
            assignment_sha256=_project(
                "observation-assignment/v1",
                {"recovered_run_sha256": run.recovered_run_sha256, "scope_sha256": aggregate_scope},
            ),
            evaluator_contract_sha256s=(evaluator.evaluator_contract_sha256,),
            budget_sha256=_project(
                "observation-budget/v1",
                {"selected_count": run.selected_count, "total_count": run.total_count},
            ),
            stop_criteria_sha256=_project(
                "observation-stop-criteria/v1", {"failed_count": run.failed_count}
            ),
        )
        evaluations: list[EvaluationRecord] = []
        trials: list[CaseTrial] = []
        for case in cases:
            trace = _case_trace(run, case)
            scope = _case_scope(case.dataset_item_sha256)
            evaluation = EvaluationRecord(
                trace_sha256=trace,
                metric_contract_sha256=evaluator.metric_contract_sha256,
                dataset_snapshot_sha256=dataset.dataset_snapshot_sha256,
                scope_sha256=scope,
                value_microunits=case.metric_value_microunits,
                selected_count=1,
                total_count=1,
                status="recovered",
            )
            missing = set(run.missing_evidence) | _LINEAGE_MISSING
            if case.resolution_status == "not-available":
                missing.add("retrieval-coverage")
            trials.append(
                CaseTrial(
                    experiment_plan_sha256=plan.experiment_plan_sha256,
                    dataset_item_sha256=case.dataset_item_sha256,
                    variant_sha256=variant.variant_sha256,
                    trace_sha256=trace,
                    evaluation_sha256s=(evaluation.evaluation_sha256,),
                    evidence_state="recovered",
                    missing_evidence=tuple(sorted(missing)),
                )
            )
            evaluations.append(evaluation)
        evaluations.append(
            EvaluationRecord(
                trace_sha256=_project(
                    "aggregate-trace/v1",
                    {
                        "recovered_run_sha256": run.recovered_run_sha256,
                        "case_source_sha256s": tuple(case.case_source_sha256 for case in cases),
                    },
                ),
                metric_contract_sha256=evaluator.metric_contract_sha256,
                dataset_snapshot_sha256=dataset.dataset_snapshot_sha256,
                scope_sha256=aggregate_scope,
                value_microunits=run.metric_value_microunits,
                selected_count=run.selected_count,
                total_count=run.total_count,
                status="recovered",
            )
        )
        result = ExperimentBundle.build(
            datasets=(dataset,),
            evaluators=(evaluator,),
            variants=(variant,),
            plans=(plan,),
            trials=trials,
            evaluations=evaluations,
        )
    except Exception:
        failed = True
    if failed or result is None:
        raise DciConversionError("DCI Pathlight conversion is invalid")
    return result


def _load_paper_reference(dataset_id: object) -> DciReferenceComparison:
    if type(dataset_id) is not str:
        raise ValueError
    benchmark = resolve_paper_benchmark(dataset_id)
    reproduction.reproduction_targets_sha256()
    registry = reproduction._resource_mapping("reproduction-targets.json")
    targets = reproduction._target_registry_entries(registry)
    matches = [target for target in targets if target.get("target_id") == _TARGET_ID]
    if len(matches) != 1:
        raise ValueError
    target = matches[0]
    if (
        target.get("target_status") != "executable-comparable"
        or target.get("target_role") != "main"
        or target.get("source_id") != "arxiv:2605.05242v1"
        or target.get("profile_id") != "paper-reference/claude-code"
    ):
        raise ValueError
    dataset_targets = target.get("dataset_targets")
    metric_contract = target.get("metric_contract")
    if type(dataset_targets) is not dict or type(metric_contract) is not dict:
        raise ValueError
    metric_name: Literal["accuracy", "ndcg-at-10"]
    target_metric: str
    if benchmark.metric == "llm-answer-correctness":
        metric_name, target_metric = "accuracy", "llm-answer-correctness"
    elif benchmark.metric == "ndcg@10-binary-deduplicated":
        metric_name, target_metric = "ndcg-at-10", "ndcg@10-binary-deduplicated"
    else:
        raise ValueError
    identities = metric_contract.get("metric_identities")
    score = dataset_targets.get(dataset_id)
    if (
        type(identities) is not list
        or target_metric not in identities
        or benchmark.source_count != benchmark.selection_count
        or benchmark.source_count <= 0
    ):
        raise ValueError
    value_microunits = _microunits(score)
    target_sha256 = canonical_sha256(dict(target))
    return DciReferenceComparison(
        dataset_id=dataset_id,
        metric_name=metric_name,
        value_microunits=value_microunits,
        total_count=benchmark.source_count,
        target_id=_TARGET_ID,
        target_sha256=target_sha256,
        provenance_sha256=_project(
            "paper-target-provenance/v1",
            {
                "target_sha256": target_sha256,
                "source_id": target["source_id"],
                "paper_table": target["paper_table"],
                "paper_row": target["paper_row"],
            },
        ),
    )


def _validate_recovered_run(run: object) -> tuple[DciRecoveredCase, ...]:
    if type(run) is not DciRecoveredRun or type(run.variant) is not DciRecoveredVariant:
        raise ValueError
    if (
        type(run.dataset_id) is not str
        or run.mode not in {"ir", "qa"}
        or run.metric_name not in {"accuracy", "ndcg-at-10"}
        or not _is_natural(run.metric_value_microunits)
        or not _is_natural(run.selected_count)
        or not _is_natural(run.total_count)
        or not _is_natural(run.failed_count)
        or not _is_natural(run.corpus_file_count)
        or not _sha256(run.dataset_snapshot_sha256)
        or not _sha256(run.recovered_run_sha256)
        or type(run.cases) is not tuple
        or type(run.source_document_sha256s) is not tuple
        or not run.source_document_sha256s
        or any(not _sha256(value) for value in run.source_document_sha256s)
        or type(run.missing_evidence) is not tuple
        or set(run.missing_evidence) != _RECOVERY_MISSING
    ):
        raise ValueError
    benchmark = resolve_paper_benchmark(run.dataset_id)
    expected_mode = "ir" if benchmark.mode == "ir" else "qa"
    expected_metric = "ndcg-at-10" if expected_mode == "ir" else "accuracy"
    if run.mode != expected_mode or run.metric_name != expected_metric:
        raise ValueError
    _validate_variant(run.variant)
    cases = tuple(sorted(run.cases, key=lambda case: case.dataset_item_sha256))
    if (
        len(cases) != run.selected_count
        or run.total_count != run.selected_count
        or len({case.dataset_item_sha256 for case in cases}) != len(cases)
        or run.failed_count != sum(case.run_status == "failed" for case in cases)
    ):
        raise ValueError
    for case in cases:
        _validate_case(case)
    return cases


def _validate_variant(variant: DciRecoveredVariant) -> None:
    if any(not _sha256(getattr(variant, field)) for field in variant.to_mapping()):
        raise ValueError


def _validate_case(case: object) -> None:
    if type(case) is not DciRecoveredCase:
        raise ValueError
    if (
        not _sha256(case.dataset_item_sha256)
        or not _sha256(case.case_source_sha256)
        or not _is_natural(case.metric_value_microunits)
        or case.run_status not in {"completed", "failed"}
        or case.resolution_status not in {"available", "not-available"}
        or (case.resolution_status == "available" and not _is_natural(case.resolution_coverage_microunits))
        or (case.resolution_status == "not-available" and case.resolution_coverage_microunits is not None)
    ):
        raise ValueError
    numeric_fields = (
        "agent_total_tokens",
        "overall_cost_microusd",
        "wall_time_ns",
        "tool_time_ns",
        "tool_call_count",
        "tool_error_count",
        "read_call_count",
        "grep_call_count",
        "read_time_ns",
        "grep_time_ns",
        "question_word_count",
    )
    if any(not _is_natural(getattr(case, field)) for field in numeric_fields):
        raise ValueError
    if case.tool_call_count != case.read_call_count + case.grep_call_count:
        raise ValueError
    if case.tool_time_ns != case.read_time_ns + case.grep_time_ns:
        raise ValueError


def _evaluator(run: DciRecoveredRun) -> EvaluatorContract:
    return EvaluatorContract(
        metric_contract_sha256=_project("metric-contract/v1", run.variant.metric_contract_sha256),
        evaluator_kind="recovered",
        implementation_sha256=_project("evaluator-implementation/v1", run.variant.implementation_sha256),
        input_contract_sha256=_project("evaluator-input/v1", run.dataset_snapshot_sha256),
        output_contract_sha256=_project("evaluator-output/v1", run.variant.metric_contract_sha256),
        failure_semantics_sha256=_project(
            "evaluator-failure-semantics/v1", {"failed_count": run.failed_count}
        ),
        contract_version="1.0.0",
    )


def _variant(run: DciRecoveredRun) -> Variant:
    source = run.variant
    return Variant(
        assembly_sha256=_project(
            "assembly-projection/v1",
            {"recovered_run_sha256": run.recovered_run_sha256, "runtime_contract_sha256": source.runtime_contract_sha256},
        ),
        package_set_sha256=_project(
            "package-projection/v1",
            {"recovered_run_sha256": run.recovered_run_sha256, "profile_sha256": source.profile_sha256},
        ),
        implementation_sha256=_project("implementation-projection/v1", source.implementation_sha256),
        runtime_sha256=_project("runtime-projection/v1", source.runtime_contract_sha256),
        model_sha256=_project("model-projection/v1", source.model_sha256),
        toolset_sha256=_project("toolset-projection/v1", source.toolset_sha256),
        prompt_contract_sha256=_project("prompt-projection/v1", source.prompt_contract_sha256),
        policy_sha256=_project("policy-projection/v1", source.policy_sha256),
        change_sha256=_project("recovery-variant/v1", run.recovered_run_sha256),
    )


def _case_trace(run: DciRecoveredRun, case: DciRecoveredCase) -> str:
    return _project(
        "case-trace/v1",
        {"recovered_run_sha256": run.recovered_run_sha256, "case_source_sha256": case.case_source_sha256},
    )


def _case_scope(dataset_item_sha256: str) -> str:
    return _project("case-scope/v1", dataset_item_sha256)


def _project(domain: str, value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            {"domain": f"asterion.dci.pathlight/{domain}", "value": value},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sha256(value: object) -> bool:
    return type(value) is str and _HEX_SHA256.fullmatch(value) is not None


def _is_natural(value: object) -> bool:
    return type(value) is int and value >= 0


def _microunits(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError
    try:
        scaled = Decimal(str(value)) * Decimal(1_000_000)
        integer = scaled.to_integral_exact()
    except (InvalidOperation, ValueError):
        raise ValueError from None
    if scaled != integer or integer < 0 or integer > 1_000_000:
        raise ValueError
    return int(integer)
