"""Closed, deterministic differential diagnosis for recovered DCI batches.

The analyzer accepts only the six known paper-main cohorts.  It deliberately
retains aggregate identities and fixed-point measurements, never private case
text, paths, runtime configuration, or provider/model names.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
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
from asterion.pathlight.diagnosis import (
    DiagnosisBundle,
    Finding,
    Proposal,
    validate_finding,
)
from asterion.pathlight._private_file import read_private_file, write_private_file
from asterion.pathlight.evaluation import EvaluationRecord, MetricContract
from asterion.pathlight.experiment import ExperimentBundle


_ERROR = "DCI diagnosis is invalid"
AUTHORIZATION_GATE_REPORT_FILENAME = "pathlight-dci-authorization-gate.json"
_AUTHORIZATION_GATE_REPORT_SCHEMA = "asterion.dci.pathlight.authorization-gate-report/v1"
_MAX_GATE_REPORT_BYTES = 64 * 1024
_MAX_INT = (1 << 63) - 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED: dict[str, tuple[Literal["ir", "qa"], Literal["ndcg-at-10", "accuracy"], int]] = {
    "beir.scifact": ("ir", "ndcg-at-10", 300),
    "bright.biology": ("ir", "ndcg-at-10", 103),
    "bright.earth-science": ("ir", "ndcg-at-10", 116),
    "bright.economics": ("ir", "ndcg-at-10", 103),
    "bright.robotics": ("ir", "ndcg-at-10", 101),
    "qa.bamboogle": ("qa", "accuracy", 125),
}
_DATASET_ORDER = tuple(sorted(_REQUIRED))
_BRIGHT_DATASETS = (
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
)
_COVERAGE_DATASETS = (*_BRIGHT_DATASETS, "beir.scifact")
_COMPARISON_DATASETS = tuple(
    dataset_id for dataset_id in _DATASET_ORDER if dataset_id != "qa.bamboogle"
)
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


def _unit(value: object) -> int:
    value = _checked(value)
    if value > 1_000_000:
        raise ValueError
    return value


def _signed(value: object) -> int:
    if type(value) is not int or value < -_MAX_INT or value > _MAX_INT:
        raise ValueError
    return value


def _sha256(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
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
    if denominator == 0 or numerator > denominator:
        raise ValueError
    return (numerator // denominator) * 1_000_000 + (
        (numerator % denominator) * 1_000_000 // denominator
    )


def _time_share_microunits(numerator: int, denominator: int) -> int:
    numerator, denominator = _checked(numerator), _checked(denominator)
    if denominator == 0:
        if numerator != 0:
            raise ValueError
        return 0
    return _ratio_microunits(numerator, denominator)


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
class DciCoverageDatasetObservation:
    """One content-free coverage aggregate for an exact ten-query task."""

    dataset_id: str
    coverage_available_queries: int
    coverage_total_queries: int
    coverage_median_any_microunits: int | None
    coverage_median_mean_microunits: int | None
    coverage_median_all_microunits: int | None
    retained_available_queries: int
    retained_median_microunits: int | None
    tool_observation_count: int
    surfaced_gold_count: int
    model_call_count: int
    context_frame_count: int
    missing_boundary_count: int
    integrity_failure_count: int
    evidence_sha256: str

    def __post_init__(self) -> None:
        metrics = (
            self.coverage_median_any_microunits,
            self.coverage_median_mean_microunits,
            self.coverage_median_all_microunits,
        )
        try:
            if (
                type(self) is not DciCoverageDatasetObservation
                or self.dataset_id not in _COVERAGE_DATASETS
                or self.coverage_total_queries != 10
                or not 0 <= _checked(self.coverage_available_queries) <= 10
                or any(value is not None and _unit(value) != value for value in metrics)
                or self.coverage_available_queries == 0
                and any(value is not None for value in metrics)
                or self.coverage_available_queries > 0
                and any(value is None for value in metrics)
                or not 0
                <= _checked(self.retained_available_queries)
                <= self.coverage_available_queries
                or (self.retained_available_queries == 0)
                != (self.retained_median_microunits is None)
                or self.retained_median_microunits is not None
                and _unit(self.retained_median_microunits)
                != self.retained_median_microunits
                or any(
                    _checked(value) > _MAX_INT
                    for value in (
                        self.tool_observation_count,
                        self.surfaced_gold_count,
                        self.model_call_count,
                        self.context_frame_count,
                        self.missing_boundary_count,
                    )
                )
                or not 0 <= _checked(self.integrity_failure_count) <= 10
                or _sha256(self.evidence_sha256) != self.evidence_sha256
            ):
                raise ValueError
        except Exception:
            raise ValueError("invalid DCI coverage dataset observation") from None

    def to_mapping(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "coverage_available_queries": self.coverage_available_queries,
            "coverage_total_queries": self.coverage_total_queries,
            "coverage_median_any_microunits": self.coverage_median_any_microunits,
            "coverage_median_mean_microunits": self.coverage_median_mean_microunits,
            "coverage_median_all_microunits": self.coverage_median_all_microunits,
            "retained_available_queries": self.retained_available_queries,
            "retained_median_microunits": self.retained_median_microunits,
            "tool_observation_count": self.tool_observation_count,
            "surfaced_gold_count": self.surfaced_gold_count,
            "model_call_count": self.model_call_count,
            "context_frame_count": self.context_frame_count,
            "missing_boundary_count": self.missing_boundary_count,
            "integrity_failure_count": self.integrity_failure_count,
            "evidence_sha256": self.evidence_sha256,
        }


def _copy_coverage_dataset(value: object) -> DciCoverageDatasetObservation:
    if type(value) is not DciCoverageDatasetObservation:
        raise ValueError
    return DciCoverageDatasetObservation(
        dataset_id=value.dataset_id,
        coverage_available_queries=value.coverage_available_queries,
        coverage_total_queries=value.coverage_total_queries,
        coverage_median_any_microunits=value.coverage_median_any_microunits,
        coverage_median_mean_microunits=value.coverage_median_mean_microunits,
        coverage_median_all_microunits=value.coverage_median_all_microunits,
        retained_available_queries=value.retained_available_queries,
        retained_median_microunits=value.retained_median_microunits,
        tool_observation_count=value.tool_observation_count,
        surfaced_gold_count=value.surfaced_gold_count,
        model_call_count=value.model_call_count,
        context_frame_count=value.context_frame_count,
        missing_boundary_count=value.missing_boundary_count,
        integrity_failure_count=value.integrity_failure_count,
        evidence_sha256=value.evidence_sha256,
    )


@dataclass(frozen=True, slots=True)
class DciCoverageExperimentObservation:
    """A body-free aggregate of the finite Task 8 coverage experiment."""

    plan_sha256: str
    proposal_sha256: str
    scope_sha256: str
    variant_sha256: str
    registry_set_sha256: str
    authorization_sha256: str
    receipt_set_sha256: str
    datasets: tuple[DciCoverageDatasetObservation, ...]
    agent_operation_count: int
    judge_operation_count: int
    consumed_cost_microusd: int
    infrastructure_failure_count: int
    experiment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            datasets = tuple(_copy_coverage_dataset(item) for item in self.datasets)
            if (
                type(self) is not DciCoverageExperimentObservation
                or type(self.datasets) is not tuple
                or tuple(item.dataset_id for item in datasets) != _COVERAGE_DATASETS
                or any(
                    _sha256(value) != value
                    for value in (
                        self.plan_sha256,
                        self.proposal_sha256,
                        self.scope_sha256,
                        self.variant_sha256,
                        self.registry_set_sha256,
                        self.authorization_sha256,
                        self.receipt_set_sha256,
                    )
                )
                or not _sum(
                    tuple(item.coverage_available_queries for item in datasets)
                )
                <= _checked(self.agent_operation_count)
                <= 50
                or self.judge_operation_count != 0
                or not 0 <= _checked(self.consumed_cost_microusd) <= 5_000_000
                or not 0 <= _checked(self.infrastructure_failure_count) < 2
            ):
                raise ValueError
            object.__setattr__(self, "datasets", datasets)
            object.__setattr__(
                self,
                "experiment_sha256",
                _digest("coverage-experiment", self._unsigned_mapping()),
            )
        except Exception:
            raise ValueError("invalid DCI coverage experiment observation") from None

    @property
    def complete(self) -> bool:
        return (
            self.agent_operation_count == 50
            and all(
                item.coverage_available_queries == item.coverage_total_queries == 10
                and item.integrity_failure_count == 0
                for item in self.datasets
            )
        )

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "plan_sha256": self.plan_sha256,
            "proposal_sha256": self.proposal_sha256,
            "scope_sha256": self.scope_sha256,
            "variant_sha256": self.variant_sha256,
            "registry_set_sha256": self.registry_set_sha256,
            "authorization_sha256": self.authorization_sha256,
            "receipt_set_sha256": self.receipt_set_sha256,
            "datasets": [item.to_mapping() for item in self.datasets],
            "agent_operation_count": self.agent_operation_count,
            "judge_operation_count": self.judge_operation_count,
            "consumed_cost_microusd": self.consumed_cost_microusd,
            "infrastructure_failure_count": self.infrastructure_failure_count,
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "experiment_sha256": self.experiment_sha256}


def _copy_coverage_experiment(
    value: object,
) -> DciCoverageExperimentObservation:
    if type(value) is not DciCoverageExperimentObservation:
        raise ValueError
    copied = DciCoverageExperimentObservation(
        plan_sha256=value.plan_sha256,
        proposal_sha256=value.proposal_sha256,
        scope_sha256=value.scope_sha256,
        variant_sha256=value.variant_sha256,
        registry_set_sha256=value.registry_set_sha256,
        authorization_sha256=value.authorization_sha256,
        receipt_set_sha256=value.receipt_set_sha256,
        datasets=tuple(_copy_coverage_dataset(item) for item in value.datasets),
        agent_operation_count=value.agent_operation_count,
        judge_operation_count=value.judge_operation_count,
        consumed_cost_microusd=value.consumed_cost_microusd,
        infrastructure_failure_count=value.infrastructure_failure_count,
    )
    if not hmac.compare_digest(copied.experiment_sha256, value.experiment_sha256):
        raise ValueError
    return copied


def coverage_evaluation_values(
    coverage: DciCoverageExperimentObservation,
) -> tuple[MetricContract, tuple[EvaluationRecord, ...]]:
    """Project coverage aggregates into real, body-free Pathlight evaluations."""

    try:
        coverage = _copy_coverage_experiment(coverage)
        contract = MetricContract("coverage", "ratio", True, "1.0.0")
        records = tuple(
            EvaluationRecord(
                trace_sha256=item.evidence_sha256,
                metric_contract_sha256=contract.metric_contract_sha256,
                dataset_snapshot_sha256=_digest(
                    "coverage-dataset",
                    {
                        "dataset_id": item.dataset_id,
                        "registry_set_sha256": coverage.registry_set_sha256,
                    },
                ),
                scope_sha256=coverage.scope_sha256,
                value_microunits=item.coverage_median_mean_microunits,
                selected_count=item.coverage_available_queries,
                total_count=item.coverage_total_queries,
                status=(
                    "missing"
                    if item.coverage_available_queries == 0
                    else "observed"
                ),
            )
            for item in coverage.datasets
        )
        return contract, tuple(
            sorted(records, key=lambda item: item.evaluation_sha256)
        )
    except Exception:
        raise DciDiagnosisError(_ERROR) from None


@dataclass(frozen=True, slots=True)
class DciWorkflowMetrics:
    """Integer-only metrics; even medians round down and read/grep share tool time."""

    zero_score_rate_microunits: int
    median_agent_total_tokens: int
    median_tool_call_count: int
    median_wall_time_ns: int
    median_tool_time_ns: int
    median_read_call_count: int
    median_grep_call_count: int
    median_read_time_ns: int
    median_grep_time_ns: int
    median_question_word_count: int
    total_tool_error_count: int
    total_wall_time_ns: int
    total_tool_time_ns: int
    total_read_time_ns: int
    total_grep_time_ns: int
    tool_time_share_microunits: int
    read_time_share_microunits: int
    grep_time_share_microunits: int

    def __post_init__(self) -> None:
        natural_fields = (
            self.median_agent_total_tokens,
            self.median_tool_call_count,
            self.median_wall_time_ns,
            self.median_tool_time_ns,
            self.median_read_call_count,
            self.median_grep_call_count,
            self.median_read_time_ns,
            self.median_grep_time_ns,
            self.median_question_word_count,
            self.total_tool_error_count,
            self.total_wall_time_ns,
            self.total_tool_time_ns,
            self.total_read_time_ns,
            self.total_grep_time_ns,
        )
        try:
            if type(self) is not DciWorkflowMetrics:
                raise ValueError
            for value in natural_fields:
                _checked(value)
            for value in (
                self.zero_score_rate_microunits,
                self.tool_time_share_microunits,
                self.read_time_share_microunits,
                self.grep_time_share_microunits,
            ):
                _unit(value)
            if (
                self.total_wall_time_ns == 0
                or self.total_tool_time_ns
                != self.total_read_time_ns + self.total_grep_time_ns
                or self.total_tool_time_ns > self.total_wall_time_ns
                or self.tool_time_share_microunits
                != _ratio_microunits(self.total_tool_time_ns, self.total_wall_time_ns)
                or self.read_time_share_microunits
                != _time_share_microunits(self.total_read_time_ns, self.total_tool_time_ns)
                or self.grep_time_share_microunits
                != _time_share_microunits(self.total_grep_time_ns, self.total_tool_time_ns)
            ):
                raise ValueError
        except Exception:
            raise ValueError("invalid DCI workflow metrics") from None

    def to_mapping(self) -> dict[str, int]:
        return {
            "zero_score_rate_microunits": self.zero_score_rate_microunits,
            "median_agent_total_tokens": self.median_agent_total_tokens,
            "median_tool_call_count": self.median_tool_call_count,
            "median_wall_time_ns": self.median_wall_time_ns,
            "median_tool_time_ns": self.median_tool_time_ns,
            "median_read_call_count": self.median_read_call_count,
            "median_grep_call_count": self.median_grep_call_count,
            "median_read_time_ns": self.median_read_time_ns,
            "median_grep_time_ns": self.median_grep_time_ns,
            "median_question_word_count": self.median_question_word_count,
            "total_tool_error_count": self.total_tool_error_count,
            "total_wall_time_ns": self.total_wall_time_ns,
            "total_tool_time_ns": self.total_tool_time_ns,
            "total_read_time_ns": self.total_read_time_ns,
            "total_grep_time_ns": self.total_grep_time_ns,
            "tool_time_share_microunits": self.tool_time_share_microunits,
            "read_time_share_microunits": self.read_time_share_microunits,
            "grep_time_share_microunits": self.grep_time_share_microunits,
        }


@dataclass(frozen=True, slots=True)
class DciAggregateWorkflowMetrics:
    """Cross-dataset workflow metrics with no score-derived statistic."""

    median_agent_total_tokens: int
    median_tool_call_count: int
    median_wall_time_ns: int
    median_tool_time_ns: int
    median_read_call_count: int
    median_grep_call_count: int
    median_read_time_ns: int
    median_grep_time_ns: int
    median_question_word_count: int
    total_tool_error_count: int
    total_wall_time_ns: int
    total_tool_time_ns: int
    total_read_time_ns: int
    total_grep_time_ns: int
    tool_time_share_microunits: int
    read_time_share_microunits: int
    grep_time_share_microunits: int

    def __post_init__(self) -> None:
        try:
            if type(self) is not DciAggregateWorkflowMetrics:
                raise ValueError
            for value in (
                self.median_agent_total_tokens,
                self.median_tool_call_count,
                self.median_wall_time_ns,
                self.median_tool_time_ns,
                self.median_read_call_count,
                self.median_grep_call_count,
                self.median_read_time_ns,
                self.median_grep_time_ns,
                self.median_question_word_count,
                self.total_tool_error_count,
                self.total_wall_time_ns,
                self.total_tool_time_ns,
                self.total_read_time_ns,
                self.total_grep_time_ns,
            ):
                _checked(value)
            for value in (
                self.tool_time_share_microunits,
                self.read_time_share_microunits,
                self.grep_time_share_microunits,
            ):
                _unit(value)
            if (
                self.total_wall_time_ns == 0
                or self.total_tool_time_ns
                != self.total_read_time_ns + self.total_grep_time_ns
                or self.total_tool_time_ns > self.total_wall_time_ns
                or self.tool_time_share_microunits
                != _ratio_microunits(self.total_tool_time_ns, self.total_wall_time_ns)
                or self.read_time_share_microunits
                != _time_share_microunits(self.total_read_time_ns, self.total_tool_time_ns)
                or self.grep_time_share_microunits
                != _time_share_microunits(self.total_grep_time_ns, self.total_tool_time_ns)
            ):
                raise ValueError
        except Exception:
            raise ValueError("invalid DCI aggregate workflow metrics") from None

    def to_mapping(self) -> dict[str, int]:
        return {
            "median_agent_total_tokens": self.median_agent_total_tokens,
            "median_tool_call_count": self.median_tool_call_count,
            "median_wall_time_ns": self.median_wall_time_ns,
            "median_tool_time_ns": self.median_tool_time_ns,
            "median_read_call_count": self.median_read_call_count,
            "median_grep_call_count": self.median_grep_call_count,
            "median_read_time_ns": self.median_read_time_ns,
            "median_grep_time_ns": self.median_grep_time_ns,
            "median_question_word_count": self.median_question_word_count,
            "total_tool_error_count": self.total_tool_error_count,
            "total_wall_time_ns": self.total_wall_time_ns,
            "total_tool_time_ns": self.total_tool_time_ns,
            "total_read_time_ns": self.total_read_time_ns,
            "total_grep_time_ns": self.total_grep_time_ns,
            "tool_time_share_microunits": self.tool_time_share_microunits,
            "read_time_share_microunits": self.read_time_share_microunits,
            "grep_time_share_microunits": self.grep_time_share_microunits,
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
    resolution_available_queries: int
    resolution_total_queries: int
    resolution_coverage_status: Literal["not-available"]
    aggregate_evaluation_sha256: str
    workflow_metrics: DciWorkflowMetrics
    coverage_available_queries: int = 0
    coverage_total_queries: int = 0
    coverage_median_any_microunits: int | None = None
    coverage_median_mean_microunits: int | None = None
    coverage_median_all_microunits: int | None = None
    retained_available_queries: int = 0
    retained_median_microunits: int | None = None
    tool_observation_count: int = 0
    surfaced_gold_count: int = 0
    model_call_count: int = 0
    context_frame_count: int = 0
    missing_boundary_count: int = 0
    integrity_failure_count: int = 0
    coverage_evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        try:
            expected = _REQUIRED.get(self.dataset_id) if type(self.dataset_id) is str else None
            if (
                type(self) is not DciDatasetObservation
                or expected is None
                or type(self.metric_name) is not str
                or self.metric_name != expected[1]
                or self.selected_count != expected[2]
                or self.total_count != expected[2]
                or _checked(self.failed_count) > self.total_count
                or _checked(self.corpus_file_count) > _MAX_INT
                or _unit(self.score_microunits) != self.score_microunits
                or _unit(self.reference_score_microunits) != self.reference_score_microunits
                or _signed(self.reference_gap_microunits)
                != self.score_microunits - self.reference_score_microunits
                or type(self.reference_status) is not str
                or self.reference_status != "reference-only"
                or _checked(self.resolution_available_queries) > self.selected_count
                or self.resolution_available_queries != 0
                or self.resolution_total_queries != self.selected_count
                or type(self.resolution_coverage_status) is not str
                or self.resolution_coverage_status != "not-available"
                or _sha256(self.aggregate_evaluation_sha256)
                != self.aggregate_evaluation_sha256
                or type(self.workflow_metrics) is not DciWorkflowMetrics
            ):
                raise ValueError
            coverage_values = (
                self.coverage_median_any_microunits,
                self.coverage_median_mean_microunits,
                self.coverage_median_all_microunits,
                self.retained_median_microunits,
            )
            if self.coverage_total_queries == 0:
                if (
                    self.coverage_available_queries != 0
                    or any(value is not None for value in coverage_values)
                    or any(
                        value != 0
                        for value in (
                            self.retained_available_queries,
                            self.tool_observation_count,
                            self.surfaced_gold_count,
                            self.model_call_count,
                            self.context_frame_count,
                            self.missing_boundary_count,
                            self.integrity_failure_count,
                        )
                    )
                    or self.coverage_evidence_sha256 is not None
                ):
                    raise ValueError
            else:
                coverage = DciCoverageDatasetObservation(
                    dataset_id=self.dataset_id,
                    coverage_available_queries=self.coverage_available_queries,
                    coverage_total_queries=self.coverage_total_queries,
                    coverage_median_any_microunits=self.coverage_median_any_microunits,
                    coverage_median_mean_microunits=self.coverage_median_mean_microunits,
                    coverage_median_all_microunits=self.coverage_median_all_microunits,
                    retained_available_queries=self.retained_available_queries,
                    retained_median_microunits=self.retained_median_microunits,
                    tool_observation_count=self.tool_observation_count,
                    surfaced_gold_count=self.surfaced_gold_count,
                    model_call_count=self.model_call_count,
                    context_frame_count=self.context_frame_count,
                    missing_boundary_count=self.missing_boundary_count,
                    integrity_failure_count=self.integrity_failure_count,
                    evidence_sha256=str(self.coverage_evidence_sha256),
                )
                if coverage.dataset_id != self.dataset_id:
                    raise ValueError
            object.__setattr__(self, "workflow_metrics", _copy_workflow_metrics(self.workflow_metrics))
        except Exception:
            raise ValueError("invalid DCI dataset observation") from None

    def to_mapping(self) -> dict[str, object]:
        value: dict[str, object] = {
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
            "resolution_available_queries": self.resolution_available_queries,
            "resolution_total_queries": self.resolution_total_queries,
            "resolution_coverage_status": self.resolution_coverage_status,
            "aggregate_evaluation_sha256": self.aggregate_evaluation_sha256,
            "workflow_metrics": self.workflow_metrics.to_mapping(),
        }
        if self.coverage_total_queries:
            value["coverage"] = {
                "available_queries": self.coverage_available_queries,
                "total_queries": self.coverage_total_queries,
                "median_any_microunits": self.coverage_median_any_microunits,
                "median_mean_microunits": self.coverage_median_mean_microunits,
                "median_all_microunits": self.coverage_median_all_microunits,
                "retained_available_queries": self.retained_available_queries,
                "retained_median_microunits": self.retained_median_microunits,
                "tool_observation_count": self.tool_observation_count,
                "surfaced_gold_count": self.surfaced_gold_count,
                "model_call_count": self.model_call_count,
                "context_frame_count": self.context_frame_count,
                "missing_boundary_count": self.missing_boundary_count,
                "integrity_failure_count": self.integrity_failure_count,
                "evidence_sha256": self.coverage_evidence_sha256,
            }
        return value


@dataclass(frozen=True, slots=True)
class DciComponentComparison:
    dataset_id: str
    component: Literal["runtime", "model", "toolset", "prompt", "context", "metric"]
    relation_to_bright_biology: Literal["same", "different"]

    def __post_init__(self) -> None:
        if (
            type(self) is not DciComponentComparison
            or type(self.dataset_id) is not str
            or self.dataset_id not in _COMPARISON_DATASETS
            or type(self.component) is not str
            or self.component not in _COMPONENTS
            or type(self.relation_to_bright_biology) is not str
            or self.relation_to_bright_biology not in {"same", "different"}
        ):
            raise ValueError("invalid DCI component comparison")

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
    dataset_case_counts: tuple[tuple[str, int], ...]
    dataset_case_scope_sha256s: tuple[tuple[str, str], ...]
    case_scope_sha256: str
    baseline_operation_count: int
    candidate_operation_count: int
    sole_variable_sha256: str

    def __post_init__(self) -> None:
        try:
            if (
                type(self) is not DciProposalSummary
                or type(self.code) is not str
                or self.code not in _PROPOSAL_CODES
                or _sha256(self.proposal_sha256) != self.proposal_sha256
                or self.requires_operator_authorization is not True
                or self.execution_authorized is not False
            ):
                raise ValueError
            _checked(self.agent_operation_cap)
            _checked(self.max_cost_microusd)
            if self.code == "coverage-instrumentation":
                dataset_ids = _COVERAGE_DATASETS
                expected = (50, 5_000_000, 2, None, None, None, 50, 0)
                purpose = "coverage"
                sole_variable = "trajectory-coverage-instrumentation-only"
            else:
                if self.prerequisite_proposal_sha256 is None:
                    raise ValueError
                _sha256(self.prerequisite_proposal_sha256)
                dataset_ids = _BRIGHT_DATASETS
                expected = (
                    80, 8_000_000, None, self.prerequisite_proposal_sha256,
                    50_000, 250_000, 40, 40,
                )
                purpose = "paired-bright"
                sole_variable = "retrieval-query-planning"
            if (
                type(self.dataset_case_counts) is not tuple
                or type(self.dataset_case_scope_sha256s) is not tuple
                or tuple(item[0] for item in self.dataset_case_counts) != dataset_ids
                or tuple(item[0] for item in self.dataset_case_scope_sha256s) != dataset_ids
                or any(
                    type(item) is not tuple
                    or len(item) != 2
                    or type(item[0]) is not str
                    or type(item[1]) is not int
                    or item[1] != 10
                    for item in self.dataset_case_counts
                )
                or any(
                    type(item) is not tuple
                    or len(item) != 2
                    or type(item[0]) is not str
                    or _sha256(item[1]) != item[1]
                    for item in self.dataset_case_scope_sha256s
                )
                or _sha256(self.case_scope_sha256) != self.case_scope_sha256
                or _sha256(self.sole_variable_sha256) != self.sole_variable_sha256
                or self.sole_variable_sha256
                != _digest("proposal-sole-variable", sole_variable)
                or self.case_scope_sha256
                != _combined_case_scope_sha256(
                    self.dataset_case_scope_sha256s, dataset_ids, purpose
                )
            ):
                raise ValueError
            actual = (
                self.agent_operation_cap,
                self.max_cost_microusd,
                self.infrastructure_failure_stop,
                self.prerequisite_proposal_sha256,
                self.minimum_mean_ndcg_gain_microunits,
                self.maximum_cost_or_time_increase_microunits,
                self.baseline_operation_count,
                self.candidate_operation_count,
            )
            if actual != expected:
                raise ValueError
        except Exception:
            raise ValueError("invalid DCI proposal summary") from None

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
            "dataset_case_counts": [list(item) for item in self.dataset_case_counts],
            "dataset_case_scope_sha256s": [
                list(item) for item in self.dataset_case_scope_sha256s
            ],
            "case_scope_sha256": self.case_scope_sha256,
            "baseline_operation_count": self.baseline_operation_count,
            "candidate_operation_count": self.candidate_operation_count,
            "sole_variable_sha256": self.sole_variable_sha256,
        }


@dataclass(frozen=True, slots=True)
class DciDiagnosisReport:
    observations: tuple[DciDatasetObservation, ...]
    component_comparisons: tuple[DciComponentComparison, ...]
    findings: tuple[Finding, ...]
    missing_evidence: tuple[str, ...]
    hypothesis_codes: tuple[str, ...]
    proposals: tuple[DciProposalSummary, ...]
    aggregate_workflow_metrics: DciAggregateWorkflowMetrics
    diagnosis_bundle: DiagnosisBundle
    coverage_experiment: DciCoverageExperimentObservation | None = None
    query_decomposition_gate: Literal[
        "blocked-by-coverage", "ready-for-authorization"
    ] = "blocked-by-coverage"
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            if type(self) is not DciDiagnosisReport or any(
                type(value) is not tuple
                for value in (
                    self.observations,
                    self.component_comparisons,
                    self.findings,
                    self.missing_evidence,
                    self.hypothesis_codes,
                    self.proposals,
                )
            ):
                raise ValueError
            observations = tuple(_copy_observation(item) for item in self.observations)
            components = tuple(_copy_component(item) for item in self.component_comparisons)
            findings = tuple(_copy_finding(item) for item in self.findings)
            proposals = tuple(_copy_proposal_summary(item) for item in self.proposals)
            coverage_experiment = (
                None
                if self.coverage_experiment is None
                else _copy_coverage_experiment(self.coverage_experiment)
            )
            expected_missing = _missing_codes(coverage_experiment)
            expected_gate = (
                "ready-for-authorization"
                if coverage_experiment is not None and coverage_experiment.complete
                else "blocked-by-coverage"
            )
            aggregate_metrics = _copy_aggregate_workflow_metrics(
                self.aggregate_workflow_metrics
            )
            diagnosis_bundle = _copy_diagnosis_bundle(self.diagnosis_bundle)
            expected_components = tuple(
                (dataset_id, component)
                for dataset_id in _COMPARISON_DATASETS
                for component in _COMPONENTS
            )
            expected_finding_codes = {
                ("observed", _digest("code", f"observed:{dataset_id}"))
                for dataset_id in _DATASET_ORDER
            }
            if coverage_experiment is not None:
                expected_finding_codes.update(
                    (
                        "observed",
                        _digest("code", f"observed:coverage:{dataset_id}"),
                    )
                    for dataset_id in _COVERAGE_DATASETS
                )
            expected_finding_codes.update(
                ("missing-evidence", _digest("code", f"missing:{code}"))
                for code in expected_missing
            )
            expected_finding_codes.update(
                ("hypothesis", _digest("code", f"hypothesis:{code}"))
                for code in _HYPOTHESIS_CODES
            )
            expected_finding_codes.add(
                ("not-comparable", _digest("code", "not-comparable:paper-reference"))
            )
            evaluation_ids = tuple(
                item.aggregate_evaluation_sha256 for item in observations
            )
            coverage_evaluation_ids = (
                {}
                if coverage_experiment is None
                else {
                    dataset.dataset_id: item.evaluation_sha256
                    for dataset in coverage_experiment.datasets
                    for item in coverage_evaluation_values(coverage_experiment)[1]
                    if item.trace_sha256 == dataset.evidence_sha256
                }
            )
            bundle_evaluation_ids = (
                *evaluation_ids,
                *coverage_evaluation_ids.values(),
            )
            expected_findings = tuple(
                sorted(
                    _findings(
                        observations,
                        {
                            item.dataset_id: item.aggregate_evaluation_sha256
                            for item in observations
                        },
                        expected_missing,
                        coverage_experiment,
                        coverage_evaluation_ids,
                    ),
                    key=lambda item: item.finding_sha256,
                )
            )
            expected_bundle_proposals = _fixed_pathlight_proposals(
                expected_findings, proposals
            )
            if (
                tuple(item.dataset_id for item in observations) != _DATASET_ORDER
                or len(set(evaluation_ids)) != len(evaluation_ids)
                or tuple((item.dataset_id, item.component) for item in components)
                != expected_components
                or len({(item.dataset_id, item.component) for item in components})
                != len(components)
                or findings
                != tuple(sorted(findings, key=lambda item: item.finding_sha256))
                or findings != expected_findings
                or len({item.finding_sha256 for item in findings}) != len(findings)
                or {(item.category, item.finding_code_sha256) for item in findings}
                != expected_finding_codes
                or self.missing_evidence != expected_missing
                or any(type(code) is not str for code in self.missing_evidence)
                or self.hypothesis_codes != _HYPOTHESIS_CODES
                or any(type(code) is not str for code in self.hypothesis_codes)
                or tuple(item.code for item in proposals) != _PROPOSAL_CODES
                or proposals[1].prerequisite_proposal_sha256
                != proposals[0].proposal_sha256
                or findings != diagnosis_bundle.findings
                or set(bundle_evaluation_ids)
                != set(diagnosis_bundle.evaluation_sha256s)
                or len(diagnosis_bundle.evaluation_sha256s) != len(_DATASET_ORDER)
                + (0 if coverage_experiment is None else len(_COVERAGE_DATASETS))
                or len(diagnosis_bundle.experiment_bundle_sha256s)
                != len(_DATASET_ORDER)
                or {item.proposal_sha256 for item in proposals}
                != {item.proposal_sha256 for item in diagnosis_bundle.proposals}
                or tuple(item.proposal_sha256 for item in proposals)
                != tuple(item.proposal_sha256 for item in expected_bundle_proposals)
                or set(diagnosis_bundle.proposals) != set(expected_bundle_proposals)
                or self.query_decomposition_gate != expected_gate
            ):
                raise ValueError
            normalized = (
                observations,
                components,
                findings,
                expected_missing,
                _HYPOTHESIS_CODES,
                proposals,
                aggregate_metrics,
                diagnosis_bundle,
                coverage_experiment,
                expected_gate,
            )
            for name, value in zip(
                (
                    "observations",
                    "component_comparisons",
                    "findings",
                    "missing_evidence",
                    "hypothesis_codes",
                    "proposals",
                    "aggregate_workflow_metrics",
                    "diagnosis_bundle",
                    "coverage_experiment",
                    "query_decomposition_gate",
                ),
                normalized,
                strict=True,
            ):
                object.__setattr__(self, name, value)
            object.__setattr__(self, "report_sha256", _digest("report", self._unsigned_mapping()))
        except Exception:
            raise ValueError("invalid DCI diagnosis report") from None

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
        value: dict[str, object] = {
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
        if self.coverage_experiment is not None:
            value["coverage_experiment"] = self.coverage_experiment.to_mapping()
            value["query_decomposition_gate"] = self.query_decomposition_gate
        return value

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "report_sha256": self.report_sha256}


def write_authorization_gate_report(report: DciDiagnosisReport, path: Path) -> None:
    """Publish one coverage-complete, DCI-owned authorization gate report.

    The report is evidence of a completed coverage observation only; it never
    grants execution authority.  It is deliberately emitted from a verified
    ``DciDiagnosisReport`` while the diagnosis command still owns its atomic
    publication staging tree.
    """

    try:
        if (
            type(report) is not DciDiagnosisReport
            or not isinstance(path, Path)
            or path.name != AUTHORIZATION_GATE_REPORT_FILENAME
            or report.coverage_experiment is None
            or not report.coverage_experiment.complete
            or report.query_decomposition_gate != "ready-for-authorization"
        ):
            raise ValueError
        coverage = report.coverage_experiment
        query = next(
            item
            for item in report.proposals
            if item.code == "retrieval-query-decomposition"
        )
        if (
            query.proposal_sha256
            not in {item.proposal_sha256 for item in report.diagnosis_bundle.proposals}
        ):
            raise ValueError
        value: dict[str, object] = {
            "schema": _AUTHORIZATION_GATE_REPORT_SCHEMA,
            "diagnosis_bundle_sha256": report.diagnosis_bundle.bundle_sha256,
            "diagnosis_report_sha256": report.report_sha256,
            "query_proposal_sha256": query.proposal_sha256,
            "query_scope_sha256": query.case_scope_sha256,
            "coverage_experiment_sha256": coverage.experiment_sha256,
            "coverage_plan_sha256": coverage.plan_sha256,
            "coverage_proposal_sha256": coverage.proposal_sha256,
            "coverage_scope_sha256": coverage.scope_sha256,
            "coverage_variant_sha256": coverage.variant_sha256,
            "coverage_registry_set_sha256": coverage.registry_set_sha256,
            "coverage_authorization_sha256": coverage.authorization_sha256,
            "coverage_receipt_set_sha256": coverage.receipt_set_sha256,
            "coverage_evidence_set_sha256": _digest(
                "authorization-gate-evidence-set",
                [
                    {
                        "dataset_id": item.dataset_id,
                        "evidence_sha256": item.evidence_sha256,
                    }
                    for item in coverage.datasets
                ],
            ),
            "coverage_dataset_count": len(coverage.datasets),
            "coverage_agent_operation_count": coverage.agent_operation_count,
            "coverage_judge_operation_count": coverage.judge_operation_count,
            "coverage_infrastructure_failure_count": (
                coverage.infrastructure_failure_count
            ),
            "coverage_complete": True,
            "query_decomposition_gate": "ready-for-authorization",
        }
        value["gate_report_sha256"] = _canonical_gate_digest(value)
        encoded = _canonical_gate_bytes(value)
        _validate_authorization_gate_report(value)
        write_private_file(path, encoded)
    except Exception:
        raise DciDiagnosisError(_ERROR) from None


def read_authorization_gate_report(path: Path) -> dict[str, object]:
    """Read a descriptor-verified, authorization-ready DCI gate report."""

    try:
        if not isinstance(path, Path) or path.name != AUTHORIZATION_GATE_REPORT_FILENAME:
            raise ValueError
        encoded = read_private_file(path, _MAX_GATE_REPORT_BYTES)
        value = json.loads(encoded, object_pairs_hook=_unique_gate_object)
        if encoded != _canonical_gate_bytes(value) or type(value) is not dict:
            raise ValueError
        _validate_authorization_gate_report(value)
        return dict(value)
    except Exception:
        raise DciDiagnosisError(_ERROR) from None


def _validate_authorization_gate_report(value: object) -> None:
    fields = {
        "schema",
        "diagnosis_bundle_sha256",
        "diagnosis_report_sha256",
        "query_proposal_sha256",
        "query_scope_sha256",
        "coverage_experiment_sha256",
        "coverage_plan_sha256",
        "coverage_proposal_sha256",
        "coverage_scope_sha256",
        "coverage_variant_sha256",
        "coverage_registry_set_sha256",
        "coverage_authorization_sha256",
        "coverage_receipt_set_sha256",
        "coverage_evidence_set_sha256",
        "coverage_dataset_count",
        "coverage_agent_operation_count",
        "coverage_judge_operation_count",
        "coverage_infrastructure_failure_count",
        "coverage_complete",
        "query_decomposition_gate",
        "gate_report_sha256",
    }
    if type(value) is not dict or set(value) != fields:
        raise ValueError
    unsigned = dict(value)
    digest = unsigned.pop("gate_report_sha256")
    hashes = (
        "diagnosis_bundle_sha256",
        "diagnosis_report_sha256",
        "query_proposal_sha256",
        "query_scope_sha256",
        "coverage_experiment_sha256",
        "coverage_plan_sha256",
        "coverage_proposal_sha256",
        "coverage_scope_sha256",
        "coverage_variant_sha256",
        "coverage_registry_set_sha256",
        "coverage_authorization_sha256",
        "coverage_receipt_set_sha256",
        "coverage_evidence_set_sha256",
    )
    if (
        unsigned.get("schema") != _AUTHORIZATION_GATE_REPORT_SCHEMA
        or any(_sha256(unsigned.get(name)) != unsigned.get(name) for name in hashes)
        or unsigned.get("coverage_dataset_count") != len(_COVERAGE_DATASETS)
        or unsigned.get("coverage_agent_operation_count") != 50
        or unsigned.get("coverage_judge_operation_count") != 0
        or unsigned.get("coverage_infrastructure_failure_count") != 0
        or unsigned.get("coverage_complete") is not True
        or unsigned.get("query_decomposition_gate") != "ready-for-authorization"
        or _sha256(digest) != digest
        or not hmac.compare_digest(str(digest), _canonical_gate_digest(unsigned))
    ):
        raise ValueError


def _canonical_gate_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _canonical_gate_digest(value: object) -> str:
    return hashlib.sha256(_canonical_gate_bytes(value)).hexdigest()


def _unique_gate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def _copy_workflow_metrics(value: object) -> DciWorkflowMetrics:
    if type(value) is not DciWorkflowMetrics:
        raise ValueError
    return DciWorkflowMetrics(**value.to_mapping())


def _copy_aggregate_workflow_metrics(value: object) -> DciAggregateWorkflowMetrics:
    if type(value) is not DciAggregateWorkflowMetrics:
        raise ValueError
    return DciAggregateWorkflowMetrics(**value.to_mapping())


def _copy_observation(value: object) -> DciDatasetObservation:
    if type(value) is not DciDatasetObservation:
        raise ValueError
    return DciDatasetObservation(
        dataset_id=value.dataset_id,
        metric_name=value.metric_name,
        selected_count=value.selected_count,
        total_count=value.total_count,
        failed_count=value.failed_count,
        corpus_file_count=value.corpus_file_count,
        score_microunits=value.score_microunits,
        reference_score_microunits=value.reference_score_microunits,
        reference_gap_microunits=value.reference_gap_microunits,
        reference_status=value.reference_status,
        resolution_available_queries=value.resolution_available_queries,
        resolution_total_queries=value.resolution_total_queries,
        resolution_coverage_status=value.resolution_coverage_status,
        aggregate_evaluation_sha256=value.aggregate_evaluation_sha256,
        workflow_metrics=_copy_workflow_metrics(value.workflow_metrics),
        coverage_available_queries=value.coverage_available_queries,
        coverage_total_queries=value.coverage_total_queries,
        coverage_median_any_microunits=value.coverage_median_any_microunits,
        coverage_median_mean_microunits=value.coverage_median_mean_microunits,
        coverage_median_all_microunits=value.coverage_median_all_microunits,
        retained_available_queries=value.retained_available_queries,
        retained_median_microunits=value.retained_median_microunits,
        tool_observation_count=value.tool_observation_count,
        surfaced_gold_count=value.surfaced_gold_count,
        model_call_count=value.model_call_count,
        context_frame_count=value.context_frame_count,
        missing_boundary_count=value.missing_boundary_count,
        integrity_failure_count=value.integrity_failure_count,
        coverage_evidence_sha256=value.coverage_evidence_sha256,
    )


def _copy_component(value: object) -> DciComponentComparison:
    if type(value) is not DciComponentComparison:
        raise ValueError
    return DciComponentComparison(
        value.dataset_id, value.component, value.relation_to_bright_biology
    )


def _copy_proposal_summary(value: object) -> DciProposalSummary:
    if type(value) is not DciProposalSummary:
        raise ValueError
    return DciProposalSummary(
        value.code,
        value.proposal_sha256,
        value.requires_operator_authorization,
        value.execution_authorized,
        value.agent_operation_cap,
        value.max_cost_microusd,
        value.infrastructure_failure_stop,
        value.prerequisite_proposal_sha256,
        value.minimum_mean_ndcg_gain_microunits,
        value.maximum_cost_or_time_increase_microunits,
        value.dataset_case_counts,
        value.dataset_case_scope_sha256s,
        value.case_scope_sha256,
        value.baseline_operation_count,
        value.candidate_operation_count,
        value.sole_variable_sha256,
    )


def _copy_finding(value: object) -> Finding:
    if type(value) is not Finding:
        raise ValueError
    return validate_finding(value.to_mapping())


def _copy_diagnosis_bundle(value: object) -> DiagnosisBundle:
    if type(value) is not DiagnosisBundle:
        raise ValueError
    if any(
        type(items) is not tuple
        for items in (
            value.experiment_bundle_sha256s,
            value.evaluation_sha256s,
            value.findings,
            value.proposals,
        )
    ):
        raise ValueError
    experiment_ids = tuple(_sha256(item) for item in value.experiment_bundle_sha256s)
    evaluation_ids = tuple(_sha256(item) for item in value.evaluation_sha256s)
    findings = tuple(_copy_finding(item) for item in value.findings)
    proposals = tuple(_copy_pathlight_proposal(item) for item in value.proposals)
    canonical = DiagnosisBundle.build(
        experiment_bundle_sha256s=experiment_ids,
        evaluation_sha256s=evaluation_ids,
        findings=findings,
        proposals=proposals,
    )
    if (
        experiment_ids != tuple(sorted(experiment_ids))
        or evaluation_ids != tuple(sorted(evaluation_ids))
        or findings != canonical.findings
        or proposals != canonical.proposals
        or not hmac.compare_digest(_sha256(value.bundle_sha256), canonical.bundle_sha256)
    ):
        raise ValueError
    return canonical


def _copy_pathlight_proposal(value: object) -> Proposal:
    if type(value) is not Proposal:
        raise ValueError
    canonical = Proposal(
        value.finding_sha256,
        value.change_sha256,
        value.scope_sha256,
        value.success_criteria_sha256,
        value.stop_criteria_sha256,
        value.budget_sha256,
        value.status,
        value.requires_operator_authorization,
        value.execution_authorized,
    )
    if not hmac.compare_digest(_sha256(value.proposal_sha256), canonical.proposal_sha256):
        raise ValueError
    return canonical


def diagnose_recommended_pack(
    runs: object,
    *,
    coverage_experiment: DciCoverageExperimentObservation | None = None,
) -> DciDiagnosisReport:
    """Diagnose exactly the six fixed recovered DCI cohorts without execution."""

    result: DciDiagnosisReport | None = None
    try:
        coverage = (
            None
            if coverage_experiment is None
            else _copy_coverage_experiment(coverage_experiment)
        )
        normalized = _validate_pack(runs)
        experiments = {dataset_id: recovered_run_to_experiment(run) for dataset_id, run in normalized.items()}
        references = {dataset_id: load_paper_reference(dataset_id) for dataset_id in _DATASET_ORDER}
        observations = tuple(
            _observation(dataset_id, normalized[dataset_id], experiments[dataset_id], references[dataset_id])
            for dataset_id in _DATASET_ORDER
        )
        observations = _merge_coverage_observations(observations, coverage)
        aggregate_ids = {item.dataset_id: item.aggregate_evaluation_sha256 for item in observations}
        coverage_evaluation_ids = (
            {}
            if coverage is None
            else {
                dataset.dataset_id: item.evaluation_sha256
                for dataset in coverage.datasets
                for item in coverage_evaluation_values(coverage)[1]
                if item.trace_sha256 == dataset.evidence_sha256
            }
        )
        missing_evidence = _missing_codes(coverage)
        findings = _findings(
            observations,
            aggregate_ids,
            missing_evidence,
            coverage,
            coverage_evaluation_ids,
        )
        bundle, public_proposals = _diagnosis_bundle(
            experiments,
            aggregate_ids,
            findings,
            normalized,
            coverage,
            coverage_evaluation_ids,
        )
        comparisons = _component_comparisons(normalized)
        result = DciDiagnosisReport(
            observations=observations,
            component_comparisons=comparisons,
            findings=tuple(sorted(findings, key=lambda item: item.finding_sha256)),
            missing_evidence=missing_evidence,
            hypothesis_codes=_HYPOTHESIS_CODES,
            proposals=public_proposals,
            aggregate_workflow_metrics=_aggregate_workflow_metrics(
                tuple(case for run in normalized.values() for case in run.cases)
            ),
            diagnosis_bundle=bundle,
            coverage_experiment=coverage,
            query_decomposition_gate=(
                "ready-for-authorization"
                if coverage is not None and coverage.complete
                else "blocked-by-coverage"
            ),
        )
    except Exception:
        pass
    if result is None:
        raise DciDiagnosisError(_ERROR) from None
    return result


def _merge_coverage_observations(
    observations: tuple[DciDatasetObservation, ...],
    coverage: DciCoverageExperimentObservation | None,
) -> tuple[DciDatasetObservation, ...]:
    if coverage is None:
        return observations
    by_dataset = {item.dataset_id: item for item in coverage.datasets}
    return tuple(
        item
        if item.dataset_id not in by_dataset
        else replace(
            item,
            coverage_available_queries=by_dataset[
                item.dataset_id
            ].coverage_available_queries,
            coverage_total_queries=by_dataset[item.dataset_id].coverage_total_queries,
            coverage_median_any_microunits=by_dataset[
                item.dataset_id
            ].coverage_median_any_microunits,
            coverage_median_mean_microunits=by_dataset[
                item.dataset_id
            ].coverage_median_mean_microunits,
            coverage_median_all_microunits=by_dataset[
                item.dataset_id
            ].coverage_median_all_microunits,
            retained_available_queries=by_dataset[
                item.dataset_id
            ].retained_available_queries,
            retained_median_microunits=by_dataset[
                item.dataset_id
            ].retained_median_microunits,
            tool_observation_count=by_dataset[item.dataset_id].tool_observation_count,
            surfaced_gold_count=by_dataset[item.dataset_id].surfaced_gold_count,
            model_call_count=by_dataset[item.dataset_id].model_call_count,
            context_frame_count=by_dataset[item.dataset_id].context_frame_count,
            missing_boundary_count=by_dataset[item.dataset_id].missing_boundary_count,
            integrity_failure_count=by_dataset[
                item.dataset_id
            ].integrity_failure_count,
            coverage_evidence_sha256=by_dataset[item.dataset_id].evidence_sha256,
        )
        for item in observations
    )


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
    resolution_available_queries = sum(
        case.resolution_status == "available" for case in run.cases
    )
    return DciDatasetObservation(
        dataset_id=dataset_id,
        metric_name=run.metric_name,
        selected_count=run.selected_count,
        total_count=run.total_count,
        failed_count=run.failed_count,
        corpus_file_count=run.corpus_file_count,
        score_microunits=run.metric_value_microunits,
        reference_score_microunits=reference.value_microunits,
        reference_gap_microunits=gap,
        reference_status=reference.comparison_status,
        resolution_available_queries=resolution_available_queries,
        resolution_total_queries=run.selected_count,
        resolution_coverage_status="not-available",
        aggregate_evaluation_sha256=aggregates[0].evaluation_sha256,
        workflow_metrics=_workflow_metrics(run.cases),
    )


def _workflow_metrics(cases: tuple[DciRecoveredCase, ...]) -> DciWorkflowMetrics:
    if not cases:
        raise ValueError
    def values(attribute: str) -> tuple[int, ...]:
        return tuple(getattr(case, attribute) for case in cases)

    zero_count = sum(case.metric_value_microunits == 0 for case in cases)
    wall = _sum(values("wall_time_ns"))
    tool = _sum(values("tool_time_ns"))
    read = _sum(values("read_time_ns"))
    grep = _sum(values("grep_time_ns"))
    return DciWorkflowMetrics(
        zero_score_rate_microunits=_ratio_microunits(zero_count, len(cases)),
        median_agent_total_tokens=_median(values("agent_total_tokens")),
        median_tool_call_count=_median(values("tool_call_count")),
        median_wall_time_ns=_median(values("wall_time_ns")),
        median_tool_time_ns=_median(values("tool_time_ns")),
        median_read_call_count=_median(values("read_call_count")),
        median_grep_call_count=_median(values("grep_call_count")),
        median_read_time_ns=_median(values("read_time_ns")),
        median_grep_time_ns=_median(values("grep_time_ns")),
        median_question_word_count=_median(values("question_word_count")),
        total_tool_error_count=_sum(values("tool_error_count")),
        total_wall_time_ns=wall,
        total_tool_time_ns=tool,
        total_read_time_ns=read,
        total_grep_time_ns=grep,
        tool_time_share_microunits=_ratio_microunits(tool, wall),
        read_time_share_microunits=_time_share_microunits(read, tool),
        grep_time_share_microunits=_time_share_microunits(grep, tool),
    )


def _aggregate_workflow_metrics(
    cases: tuple[DciRecoveredCase, ...],
) -> DciAggregateWorkflowMetrics:
    """Aggregate workflow behavior only; scores are intentionally never read."""

    if not cases:
        raise ValueError

    def values(attribute: str) -> tuple[int, ...]:
        return tuple(getattr(case, attribute) for case in cases)

    wall = _sum(values("wall_time_ns"))
    tool = _sum(values("tool_time_ns"))
    read = _sum(values("read_time_ns"))
    grep = _sum(values("grep_time_ns"))
    return DciAggregateWorkflowMetrics(
        median_agent_total_tokens=_median(values("agent_total_tokens")),
        median_tool_call_count=_median(values("tool_call_count")),
        median_wall_time_ns=_median(values("wall_time_ns")),
        median_tool_time_ns=_median(values("tool_time_ns")),
        median_read_call_count=_median(values("read_call_count")),
        median_grep_call_count=_median(values("grep_call_count")),
        median_read_time_ns=_median(values("read_time_ns")),
        median_grep_time_ns=_median(values("grep_time_ns")),
        median_question_word_count=_median(values("question_word_count")),
        total_tool_error_count=_sum(values("tool_error_count")),
        total_wall_time_ns=wall,
        total_tool_time_ns=tool,
        total_read_time_ns=read,
        total_grep_time_ns=grep,
        tool_time_share_microunits=_ratio_microunits(tool, wall),
        read_time_share_microunits=_time_share_microunits(read, tool),
        grep_time_share_microunits=_time_share_microunits(grep, tool),
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
        for dataset_id in _COMPARISON_DATASETS
        for component in _COMPONENTS
    )


def _finding(category: str, code: str, evidence: tuple[str, ...], counter: tuple[str, ...] = ()) -> Finding:
    return Finding(category, _digest("subject", code), tuple(sorted(evidence)), tuple(sorted(counter)), "confirmed" if category == "observed" else ("unknown" if category in {"missing-evidence", "not-comparable"} else "medium"), _digest("code", code))  # type: ignore[arg-type]


def _missing_codes(
    coverage: DciCoverageExperimentObservation | None,
) -> tuple[str, ...]:
    if coverage is not None and coverage.complete:
        return tuple(code for code in _MISSING_CODES if code != "retrieval-coverage")
    return _MISSING_CODES


def _findings(
    observations: tuple[DciDatasetObservation, ...],
    aggregate_ids: dict[str, str],
    missing_codes: tuple[str, ...],
    coverage: DciCoverageExperimentObservation | None,
    coverage_evaluation_ids: Mapping[str, str],
) -> tuple[Finding, ...]:
    observed = tuple(_finding("observed", f"observed:{item.dataset_id}", (item.aggregate_evaluation_sha256,)) for item in observations)
    coverage_observed = (
        ()
        if coverage is None
        else tuple(
            _finding(
                "observed",
                f"observed:coverage:{item.dataset_id}",
                (coverage_evaluation_ids[item.dataset_id],),
            )
            for item in coverage.datasets
        )
    )
    by_code = {item.finding_code_sha256: item for item in observed}
    def observed_id(dataset_id: str) -> str:
        return by_code[_digest("code", f"observed:{dataset_id}")].finding_sha256
    missing = tuple(
        _finding("missing-evidence", f"missing:{code}", tuple(sorted(aggregate_ids.values())))
        for code in missing_codes
    )
    missing_by_code = dict(zip(missing_codes, missing, strict=True))
    not_comparable = _finding("not-comparable", "not-comparable:paper-reference", (aggregate_ids["bright.biology"],))
    coverage_finding_ids = (
        ()
        if coverage is None
        else tuple(item.finding_sha256 for item in coverage_observed)
    )
    context_evidence = (
        (missing_by_code["retrieval-coverage"].finding_sha256,)
        if "retrieval-coverage" in missing_by_code
        else coverage_finding_ids
    )
    hypotheses = (
        _finding("hypothesis", "hypothesis:retrieval-scale-noise", (observed_id("bright.biology"), observed_id("bright.earth-science")), (not_comparable.finding_sha256,)),
        _finding("hypothesis", "hypothesis:query-decomposition", (observed_id("bright.biology"), observed_id("beir.scifact"), *coverage_finding_ids), (not_comparable.finding_sha256,)),
        _finding("hypothesis", "hypothesis:context-retention", (observed_id("bright.biology"), *context_evidence), (not_comparable.finding_sha256,)),
        _finding("hypothesis", "hypothesis:paper-method-difference", (observed_id("bright.biology"), not_comparable.finding_sha256), (missing_by_code["sealed-config-digest"].finding_sha256,)),
    )
    return (*observed, *coverage_observed, *missing, not_comparable, *hypotheses)


def _diagnosis_bundle(
    experiments: Mapping[str, ExperimentBundle],
    aggregate_ids: dict[str, str],
    findings: tuple[Finding, ...],
    runs: Mapping[str, DciRecoveredRun],
    coverage_experiment: DciCoverageExperimentObservation | None,
    coverage_evaluation_ids: Mapping[str, str],
) -> tuple[DiagnosisBundle, tuple[DciProposalSummary, ...]]:
    coverage_scope = _proposal_scope(runs, _COVERAGE_DATASETS, "coverage")
    query_scope = _proposal_scope(runs, _BRIGHT_DATASETS, "paired-bright")
    coverage, decomposition = _pathlight_proposals(
        findings, coverage_scope, query_scope
    )
    bundle = DiagnosisBundle.build(
        experiment_bundle_sha256s=tuple(experiments[key].bundle_sha256 for key in _DATASET_ORDER),
        evaluation_sha256s=(
            *tuple(aggregate_ids.values()),
            *(
                ()
                if coverage_experiment is None
                else tuple(coverage_evaluation_ids.values())
            ),
        ), findings=findings, proposals=(coverage, decomposition),
    )
    summaries = (
        DciProposalSummary(
            "coverage-instrumentation", coverage.proposal_sha256, True, False,
            50, 5_000_000, 2, None, None, None,
            coverage_scope.dataset_case_counts,
            coverage_scope.dataset_case_scope_sha256s,
            coverage_scope.case_scope_sha256, 50, 0,
            coverage_scope.sole_variable_sha256,
        ),
        DciProposalSummary(
            "retrieval-query-decomposition", decomposition.proposal_sha256,
            True, False, 80, 8_000_000, None, coverage.proposal_sha256,
            50_000, 250_000, query_scope.dataset_case_counts,
            query_scope.dataset_case_scope_sha256s,
            query_scope.case_scope_sha256, 40, 40,
            query_scope.sole_variable_sha256,
        ),
    )
    return bundle, summaries


@dataclass(frozen=True, slots=True)
class _ProposalScope:
    dataset_case_counts: tuple[tuple[str, int], ...]
    dataset_case_scope_sha256s: tuple[tuple[str, str], ...]
    case_scope_sha256: str
    baseline_operation_count: int
    candidate_operation_count: int
    sole_variable_sha256: str


def _combined_case_scope_sha256(
    scopes: tuple[tuple[str, str], ...],
    dataset_ids: tuple[str, ...],
    purpose: str,
) -> str:
    scope_by_dataset = dict(scopes)
    return _digest(
        "proposal-case-scope",
        {
            "datasets": [
                {
                    "dataset_id": dataset_id,
                    "case_count": 10,
                    "case_scope_sha256": scope_by_dataset[dataset_id],
                    "role": (
                        "scifact-anchor"
                        if dataset_id == "beir.scifact"
                        else "bright-target"
                    ),
                }
                for dataset_id in dataset_ids
            ],
            "purpose": purpose,
            "total_case_count": len(dataset_ids) * 10,
        },
    )


def _proposal_scope(
    runs: Mapping[str, DciRecoveredRun],
    dataset_ids: tuple[str, ...],
    purpose: str,
) -> _ProposalScope:
    scope_digests = tuple(
        (
            dataset_id,
            _digest(
                "proposal-dataset-case-scope",
                {
                    "dataset_id": dataset_id,
                    "case_sha256s": [
                        case.dataset_item_sha256
                        for case in runs[dataset_id].cases[:10]
                    ],
                },
            ),
        )
        for dataset_id in dataset_ids
    )
    coverage = purpose == "coverage"
    return _ProposalScope(
        dataset_case_counts=tuple((dataset_id, 10) for dataset_id in dataset_ids),
        dataset_case_scope_sha256s=scope_digests,
        case_scope_sha256=_combined_case_scope_sha256(
            scope_digests, dataset_ids, purpose
        ),
        baseline_operation_count=50 if coverage else 40,
        candidate_operation_count=0 if coverage else 40,
        sole_variable_sha256=_digest(
            "proposal-sole-variable",
            (
                "trajectory-coverage-instrumentation-only"
                if coverage
                else "retrieval-query-planning"
            ),
        ),
    )


def _scope_from_summary(summary: DciProposalSummary) -> _ProposalScope:
    return _ProposalScope(
        summary.dataset_case_counts,
        summary.dataset_case_scope_sha256s,
        summary.case_scope_sha256,
        summary.baseline_operation_count,
        summary.candidate_operation_count,
        summary.sole_variable_sha256,
    )


def _fixed_pathlight_proposals(
    findings: tuple[Finding, ...],
    summaries: tuple[DciProposalSummary, ...],
) -> tuple[Proposal, Proposal]:
    if len(summaries) != 2:
        raise ValueError
    return _pathlight_proposals(
        findings, _scope_from_summary(summaries[0]), _scope_from_summary(summaries[1])
    )


def _pathlight_proposals(
    findings: tuple[Finding, ...],
    coverage_scope: _ProposalScope,
    query_scope: _ProposalScope,
) -> tuple[Proposal, Proposal]:
    hypothesis = {
        code: next(item for item in findings if item.finding_code_sha256 == _digest("code", f"hypothesis:{code}"))
        for code in _HYPOTHESIS_CODES
    }
    coverage = Proposal(
        hypothesis["context-retention"].finding_sha256,
        _digest(
            "proposal-change",
            {
                "change": "coverage-instrumentation",
                "sole_variable_sha256": coverage_scope.sole_variable_sha256,
            },
        ),
        _digest("proposal-scope", _proposal_scope_mapping(coverage_scope)),
        _digest("proposal-success", {"trajectory_coverage_recorded": True}),
        _digest("proposal-stop", {"infrastructure_failures": 2}),
        _digest("proposal-budget", {"agent_operations": 50, "max_cost_microusd": 5_000_000}),
    )
    decomposition = Proposal(
        hypothesis["query-decomposition"].finding_sha256,
        _digest(
            "proposal-change",
            {
                "change": "retrieval-query-decomposition",
                "sole_variable_sha256": query_scope.sole_variable_sha256,
            },
        ),
        _digest("proposal-scope", _proposal_scope_mapping(query_scope)),
        _digest("proposal-success", {"mean_ndcg_gain_microunits": 50_000, "maximum_cost_or_time_increase_microunits": 250_000}),
        _digest(
            "proposal-stop",
            {"prerequisite_proposal_sha256": coverage.proposal_sha256},
        ),
        _digest("proposal-budget", {"agent_operations": 80, "max_cost_microusd": 8_000_000}),
    )
    return coverage, decomposition


def _proposal_scope_mapping(scope: _ProposalScope) -> dict[str, object]:
    return {
        "case_scope_sha256": scope.case_scope_sha256,
        "dataset_case_counts": [list(item) for item in scope.dataset_case_counts],
        "dataset_case_scope_sha256s": [
            list(item) for item in scope.dataset_case_scope_sha256s
        ],
        "baseline_operation_count": scope.baseline_operation_count,
        "candidate_operation_count": scope.candidate_operation_count,
    }


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
_CN_COMPONENTS = {
    "runtime": "运行时",
    "model": "模型",
    "toolset": "工具集",
    "prompt": "提示契约",
    "context": "上下文契约",
    "metric": "度量契约",
}
_CN_MISSING = {
    "assembly-lineage": "装配谱系", "package-lineage": "包谱系", "retrieval-coverage": "检索覆盖率",
    "sealed-analysis-digest": "封存分析摘要", "sealed-config-digest": "封存配置摘要", "trace-graph": "轨迹图谱",
}


def render_chinese_diagnosis(report: object) -> str:
    """Render only fixed Chinese dictionaries plus safe numeric report fields."""

    rendered: str | None = None
    try:
        if type(report) is not DciDiagnosisReport:
            raise ValueError
        supplied_digest = _sha256(report.report_sha256)
        canonical = DciDiagnosisReport(
            report.observations, report.component_comparisons, report.findings, report.missing_evidence,
            report.hypothesis_codes, report.proposals, report.aggregate_workflow_metrics, report.diagnosis_bundle,
            report.coverage_experiment, report.query_decomposition_gate,
        )
        if not hmac.compare_digest(canonical.report_sha256, supplied_digest):
            raise ValueError
        lines = ["# DCI 差分诊断", "", "## 已证实事实", ""]
        for item in canonical.observations:
            metrics = item.workflow_metrics
            lines.extend((
                f"### {_CN_DATASETS[item.dataset_id]}",
                "",
                f"- 分数：{_CN_METRICS[item.metric_name]} {item.score_microunits} 微单位；样本 {item.selected_count}/{item.total_count}；失败 {item.failed_count}；语料文件 {item.corpus_file_count}。",
                f"- 论文参照：{item.reference_score_microunits} 微单位；差值 {item.reference_gap_microunits} 微单位；状态：仅参考、不可作完全可比结论。",
                f"- 零分率：{metrics.zero_score_rate_microunits} 微单位；覆盖可用 {item.resolution_available_queries}/{item.resolution_total_queries}；解析状态：不可用。",
                f"- 中位数：tokens {metrics.median_agent_total_tokens}；工具调用 {metrics.median_tool_call_count}；墙钟 {metrics.median_wall_time_ns} ns；工具 {metrics.median_tool_time_ns} ns；read 调用 {metrics.median_read_call_count}；grep 调用 {metrics.median_grep_call_count}；read {metrics.median_read_time_ns} ns；grep {metrics.median_grep_time_ns} ns；问题词 {metrics.median_question_word_count}。",
                f"- 工具错误：{metrics.total_tool_error_count}；时间占比：工具/墙钟 {metrics.tool_time_share_microunits} 微单位、read/工具 {metrics.read_time_share_microunits} 微单位、grep/工具 {metrics.grep_time_share_microunits} 微单位。",
                "",
            ))
            if item.coverage_total_queries:
                lines.extend((
                    f"- 覆盖观测：可用 {item.coverage_available_queries}/{item.coverage_total_queries}；any/mean/all 中位数 {item.coverage_median_any_microunits}/{item.coverage_median_mean_microunits}/{item.coverage_median_all_microunits} 微单位；保留覆盖可用 {item.retained_available_queries}、中位数 {item.retained_median_microunits} 微单位。",
                    f"- 轨迹计数：工具观测 {item.tool_observation_count}；浮现 gold {item.surfaced_gold_count}；模型调用 {item.model_call_count}；上下文帧 {item.context_frame_count}；缺失边界 {item.missing_boundary_count}；完整性失败 {item.integrity_failure_count}。",
                    "",
                ))
        lines.extend(("## 组件摘要关系", ""))
        for item in canonical.component_comparisons:
            lines.append(
                f"- {_CN_DATASETS[item.dataset_id]} 的{_CN_COMPONENTS[item.component]}组件摘要关系：相对 Bright 生物学{('相同' if item.relation_to_bright_biology == 'same' else '不同')}。"
            )
        if canonical.coverage_experiment is not None:
            lines.extend((
                "",
                "- 覆盖与历史分数之间仅为观测相关性，不证明因果关系。",
            ))
        lines.extend(["", "## 待验证假设", ""])
        lines.extend(f"- {_CN_HYPOTHESES[code]}。" for code in canonical.hypothesis_codes)
        lines.extend([
            "", "## 反证与不可比较项", "",
            "- 论文数值仅作参考，当前变体不可视为完全可比；因此没有跨数据集汇总分数或分数导出指标。",
        ])
        if canonical.coverage_experiment is None:
            lines.append(
                "- 缺少封存配置、封存分析、装配/包谱系、轨迹图谱与检索覆盖率，不能把差值归因于任一组件。"
            )
        elif canonical.coverage_experiment.complete:
            lines.append(
                "- 覆盖观测只关闭检索覆盖率缺口；其余证据缺口仍禁止把差值归因于任一组件。"
            )
        else:
            lines.append(
                "- 覆盖观测未完整，未关闭检索覆盖率缺口；其余证据缺口仍禁止把差值归因于任一组件。"
            )
        lines.extend(["", "## 证据缺口", ""])
        lines.extend(f"- {_CN_MISSING[code]}" for code in canonical.missing_evidence)
        lines.extend(["", "## 最小受控实验", ""])
        for item in canonical.proposals:
            if item.code == "coverage-instrumentation":
                lines.append(
                    f"- {_CN_PROPOSALS[item.code]}：状态 proposed；最多 {item.agent_operation_cap} 次 Agent 操作，成本上限 {item.max_cost_microusd} 微美元，基础设施失败停止线 {item.infrastructure_failure_stop}；覆盖 {len(item.dataset_case_counts)} 个数据集、每项 10 例；需运营者授权，当前未授权。"
                )
            else:
                if canonical.coverage_experiment is None:
                    lines.append(
                        f"- {_CN_PROPOSALS[item.code]}：状态 proposed；最多 {item.agent_operation_cap} 次 Agent 操作，成本上限 {item.max_cost_microusd} 微美元；前提为覆盖率观测；最小平均 nDCG 增益 {item.minimum_mean_ndcg_gain_microunits} 微单位，成本或时间增长上限 {item.maximum_cost_or_time_increase_microunits} 微单位；覆盖 {len(item.dataset_case_counts)} 个数据集、每项 10 例；需运营者授权，当前未授权。"
                    )
                else:
                    gate = (
                        "覆盖观测已完整，可申请单独授权"
                        if canonical.query_decomposition_gate
                        == "ready-for-authorization"
                        else "覆盖观测未完整，授权门槛阻塞"
                    )
                    lines.append(
                        f"- {_CN_PROPOSALS[item.code]}：状态 proposed；{gate}；最多 {item.agent_operation_cap} 次 Agent 操作，成本上限 {item.max_cost_microusd} 微美元；前提为覆盖率观测；最小平均 nDCG 增益 {item.minimum_mean_ndcg_gain_microunits} 微单位，成本或时间增长上限 {item.maximum_cost_or_time_increase_microunits} 微单位；覆盖 {len(item.dataset_case_counts)} 个数据集、每项 10 例；需运营者授权，当前未授权。"
                    )
        rendered = "\n".join(lines) + "\n"
    except Exception:
        pass
    if rendered is None:
        raise DciDiagnosisError(_ERROR) from None
    return rendered
