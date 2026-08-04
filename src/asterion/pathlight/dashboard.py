"""Immutable, provider-free data snapshots for the Pathlight Dashboard."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from asterion.pathlight.diagnosis import (
    DiagnosisBundle,
    validate_diagnosis_bundle,
)
from asterion.pathlight.evaluation import (
    EVALUATION_BUNDLE_SCHEMA,
    EvaluationBundle,
    validate_evaluation_record,
    validate_metric_contract,
)
from asterion.pathlight.experiment import (
    ExperimentBundle,
    validate_experiment_bundle,
)
from asterion.pathlight.optimization import (
    OptimizationBundle,
    validate_optimization_bundle,
    validate_optimization_closure,
)
from asterion.pathlight.flow import project_trace_flow
from asterion.pathlight.protocol import (
    PathlightError,
    trace_graph_from_mapping,
)
from asterion.workflow_evidence.storage import (
    WorkflowObservationBundle,
    validate_workflow_observation_bundle,
)


DASHBOARD_SNAPSHOT_SCHEMA = "asterion.pathlight-dashboard-snapshot/v2"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = frozenset(
    {
        "schema",
        "summary",
        "traces",
        "flows",
        "evaluations",
        "experiments",
        "diagnoses",
        "optimizations",
        "snapshot_sha256",
    }
)
_SUMMARY_FIELDS = frozenset(
    {
        "trace_count",
        "context_frame_count",
        "model_call_count",
        "tool_call_count",
        "evaluation_count",
        "experiment_count",
        "trial_count",
        "finding_count",
        "proposal_count",
        "evidence_gap_count",
        "status_counts",
        "optimization_history_count",
        "decision_counts",
    }
)
_STATUS_COUNT_FIELDS = frozenset({"completed", "failed", "cancelled", "skipped"})
_DECISION_COUNT_FIELDS = frozenset({"accepted", "rejected", "inconclusive"})
_OPTIMIZATION_IDENTITY_FIELDS = MappingProxyType(
    {
        "trials": "optimization_trial_sha256",
        "histories": "trial_history_sha256",
        "decisions": "decision_sha256",
    }
)
_FLOW_FIELDS = frozenset({"trace_id", "trace_sha256", "nodes", "missing_evidence"})


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    """One immutable, content-safe Dashboard input closure."""

    traces: tuple[Mapping[str, object], ...]
    flows: tuple[Mapping[str, object], ...]
    evaluations: tuple[Mapping[str, object], ...]
    experiments: tuple[Mapping[str, object], ...]
    diagnoses: tuple[Mapping[str, object], ...]
    optimizations: tuple[Mapping[str, object], ...]
    summary: Mapping[str, object]
    snapshot_sha256: str

    def __post_init__(self) -> None:
        try:
            canonical = _snapshot_components(
                self.traces,
                self.evaluations,
                self.experiments,
                self.diagnoses,
                self.optimizations,
            )
            traces, flows, evaluations, experiments, diagnoses, optimizations, summary = canonical
            _validate_snapshot_optimization_lineage(
                traces, evaluations, experiments, diagnoses, optimizations
            )
            if _json_value(self.flows) != _json_value(flows):
                raise ValueError
            if _json_value(self.summary) != _json_value(summary):
                raise ValueError
            supplied = _require_sha256(self.snapshot_sha256)
            unsigned = _unsigned_mapping(
                traces, flows, evaluations, experiments, diagnoses, optimizations, summary
            )
            if not hmac.compare_digest(supplied, _canonical_digest(unsigned)):
                raise ValueError
        except Exception:
            raise PathlightError("Pathlight Dashboard snapshot is invalid") from None
        object.__setattr__(self, "traces", _freeze_sequence(traces))
        object.__setattr__(self, "flows", _freeze_sequence(flows))
        object.__setattr__(self, "evaluations", _freeze_sequence(evaluations))
        object.__setattr__(self, "experiments", _freeze_sequence(experiments))
        object.__setattr__(self, "diagnoses", _freeze_sequence(diagnoses))
        object.__setattr__(self, "optimizations", _freeze_sequence(optimizations))
        object.__setattr__(self, "summary", _freeze_mapping(summary))
        _validate_public_shapes(self)

    @classmethod
    def build(
        cls,
        *,
        workflow_bundles: Sequence[WorkflowObservationBundle] = (),
        evaluation_bundles: Sequence[EvaluationBundle] = (),
        experiment_bundles: Sequence[ExperimentBundle] = (),
        diagnosis_bundles: Sequence[DiagnosisBundle] = (),
        optimization_bundles: Sequence[OptimizationBundle] = (),
    ) -> DashboardSnapshot:
        """Build a deterministic snapshot from already-validated safe values."""

        try:
            traces = _traces_from_workflow_bundles(workflow_bundles)
            evaluations = _evaluation_bundle_mappings(evaluation_bundles)
            experiments = _experiment_bundle_mappings(experiment_bundles)
            diagnoses = _diagnosis_bundle_mappings(diagnosis_bundles)
            optimizations = _optimization_bundle_mappings(optimization_bundles)
            _validate_optimization_lineage(
                optimization_bundles,
                traces,
                experiment_bundles,
                evaluation_bundles,
                diagnosis_bundles,
            )
            if not any((traces, evaluations, experiments, diagnoses, optimizations)):
                raise ValueError
            components = _snapshot_components(
                traces, evaluations, experiments, diagnoses, optimizations
            )
            unsigned = _unsigned_mapping(*components)
            return cls(*components[:-1], components[-1], _canonical_digest(unsigned))
        except Exception:
            raise PathlightError("Pathlight Dashboard snapshot is invalid") from None

    def to_mapping(self) -> dict[str, object]:
        return {
            **_unsigned_mapping(
                self.traces,
                self.flows,
                self.evaluations,
                self.experiments,
                self.diagnoses,
                self.optimizations,
                self.summary,
            ),
            "snapshot_sha256": self.snapshot_sha256,
        }


def validate_dashboard_snapshot(mapping: Mapping[str, object]) -> DashboardSnapshot:
    """Validate an exact JSON Dashboard snapshot and return its immutable value."""

    try:
        if type(mapping) is not dict or set(mapping) != _FIELDS:
            raise ValueError
        if mapping["schema"] != DASHBOARD_SNAPSHOT_SCHEMA:
            raise ValueError
        traces = tuple(
            _trace_mapping(value) for value in _exact_list(mapping["traces"])
        )
        evaluations = tuple(
            _evaluation_mapping(_evaluation_bundle_from_mapping(value))
            for value in _exact_list(mapping["evaluations"])
        )
        experiments = tuple(
            validate_experiment_bundle(_exact_mapping(value)).to_mapping()
            for value in _exact_list(mapping["experiments"])
        )
        diagnoses = tuple(
            validate_diagnosis_bundle(_exact_mapping(value)).to_mapping()
            for value in _exact_list(mapping["diagnoses"])
        )
        optimizations = tuple(
            validate_optimization_bundle(_exact_mapping(value)).to_mapping()
            for value in _exact_list(mapping["optimizations"])
        )
        components = _snapshot_components(
            traces, evaluations, experiments, diagnoses, optimizations
        )
        _validate_snapshot_optimization_lineage(
            components[0], components[2], components[3], components[4], components[5]
        )
        supplied_flows = _exact_list(mapping["flows"])
        supplied_summary = _exact_mapping(mapping["summary"])
        if _json_value(supplied_flows) != _json_value(components[1]):
            raise ValueError
        if _json_value(supplied_summary) != _json_value(components[-1]):
            raise ValueError
        return DashboardSnapshot(
            components[0],
            components[1],
            components[2],
            components[3],
            components[4],
            components[5],
            components[6],
            _require_sha256(mapping["snapshot_sha256"]),
        )
    except Exception:
        raise PathlightError("Pathlight Dashboard snapshot is invalid") from None


def _snapshot_components(
    traces: Sequence[Mapping[str, object]],
    evaluations: Sequence[Mapping[str, object]],
    experiments: Sequence[Mapping[str, object]],
    diagnoses: Sequence[Mapping[str, object]],
    optimizations: Sequence[Mapping[str, object]],
) -> tuple[
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
    Mapping[str, object],
]:
    normalized_traces = tuple(
        sorted(
            (_trace_mapping(value) for value in traces),
            key=lambda value: cast(str, value["trace_id"]),
        )
    )
    _reject_duplicate(normalized_traces, "trace_id")
    normalized_evaluations = tuple(
        sorted(
            (
                _evaluation_mapping(_evaluation_bundle_from_mapping(value))
                for value in evaluations
            ),
            key=lambda value: cast(str, value["bundle_sha256"]),
        )
    )
    _reject_duplicate(normalized_evaluations, "bundle_sha256")
    normalized_experiments = tuple(
        sorted(
            (
                validate_experiment_bundle(
                    _exact_mapping(_json_value(value))
                ).to_mapping()
                for value in experiments
            ),
            key=lambda value: cast(str, value["bundle_sha256"]),
        )
    )
    _reject_duplicate(normalized_experiments, "bundle_sha256")
    normalized_diagnoses = tuple(
        sorted(
            (
                validate_diagnosis_bundle(
                    _exact_mapping(_json_value(value))
                ).to_mapping()
                for value in diagnoses
            ),
            key=lambda value: cast(str, value["bundle_sha256"]),
        )
    )
    _reject_duplicate(normalized_diagnoses, "bundle_sha256")
    normalized_optimizations = tuple(
        sorted(
            (
                validate_optimization_bundle(
                    _exact_mapping(_json_value(value))
                ).to_mapping()
                for value in optimizations
            ),
            key=lambda value: cast(str, value["bundle_sha256"]),
        )
    )
    _reject_duplicate(normalized_optimizations, "bundle_sha256")
    _reject_duplicate_optimization_identities(normalized_optimizations)
    if not any(
        (
            normalized_traces,
            normalized_evaluations,
            normalized_experiments,
            normalized_diagnoses,
            normalized_optimizations,
        )
    ):
        raise ValueError
    _validate_diagnosis_lineage(
        normalized_evaluations, normalized_experiments, normalized_diagnoses
    )
    flows = tuple(_flow_mapping(trace) for trace in normalized_traces)
    summary = _summary(
        normalized_traces,
        flows,
        normalized_evaluations,
        normalized_experiments,
        normalized_diagnoses,
        normalized_optimizations,
    )
    return (
        normalized_traces,
        flows,
        normalized_evaluations,
        normalized_experiments,
        normalized_diagnoses,
        normalized_optimizations,
        summary,
    )


def _validate_diagnosis_lineage(
    evaluations: Sequence[Mapping[str, object]],
    experiments: Sequence[Mapping[str, object]],
    diagnoses: Sequence[Mapping[str, object]],
) -> None:
    experiment_ids = {value["bundle_sha256"] for value in experiments}
    evaluation_ids = {
        record["evaluation_sha256"]
        for bundle in (*evaluations, *experiments)
        for record in cast(Sequence[Mapping[str, object]], bundle["evaluations"])
    }
    for diagnosis in diagnoses:
        referenced_experiments = cast(
            Sequence[str], diagnosis["experiment_bundle_sha256s"]
        )
        referenced_evaluations = cast(Sequence[str], diagnosis["evaluation_sha256s"])
        if any(value not in experiment_ids for value in referenced_experiments) or any(
            value not in evaluation_ids for value in referenced_evaluations
        ):
            raise ValueError


def _reject_duplicate_optimization_identities(
    bundles: Sequence[Mapping[str, object]],
) -> None:
    for collection, field in _OPTIMIZATION_IDENTITY_FIELDS.items():
        values = tuple(
            value[field]
            for bundle in bundles
            for value in cast(Sequence[Mapping[str, object]], bundle[collection])
        )
        if len(values) != len(set(values)):
            raise ValueError


def _validate_optimization_lineage(
    bundles: Sequence[OptimizationBundle],
    traces: Sequence[Mapping[str, object]],
    experiments: Sequence[ExperimentBundle],
    evaluations: Sequence[EvaluationBundle],
    diagnoses: Sequence[DiagnosisBundle],
) -> None:
    trace_sha256s = tuple(cast(str, value["trace_sha256"]) for value in traces)
    for bundle in bundles:
        if type(bundle) is not OptimizationBundle:
            raise ValueError
        validate_optimization_closure(
            bundle,
            workflow_trace_sha256s=trace_sha256s,
            experiment_bundles=experiments,
            evaluation_bundles=evaluations,
            diagnosis_bundles=diagnoses,
        )


def _validate_snapshot_optimization_lineage(
    traces: Sequence[Mapping[str, object]],
    evaluations: Sequence[Mapping[str, object]],
    experiments: Sequence[Mapping[str, object]],
    diagnoses: Sequence[Mapping[str, object]],
    optimizations: Sequence[Mapping[str, object]],
) -> None:
    trace_sha256s = tuple(cast(str, value["trace_sha256"]) for value in traces)
    evaluation_bundles = tuple(
        _evaluation_bundle_from_mapping(value) for value in evaluations
    )
    experiment_bundles = tuple(
        validate_experiment_bundle(_exact_mapping(value)) for value in experiments
    )
    diagnosis_bundles = tuple(
        validate_diagnosis_bundle(_exact_mapping(value)) for value in diagnoses
    )
    for mapping in optimizations:
        validate_optimization_closure(
            validate_optimization_bundle(_exact_mapping(mapping)),
            workflow_trace_sha256s=trace_sha256s,
            experiment_bundles=experiment_bundles,
            evaluation_bundles=evaluation_bundles,
            diagnosis_bundles=diagnosis_bundles,
        )


def _traces_from_workflow_bundles(
    bundles: Sequence[WorkflowObservationBundle],
) -> tuple[Mapping[str, object], ...]:
    traces: list[Mapping[str, object]] = []
    for bundle in bundles:
        if type(bundle) is not WorkflowObservationBundle:
            raise ValueError
        validate_workflow_observation_bundle(bundle)
        traces.extend(_trace_mapping(trace) for trace in bundle.pathlight_traces)
    return tuple(traces)


def _evaluation_bundle_mappings(
    bundles: Sequence[EvaluationBundle],
) -> tuple[Mapping[str, object], ...]:
    values: list[Mapping[str, object]] = []
    for bundle in bundles:
        if type(bundle) is not EvaluationBundle:
            raise ValueError
        verified = EvaluationBundle(
            bundle.metric_contracts, bundle.evaluations, bundle.bundle_sha256
        )
        values.append(_evaluation_mapping(verified))
    return tuple(values)


def _experiment_bundle_mappings(
    bundles: Sequence[ExperimentBundle],
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        validate_experiment_bundle(bundle.to_mapping()).to_mapping()
        if type(bundle) is ExperimentBundle
        else _invalid_value()
        for bundle in bundles
    )


def _diagnosis_bundle_mappings(
    bundles: Sequence[DiagnosisBundle],
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        validate_diagnosis_bundle(bundle.to_mapping()).to_mapping()
        if type(bundle) is DiagnosisBundle
        else _invalid_value()
        for bundle in bundles
    )


def _optimization_bundle_mappings(
    bundles: Sequence[OptimizationBundle],
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        validate_optimization_bundle(bundle.to_mapping()).to_mapping()
        if type(bundle) is OptimizationBundle
        else _invalid_value()
        for bundle in bundles
    )


def _invalid_value() -> Mapping[str, object]:
    raise ValueError


def _trace_mapping(value: object) -> Mapping[str, object]:
    mapping = _exact_mapping(_json_value(value))
    return trace_graph_from_mapping(mapping).to_mapping()


def _evaluation_mapping(bundle: EvaluationBundle) -> dict[str, object]:
    return {
        "schema": EVALUATION_BUNDLE_SCHEMA,
        "metric_contracts": [value.to_mapping() for value in bundle.metric_contracts],
        "evaluations": [value.to_mapping() for value in bundle.evaluations],
        "bundle_sha256": bundle.bundle_sha256,
    }


def _evaluation_bundle_from_mapping(value: object) -> EvaluationBundle:
    mapping = _exact_mapping(_json_value(value))
    if (
        set(mapping)
        != {
            "schema",
            "metric_contracts",
            "evaluations",
            "bundle_sha256",
        }
        or mapping["schema"] != EVALUATION_BUNDLE_SCHEMA
    ):
        raise ValueError
    contracts = tuple(
        validate_metric_contract(_exact_mapping(item))
        for item in _exact_list(mapping["metric_contracts"])
    )
    evaluations = tuple(
        validate_evaluation_record(_exact_mapping(item))
        for item in _exact_list(mapping["evaluations"])
    )
    return EvaluationBundle(
        contracts, evaluations, _require_sha256(mapping["bundle_sha256"])
    )


def _flow_mapping(trace: Mapping[str, object]) -> Mapping[str, object]:
    nodes = tuple(project_trace_flow(trace))
    missing = not nodes or any(bool(node.get("missing_evidence")) for node in nodes)
    return {
        "trace_id": trace["trace_id"],
        "trace_sha256": trace["trace_sha256"],
        "nodes": [_json_value(node) for node in nodes],
        "missing_evidence": missing,
    }


def _summary(
    traces: Sequence[Mapping[str, object]],
    flows: Sequence[Mapping[str, object]],
    evaluations: Sequence[Mapping[str, object]],
    experiments: Sequence[Mapping[str, object]],
    diagnoses: Sequence[Mapping[str, object]],
    optimizations: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    nodes = tuple(
        node
        for flow in flows
        for node in cast(Sequence[Mapping[str, object]], flow["nodes"])
    )
    evaluation_ids = {
        record["evaluation_sha256"]
        for bundle in (*evaluations, *experiments)
        for record in cast(Sequence[Mapping[str, object]], bundle["evaluations"])
    }
    status_counts = {name: 0 for name in sorted(_STATUS_COUNT_FIELDS)}
    for trace in traces:
        status_counts[_trace_status(trace)] += 1
    missing_trials = sum(
        1
        for bundle in experiments
        for trial in cast(Sequence[Mapping[str, object]], bundle["trials"])
        if trial["evidence_state"] == "missing" or bool(trial["missing_evidence"])
    )
    missing_findings = sum(
        1
        for bundle in diagnoses
        for finding in cast(Sequence[Mapping[str, object]], bundle["findings"])
        if finding["category"] in {"missing-evidence", "not-comparable"}
    )
    return {
        "trace_count": len(traces),
        "context_frame_count": sum(node["kind"] == "context-frame" for node in nodes),
        "model_call_count": sum(node["kind"] == "model-call" for node in nodes),
        "tool_call_count": sum(node["kind"] == "tool-call" for node in nodes),
        "evaluation_count": len(evaluation_ids),
        "experiment_count": sum(
            len(cast(Sequence[object], value["plans"])) for value in experiments
        ),
        "trial_count": sum(
            len(cast(Sequence[object], value["trials"])) for value in experiments
        ),
        "finding_count": sum(
            len(cast(Sequence[object], value["findings"])) for value in diagnoses
        ),
        "proposal_count": sum(
            len(cast(Sequence[object], value["proposals"])) for value in diagnoses
        ),
        "evidence_gap_count": sum(bool(flow["missing_evidence"]) for flow in flows)
        + missing_trials
        + missing_findings,
        "status_counts": status_counts,
        "optimization_history_count": sum(
            len(cast(Sequence[object], value["histories"]))
            for value in optimizations
        ),
        "decision_counts": {
            decision: sum(
                1
                for bundle in optimizations
                for value in cast(Sequence[Mapping[str, object]], bundle["decisions"])
                if value["result"] == decision
            )
            for decision in sorted(_DECISION_COUNT_FIELDS)
        },
    }


def _trace_status(trace: Mapping[str, object]) -> str:
    events = cast(Sequence[Mapping[str, object]], trace["events"])
    root = events[0]["span_id"]
    for event in reversed(events):
        if event["span_id"] == root and event["status"] != "started":
            status = event["status"]
            if status in _STATUS_COUNT_FIELDS:
                return cast(str, status)
            break
    raise ValueError


def _unsigned_mapping(
    traces: Sequence[Mapping[str, object]],
    flows: Sequence[Mapping[str, object]],
    evaluations: Sequence[Mapping[str, object]],
    experiments: Sequence[Mapping[str, object]],
    diagnoses: Sequence[Mapping[str, object]],
    optimizations: Sequence[Mapping[str, object]],
    summary: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema": DASHBOARD_SNAPSHOT_SCHEMA,
        "summary": _json_value(summary),
        "traces": [_json_value(value) for value in traces],
        "flows": [_json_value(value) for value in flows],
        "evaluations": [_json_value(value) for value in evaluations],
        "experiments": [_json_value(value) for value in experiments],
        "diagnoses": [_json_value(value) for value in diagnoses],
        "optimizations": [_json_value(value) for value in optimizations],
    }


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError
    return value


def _reject_duplicate(values: Sequence[Mapping[str, object]], key: str) -> None:
    identities = tuple(value[key] for value in values)
    if len(identities) != len(set(identities)):
        raise ValueError


def _exact_list(value: object) -> list[object]:
    if type(value) is not list:
        raise ValueError
    return list(cast(list[object], value))


def _exact_mapping(value: object) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValueError
    return dict(cast(dict[str, object], value))


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or type(value) in {str, int, bool}:
        return value
    raise ValueError


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})


def _freeze_sequence(
    values: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    return tuple(_freeze_mapping(value) for value in values)


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(cast(Mapping[str, object], value))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    return value


def _validate_public_shapes(snapshot: DashboardSnapshot) -> None:
    """Keep the exact summary/flow fields closed for future schema changes."""

    if set(snapshot.summary) != _SUMMARY_FIELDS:
        raise PathlightError("Pathlight Dashboard snapshot is invalid")
    statuses = snapshot.summary["status_counts"]
    if not isinstance(statuses, Mapping) or set(statuses) != _STATUS_COUNT_FIELDS:
        raise PathlightError("Pathlight Dashboard snapshot is invalid")
    decisions = snapshot.summary["decision_counts"]
    if not isinstance(decisions, Mapping) or set(decisions) != _DECISION_COUNT_FIELDS:
        raise PathlightError("Pathlight Dashboard snapshot is invalid")
    if any(set(flow) != _FLOW_FIELDS for flow in snapshot.flows):
        raise PathlightError("Pathlight Dashboard snapshot is invalid")
