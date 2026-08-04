"""Immutable, evidence-closed, provider-neutral Pathlight optimization records."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Literal, TypeAlias, cast

from asterion.pathlight._private_file import read_private_file, write_private_file
from asterion.pathlight.diagnosis import DiagnosisBundle, validate_diagnosis_bundle
from asterion.pathlight.evaluation import (
    EvaluationBundle,
    EvaluationRecord,
    validate_evaluation_record,
)
from asterion.pathlight.experiment import (
    ExperimentBundle,
    ExperimentPlan,
    Variant,
    validate_experiment_bundle,
    validate_experiment_plan,
    validate_variant,
)
from asterion.pathlight.protocol import PathlightError


DecisionResult: TypeAlias = Literal["accepted", "rejected", "inconclusive"]
TrialStatus: TypeAlias = Literal["completed", "failed", "cancelled"]
VariantRole: TypeAlias = Literal["baseline", "candidate"]
EvidenceState: TypeAlias = Literal["complete", "incomplete"]
DecisionReason: TypeAlias = Literal[
    "quality-and-efficiency-met",
    "quality-threshold-missed",
    "cost-threshold-exceeded",
    "time-threshold-exceeded",
    "multiple-thresholds-missed",
    "incomplete-trials",
    "comparison-invalid",
    "evidence-closure-invalid",
]

OPTIMIZATION_BUNDLE_SCHEMA = "asterion.pathlight-optimization/v1"
OPTIMIZATION_BUNDLE_FILENAME = "pathlight-optimization.json"
_MAX_OPTIMIZATION_BUNDLE_BYTES = 1_000_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FAILURE_CATEGORIES = frozenset({"authentication", "rate-limit", "network", "mapping", "service"})
_TRIAL_FIELDS = frozenset({
    "experiment_plan_sha256", "case_trial_sha256", "dataset_item_sha256", "variant_role",
    "variant_sha256", "trace_sha256", "evaluation_sha256", "status", "failure_category",
    "agent_cost_microusd", "input_tokens", "output_tokens", "elapsed_ns", "optimization_trial_sha256",
})
_CRITERIA_FIELDS = frozenset({
    "minimum_mean_gain_microunits", "maximum_cost_increase_microunits",
    "maximum_time_increase_microunits", "success_criteria_sha256",
})
_HISTORY_FIELDS = frozenset({
    "experiment_plan_sha256", "baseline_variant_sha256", "candidate_variant_sha256",
    "dataset_snapshot_sha256", "scope_sha256", "metric_contract_sha256",
    "evaluator_contract_sha256", "assignment_sha256", "stop_criteria_sha256", "budget_sha256",
    "expected_dataset_item_sha256s", "baseline_optimization_trial_sha256s",
    "candidate_optimization_trial_sha256s", "baseline_completed_count", "baseline_failed_count",
    "baseline_cancelled_count", "candidate_completed_count", "candidate_failed_count",
    "candidate_cancelled_count", "baseline_mean_microunits", "candidate_mean_microunits",
    "mean_gain_microunits", "baseline_agent_cost_microusd", "candidate_agent_cost_microusd",
    "cost_increase_microunits", "baseline_input_tokens", "candidate_input_tokens",
    "baseline_output_tokens", "candidate_output_tokens", "baseline_elapsed_ns",
    "candidate_elapsed_ns", "time_increase_microunits", "evidence_state", "trial_history_sha256",
})
_DECISION_FIELDS = frozenset({
    "proposal_sha256", "finding_sha256", "experiment_plan_sha256", "trial_history_sha256",
    "success_criteria_sha256", "minimum_mean_gain_microunits",
    "maximum_cost_increase_microunits", "maximum_time_increase_microunits",
    "operator_approval_sha256", "result", "reason", "decision_sha256",
})
_BUNDLE_FIELDS = frozenset({
    "schema", "experiment_bundle_sha256s", "evaluation_bundle_sha256s", "diagnosis_bundle_sha256s",
    "trace_sha256s", "trials", "histories", "decisions", "bundle_sha256",
})


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _require_sha256(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError
    return value


def _require_nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _require_int(value: object) -> int:
    if type(value) is not int:
        raise ValueError
    return value


def _require_sorted_unique_sha256s(value: object, *, nonempty: bool = False) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise ValueError
    values = tuple(_require_sha256(item) for item in value)
    if values != tuple(sorted(values)) or len(values) != len(set(values)) or (nonempty and not values):
        raise ValueError
    return values


def _as_sequence(value: object) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError
    return value


def _round_half_even(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError
    sign = -1 if numerator < 0 else 1
    quotient, remainder = divmod(abs(numerator), denominator)
    if remainder * 2 > denominator or (remainder * 2 == denominator and quotient % 2):
        quotient += 1
    return sign * quotient


def _relative_increase_microunits(baseline: int, candidate: int) -> int:
    if baseline == 0:
        return 0 if candidate == 0 else 1_000_001
    return ((candidate - baseline) * 1_000_000) // baseline


@dataclass(frozen=True, slots=True)
class OptimizationCriteria:
    """Pre-registered, digest-only thresholds used to derive a decision."""

    minimum_mean_gain_microunits: int
    maximum_cost_increase_microunits: int
    maximum_time_increase_microunits: int
    success_criteria_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            _require_nonnegative_int(self.minimum_mean_gain_microunits)
            _require_nonnegative_int(self.maximum_cost_increase_microunits)
            _require_nonnegative_int(self.maximum_time_increase_microunits)
        except Exception:
            raise PathlightError("Pathlight optimization criteria is invalid") from None
        object.__setattr__(self, "success_criteria_sha256", _canonical_digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "minimum_mean_gain_microunits": self.minimum_mean_gain_microunits,
            "maximum_cost_increase_microunits": self.maximum_cost_increase_microunits,
            "maximum_time_increase_microunits": self.maximum_time_increase_microunits,
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "success_criteria_sha256": self.success_criteria_sha256}


def validate_optimization_criteria(mapping: Mapping[str, object]) -> OptimizationCriteria:
    try:
        if type(mapping) is not dict or set(mapping) != _CRITERIA_FIELDS:
            raise ValueError
        criteria = OptimizationCriteria(
            _require_nonnegative_int(mapping["minimum_mean_gain_microunits"]),
            _require_nonnegative_int(mapping["maximum_cost_increase_microunits"]),
            _require_nonnegative_int(mapping["maximum_time_increase_microunits"]),
        )
        if not hmac.compare_digest(_require_sha256(mapping["success_criteria_sha256"]), criteria.success_criteria_sha256):
            raise ValueError
        return criteria
    except Exception:
        raise PathlightError("Pathlight optimization criteria is invalid") from None


@dataclass(frozen=True, slots=True)
class OptimizationTrial:
    """One body-free, terminal optimization attempt linked to native evidence."""

    experiment_plan_sha256: str
    case_trial_sha256: str
    dataset_item_sha256: str
    variant_role: VariantRole
    variant_sha256: str
    trace_sha256: str | None
    evaluation_sha256: str | None
    status: TrialStatus
    failure_category: str | None
    agent_cost_microusd: int
    input_tokens: int
    output_tokens: int
    elapsed_ns: int
    optimization_trial_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            for value in (self.experiment_plan_sha256, self.case_trial_sha256, self.dataset_item_sha256, self.variant_sha256):
                _require_sha256(value)
            if type(self.variant_role) is not str or self.variant_role not in {"baseline", "candidate"}:
                raise ValueError
            if type(self.status) is not str or self.status not in {"completed", "failed", "cancelled"}:
                raise ValueError
            for value in (self.agent_cost_microusd, self.input_tokens, self.output_tokens, self.elapsed_ns):
                _require_nonnegative_int(value)
            if self.status == "completed":
                _require_sha256(self.trace_sha256)
                _require_sha256(self.evaluation_sha256)
                if self.failure_category is not None:
                    raise ValueError
            elif self.trace_sha256 is not None or self.evaluation_sha256 is not None or type(self.failure_category) is not str or self.failure_category not in _FAILURE_CATEGORIES:
                raise ValueError
        except Exception:
            raise PathlightError("Pathlight optimization trial is invalid") from None
        object.__setattr__(self, "optimization_trial_sha256", _canonical_digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "experiment_plan_sha256": self.experiment_plan_sha256,
            "case_trial_sha256": self.case_trial_sha256,
            "dataset_item_sha256": self.dataset_item_sha256,
            "variant_role": self.variant_role,
            "variant_sha256": self.variant_sha256,
            "trace_sha256": self.trace_sha256,
            "evaluation_sha256": self.evaluation_sha256,
            "status": self.status,
            "failure_category": self.failure_category,
            "agent_cost_microusd": self.agent_cost_microusd,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "elapsed_ns": self.elapsed_ns,
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "optimization_trial_sha256": self.optimization_trial_sha256}


def validate_optimization_trial(mapping: Mapping[str, object]) -> OptimizationTrial:
    try:
        if type(mapping) is not dict or set(mapping) != _TRIAL_FIELDS:
            raise ValueError
        trial = OptimizationTrial(
            _require_sha256(mapping["experiment_plan_sha256"]), _require_sha256(mapping["case_trial_sha256"]),
            _require_sha256(mapping["dataset_item_sha256"]), cast(VariantRole, mapping["variant_role"]),
            _require_sha256(mapping["variant_sha256"]), mapping["trace_sha256"], mapping["evaluation_sha256"],
            cast(TrialStatus, mapping["status"]), mapping["failure_category"],
            _require_nonnegative_int(mapping["agent_cost_microusd"]), _require_nonnegative_int(mapping["input_tokens"]),
            _require_nonnegative_int(mapping["output_tokens"]), _require_nonnegative_int(mapping["elapsed_ns"]),
        )
        if not hmac.compare_digest(_require_sha256(mapping["optimization_trial_sha256"]), trial.optimization_trial_sha256):
            raise ValueError
        return trial
    except Exception:
        raise PathlightError("Pathlight optimization trial is invalid") from None


@dataclass(frozen=True, slots=True)
class TrialHistory:
    """The deterministic paired evidence and aggregate for one exact experiment plan."""

    experiment_plan_sha256: str
    baseline_variant_sha256: str
    candidate_variant_sha256: str
    dataset_snapshot_sha256: str
    scope_sha256: str
    metric_contract_sha256: str
    evaluator_contract_sha256: str
    assignment_sha256: str
    stop_criteria_sha256: str
    budget_sha256: str
    expected_dataset_item_sha256s: tuple[str, ...]
    baseline_optimization_trial_sha256s: tuple[str, ...]
    candidate_optimization_trial_sha256s: tuple[str, ...]
    baseline_completed_count: int
    baseline_failed_count: int
    baseline_cancelled_count: int
    candidate_completed_count: int
    candidate_failed_count: int
    candidate_cancelled_count: int
    baseline_mean_microunits: int | None
    candidate_mean_microunits: int | None
    mean_gain_microunits: int | None
    baseline_agent_cost_microusd: int
    candidate_agent_cost_microusd: int
    cost_increase_microunits: int | None
    baseline_input_tokens: int
    candidate_input_tokens: int
    baseline_output_tokens: int
    candidate_output_tokens: int
    baseline_elapsed_ns: int
    candidate_elapsed_ns: int
    time_increase_microunits: int | None
    evidence_state: EvidenceState
    trial_history_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            for value in (
                self.experiment_plan_sha256, self.baseline_variant_sha256, self.candidate_variant_sha256,
                self.dataset_snapshot_sha256, self.scope_sha256, self.metric_contract_sha256,
                self.evaluator_contract_sha256, self.assignment_sha256, self.stop_criteria_sha256, self.budget_sha256,
            ):
                _require_sha256(value)
            if self.baseline_variant_sha256 == self.candidate_variant_sha256:
                raise ValueError
            _require_sorted_unique_sha256s(self.expected_dataset_item_sha256s, nonempty=True)
            for values in (self.baseline_optimization_trial_sha256s, self.candidate_optimization_trial_sha256s):
                _require_sorted_unique_sha256s(values)
            for value in (
                self.baseline_completed_count, self.baseline_failed_count, self.baseline_cancelled_count,
                self.candidate_completed_count, self.candidate_failed_count, self.candidate_cancelled_count,
                self.baseline_agent_cost_microusd, self.candidate_agent_cost_microusd,
                self.baseline_input_tokens, self.candidate_input_tokens, self.baseline_output_tokens,
                self.candidate_output_tokens, self.baseline_elapsed_ns, self.candidate_elapsed_ns,
            ):
                _require_nonnegative_int(value)
            if type(self.evidence_state) is not str or self.evidence_state not in {"complete", "incomplete"}:
                raise ValueError
            _validate_history_aggregates(self)
        except Exception:
            raise PathlightError("Pathlight trial history is invalid") from None
        object.__setattr__(self, "trial_history_sha256", _canonical_digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in _HISTORY_FIELDS if name != "trial_history_sha256"}

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "trial_history_sha256": self.trial_history_sha256}

    @classmethod
    def build(
        cls,
        *,
        experiment_plan: ExperimentPlan,
        baseline_variant: Variant,
        candidate_variant: Variant,
        trials: Sequence[OptimizationTrial],
        evaluations: Sequence[EvaluationRecord],
        expected_dataset_item_sha256s: Sequence[str],
    ) -> TrialHistory:
        try:
            if type(experiment_plan) is not ExperimentPlan or type(baseline_variant) is not Variant or type(candidate_variant) is not Variant:
                raise ValueError
            plan = validate_experiment_plan(experiment_plan.to_mapping())
            baseline = validate_variant(baseline_variant.to_mapping())
            candidate = validate_variant(candidate_variant.to_mapping())
            if plan.baseline_variant_sha256 != baseline.variant_sha256 or plan.candidate_variant_sha256s != (candidate.variant_sha256,) or len(plan.evaluator_contract_sha256s) != 1:
                raise ValueError
            expected = tuple(_require_sha256(value) for value in _as_sequence(expected_dataset_item_sha256s))
            if not expected or expected != tuple(sorted(expected)) or len(expected) != len(set(expected)):
                raise ValueError
            verified_trials = _canonical_values(trials, OptimizationTrial, validate_optimization_trial, "optimization_trial_sha256")
            verified_evaluations = _canonical_values(evaluations, EvaluationRecord, validate_evaluation_record, "evaluation_sha256")
            return _build_history(plan, baseline, candidate, verified_trials, verified_evaluations, expected)
        except Exception:
            raise PathlightError("Pathlight trial history is invalid") from None


def _validate_history_aggregates(history: TrialHistory) -> None:
    if len(history.baseline_optimization_trial_sha256s) != history.baseline_completed_count + history.baseline_failed_count + history.baseline_cancelled_count:
        raise ValueError
    if len(history.candidate_optimization_trial_sha256s) != history.candidate_completed_count + history.candidate_failed_count + history.candidate_cancelled_count:
        raise ValueError
    values = (history.baseline_mean_microunits, history.candidate_mean_microunits, history.mean_gain_microunits, history.cost_increase_microunits, history.time_increase_microunits)
    if history.evidence_state == "complete":
        if (history.baseline_completed_count != len(history.expected_dataset_item_sha256s) or history.candidate_completed_count != len(history.expected_dataset_item_sha256s) or any(value is None for value in values)):
            raise ValueError
        if history.mean_gain_microunits != history.candidate_mean_microunits - history.baseline_mean_microunits:  # type: ignore[operator]
            raise ValueError
        if history.cost_increase_microunits != _relative_increase_microunits(history.baseline_agent_cost_microusd, history.candidate_agent_cost_microusd):
            raise ValueError
        if history.time_increase_microunits != _relative_increase_microunits(history.baseline_elapsed_ns, history.candidate_elapsed_ns):
            raise ValueError
    elif any(value is not None for value in values):
        raise ValueError


def _canonical_values(
    values: object, expected_type: type[object], validator: Callable[[Mapping[str, object]], object], identity_name: str,
) -> tuple[object, ...]:
    verified: list[object] = []
    for value in _as_sequence(values):
        if type(value) is not expected_type:
            raise ValueError
        verified.append(validator(cast(object, value).to_mapping()))  # type: ignore[attr-defined]
    identities = tuple(getattr(value, identity_name) for value in verified)
    if len(identities) != len(set(identities)):
        raise ValueError
    return tuple(sorted(verified, key=lambda value: getattr(value, identity_name)))


def _build_history(
    plan: ExperimentPlan, baseline: Variant, candidate: Variant, trials: tuple[object, ...],
    evaluations: tuple[object, ...], expected: tuple[str, ...],
) -> TrialHistory:
    trial_values = cast(tuple[OptimizationTrial, ...], trials)
    evaluation_values = cast(tuple[EvaluationRecord, ...], evaluations)
    evaluation_by_id = {value.evaluation_sha256: value for value in evaluation_values}
    if len(evaluation_by_id) != len(evaluation_values):
        raise ValueError
    pairs: dict[tuple[str, str], OptimizationTrial] = {}
    case_ids: set[str] = set()
    scored: dict[str, list[int]] = {"baseline": [], "candidate": []}
    counts: dict[str, dict[str, int]] = {role: {status: 0 for status in ("completed", "failed", "cancelled")} for role in ("baseline", "candidate")}
    totals: dict[str, dict[str, int]] = {role: {name: 0 for name in ("cost", "input", "output", "elapsed")} for role in ("baseline", "candidate")}
    for trial in trial_values:
        if trial.experiment_plan_sha256 != plan.experiment_plan_sha256 or trial.dataset_item_sha256 not in expected:
            raise ValueError
        expected_variant = baseline.variant_sha256 if trial.variant_role == "baseline" else candidate.variant_sha256
        if trial.variant_sha256 != expected_variant or trial.case_trial_sha256 in case_ids:
            raise ValueError
        case_ids.add(trial.case_trial_sha256)
        key = (trial.dataset_item_sha256, trial.variant_role)
        if key in pairs:
            raise ValueError
        pairs[key] = trial
        counts[trial.variant_role][trial.status] += 1
        totals[trial.variant_role]["cost"] += trial.agent_cost_microusd
        totals[trial.variant_role]["input"] += trial.input_tokens
        totals[trial.variant_role]["output"] += trial.output_tokens
        totals[trial.variant_role]["elapsed"] += trial.elapsed_ns
        if trial.status == "completed":
            if trial.evaluation_sha256 is None or trial.trace_sha256 is None:
                raise ValueError
            evaluation = evaluation_by_id.get(trial.evaluation_sha256)
            if evaluation is None or evaluation.trace_sha256 != trial.trace_sha256 or evaluation.value_microunits is None or evaluation.status == "missing":
                raise ValueError
            scored[trial.variant_role].append(evaluation.value_microunits)
    complete = all((item, role) in pairs and pairs[(item, role)].status == "completed" for item in expected for role in ("baseline", "candidate"))
    if complete:
        metrics = {(value.metric_contract_sha256, value.dataset_snapshot_sha256, value.scope_sha256) for value in evaluation_by_id.values()}
        if len(metrics) != 1:
            raise ValueError
        metric_contract_sha256, dataset_snapshot_sha256, scope_sha256 = next(iter(metrics))
        if dataset_snapshot_sha256 != plan.dataset_snapshot_sha256 or scope_sha256 != plan.scope_sha256:
            raise ValueError
        baseline_mean = _round_half_even(sum(scored["baseline"]), len(scored["baseline"]))
        candidate_mean = _round_half_even(sum(scored["candidate"]), len(scored["candidate"]))
        gain: int | None = candidate_mean - baseline_mean
        cost_increase: int | None = _relative_increase_microunits(totals["baseline"]["cost"], totals["candidate"]["cost"])
        time_increase: int | None = _relative_increase_microunits(totals["baseline"]["elapsed"], totals["candidate"]["elapsed"])
        evidence_state: EvidenceState = "complete"
    else:
        # No partial denominator or partial score is ever published as a comparison.
        metric_contract_sha256 = _common_completed_metric(plan, trial_values, evaluation_by_id)
        dataset_snapshot_sha256 = plan.dataset_snapshot_sha256
        scope_sha256 = plan.scope_sha256
        baseline_mean = candidate_mean = gain = cost_increase = time_increase = None
        evidence_state = "incomplete"
    return TrialHistory(
        plan.experiment_plan_sha256, baseline.variant_sha256, candidate.variant_sha256,
        dataset_snapshot_sha256, scope_sha256, metric_contract_sha256, plan.evaluator_contract_sha256s[0],
        plan.assignment_sha256, plan.stop_criteria_sha256, plan.budget_sha256, expected,
        tuple(sorted(value.optimization_trial_sha256 for value in trial_values if value.variant_role == "baseline")),
        tuple(sorted(value.optimization_trial_sha256 for value in trial_values if value.variant_role == "candidate")),
        counts["baseline"]["completed"], counts["baseline"]["failed"], counts["baseline"]["cancelled"],
        counts["candidate"]["completed"], counts["candidate"]["failed"], counts["candidate"]["cancelled"],
        baseline_mean, candidate_mean, gain, totals["baseline"]["cost"], totals["candidate"]["cost"], cost_increase,
        totals["baseline"]["input"], totals["candidate"]["input"], totals["baseline"]["output"], totals["candidate"]["output"],
        totals["baseline"]["elapsed"], totals["candidate"]["elapsed"], time_increase, evidence_state,
    )


def _common_completed_metric(plan: ExperimentPlan, trials: tuple[OptimizationTrial, ...], evaluations: Mapping[str, EvaluationRecord]) -> str:
    metrics = {evaluations[cast(str, value.evaluation_sha256)].metric_contract_sha256 for value in trials if value.status == "completed" and value.evaluation_sha256 in evaluations}
    if len(metrics) != 1:
        raise ValueError
    return next(iter(metrics))


def validate_trial_history(mapping: Mapping[str, object]) -> TrialHistory:
    try:
        if type(mapping) is not dict or set(mapping) != _HISTORY_FIELDS:
            raise ValueError
        copy = dict(mapping)
        for name in ("expected_dataset_item_sha256s", "baseline_optimization_trial_sha256s", "candidate_optimization_trial_sha256s"):
            if type(copy[name]) not in {list, tuple}:
                raise ValueError
            copy[name] = tuple(copy[name])
        history = TrialHistory(**{name: copy[name] for name in _HISTORY_FIELDS if name != "trial_history_sha256"})  # type: ignore[arg-type]
        if not hmac.compare_digest(_require_sha256(mapping["trial_history_sha256"]), history.trial_history_sha256):
            raise ValueError
        return history
    except Exception:
        raise PathlightError("Pathlight trial history is invalid") from None


@dataclass(frozen=True, slots=True)
class Decision:
    """A non-overridable result derived from closed history and fixed criteria."""

    proposal_sha256: str
    finding_sha256: str
    experiment_plan_sha256: str
    trial_history_sha256: str
    success_criteria_sha256: str
    minimum_mean_gain_microunits: int
    maximum_cost_increase_microunits: int
    maximum_time_increase_microunits: int
    operator_approval_sha256: str
    result: DecisionResult
    reason: DecisionReason
    decision_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            for value in (self.proposal_sha256, self.finding_sha256, self.experiment_plan_sha256, self.trial_history_sha256, self.success_criteria_sha256, self.operator_approval_sha256):
                _require_sha256(value)
            for value in (self.minimum_mean_gain_microunits, self.maximum_cost_increase_microunits, self.maximum_time_increase_microunits):
                _require_nonnegative_int(value)
            if type(self.result) is not str or self.result not in {"accepted", "rejected", "inconclusive"}:
                raise ValueError
            if type(self.reason) is not str or self.reason not in {
                "quality-and-efficiency-met", "quality-threshold-missed", "cost-threshold-exceeded", "time-threshold-exceeded",
                "multiple-thresholds-missed", "incomplete-trials", "comparison-invalid", "evidence-closure-invalid",
            }:
                raise ValueError
            if (self.result == "accepted") != (self.reason == "quality-and-efficiency-met"):
                raise ValueError
            if self.result == "rejected" and self.reason not in {"quality-threshold-missed", "cost-threshold-exceeded", "time-threshold-exceeded", "multiple-thresholds-missed"}:
                raise ValueError
            if self.result == "inconclusive" and self.reason not in {"incomplete-trials", "comparison-invalid", "evidence-closure-invalid"}:
                raise ValueError
        except Exception:
            raise PathlightError("Pathlight decision is invalid") from None
        object.__setattr__(self, "decision_sha256", _canonical_digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in _DECISION_FIELDS if name != "decision_sha256"}

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "decision_sha256": self.decision_sha256}

    @classmethod
    def derive(
        cls, *, proposal_sha256: str, finding_sha256: str, history: TrialHistory,
        criteria: OptimizationCriteria, operator_approval_sha256: str,
    ) -> Decision:
        try:
            _require_sha256(proposal_sha256)
            _require_sha256(finding_sha256)
            _require_sha256(operator_approval_sha256)
            if type(history) is not TrialHistory or type(criteria) is not OptimizationCriteria:
                raise ValueError
            verified_history = validate_trial_history(history.to_mapping())
            verified_criteria = validate_optimization_criteria(criteria.to_mapping())
            result, reason = _derived_result(verified_history, verified_criteria)
            return cls(
                proposal_sha256, finding_sha256, verified_history.experiment_plan_sha256,
                verified_history.trial_history_sha256, verified_criteria.success_criteria_sha256,
                verified_criteria.minimum_mean_gain_microunits,
                verified_criteria.maximum_cost_increase_microunits,
                verified_criteria.maximum_time_increase_microunits,
                operator_approval_sha256, result, reason,
            )
        except Exception:
            raise PathlightError("Pathlight decision is invalid") from None


def _derived_result(history: TrialHistory, criteria: OptimizationCriteria) -> tuple[DecisionResult, DecisionReason]:
    if history.evidence_state != "complete":
        return "inconclusive", "incomplete-trials"
    if any(value is None for value in (history.mean_gain_microunits, history.cost_increase_microunits, history.time_increase_microunits)):
        return "inconclusive", "comparison-invalid"
    failed = (
        history.mean_gain_microunits < criteria.minimum_mean_gain_microunits,  # type: ignore[operator]
        history.cost_increase_microunits > criteria.maximum_cost_increase_microunits,  # type: ignore[operator]
        history.time_increase_microunits > criteria.maximum_time_increase_microunits,  # type: ignore[operator]
    )
    if not any(failed):
        return "accepted", "quality-and-efficiency-met"
    if sum(failed) > 1:
        return "rejected", "multiple-thresholds-missed"
    return "rejected", cast(DecisionReason, ("quality-threshold-missed", "cost-threshold-exceeded", "time-threshold-exceeded")[failed.index(True)])


def validate_decision(mapping: Mapping[str, object]) -> Decision:
    try:
        if type(mapping) is not dict or set(mapping) != _DECISION_FIELDS:
            raise ValueError
        decision = Decision(
            proposal_sha256=_require_sha256(mapping["proposal_sha256"]), finding_sha256=_require_sha256(mapping["finding_sha256"]),
            experiment_plan_sha256=_require_sha256(mapping["experiment_plan_sha256"]), trial_history_sha256=_require_sha256(mapping["trial_history_sha256"]),
            success_criteria_sha256=_require_sha256(mapping["success_criteria_sha256"]),
            minimum_mean_gain_microunits=_require_nonnegative_int(mapping["minimum_mean_gain_microunits"]),
            maximum_cost_increase_microunits=_require_nonnegative_int(mapping["maximum_cost_increase_microunits"]),
            maximum_time_increase_microunits=_require_nonnegative_int(mapping["maximum_time_increase_microunits"]),
            operator_approval_sha256=_require_sha256(mapping["operator_approval_sha256"]),
            result=cast(DecisionResult, mapping["result"]), reason=cast(DecisionReason, mapping["reason"]),
        )
        if not hmac.compare_digest(_require_sha256(mapping["decision_sha256"]), decision.decision_sha256):
            raise ValueError
        return decision
    except Exception:
        raise PathlightError("Pathlight decision is invalid") from None


@dataclass(frozen=True, slots=True)
class OptimizationBundle:
    """A canonical optimization closure with only public-safe identities and usage."""

    experiment_bundle_sha256s: tuple[str, ...]
    evaluation_bundle_sha256s: tuple[str, ...]
    diagnosis_bundle_sha256s: tuple[str, ...]
    trace_sha256s: tuple[str, ...]
    trials: tuple[OptimizationTrial, ...]
    histories: tuple[TrialHistory, ...]
    decisions: tuple[Decision, ...]
    bundle_sha256: str

    def __post_init__(self) -> None:
        try:
            values = _normalize_bundle_values(self.experiment_bundle_sha256s, self.evaluation_bundle_sha256s, self.diagnosis_bundle_sha256s, self.trace_sha256s, self.trials, self.histories, self.decisions, require_sorted=True)
            _validate_internal_closure(*values)
            expected = _canonical_digest(_bundle_document(*values))
            if not hmac.compare_digest(_require_sha256(self.bundle_sha256), expected):
                raise ValueError
        except Exception:
            raise PathlightError("Pathlight optimization bundle is invalid") from None
        for name, value in zip(("experiment_bundle_sha256s", "evaluation_bundle_sha256s", "diagnosis_bundle_sha256s", "trace_sha256s", "trials", "histories", "decisions"), values, strict=True):
            object.__setattr__(self, name, value)

    @classmethod
    def build(
        cls, *, experiment_bundle_sha256s: Sequence[str], evaluation_bundle_sha256s: Sequence[str], diagnosis_bundle_sha256s: Sequence[str], trace_sha256s: Sequence[str], trials: Sequence[OptimizationTrial], histories: Sequence[TrialHistory], decisions: Sequence[Decision],
    ) -> OptimizationBundle:
        try:
            values = _normalize_bundle_values(experiment_bundle_sha256s, evaluation_bundle_sha256s, diagnosis_bundle_sha256s, trace_sha256s, trials, histories, decisions, require_sorted=False)
            _validate_internal_closure(*values)
            return cls(*values, _canonical_digest(_bundle_document(*values)))
        except Exception:
            raise PathlightError("Pathlight optimization bundle is invalid") from None

    def to_mapping(self) -> dict[str, object]:
        return {**_bundle_document(self.experiment_bundle_sha256s, self.evaluation_bundle_sha256s, self.diagnosis_bundle_sha256s, self.trace_sha256s, self.trials, self.histories, self.decisions), "bundle_sha256": self.bundle_sha256}


def _normalize_bundle_values(experiments: object, evaluations: object, diagnoses: object, traces: object, trials: object, histories: object, decisions: object, *, require_sorted: bool) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[OptimizationTrial, ...], tuple[TrialHistory, ...], tuple[Decision, ...]]:
    if require_sorted and any(type(value) is not tuple for value in (experiments, evaluations, diagnoses, traces, trials, histories, decisions)):
        raise ValueError
    experiment_ids = _canonical_sha_sequence(experiments)
    evaluation_ids = _canonical_sha_sequence(evaluations)
    diagnosis_ids = _canonical_sha_sequence(diagnoses)
    trace_ids = _canonical_sha_sequence(traces)
    identifiers = (experiment_ids, evaluation_ids, diagnosis_ids, trace_ids)
    if require_sorted:
        for raw, canonical in zip((experiments, evaluations, diagnoses, traces), identifiers, strict=True):
            if tuple(cast(Sequence[Any], raw)) != canonical:
                raise ValueError
    collections = (
        _canonical_values(trials, OptimizationTrial, validate_optimization_trial, "optimization_trial_sha256"),
        _canonical_values(histories, TrialHistory, validate_trial_history, "trial_history_sha256"),
        _canonical_values(decisions, Decision, validate_decision, "decision_sha256"),
    )
    if require_sorted:
        for raw, canonical in zip((trials, histories, decisions), collections, strict=True):
            if tuple(cast(Sequence[Any], raw)) != canonical:
                raise ValueError
    return (
        experiment_ids, evaluation_ids, diagnosis_ids, trace_ids,
        cast(tuple[OptimizationTrial, ...], collections[0]),
        cast(tuple[TrialHistory, ...], collections[1]),
        cast(tuple[Decision, ...], collections[2]),
    )


def _canonical_sha_sequence(value: object) -> tuple[str, ...]:
    items = tuple(_require_sha256(item) for item in _as_sequence(value))
    if not items or len(items) != len(set(items)):
        raise ValueError
    return tuple(sorted(items))


def _validate_internal_closure(experiments: tuple[str, ...], evaluations: tuple[str, ...], diagnoses: tuple[str, ...], traces: tuple[str, ...], trials: tuple[OptimizationTrial, ...], histories: tuple[TrialHistory, ...], decisions: tuple[Decision, ...]) -> None:
    del experiments, evaluations, diagnoses
    trials_by_id = {value.optimization_trial_sha256: value for value in trials}
    histories_by_id = {value.trial_history_sha256: value for value in histories}
    if not trials_by_id or not histories_by_id or not decisions:
        raise ValueError
    assigned: set[str] = set()
    for history in histories:
        ids = history.baseline_optimization_trial_sha256s + history.candidate_optimization_trial_sha256s
        if any(value not in trials_by_id for value in ids) or assigned.intersection(ids):
            raise ValueError
        assigned.update(ids)
        for trial_id in history.baseline_optimization_trial_sha256s:
            if trials_by_id[trial_id].variant_role != "baseline":
                raise ValueError
        for trial_id in history.candidate_optimization_trial_sha256s:
            if trials_by_id[trial_id].variant_role != "candidate":
                raise ValueError
        if any(value.trace_sha256 is not None and value.trace_sha256 not in traces for value in (trials_by_id[item] for item in ids)):
            raise ValueError
    if assigned != set(trials_by_id):
        raise ValueError
    for decision in decisions:
        history = histories_by_id.get(decision.trial_history_sha256)
        if history is None or decision.experiment_plan_sha256 != history.experiment_plan_sha256:
            raise ValueError
        criteria = OptimizationCriteria(
            decision.minimum_mean_gain_microunits,
            decision.maximum_cost_increase_microunits,
            decision.maximum_time_increase_microunits,
        )
        expected = Decision.derive(
            proposal_sha256=decision.proposal_sha256, finding_sha256=decision.finding_sha256,
            history=history, criteria=criteria, operator_approval_sha256=decision.operator_approval_sha256,
        )
        if expected != decision:
            raise ValueError


def _bundle_document(experiments: tuple[str, ...], evaluations: tuple[str, ...], diagnoses: tuple[str, ...], traces: tuple[str, ...], trials: tuple[OptimizationTrial, ...], histories: tuple[TrialHistory, ...], decisions: tuple[Decision, ...]) -> dict[str, object]:
    return {
        "schema": OPTIMIZATION_BUNDLE_SCHEMA, "experiment_bundle_sha256s": list(experiments),
        "evaluation_bundle_sha256s": list(evaluations), "diagnosis_bundle_sha256s": list(diagnoses),
        "trace_sha256s": list(traces), "trials": [value.to_mapping() for value in trials],
        "histories": [value.to_mapping() for value in histories], "decisions": [value.to_mapping() for value in decisions],
    }


def validate_optimization_bundle(mapping: Mapping[str, object]) -> OptimizationBundle:
    try:
        if type(mapping) is not dict or set(mapping) != _BUNDLE_FIELDS or mapping["schema"] != OPTIMIZATION_BUNDLE_SCHEMA:
            raise ValueError
        for name in ("experiment_bundle_sha256s", "evaluation_bundle_sha256s", "diagnosis_bundle_sha256s", "trace_sha256s", "trials", "histories", "decisions"):
            if type(mapping[name]) is not list:
                raise ValueError
        for name in ("experiment_bundle_sha256s", "evaluation_bundle_sha256s", "diagnosis_bundle_sha256s", "trace_sha256s"):
            values = tuple(_require_sha256(value) for value in cast(list[object], mapping[name]))
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError
        for name, validator, identity_name in (
            ("trials", validate_optimization_trial, "optimization_trial_sha256"),
            ("histories", validate_trial_history, "trial_history_sha256"),
            ("decisions", validate_decision, "decision_sha256"),
        ):
            values = tuple(validator(_plain_mapping(value)) for value in cast(list[object], mapping[name]))
            if tuple(getattr(value, identity_name) for value in values) != tuple(sorted(getattr(value, identity_name) for value in values)):
                raise ValueError
        document = {key: value for key, value in mapping.items() if key != "bundle_sha256"}
        supplied = _require_sha256(mapping["bundle_sha256"])
        if not hmac.compare_digest(supplied, _canonical_digest(document)):
            raise ValueError
        return OptimizationBundle(
            tuple(mapping["experiment_bundle_sha256s"]), tuple(mapping["evaluation_bundle_sha256s"]), tuple(mapping["diagnosis_bundle_sha256s"]), tuple(mapping["trace_sha256s"]),
            tuple(validate_optimization_trial(_plain_mapping(value)) for value in mapping["trials"]),
            tuple(validate_trial_history(_plain_mapping(value)) for value in mapping["histories"]),
            tuple(validate_decision(_plain_mapping(value)) for value in mapping["decisions"]), supplied,
        )
    except Exception:
        raise PathlightError("Pathlight optimization bundle is invalid") from None


def _plain_mapping(value: object) -> Mapping[str, object]:
    if type(value) is not dict:
        raise ValueError
    return value


def write_optimization_bundle(path: Path, bundle: OptimizationBundle) -> None:
    try:
        if not isinstance(path, Path) or path.name != OPTIMIZATION_BUNDLE_FILENAME or type(bundle) is not OptimizationBundle:
            raise ValueError
        encoded = json.dumps(validate_optimization_bundle(bundle.to_mapping()).to_mapping(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        write_private_file(path, encoded)
    except Exception:
        raise PathlightError("Pathlight optimization target is unavailable") from None


def read_optimization_bundle(path: Path) -> OptimizationBundle:
    try:
        if not isinstance(path, Path) or path.name != OPTIMIZATION_BUNDLE_FILENAME:
            raise ValueError
        document = json.loads(read_private_file(path, _MAX_OPTIMIZATION_BUNDLE_BYTES).decode("utf-8"))
        if type(document) is not dict:
            raise ValueError
        return validate_optimization_bundle(document)
    except Exception:
        raise PathlightError("Pathlight optimization source is invalid") from None


def validate_optimization_closure(
    bundle: OptimizationBundle, *, workflow_trace_sha256s: Sequence[str] = (), workflow_bundles: Sequence[object] = (),
    experiment_bundles: Sequence[ExperimentBundle], evaluation_bundles: Sequence[EvaluationBundle], diagnosis_bundles: Sequence[DiagnosisBundle],
) -> None:
    """Validate every optimization reference against supplied immutable public evidence."""
    try:
        if type(bundle) is not OptimizationBundle:
            raise ValueError
        verified = validate_optimization_bundle(bundle.to_mapping())
        traces = _trace_identities(workflow_trace_sha256s, workflow_bundles)
        experiments = cast(dict[str, ExperimentBundle], _verified_bundles(experiment_bundles, ExperimentBundle, lambda value: validate_experiment_bundle(value.to_mapping())))
        evaluations = cast(dict[str, EvaluationBundle], _verified_bundles(evaluation_bundles, EvaluationBundle, lambda value: EvaluationBundle(value.metric_contracts, value.evaluations, value.bundle_sha256)))
        diagnoses = cast(dict[str, DiagnosisBundle], _verified_bundles(diagnosis_bundles, DiagnosisBundle, lambda value: validate_diagnosis_bundle(value.to_mapping())))
        if not set(verified.trace_sha256s) <= traces or not set(verified.experiment_bundle_sha256s) <= set(experiments) or not set(verified.evaluation_bundle_sha256s) <= set(evaluations) or not set(verified.diagnosis_bundle_sha256s) <= set(diagnoses):
            raise ValueError
        case_by_id = {trial.case_trial_sha256: trial for item in experiments.values() for trial in item.trials}
        evaluation_by_id = {record.evaluation_sha256: record for item in evaluations.values() for record in item.evaluations}
        plan_by_id = {plan.experiment_plan_sha256: plan for item in experiments.values() for plan in item.plans}
        variant_by_id = {variant.variant_sha256: variant for item in experiments.values() for variant in item.variants}
        evaluator_ids = {evaluator.evaluator_contract_sha256 for item in experiments.values() for evaluator in item.evaluators}
        finding_ids = {finding.finding_sha256 for item in diagnoses.values() for finding in item.findings}
        proposal_by_id = {proposal.proposal_sha256: proposal for item in diagnoses.values() for proposal in item.proposals}
        for trial in verified.trials:
            case = case_by_id.get(trial.case_trial_sha256)
            if case is None or (case.experiment_plan_sha256, case.dataset_item_sha256, case.variant_sha256) != (trial.experiment_plan_sha256, trial.dataset_item_sha256, trial.variant_sha256):
                raise ValueError
            if trial.status == "completed":
                evaluation = evaluation_by_id.get(cast(str, trial.evaluation_sha256))
                if evaluation is None or evaluation.trace_sha256 != trial.trace_sha256 or case.trace_sha256 != trial.trace_sha256 or trial.evaluation_sha256 not in case.evaluation_sha256s:
                    raise ValueError
        for history in verified.histories:
            plan = plan_by_id.get(history.experiment_plan_sha256)
            if plan is None or history.baseline_variant_sha256 not in variant_by_id or history.candidate_variant_sha256 not in variant_by_id or history.evaluator_contract_sha256 not in evaluator_ids or history.evaluator_contract_sha256 not in plan.evaluator_contract_sha256s:
                raise ValueError
            if (history.dataset_snapshot_sha256, history.scope_sha256, history.assignment_sha256, history.stop_criteria_sha256, history.budget_sha256) != (plan.dataset_snapshot_sha256, plan.scope_sha256, plan.assignment_sha256, plan.stop_criteria_sha256, plan.budget_sha256):
                raise ValueError
            history_trial_ids = history.baseline_optimization_trial_sha256s + history.candidate_optimization_trial_sha256s
            history_trials = tuple(next(value for value in verified.trials if value.optimization_trial_sha256 == identity) for identity in history_trial_ids)
            history_evaluations = tuple(evaluation_by_id[value.evaluation_sha256] for value in history_trials if value.evaluation_sha256 is not None)
            rebuilt = TrialHistory.build(
                experiment_plan=plan, baseline_variant=variant_by_id[history.baseline_variant_sha256],
                candidate_variant=variant_by_id[history.candidate_variant_sha256], trials=history_trials,
                evaluations=history_evaluations,
                expected_dataset_item_sha256s=history.expected_dataset_item_sha256s,
            )
            if rebuilt != history:
                raise ValueError
        for decision in verified.decisions:
            proposal = proposal_by_id.get(decision.proposal_sha256)
            if proposal is None or decision.finding_sha256 not in finding_ids or proposal.finding_sha256 != decision.finding_sha256:
                raise ValueError
    except Exception:
        raise PathlightError("Pathlight optimization closure is invalid") from None


def _trace_identities(direct: Sequence[str], bundles: Sequence[object]) -> set[str]:
    values = {_require_sha256(value) for value in _as_sequence(direct)}
    for bundle in _as_sequence(bundles):
        mapping = cast(Any, bundle).to_mapping() if hasattr(bundle, "to_mapping") else bundle
        if not isinstance(mapping, Mapping):
            raise ValueError
        values.add(_require_sha256(mapping.get("trace_sha256")))
    return values


def _verified_bundles(values: Sequence[object], expected_type: type[object], validator: Callable[[Any], object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for value in _as_sequence(values):
        if type(value) is not expected_type:
            raise ValueError
        verified = validator(cast(Any, value))
        if type(verified) is not expected_type:
            raise ValueError
        identity = _require_sha256(getattr(verified, "bundle_sha256"))
        if identity in result:
            raise ValueError
        result[identity] = verified
    return result


@dataclass(frozen=True, slots=True)
class OptimizationCatalog:
    """A deterministic, read-only index over verified optimization bundles."""

    _trials: Mapping[str, OptimizationTrial]
    _histories: Mapping[str, TrialHistory]
    _decisions: Mapping[str, Decision]

    def __post_init__(self) -> None:
        try:
            trials = _verified_catalog(self._trials, OptimizationTrial, validate_optimization_trial, "optimization_trial_sha256")
            histories = _verified_catalog(self._histories, TrialHistory, validate_trial_history, "trial_history_sha256")
            decisions = _verified_catalog(self._decisions, Decision, validate_decision, "decision_sha256")
        except Exception:
            raise PathlightError("Pathlight optimization catalog is invalid") from None
        object.__setattr__(self, "_trials", MappingProxyType(trials))
        object.__setattr__(self, "_histories", MappingProxyType(histories))
        object.__setattr__(self, "_decisions", MappingProxyType(decisions))

    @classmethod
    def build(cls, bundles: Sequence[OptimizationBundle]) -> OptimizationCatalog:
        try:
            trials: dict[str, OptimizationTrial] = {}
            histories: dict[str, TrialHistory] = {}
            decisions: dict[str, Decision] = {}
            for bundle in _as_sequence(bundles):
                if type(bundle) is not OptimizationBundle:
                    raise ValueError
                verified = validate_optimization_bundle(bundle.to_mapping())
                for value in verified.trials:
                    if value.optimization_trial_sha256 in trials:
                        raise ValueError
                    trials[value.optimization_trial_sha256] = value
                for value in verified.histories:
                    if value.trial_history_sha256 in histories:
                        raise ValueError
                    histories[value.trial_history_sha256] = value
                for value in verified.decisions:
                    if value.decision_sha256 in decisions:
                        raise ValueError
                    decisions[value.decision_sha256] = value
            return cls(trials, histories, decisions)
        except Exception:
            raise PathlightError("Pathlight optimization catalog is invalid") from None

    def show_history(self, trial_history_sha256: str) -> Mapping[str, object]:
        return self._history(trial_history_sha256).to_mapping()

    def show_decision(self, decision_sha256: str) -> Mapping[str, object]:
        try:
            return self._decisions[_require_sha256(decision_sha256)].to_mapping()
        except Exception:
            raise PathlightError("Pathlight optimization decision identity is unknown") from None

    def list_trials(self, trial_history_sha256: str, *, variant_role: str | None = None) -> tuple[Mapping[str, object], ...]:
        history = self._history(trial_history_sha256)
        if variant_role is not None and (type(variant_role) is not str or variant_role not in {"baseline", "candidate"}):
            raise PathlightError("Pathlight optimization variant role is invalid")
        ids = history.baseline_optimization_trial_sha256s + history.candidate_optimization_trial_sha256s
        return tuple(self._trials[value].to_mapping() for value in sorted(ids) if variant_role is None or self._trials[value].variant_role == variant_role)

    def _history(self, identity: str) -> TrialHistory:
        try:
            return self._histories[_require_sha256(identity)]
        except Exception:
            raise PathlightError("Pathlight optimization history identity is unknown") from None


def _verified_catalog(values: Mapping[str, object], expected_type: type[object], validator: Callable[[Mapping[str, object]], object], identity_name: str) -> dict[str, object]:
    if not isinstance(values, Mapping):
        raise ValueError
    result: dict[str, object] = {}
    for identity, value in values.items():
        if type(identity) is not str or type(value) is not expected_type:
            raise ValueError
        verified = validator(value.to_mapping())  # type: ignore[attr-defined]
        if identity != getattr(verified, identity_name) or identity in result:
            raise ValueError
        result[identity] = verified
    return result
