"""Immutable, content-addressed Pathlight experiment lineage contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Literal, Protocol, Sequence, TypeAlias, cast

from asterion.pathlight.evaluation import EvaluationRecord, validate_evaluation_record
from asterion.pathlight.protocol import PathlightError


SubjectKind: TypeAlias = Literal["trace", "span", "thread", "experiment", "case-trial"]
EvidenceState: TypeAlias = Literal["observed", "recovered", "missing"]
EvaluatorKind: TypeAlias = Literal["rule", "human", "judge", "recovered"]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SUBJECT_KINDS = frozenset({"trace", "span", "thread", "experiment", "case-trial"})
_EVIDENCE_STATES = frozenset({"observed", "recovered", "missing"})
_EVALUATOR_KINDS = frozenset({"rule", "human", "judge", "recovered"})
_MISSING_EVIDENCE = frozenset(
    {
        "context-frames",
        "retrieval-coverage",
        "tool-payload-lineage",
        "sealed-config-digest",
        "sealed-analysis-digest",
        "paper-method-detail",
    }
)

_SUBJECT_REF_FIELDS = frozenset({"subject_kind", "subject_sha256", "subject_ref_sha256"})
_DATASET_SNAPSHOT_FIELDS = frozenset(
    {
        "dataset_contract_sha256",
        "content_sha256",
        "total_count",
        "snapshot_version",
        "parent_snapshot_sha256",
        "dataset_snapshot_sha256",
    }
)
_EVALUATOR_CONTRACT_FIELDS = frozenset(
    {
        "metric_contract_sha256",
        "evaluator_kind",
        "implementation_sha256",
        "input_contract_sha256",
        "output_contract_sha256",
        "failure_semantics_sha256",
        "contract_version",
        "evaluator_contract_sha256",
    }
)
_VARIANT_FIELDS = frozenset(
    {
        "assembly_sha256",
        "package_set_sha256",
        "implementation_sha256",
        "runtime_sha256",
        "model_sha256",
        "toolset_sha256",
        "prompt_contract_sha256",
        "policy_sha256",
        "change_sha256",
        "variant_sha256",
    }
)
_EXPERIMENT_PLAN_FIELDS = frozenset(
    {
        "dataset_snapshot_sha256",
        "scope_sha256",
        "baseline_variant_sha256",
        "candidate_variant_sha256s",
        "assignment_sha256",
        "evaluator_contract_sha256s",
        "budget_sha256",
        "stop_criteria_sha256",
        "authorization_sha256",
        "experiment_plan_sha256",
    }
)
_CASE_TRIAL_FIELDS = frozenset(
    {
        "experiment_plan_sha256",
        "dataset_item_sha256",
        "variant_sha256",
        "trace_sha256",
        "evaluation_sha256s",
        "evidence_state",
        "missing_evidence",
        "case_trial_sha256",
    }
)
EXPERIMENT_BUNDLE_SCHEMA = "asterion.pathlight-experiment/v1"
EXPERIMENT_BUNDLE_FILENAME = "pathlight-experiment.json"
_EXPERIMENT_BUNDLE_FIELDS = frozenset(
    {
        "schema",
        "datasets",
        "evaluators",
        "variants",
        "plans",
        "trials",
        "evaluations",
        "bundle_sha256",
    }
)
_MAX_EXPERIMENT_BUNDLE_BYTES = 1_000_000


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _require_sha256(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError
    return value


def _require_semver(value: object) -> str:
    if type(value) is not str or _SEMVER.fullmatch(value) is None:
        raise ValueError
    return value


def _require_optional_sha256(value: object) -> str | None:
    if value is None:
        return None
    return _require_sha256(value)


def _require_subject_kind(value: object) -> SubjectKind:
    if type(value) is not str or value not in _SUBJECT_KINDS:
        raise ValueError
    return cast(SubjectKind, value)


def _require_evaluator_kind(value: object) -> EvaluatorKind:
    if type(value) is not str or value not in _EVALUATOR_KINDS:
        raise ValueError
    return cast(EvaluatorKind, value)


def _require_evidence_state(value: object) -> EvidenceState:
    if type(value) is not str or value not in _EVIDENCE_STATES:
        raise ValueError
    return cast(EvidenceState, value)


def _require_nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _require_sorted_unique_sha256s(value: object) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise ValueError
    values = tuple(_require_sha256(item) for item in value)
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError
    return values


def _require_sorted_unique_missing_evidence(value: object) -> tuple[str, ...]:
    if type(value) is not tuple or any(
        type(item) is not str or item not in _MISSING_EVIDENCE for item in value
    ):
        raise ValueError
    values = tuple(value)
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError
    return values


def _validated_values(
    mapping: Mapping[str, object], fields: frozenset[str]
) -> dict[str, object]:
    if not isinstance(mapping, Mapping) or set(mapping) != fields:
        raise ValueError
    return {name: mapping[name] for name in fields}


@dataclass(frozen=True, slots=True)
class SubjectRef:
    """An exact, public-safe reference to one content-addressed subject."""

    subject_kind: SubjectKind
    subject_sha256: str
    subject_ref_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            _require_subject_kind(self.subject_kind)
            _require_sha256(self.subject_sha256)
        except ValueError:
            raise PathlightError("Pathlight subject ref is invalid") from None
        object.__setattr__(self, "subject_ref_sha256", _canonical_digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {"subject_kind": self.subject_kind, "subject_sha256": self.subject_sha256}

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "subject_ref_sha256": self.subject_ref_sha256}


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    """A versioned dataset identity with no dataset-item content."""

    dataset_contract_sha256: str
    content_sha256: str
    total_count: int
    snapshot_version: str
    parent_snapshot_sha256: str | None = None
    dataset_snapshot_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            _require_sha256(self.dataset_contract_sha256)
            _require_sha256(self.content_sha256)
            _require_nonnegative_int(self.total_count)
            _require_semver(self.snapshot_version)
            _require_optional_sha256(self.parent_snapshot_sha256)
        except ValueError:
            raise PathlightError("Pathlight dataset snapshot is invalid") from None
        object.__setattr__(self, "dataset_snapshot_sha256", _canonical_digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "dataset_contract_sha256": self.dataset_contract_sha256,
            "content_sha256": self.content_sha256,
            "total_count": self.total_count,
            "snapshot_version": self.snapshot_version,
            "parent_snapshot_sha256": self.parent_snapshot_sha256,
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "dataset_snapshot_sha256": self.dataset_snapshot_sha256}


@dataclass(frozen=True, slots=True)
class EvaluatorContract:
    """A versioned, public-safe evaluator implementation contract."""

    metric_contract_sha256: str
    evaluator_kind: EvaluatorKind
    implementation_sha256: str
    input_contract_sha256: str
    output_contract_sha256: str
    failure_semantics_sha256: str
    contract_version: str
    evaluator_contract_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            _require_sha256(self.metric_contract_sha256)
            _require_sha256(self.implementation_sha256)
            _require_sha256(self.input_contract_sha256)
            _require_sha256(self.output_contract_sha256)
            _require_sha256(self.failure_semantics_sha256)
            _require_semver(self.contract_version)
            _require_evaluator_kind(self.evaluator_kind)
        except ValueError:
            raise PathlightError("Pathlight evaluator contract is invalid") from None
        object.__setattr__(self, "evaluator_contract_sha256", _canonical_digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "metric_contract_sha256": self.metric_contract_sha256,
            "evaluator_kind": self.evaluator_kind,
            "implementation_sha256": self.implementation_sha256,
            "input_contract_sha256": self.input_contract_sha256,
            "output_contract_sha256": self.output_contract_sha256,
            "failure_semantics_sha256": self.failure_semantics_sha256,
            "contract_version": self.contract_version,
        }

    def to_mapping(self) -> dict[str, object]:
        return {
            **self._unsigned_mapping(),
            "evaluator_contract_sha256": self.evaluator_contract_sha256,
        }


@dataclass(frozen=True, slots=True)
class Variant:
    """The exact safe digests that identify one executable experiment variant."""

    assembly_sha256: str
    package_set_sha256: str
    implementation_sha256: str
    runtime_sha256: str
    model_sha256: str
    toolset_sha256: str
    prompt_contract_sha256: str
    policy_sha256: str
    change_sha256: str
    variant_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            for value in self._unsigned_mapping().values():
                _require_sha256(value)
        except ValueError:
            raise PathlightError("Pathlight variant is invalid") from None
        object.__setattr__(self, "variant_sha256", _canonical_digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "assembly_sha256": self.assembly_sha256,
            "package_set_sha256": self.package_set_sha256,
            "implementation_sha256": self.implementation_sha256,
            "runtime_sha256": self.runtime_sha256,
            "model_sha256": self.model_sha256,
            "toolset_sha256": self.toolset_sha256,
            "prompt_contract_sha256": self.prompt_contract_sha256,
            "policy_sha256": self.policy_sha256,
            "change_sha256": self.change_sha256,
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "variant_sha256": self.variant_sha256}


@dataclass(frozen=True, slots=True)
class ExperimentPlan:
    """An authorized, deterministic experiment definition without execution authority."""

    dataset_snapshot_sha256: str
    scope_sha256: str
    baseline_variant_sha256: str
    candidate_variant_sha256s: tuple[str, ...]
    assignment_sha256: str
    evaluator_contract_sha256s: tuple[str, ...]
    budget_sha256: str
    stop_criteria_sha256: str
    authorization_sha256: str | None = None
    experiment_plan_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            _require_sha256(self.dataset_snapshot_sha256)
            _require_sha256(self.scope_sha256)
            _require_sha256(self.baseline_variant_sha256)
            _require_sorted_unique_sha256s(self.candidate_variant_sha256s)
            _require_sha256(self.assignment_sha256)
            _require_sorted_unique_sha256s(self.evaluator_contract_sha256s)
            _require_sha256(self.budget_sha256)
            _require_sha256(self.stop_criteria_sha256)
            _require_optional_sha256(self.authorization_sha256)
        except ValueError:
            raise PathlightError("Pathlight experiment plan is invalid") from None
        object.__setattr__(self, "experiment_plan_sha256", _canonical_digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "dataset_snapshot_sha256": self.dataset_snapshot_sha256,
            "scope_sha256": self.scope_sha256,
            "baseline_variant_sha256": self.baseline_variant_sha256,
            "candidate_variant_sha256s": self.candidate_variant_sha256s,
            "assignment_sha256": self.assignment_sha256,
            "evaluator_contract_sha256s": self.evaluator_contract_sha256s,
            "budget_sha256": self.budget_sha256,
            "stop_criteria_sha256": self.stop_criteria_sha256,
            "authorization_sha256": self.authorization_sha256,
        }

    def to_mapping(self) -> dict[str, object]:
        return {
            **self._unsigned_mapping(),
            "experiment_plan_sha256": self.experiment_plan_sha256,
        }


@dataclass(frozen=True, slots=True)
class CaseTrial:
    """One public-safe dataset item, variant, trace, and evaluation lineage link."""

    experiment_plan_sha256: str
    dataset_item_sha256: str
    variant_sha256: str
    trace_sha256: str
    evaluation_sha256s: tuple[str, ...]
    evidence_state: EvidenceState
    missing_evidence: tuple[str, ...]
    case_trial_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            _require_sha256(self.experiment_plan_sha256)
            _require_sha256(self.dataset_item_sha256)
            _require_sha256(self.variant_sha256)
            _require_sha256(self.trace_sha256)
            _require_sorted_unique_sha256s(self.evaluation_sha256s)
            _require_sorted_unique_missing_evidence(self.missing_evidence)
            _require_evidence_state(self.evidence_state)
        except ValueError:
            raise PathlightError("Pathlight case trial is invalid") from None
        object.__setattr__(self, "case_trial_sha256", _canonical_digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "experiment_plan_sha256": self.experiment_plan_sha256,
            "dataset_item_sha256": self.dataset_item_sha256,
            "variant_sha256": self.variant_sha256,
            "trace_sha256": self.trace_sha256,
            "evaluation_sha256s": self.evaluation_sha256s,
            "evidence_state": self.evidence_state,
            "missing_evidence": self.missing_evidence,
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "case_trial_sha256": self.case_trial_sha256}


def validate_subject_ref(mapping: Mapping[str, object]) -> SubjectRef:
    """Validate one exact public subject reference mapping."""

    try:
        value = _validated_values(mapping, _SUBJECT_REF_FIELDS)
        subject = SubjectRef(
            _require_subject_kind(value["subject_kind"]),
            _require_sha256(value["subject_sha256"]),
        )
        if not hmac.compare_digest(
            _require_sha256(value["subject_ref_sha256"]), subject.subject_ref_sha256
        ):
            raise ValueError
    except Exception:
        pass
    else:
        return subject
    raise PathlightError("Pathlight subject ref is invalid")


def validate_dataset_snapshot(mapping: Mapping[str, object]) -> DatasetSnapshot:
    """Validate one exact public dataset snapshot mapping."""

    try:
        value = _validated_values(mapping, _DATASET_SNAPSHOT_FIELDS)
        dataset = DatasetSnapshot(
            _require_sha256(value["dataset_contract_sha256"]),
            _require_sha256(value["content_sha256"]),
            _require_nonnegative_int(value["total_count"]),
            _require_semver(value["snapshot_version"]),
            _require_optional_sha256(value["parent_snapshot_sha256"]),
        )
        if not hmac.compare_digest(
            _require_sha256(value["dataset_snapshot_sha256"]), dataset.dataset_snapshot_sha256
        ):
            raise ValueError
    except Exception:
        pass
    else:
        return dataset
    raise PathlightError("Pathlight dataset snapshot is invalid")


def validate_evaluator_contract(mapping: Mapping[str, object]) -> EvaluatorContract:
    """Validate one exact public evaluator contract mapping."""

    try:
        value = _validated_values(mapping, _EVALUATOR_CONTRACT_FIELDS)
        evaluator = EvaluatorContract(
            _require_sha256(value["metric_contract_sha256"]),
            _require_evaluator_kind(value["evaluator_kind"]),
            _require_sha256(value["implementation_sha256"]),
            _require_sha256(value["input_contract_sha256"]),
            _require_sha256(value["output_contract_sha256"]),
            _require_sha256(value["failure_semantics_sha256"]),
            _require_semver(value["contract_version"]),
        )
        if not hmac.compare_digest(
            _require_sha256(value["evaluator_contract_sha256"]),
            evaluator.evaluator_contract_sha256,
        ):
            raise ValueError
    except Exception:
        pass
    else:
        return evaluator
    raise PathlightError("Pathlight evaluator contract is invalid")


def validate_variant(mapping: Mapping[str, object]) -> Variant:
    """Validate one exact public variant mapping."""

    try:
        value = _validated_values(mapping, _VARIANT_FIELDS)
        variant = Variant(
            _require_sha256(value["assembly_sha256"]),
            _require_sha256(value["package_set_sha256"]),
            _require_sha256(value["implementation_sha256"]),
            _require_sha256(value["runtime_sha256"]),
            _require_sha256(value["model_sha256"]),
            _require_sha256(value["toolset_sha256"]),
            _require_sha256(value["prompt_contract_sha256"]),
            _require_sha256(value["policy_sha256"]),
            _require_sha256(value["change_sha256"]),
        )
        if not hmac.compare_digest(
            _require_sha256(value["variant_sha256"]), variant.variant_sha256
        ):
            raise ValueError
    except Exception:
        pass
    else:
        return variant
    raise PathlightError("Pathlight variant is invalid")


def validate_experiment_plan(mapping: Mapping[str, object]) -> ExperimentPlan:
    """Validate one exact public experiment plan mapping."""

    try:
        value = _validated_values(mapping, _EXPERIMENT_PLAN_FIELDS)
        plan = ExperimentPlan(
            _require_sha256(value["dataset_snapshot_sha256"]),
            _require_sha256(value["scope_sha256"]),
            _require_sha256(value["baseline_variant_sha256"]),
            _require_sorted_unique_sha256s(value["candidate_variant_sha256s"]),
            _require_sha256(value["assignment_sha256"]),
            _require_sorted_unique_sha256s(value["evaluator_contract_sha256s"]),
            _require_sha256(value["budget_sha256"]),
            _require_sha256(value["stop_criteria_sha256"]),
            _require_optional_sha256(value["authorization_sha256"]),
        )
        if not hmac.compare_digest(
            _require_sha256(value["experiment_plan_sha256"]), plan.experiment_plan_sha256
        ):
            raise ValueError
    except Exception:
        pass
    else:
        return plan
    raise PathlightError("Pathlight experiment plan is invalid")


def validate_case_trial(mapping: Mapping[str, object]) -> CaseTrial:
    """Validate one exact public case-trial mapping."""

    try:
        value = _validated_values(mapping, _CASE_TRIAL_FIELDS)
        trial = CaseTrial(
            _require_sha256(value["experiment_plan_sha256"]),
            _require_sha256(value["dataset_item_sha256"]),
            _require_sha256(value["variant_sha256"]),
            _require_sha256(value["trace_sha256"]),
            _require_sorted_unique_sha256s(value["evaluation_sha256s"]),
            _require_evidence_state(value["evidence_state"]),
            _require_sorted_unique_missing_evidence(value["missing_evidence"]),
        )
        if not hmac.compare_digest(
            _require_sha256(value["case_trial_sha256"]), trial.case_trial_sha256
        ):
            raise ValueError
    except Exception:
        pass
    else:
        return trial
    raise PathlightError("Pathlight case trial is invalid")


@dataclass(frozen=True, slots=True)
class ExperimentBundle:
    """A complete, immutable, content-addressed Pathlight experiment closure."""

    datasets: tuple[DatasetSnapshot, ...]
    evaluators: tuple[EvaluatorContract, ...]
    variants: tuple[Variant, ...]
    plans: tuple[ExperimentPlan, ...]
    trials: tuple[CaseTrial, ...]
    evaluations: tuple[EvaluationRecord, ...]
    bundle_sha256: str

    def __post_init__(self) -> None:
        values: tuple[
            tuple[DatasetSnapshot, ...],
            tuple[EvaluatorContract, ...],
            tuple[Variant, ...],
            tuple[ExperimentPlan, ...],
            tuple[CaseTrial, ...],
            tuple[EvaluationRecord, ...],
        ] | None = None
        valid = False
        try:
            values = _normalize_experiment_values(
                self.datasets,
                self.evaluators,
                self.variants,
                self.plans,
                self.trials,
                self.evaluations,
                require_sorted=True,
            )
            _validate_experiment_closure(*values)
            supplied = _require_sha256(self.bundle_sha256)
            expected = _canonical_digest(_experiment_document(*values))
            if not hmac.compare_digest(supplied, expected):
                raise ValueError
            valid = True
        except Exception:
            pass
        if values is None or not valid:
            raise PathlightError("Pathlight experiment bundle is invalid")
        for field_name, value in zip(
            ("datasets", "evaluators", "variants", "plans", "trials", "evaluations"),
            values,
            strict=True,
        ):
            object.__setattr__(self, field_name, value)

    @classmethod
    def build(
        cls,
        *,
        datasets: Sequence[DatasetSnapshot],
        evaluators: Sequence[EvaluatorContract],
        variants: Sequence[Variant],
        plans: Sequence[ExperimentPlan],
        trials: Sequence[CaseTrial],
        evaluations: Sequence[EvaluationRecord],
    ) -> ExperimentBundle:
        """Build one canonical bundle after validating its exact reference closure."""

        failure: PathlightError | None = None
        try:
            values = _normalize_experiment_values(
                datasets,
                evaluators,
                variants,
                plans,
                trials,
                evaluations,
                require_sorted=False,
            )
            _validate_experiment_closure(*values)
            document = _experiment_document(*values)
            return cls(*values, _canonical_digest(document))
        except PathlightError as error:
            failure = error
        except Exception:
            pass
        if failure is not None:
            raise failure
        raise PathlightError("Pathlight experiment bundle is invalid")

    def to_mapping(self) -> dict[str, object]:
        """Return the complete canonical JSON-compatible bundle document."""

        return {
            **_experiment_document(
                self.datasets,
                self.evaluators,
                self.variants,
                self.plans,
                self.trials,
                self.evaluations,
            ),
            "bundle_sha256": self.bundle_sha256,
        }


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _normalize_experiment_values(
    datasets: object,
    evaluators: object,
    variants: object,
    plans: object,
    trials: object,
    evaluations: object,
    *,
    require_sorted: bool,
) -> tuple[
    tuple[DatasetSnapshot, ...],
    tuple[EvaluatorContract, ...],
    tuple[Variant, ...],
    tuple[ExperimentPlan, ...],
    tuple[CaseTrial, ...],
    tuple[EvaluationRecord, ...],
]:
    if require_sorted and any(
        type(value) is not tuple
        for value in (datasets, evaluators, variants, plans, trials, evaluations)
    ):
        raise ValueError
    if not require_sorted and any(
        not _is_sequence(value)
        for value in (datasets, evaluators, variants, plans, trials, evaluations)
    ):
        raise ValueError
    normalized_datasets = _normalize_collection(
        datasets,
        DatasetSnapshot,
        validate_dataset_snapshot,
        "dataset_snapshot_sha256",
        require_sorted,
    )
    normalized_evaluators = _normalize_collection(
        evaluators,
        EvaluatorContract,
        validate_evaluator_contract,
        "evaluator_contract_sha256",
        require_sorted,
    )
    normalized_variants = _normalize_collection(
        variants, Variant, validate_variant, "variant_sha256", require_sorted
    )
    normalized_plans = _normalize_collection(
        plans,
        ExperimentPlan,
        validate_experiment_plan,
        "experiment_plan_sha256",
        require_sorted,
    )
    normalized_trials = _normalize_collection(
        trials, CaseTrial, validate_case_trial, "case_trial_sha256", require_sorted
    )
    normalized_evaluations = _normalize_collection(
        evaluations,
        EvaluationRecord,
        validate_evaluation_record,
        "evaluation_sha256",
        require_sorted,
    )
    return (
        cast(tuple[DatasetSnapshot, ...], normalized_datasets),
        cast(tuple[EvaluatorContract, ...], normalized_evaluators),
        cast(tuple[Variant, ...], normalized_variants),
        cast(tuple[ExperimentPlan, ...], normalized_plans),
        cast(tuple[CaseTrial, ...], normalized_trials),
        cast(tuple[EvaluationRecord, ...], normalized_evaluations),
    )


def _normalize_collection(
    values: object,
    expected_type: type[object],
    validator: Callable[[Mapping[str, object]], object],
    identity_name: str,
    require_sorted: bool,
) -> tuple[object, ...]:
    if not _is_sequence(values):
        raise ValueError
    normalized: list[object] = []
    for value in cast(Sequence[object], values):
        if type(value) is not expected_type:
            raise ValueError
        normalized.append(
            cast(
                object,
                validator(cast(_Mappable, value).to_mapping()),
            )
        )
    identities = tuple(getattr(value, identity_name) for value in normalized)
    if len(identities) != len(set(identities)):
        raise ValueError
    ordered = tuple(sorted(normalized, key=lambda value: getattr(value, identity_name)))
    if require_sorted and tuple(normalized) != ordered:
        raise ValueError
    return ordered


class _Mappable(Protocol):
    def to_mapping(self) -> dict[str, object]: ...


def _validate_experiment_closure(
    datasets: tuple[DatasetSnapshot, ...],
    evaluators: tuple[EvaluatorContract, ...],
    variants: tuple[Variant, ...],
    plans: tuple[ExperimentPlan, ...],
    trials: tuple[CaseTrial, ...],
    evaluations: tuple[EvaluationRecord, ...],
) -> None:
    dataset_ids = {value.dataset_snapshot_sha256 for value in datasets}
    evaluator_ids = {value.evaluator_contract_sha256 for value in evaluators}
    metric_ids = [value.metric_contract_sha256 for value in evaluators]
    variant_ids = {value.variant_sha256 for value in variants}
    plan_ids = {value.experiment_plan_sha256 for value in plans}
    evaluation_ids = {value.evaluation_sha256 for value in evaluations}
    if len(metric_ids) != len(set(metric_ids)):
        raise PathlightError("Pathlight experiment evaluator metric is ambiguous")
    for plan in plans:
        if (
            plan.dataset_snapshot_sha256 not in dataset_ids
            or plan.baseline_variant_sha256 not in variant_ids
            or any(value not in variant_ids for value in plan.candidate_variant_sha256s)
            or any(value not in evaluator_ids for value in plan.evaluator_contract_sha256s)
        ):
            raise PathlightError("Pathlight experiment plan reference is unresolved")
    for trial in trials:
        if (
            trial.experiment_plan_sha256 not in plan_ids
            or trial.variant_sha256 not in variant_ids
            or any(value not in evaluation_ids for value in trial.evaluation_sha256s)
        ):
            raise PathlightError("Pathlight experiment trial reference is unresolved")
    metric_id_set = set(metric_ids)
    for evaluation in evaluations:
        if (
            evaluation.dataset_snapshot_sha256 not in dataset_ids
            or evaluation.metric_contract_sha256 not in metric_id_set
        ):
            raise PathlightError("Pathlight experiment evaluation reference is unresolved")


def _experiment_document(
    datasets: tuple[DatasetSnapshot, ...],
    evaluators: tuple[EvaluatorContract, ...],
    variants: tuple[Variant, ...],
    plans: tuple[ExperimentPlan, ...],
    trials: tuple[CaseTrial, ...],
    evaluations: tuple[EvaluationRecord, ...],
) -> dict[str, object]:
    return {
        "schema": EXPERIMENT_BUNDLE_SCHEMA,
        "datasets": [value.to_mapping() for value in datasets],
        "evaluators": [value.to_mapping() for value in evaluators],
        "variants": [value.to_mapping() for value in variants],
        "plans": [value.to_mapping() for value in plans],
        "trials": [value.to_mapping() for value in trials],
        "evaluations": [value.to_mapping() for value in evaluations],
    }


def write_experiment_bundle(bundle: ExperimentBundle, path: Path) -> None:
    """Exclusively write one private canonical experiment bundle."""

    encoded: bytes | None = None
    try:
        if (
            type(bundle) is not ExperimentBundle
            or not isinstance(path, Path)
            or path.name != EXPERIMENT_BUNDLE_FILENAME
        ):
            raise ValueError
        verified = validate_experiment_bundle(bundle.to_mapping())
        encoded = json.dumps(
            verified.to_mapping(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except Exception:
        pass
    if encoded is None:
        raise PathlightError("Pathlight experiment target is invalid")

    directory_fd = -1
    descriptor = -1
    failure = False
    try:
        directory_fd = _open_parent_directory(path)
        nofollow = _nofollow_flag()
        descriptor = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=directory_fd,
        )
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, encoded)
    except Exception:
        failure = True
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except Exception:
                failure = True
        if directory_fd >= 0:
            try:
                os.close(directory_fd)
            except Exception:
                failure = True
    if failure:
        raise PathlightError("Pathlight experiment target is unavailable")


def _write_all(descriptor: int, encoded: bytes) -> None:
    remaining = memoryview(encoded)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("Pathlight experiment target write is incomplete")
        remaining = remaining[written:]


def read_experiment_bundle(path: Path) -> ExperimentBundle:
    """Read one descriptor-verified private experiment bundle."""

    valid_path = False
    try:
        valid_path = (
            isinstance(path, Path) and path.name == EXPERIMENT_BUNDLE_FILENAME
        )
    except Exception:
        pass
    if not valid_path:
        raise PathlightError("Pathlight experiment source is invalid")
    document = _read_experiment_document(path)
    if not isinstance(document, Mapping):
        raise PathlightError("Pathlight experiment source is invalid")
    return validate_experiment_bundle(document)


def _read_experiment_document(path: Path) -> object:
    directory_fd = -1
    source_fd = -1
    failure = False
    document: object | None = None
    try:
        directory_fd = _open_parent_directory(path)
        source_fd = os.open(
            path.name,
            os.O_RDONLY | _nofollow_flag(),
            dir_fd=directory_fd,
        )
        before = os.fstat(source_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size > _MAX_EXPERIMENT_BUNDLE_BYTES
        ):
            raise OSError("Pathlight experiment source is unsafe")
        encoded = _read_bounded(source_fd, _MAX_EXPERIMENT_BUNDLE_BYTES + 1)
        after = os.fstat(source_fd)
        if (
            len(encoded) > _MAX_EXPERIMENT_BUNDLE_BYTES
            or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or before.st_size != after.st_size
            or after.st_size != len(encoded)
        ):
            raise OSError("Pathlight experiment source changed while reading")
        document = json.loads(encoded.decode("utf-8"))
    except Exception:
        failure = True
    finally:
        if source_fd >= 0:
            try:
                os.close(source_fd)
            except Exception:
                failure = True
        if directory_fd >= 0:
            try:
                os.close(directory_fd)
            except Exception:
                failure = True
    if failure or document is None:
        raise PathlightError("Pathlight experiment source is invalid")
    return document


def _nofollow_flag() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(nofollow, int):
        raise OSError("no-follow descriptor opening is unavailable")
    return nofollow


def _open_parent_directory(path: Path) -> int:
    absolute = path.absolute()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _nofollow_flag()
    descriptor = -1
    failure = False
    try:
        descriptor = os.open(absolute.anchor, flags)
        for component in absolute.parts[1:-1]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            try:
                os.close(descriptor)
            except Exception:
                try:
                    os.close(next_descriptor)
                except Exception:
                    pass
                raise
            descriptor = next_descriptor
    except BaseException as error:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except Exception:
                pass
            descriptor = -1
        if not isinstance(error, Exception):
            raise
        failure = True
    if failure:
        raise OSError("Pathlight experiment parent is unavailable")
    return descriptor


def _read_bounded(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total < limit:
        chunk = os.read(descriptor, min(65_536, limit - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def validate_experiment_bundle(mapping: Mapping[str, object]) -> ExperimentBundle:
    """Validate one exact experiment-bundle document and its reference closure."""

    bundle: ExperimentBundle | None = None
    try:
        if type(mapping) is not dict or set(mapping) != _EXPERIMENT_BUNDLE_FIELDS:
            raise ValueError
        if mapping["schema"] != EXPERIMENT_BUNDLE_SCHEMA:
            raise ValueError
        raw_collections = tuple(
            mapping[name]
            for name in (
                "datasets",
                "evaluators",
                "variants",
                "plans",
                "trials",
                "evaluations",
            )
        )
        if any(type(value) is not list for value in raw_collections):
            raise ValueError
        document = {
            key: value for key, value in mapping.items() if key != "bundle_sha256"
        }
        supplied = _require_sha256(mapping["bundle_sha256"])
        if not hmac.compare_digest(supplied, _canonical_digest(document)):
            raise ValueError
        datasets = tuple(
            validate_dataset_snapshot(_plain_mapping(item))
            for item in raw_collections[0]
        )
        evaluators = tuple(
            validate_evaluator_contract(_plain_mapping(item))
            for item in raw_collections[1]
        )
        variants = tuple(
            validate_variant(_plain_mapping(item)) for item in raw_collections[2]
        )
        plans = tuple(
            validate_experiment_plan(
                _tuple_fields(
                    _plain_mapping(item),
                    (
                        "candidate_variant_sha256s",
                        "evaluator_contract_sha256s",
                    ),
                )
            )
            for item in raw_collections[3]
        )
        trials = tuple(
            validate_case_trial(
                _tuple_fields(
                    _plain_mapping(item),
                    ("evaluation_sha256s", "missing_evidence"),
                )
            )
            for item in raw_collections[4]
        )
        evaluations = tuple(
            validate_evaluation_record(_plain_mapping(item))
            for item in raw_collections[5]
        )
        bundle = ExperimentBundle(
            datasets,
            evaluators,
            variants,
            plans,
            trials,
            evaluations,
            supplied,
        )
    except Exception:
        pass
    if bundle is None:
        raise PathlightError("Pathlight experiment bundle is invalid")
    return bundle


def _plain_mapping(value: object) -> Mapping[str, object]:
    if type(value) is not dict:
        raise ValueError
    return value


def _tuple_fields(mapping: Mapping[str, object], fields: tuple[str, ...]) -> Mapping[str, object]:
    copy = dict(mapping)
    for field_name in fields:
        value = copy.get(field_name)
        if type(value) not in {list, tuple}:
            raise ValueError
        copy[field_name] = tuple(cast(list[object] | tuple[object, ...], value))
    return copy


@dataclass(frozen=True, slots=True)
class ExperimentCatalog:
    """A deterministic, read-only index of verified experiment bundles."""

    _plans: Mapping[str, ExperimentPlan]
    _trials: Mapping[str, CaseTrial]

    def __post_init__(self) -> None:
        plans: dict[str, ExperimentPlan] | None = None
        trials: dict[str, CaseTrial] | None = None
        try:
            if not isinstance(self._plans, Mapping) or not isinstance(
                self._trials, Mapping
            ):
                raise ValueError
            plans = {}
            trials = {}
            for identity, plan in self._plans.items():
                if type(identity) is not str or type(plan) is not ExperimentPlan:
                    raise ValueError
                verified = validate_experiment_plan(plan.to_mapping())
                if identity != verified.experiment_plan_sha256 or identity in plans:
                    raise ValueError
                plans[identity] = verified
            for identity, trial in self._trials.items():
                if type(identity) is not str or type(trial) is not CaseTrial:
                    raise ValueError
                verified = validate_case_trial(trial.to_mapping())
                if (
                    identity != verified.case_trial_sha256
                    or identity in trials
                    or verified.experiment_plan_sha256 not in plans
                ):
                    raise ValueError
                trials[identity] = verified
        except Exception:
            plans = None
            trials = None
        if plans is None or trials is None:
            raise PathlightError("Pathlight experiment catalog is invalid")
        object.__setattr__(self, "_plans", MappingProxyType(plans))
        object.__setattr__(self, "_trials", MappingProxyType(trials))

    @classmethod
    def build(cls, bundles: Sequence[ExperimentBundle]) -> ExperimentCatalog:
        catalog: ExperimentCatalog | None = None
        try:
            if not _is_sequence(bundles):
                raise ValueError
            plans: dict[str, ExperimentPlan] = {}
            trials: dict[str, CaseTrial] = {}
            for bundle in bundles:
                if type(bundle) is not ExperimentBundle:
                    raise ValueError
                verified = validate_experiment_bundle(bundle.to_mapping())
                for plan in verified.plans:
                    if plan.experiment_plan_sha256 in plans:
                        raise ValueError
                    plans[plan.experiment_plan_sha256] = plan
                for trial in verified.trials:
                    if trial.case_trial_sha256 in trials:
                        raise ValueError
                    trials[trial.case_trial_sha256] = trial
            catalog = cls(MappingProxyType(plans), MappingProxyType(trials))
        except Exception:
            pass
        if catalog is None:
            raise PathlightError("Pathlight experiment catalog is invalid")
        return catalog

    def show_plan(self, experiment_plan_sha256: str) -> Mapping[str, object]:
        plan = self._plan(experiment_plan_sha256)
        return MappingProxyType(plan.to_mapping())

    def list_trials(
        self, experiment_plan_sha256: str, *, evidence_state: str | None = None
    ) -> tuple[Mapping[str, object], ...]:
        self._plan(experiment_plan_sha256)
        if evidence_state is not None:
            valid_evidence_state = False
            try:
                _require_evidence_state(evidence_state)
                valid_evidence_state = True
            except Exception:
                pass
            if not valid_evidence_state:
                raise PathlightError("Pathlight experiment evidence state is invalid")
        return tuple(
            MappingProxyType(trial.to_mapping())
            for trial in sorted(
                self._trials.values(), key=lambda value: value.case_trial_sha256
            )
            if trial.experiment_plan_sha256 == experiment_plan_sha256
            and (evidence_state is None or trial.evidence_state == evidence_state)
        )

    def _plan(self, experiment_plan_sha256: str) -> ExperimentPlan:
        plan: ExperimentPlan | None = None
        try:
            identity = _require_sha256(experiment_plan_sha256)
            plan = self._plans[identity]
        except (KeyError, ValueError):
            pass
        if plan is None:
            raise PathlightError("Pathlight experiment plan identity is unknown")
        return plan
