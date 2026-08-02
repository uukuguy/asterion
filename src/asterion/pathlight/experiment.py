"""Immutable, content-addressed Pathlight experiment lineage contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, TypeAlias, cast

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
