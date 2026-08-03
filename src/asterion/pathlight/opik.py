"""Versioned, body-free Pathlight mirror mapping for optional Opik adapters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import TypeVar

from asterion.pathlight.diagnosis import DiagnosisBundle
from asterion.pathlight.evaluation import EvaluationBundle, EvaluationRecord
from asterion.pathlight.experiment import ExperimentBundle
from asterion.pathlight.interop import ExportEnvelope
from asterion.pathlight.protocol import (
    PathlightError,
    TraceEvent,
    TraceGraph,
    validate_trace_graph,
)


OPIK_MAPPING_VERSION = "1.0.0"
_T = TypeVar("_T")
_SPAN_REQUEST_ATTRIBUTE_KEYS = frozenset(
    {
        "field_count",
        "leaf_count",
        "missing_evidence_labels",
        "payload_bytes",
        "private_reference_sha256",
        "request_index",
        "request_sha256",
        "request_shape_sha256",
        "text_characters",
    }
)


def map_opik_exports(
    *,
    traces: Sequence[TraceGraph] = (),
    experiments: Sequence[ExperimentBundle] = (),
    evaluations: Sequence[EvaluationBundle] = (),
    diagnoses: Sequence[DiagnosisBundle] = (),
    mapping_version: str = OPIK_MAPPING_VERSION,
) -> tuple[ExportEnvelope, ...]:
    """Map complete local Pathlight objects into deterministic safe mirror events."""

    try:
        if mapping_version != OPIK_MAPPING_VERSION:
            raise ValueError
        trace_values = _exact_sequence(traces, TraceGraph)
        experiment_values = _exact_sequence(experiments, ExperimentBundle)
        evaluation_values = _exact_sequence(evaluations, EvaluationBundle)
        diagnosis_values = _exact_sequence(diagnoses, DiagnosisBundle)
        trace_sha256s: set[str] = set()
        envelopes: list[ExportEnvelope] = []
        for trace in trace_values:
            mapping = trace.to_mapping()
            validate_trace_graph(mapping)
            trace_sha256 = _string(mapping["trace_sha256"])
            if trace_sha256 in trace_sha256s:
                raise ValueError
            trace_sha256s.add(trace_sha256)
            envelopes.extend(_trace_envelopes(trace, trace_sha256, mapping_version))

        experiment_sha256s = {item.bundle_sha256 for item in experiment_values}
        evaluation_records: dict[str, EvaluationRecord] = {}
        metric_names: dict[str, str] = {}
        for bundle in evaluation_values:
            _validate_evaluation_bundle(bundle)
            for contract in bundle.metric_contracts:
                previous = metric_names.get(contract.metric_contract_sha256)
                if previous is not None and previous != contract.metric_name:
                    raise ValueError
                metric_names[contract.metric_contract_sha256] = contract.metric_name
            for record in bundle.evaluations:
                _add_evaluation(evaluation_records, record)

        for bundle in experiment_values:
            _validate_experiment_bundle(bundle)
            for record in bundle.evaluations:
                _add_evaluation(evaluation_records, record)
            for trial in bundle.trials:
                if (
                    trial.trace_sha256 not in trace_sha256s
                    and "trace-graph" not in trial.missing_evidence
                ):
                    raise ValueError
            envelopes.extend(_experiment_envelopes(bundle, mapping_version))

        evaluation_sha256s = set(evaluation_records)
        for diagnosis in diagnosis_values:
            _validate_diagnosis_bundle(diagnosis)
            if not set(diagnosis.experiment_bundle_sha256s) <= experiment_sha256s:
                raise ValueError
            if not set(diagnosis.evaluation_sha256s) <= evaluation_sha256s:
                raise ValueError
            envelopes.extend(_diagnosis_envelopes(diagnosis, mapping_version))

        for record in evaluation_records.values():
            envelopes.append(
                _evaluation_envelope(
                    record,
                    metric_names.get(record.metric_contract_sha256),
                    mapping_version,
                )
            )
        by_identity: dict[str, ExportEnvelope] = {}
        for envelope in envelopes:
            previous = by_identity.get(envelope.idempotency_key)
            if previous is not None and previous != envelope:
                raise ValueError
            by_identity[envelope.idempotency_key] = envelope
        return tuple(
            sorted(by_identity.values(), key=lambda item: item.envelope_sha256)
        )
    except Exception:
        raise PathlightError("Pathlight Opik export mapping is invalid") from None


def _trace_envelopes(
    trace: TraceGraph, trace_sha256: str, mapping_version: str
) -> tuple[ExportEnvelope, ...]:
    starts: dict[str, TraceEvent] = {}
    terminal: dict[str, TraceEvent] = {}
    for event in trace.events:
        if event.status == "started":
            starts[event.span_id] = event
        else:
            terminal[event.span_id] = event
    root = next(item for item in starts.values() if item.parent_span_id is None)
    root_terminal = terminal[root.span_id]
    values = [
        ExportEnvelope(
            "opik",
            mapping_version,
            "trace.upsert",
            trace_sha256,
            {
                "trace_sha256": trace_sha256,
                "kind": root.kind,
                "status": root_terminal.status,
                "duration_ns": root_terminal.timestamp_ns - root.timestamp_ns,
            },
        )
    ]
    for span_id, start in starts.items():
        end = terminal[span_id]
        request_attributes = {
            key: start.attributes[key]
            for key in sorted(_SPAN_REQUEST_ATTRIBUTE_KEYS & set(start.attributes))
        }
        span_sha256 = _digest(
            {
                "trace_sha256": trace_sha256,
                "sequence": start.sequence,
                "kind": start.kind,
                "status": end.status,
                "duration_ns": end.timestamp_ns - start.timestamp_ns,
            }
        )
        values.append(
            ExportEnvelope(
                "opik",
                mapping_version,
                "span.upsert",
                span_sha256,
                {
                    "span_sha256": span_sha256,
                    "trace_sha256": trace_sha256,
                    "sequence": start.sequence,
                    "kind": start.kind,
                    "status": end.status,
                    "duration_ns": end.timestamp_ns - start.timestamp_ns,
                    **request_attributes,
                },
            )
        )
    return tuple(values)


def _experiment_envelopes(
    bundle: ExperimentBundle, mapping_version: str
) -> tuple[ExportEnvelope, ...]:
    values: list[ExportEnvelope] = []
    for dataset in bundle.datasets:
        values.append(
            ExportEnvelope(
                "opik",
                mapping_version,
                "dataset.upsert",
                dataset.dataset_snapshot_sha256,
                {
                    "dataset_snapshot_sha256": dataset.dataset_snapshot_sha256,
                    "content_sha256": dataset.content_sha256,
                    "total_count": dataset.total_count,
                    "snapshot_version": dataset.snapshot_version,
                },
            )
        )
    for plan in bundle.plans:
        values.append(
            ExportEnvelope(
                "opik",
                mapping_version,
                "experiment.upsert",
                plan.experiment_plan_sha256,
                {
                    "experiment_plan_sha256": plan.experiment_plan_sha256,
                    "dataset_snapshot_sha256": plan.dataset_snapshot_sha256,
                    "baseline_variant_sha256": plan.baseline_variant_sha256,
                    "scope_sha256": plan.scope_sha256,
                    "status": "proposed",
                    "requires_operator_authorization": True,
                    "execution_authorized": False,
                },
            )
        )
    for trial in bundle.trials:
        values.append(
            ExportEnvelope(
                "opik",
                mapping_version,
                "case-trial.upsert",
                trial.case_trial_sha256,
                {
                    "case_trial_sha256": trial.case_trial_sha256,
                    "experiment_plan_sha256": trial.experiment_plan_sha256,
                    "dataset_item_sha256": trial.dataset_item_sha256,
                    "variant_sha256": trial.variant_sha256,
                    "trace_sha256": trial.trace_sha256,
                    "evidence_state": trial.evidence_state,
                },
            )
        )
    return tuple(values)


def _evaluation_envelope(
    record: EvaluationRecord, metric_name: str | None, mapping_version: str
) -> ExportEnvelope:
    payload: dict[str, object] = {
        "evaluation_sha256": record.evaluation_sha256,
        "trace_sha256": record.trace_sha256,
        "metric_contract_sha256": record.metric_contract_sha256,
        "dataset_snapshot_sha256": record.dataset_snapshot_sha256,
        "scope_sha256": record.scope_sha256,
        "selected_count": record.selected_count,
        "total_count": record.total_count,
        "status": record.status,
    }
    if record.value_microunits is not None:
        payload["value_microunits"] = record.value_microunits
    if metric_name is not None:
        payload["metric_name"] = metric_name
    return ExportEnvelope(
        "opik",
        mapping_version,
        "evaluation.upsert",
        record.evaluation_sha256,
        payload,  # type: ignore[arg-type]
    )


def _diagnosis_envelopes(
    bundle: DiagnosisBundle, mapping_version: str
) -> tuple[ExportEnvelope, ...]:
    return tuple(
        ExportEnvelope(
            "opik",
            mapping_version,
            "proposal.observe",
            proposal.proposal_sha256,
            {
                "proposal_sha256": proposal.proposal_sha256,
                "finding_sha256": proposal.finding_sha256,
                "change_sha256": proposal.change_sha256,
                "scope_sha256": proposal.scope_sha256,
                "status": proposal.status,
                "requires_operator_authorization": True,
                "execution_authorized": False,
            },
        )
        for proposal in bundle.proposals
    )


def _exact_sequence(values: Sequence[_T], expected: type[_T]) -> tuple[_T, ...]:
    if type(values) not in {tuple, list} or any(
        type(item) is not expected for item in values
    ):
        raise ValueError
    return tuple(values)


def _validate_experiment_bundle(bundle: ExperimentBundle) -> None:
    ExperimentBundle(
        bundle.datasets,
        bundle.evaluators,
        bundle.variants,
        bundle.plans,
        bundle.trials,
        bundle.evaluations,
        bundle.bundle_sha256,
    )


def _validate_evaluation_bundle(bundle: EvaluationBundle) -> None:
    EvaluationBundle(bundle.metric_contracts, bundle.evaluations, bundle.bundle_sha256)


def _validate_diagnosis_bundle(bundle: DiagnosisBundle) -> None:
    DiagnosisBundle(
        bundle.experiment_bundle_sha256s,
        bundle.evaluation_sha256s,
        bundle.findings,
        bundle.proposals,
        bundle.bundle_sha256,
    )


def _add_evaluation(
    records: dict[str, EvaluationRecord], value: EvaluationRecord
) -> None:
    previous = records.get(value.evaluation_sha256)
    if previous is not None and previous != value:
        raise ValueError
    records[value.evaluation_sha256] = value


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _string(value: object) -> str:
    if type(value) is not str:
        raise ValueError
    return value
