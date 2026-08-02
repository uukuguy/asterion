"""Read-only, public-safe queries over validated Pathlight values."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from asterion.pathlight.evaluation import (
    EvaluationRecord,
    METRIC_NAMES,
    MetricContract,
    compare_evaluations,
    validate_evaluation_record,
    validate_metric_contract,
)
from asterion.pathlight.protocol import (
    PathlightError,
    SAFE_KINDS,
    SAFE_STATUSES,
    validate_trace_graph,
)
from asterion.workflow_evidence.collector import WorkflowEvidenceError
from asterion.workflow_evidence.storage import (
    WorkflowObservationBundle,
    validate_workflow_observation_bundle,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TRACE_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_COMPONENT_DIGEST_ATTRIBUTES = frozenset(
    {
        "application_sha256",
        "assembly_sha256",
        "capability_package_sha256",
        "capability_ref_sha256",
        "host_service_sha256",
        "implementation_sha256",
        "policy_sha256",
        "run_sha256",
        "runtime_sha256",
        "scope_sha256",
        "task_sha256",
    }
)
_METRIC_STATUSES = frozenset({"observed", "recovered", "missing"})


class _FrozenDict(dict[str, object]):
    """A JSON-encodable dictionary that rejects all public mutations."""

    def __init__(self, values: Mapping[str, object]) -> None:
        dict.__init__(self, values)

    def __delitem__(self, key: str) -> None:
        del key
        raise TypeError("Pathlight projection is immutable")

    def __ior__(self, value: object) -> _FrozenDict:
        del value
        raise TypeError("Pathlight projection is immutable")

    def __setitem__(self, key: str, value: object) -> None:
        del key, value
        raise TypeError("Pathlight projection is immutable")

    def clear(self) -> None:
        raise TypeError("Pathlight projection is immutable")

    def pop(self, key: str, default: object = None) -> object:
        del key, default
        raise TypeError("Pathlight projection is immutable")

    def popitem(self) -> tuple[str, object]:
        raise TypeError("Pathlight projection is immutable")

    def setdefault(self, key: str, default: object = None) -> object:
        del key, default
        raise TypeError("Pathlight projection is immutable")

    def update(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError("Pathlight projection is immutable")


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise PathlightError(f"Pathlight {field_name} is invalid")
    return value


def _require_trace_id(value: object) -> str:
    if type(value) is not str or _TRACE_ID.fullmatch(value) is None:
        raise PathlightError("Pathlight trace identity is invalid")
    return value


def _freeze_json(value: object) -> object:
    try:
        return _freeze_json_value(value)
    except Exception:
        raise PathlightError("Pathlight query projection is invalid") from None


def _freeze_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise PathlightError("Pathlight query projection is invalid")
        return _FrozenDict({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or type(value) in {str, int, bool}:
        return value
    raise PathlightError("Pathlight query projection is invalid")


def _mutable_json(value: object) -> object:
    try:
        return _mutable_json_value(value)
    except Exception:
        raise PathlightError("Pathlight query projection is invalid") from None


def _mutable_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise PathlightError("Pathlight trace is invalid")
        return {key: _mutable_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mutable_json(item) for item in value]
    if value is None or type(value) in {str, int, bool}:
        return value
    raise PathlightError("Pathlight trace is invalid")


@dataclass(frozen=True, slots=True)
class TraceFilter:
    """Exact public filters for immutable Pathlight trace summaries."""

    status: str | None = None
    kind: str | None = None
    component_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.status is not None and (
            type(self.status) is not str
            or self.status not in SAFE_STATUSES - {"started"}
        ):
            raise PathlightError("Pathlight trace status filter is invalid")
        if self.kind is not None and (
            type(self.kind) is not str or self.kind not in SAFE_KINDS
        ):
            raise PathlightError("Pathlight trace kind filter is invalid")
        if self.component_sha256 is not None:
            _require_sha256(self.component_sha256, field_name="component digest filter")


@dataclass(frozen=True, slots=True)
class MetricFilter:
    """Exact public filters for immutable evaluation record projections."""

    metric_name: str | None = None
    status: str | None = None
    trace_sha256: str | None = None
    metric_contract_sha256: str | None = None
    dataset_snapshot_sha256: str | None = None
    scope_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.metric_name is not None and (
            type(self.metric_name) is not str or self.metric_name not in METRIC_NAMES
        ):
            raise PathlightError("Pathlight metric name filter is invalid")
        if self.status is not None and (
            type(self.status) is not str or self.status not in _METRIC_STATUSES
        ):
            raise PathlightError("Pathlight metric status filter is invalid")
        for field_name in (
            "trace_sha256",
            "metric_contract_sha256",
            "dataset_snapshot_sha256",
            "scope_sha256",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_sha256(value, field_name=f"metric {field_name} filter")


@dataclass(frozen=True, slots=True)
class PathlightCatalog:
    """A deterministic in-memory index of verified public Pathlight records."""

    _traces: Mapping[str, Mapping[str, object]]
    _evaluations: Mapping[str, Mapping[str, object] | EvaluationRecord]
    _metric_contracts: Mapping[str, MetricContract]

    def __post_init__(self) -> None:
        try:
            self._validate_and_copy_inputs()
        except Exception:
            raise PathlightError("Pathlight catalog input is invalid") from None

    def _validate_and_copy_inputs(self) -> None:
        if (
            not isinstance(self._traces, Mapping)
            or not isinstance(self._evaluations, Mapping)
            or not isinstance(self._metric_contracts, Mapping)
        ):
            raise PathlightError("Pathlight catalog input is invalid")
        traces: dict[str, Mapping[str, object]] = {}
        records: dict[str, Mapping[str, object]] = {}
        contracts: dict[str, MetricContract] = {}
        for supplied_contract_sha256, source_contract in self._metric_contracts.items():
            if not isinstance(source_contract, MetricContract):
                raise PathlightError("Pathlight metric contract is invalid")
            contract = validate_metric_contract(source_contract.to_mapping())
            if (
                supplied_contract_sha256 != contract.metric_contract_sha256
                or contract.metric_contract_sha256 in contracts
            ):
                raise PathlightError("Pathlight metric contract identity is invalid")
            contracts[contract.metric_contract_sha256] = contract
        for supplied_trace_id, source_trace in self._traces.items():
            trace = _validated_frozen_trace(source_trace)
            trace_id = _require_trace_id(trace["trace_id"])
            if supplied_trace_id != trace_id or trace_id in traces:
                raise PathlightError("Pathlight trace identity is invalid")
            traces[trace_id] = trace
        for supplied_evaluation_sha256, source_record in self._evaluations.items():
            record = _validated_frozen_evaluation(source_record)
            evaluation_sha256 = _require_sha256(
                record["evaluation_sha256"], field_name="evaluation identity"
            )
            if (
                supplied_evaluation_sha256 != evaluation_sha256
                or evaluation_sha256 in records
                or record["metric_contract_sha256"] not in contracts
            ):
                raise PathlightError("Pathlight evaluation identity is invalid")
            records[evaluation_sha256] = record
        object.__setattr__(self, "_traces", MappingProxyType(traces))
        object.__setattr__(self, "_evaluations", MappingProxyType(records))
        object.__setattr__(self, "_metric_contracts", MappingProxyType(contracts))

    @classmethod
    def build(
        cls,
        bundles: Sequence[WorkflowObservationBundle],
        evaluations: Sequence[EvaluationRecord],
        metric_contracts: Sequence[MetricContract],
    ) -> PathlightCatalog:
        if (
            not _is_sequence(bundles)
            or not _is_sequence(evaluations)
            or not _is_sequence(metric_contracts)
        ):
            raise PathlightError("Pathlight catalog input is invalid")
        traces: dict[str, Mapping[str, object]] = {}
        records: dict[str, EvaluationRecord] = {}
        contracts: dict[str, MetricContract] = {}
        for contract in metric_contracts:
            if type(contract) is not MetricContract:
                raise PathlightError("Pathlight metric contract is invalid")
            validated_contract = validate_metric_contract(contract.to_mapping())
            identity = validated_contract.metric_contract_sha256
            existing = contracts.get(identity)
            if existing is None:
                contracts[identity] = validated_contract
            elif existing != validated_contract:
                raise PathlightError("Pathlight metric contract identity is conflicting")
        for bundle in bundles:
            if not isinstance(bundle, WorkflowObservationBundle):
                raise PathlightError("Pathlight observation bundle is invalid")
            try:
                validate_workflow_observation_bundle(bundle)
            except WorkflowEvidenceError:
                raise PathlightError(
                    "Pathlight observation bundle is invalid"
                ) from None
            for source_trace in bundle.pathlight_traces:
                trace = _validated_frozen_trace(source_trace)
                trace_id = _require_trace_id(trace["trace_id"])
                if trace_id in traces:
                    raise PathlightError("Pathlight trace identity is duplicated")
                traces[trace_id] = trace
        for record in evaluations:
            if not isinstance(record, EvaluationRecord):
                raise PathlightError("Pathlight evaluation record is invalid")
            validated = validate_evaluation_record(record.to_mapping())
            if validated.metric_contract_sha256 not in contracts:
                raise PathlightError("Pathlight evaluation record contract is unresolved")
            if validated.evaluation_sha256 in records:
                raise PathlightError("Pathlight evaluation identity is duplicated")
            records[validated.evaluation_sha256] = validated
        return cls(
            MappingProxyType(traces),
            MappingProxyType(records),
            MappingProxyType(contracts),
        )

    def list_traces(
        self, query: TraceFilter = TraceFilter()
    ) -> tuple[Mapping[str, object], ...]:
        query = _require_trace_filter(query)
        return tuple(
            _trace_summary(trace)
            for trace_id in sorted(self._traces)
            for trace in (_read_validated_trace(self._traces, trace_id),)
            if _matches_trace_filter(trace, query)
        )

    def show_trace(self, trace_id: str) -> Mapping[str, object]:
        trace_id = _require_trace_id(trace_id)
        try:
            trace = self._traces[trace_id]
        except KeyError as error:
            raise PathlightError("Pathlight trace identity is unknown") from error
        return _validated_frozen_trace(trace)

    def tail_trace(
        self, trace_id: str, *, after_sequence: int = 0
    ) -> tuple[Mapping[str, object], ...]:
        if type(after_sequence) is not int or after_sequence < 0:
            raise PathlightError("Pathlight event sequence is invalid")
        trace = self.show_trace(trace_id)
        events = trace["events"]
        if not isinstance(events, tuple):
            raise PathlightError("Pathlight trace is invalid")
        return tuple(
            event
            for event in events
            if isinstance(event, Mapping)
            and type(event.get("sequence")) is int
            and event["sequence"] > after_sequence
        )

    def query_metrics(
        self, query: MetricFilter = MetricFilter()
    ) -> tuple[Mapping[str, object], ...]:
        query = _require_metric_filter(query)
        return tuple(
            _metric_projection(
                record,
                self._metric_contract(record.metric_contract_sha256),
            )
            for evaluation_sha256 in sorted(self._evaluations)
            for record in (
                _read_validated_evaluation(self._evaluations, evaluation_sha256),
            )
            if _matches_metric_filter(
                record,
                self._metric_contract(record.metric_contract_sha256),
                query,
            )
        )

    def compare_evaluation_ids(
        self, baseline_sha256: str, candidate_sha256: str
    ) -> Mapping[str, object]:
        baseline_sha256 = _require_sha256(
            baseline_sha256, field_name="baseline evaluation identity"
        )
        candidate_sha256 = _require_sha256(
            candidate_sha256, field_name="candidate evaluation identity"
        )
        try:
            baseline_mapping = self._evaluations[baseline_sha256]
            candidate_mapping = self._evaluations[candidate_sha256]
        except KeyError as error:
            raise PathlightError("Pathlight evaluation identity is unknown") from error
        baseline = _evaluation_record(baseline_mapping)
        candidate = _evaluation_record(candidate_mapping)
        comparison = compare_evaluations(baseline, candidate)
        return _FrozenDict(
            {
                "baseline_evaluation_sha256": baseline_sha256,
                "candidate_evaluation_sha256": candidate_sha256,
                "status": comparison.status,
                "delta_microunits": comparison.delta_microunits,
                "reasons": tuple(comparison.reasons),
            }
        )

    def _metric_contract(self, metric_contract_sha256: str) -> MetricContract:
        try:
            return self._metric_contracts[metric_contract_sha256]
        except KeyError:
            raise PathlightError("Pathlight evaluation record contract is unresolved") from None


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _validated_frozen_trace(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PathlightError("Pathlight trace is invalid")
    mutable = _mutable_json(value)
    if not isinstance(mutable, Mapping):
        raise PathlightError("Pathlight trace is invalid")
    try:
        validate_trace_graph(mutable)
    except (TypeError, ValueError):
        raise PathlightError("Pathlight trace is invalid") from None
    frozen = _freeze_json(mutable)
    if not isinstance(frozen, Mapping):
        raise PathlightError("Pathlight trace is invalid")
    return frozen


def _validated_frozen_evaluation(value: object) -> Mapping[str, object]:
    if isinstance(value, EvaluationRecord):
        mutable = value.to_mapping()
    elif isinstance(value, Mapping):
        mutable = _mutable_json(value)
    else:
        raise PathlightError("Pathlight evaluation record is invalid")
    if not isinstance(mutable, Mapping):
        raise PathlightError("Pathlight evaluation record is invalid")
    try:
        record = validate_evaluation_record(mutable)
    except (PathlightError, TypeError, ValueError):
        raise PathlightError("Pathlight evaluation record is invalid") from None
    frozen = _freeze_json(record.to_mapping())
    if not isinstance(frozen, Mapping):
        raise PathlightError("Pathlight evaluation record is invalid")
    return frozen


def _read_validated_trace(
    traces: Mapping[str, Mapping[str, object]], trace_id: str
) -> Mapping[str, object]:
    return _validated_frozen_trace(traces[trace_id])


def _read_validated_evaluation(
    evaluations: Mapping[str, Mapping[str, object] | EvaluationRecord],
    evaluation_sha256: str,
) -> EvaluationRecord:
    return _evaluation_record(evaluations[evaluation_sha256])


def _evaluation_record(value: object) -> EvaluationRecord:
    frozen = _validated_frozen_evaluation(value)
    mutable = _mutable_json(frozen)
    if not isinstance(mutable, Mapping):
        raise PathlightError("Pathlight evaluation record is invalid")
    return validate_evaluation_record(mutable)


def _require_trace_filter(value: object) -> TraceFilter:
    if not isinstance(value, TraceFilter):
        raise PathlightError("Pathlight trace filter is invalid")
    return TraceFilter(value.status, value.kind, value.component_sha256)


def _require_metric_filter(value: object) -> MetricFilter:
    if not isinstance(value, MetricFilter):
        raise PathlightError("Pathlight metric filter is invalid")
    return MetricFilter(
        value.metric_name,
        value.status,
        value.trace_sha256,
        value.metric_contract_sha256,
        value.dataset_snapshot_sha256,
        value.scope_sha256,
    )


def _root_status(trace: Mapping[str, object]) -> str:
    events = trace["events"]
    if (
        not isinstance(events, tuple)
        or not events
        or not isinstance(events[0], Mapping)
    ):
        raise PathlightError("Pathlight trace is invalid")
    root_span_id = events[0].get("span_id")
    if type(root_span_id) is not str:
        raise PathlightError("Pathlight trace is invalid")
    for event in reversed(events):
        if (
            isinstance(event, Mapping)
            and event.get("span_id") == root_span_id
            and event.get("status") != "started"
        ):
            status = event.get("status")
            if type(status) is str:
                return status
    raise PathlightError("Pathlight trace is invalid")


def _trace_summary(trace: Mapping[str, object]) -> Mapping[str, object]:
    events = trace["events"]
    if not isinstance(events, tuple) or not events:
        raise PathlightError("Pathlight trace is invalid")
    event_mappings = tuple(event for event in events if isinstance(event, Mapping))
    if len(event_mappings) != len(events):
        raise PathlightError("Pathlight trace is invalid")
    component_digests = tuple(
        sorted(
            {
                value
                for event in event_mappings
                for key, value in _event_attributes(event).items()
                if key in _COMPONENT_DIGEST_ATTRIBUTES and type(value) is str
            }
        )
    )
    timestamps = tuple(event.get("timestamp_ns") for event in event_mappings)
    if any(type(timestamp) is not int for timestamp in timestamps):
        raise PathlightError("Pathlight trace is invalid")
    return _FrozenDict(
        {
            "trace_id": _require_trace_id(trace["trace_id"]),
            "trace_sha256": _require_sha256(
                trace["trace_sha256"], field_name="trace digest"
            ),
            "root_status": _root_status(trace),
            "event_count": len(event_mappings),
            "span_count": sum(
                event.get("status") == "started" for event in event_mappings
            ),
            "first_timestamp_ns": timestamps[0],
            "last_timestamp_ns": timestamps[-1],
            "component_sha256s": component_digests,
            "missing_evidence_count": sum(
                _event_attributes(event).get("missing_evidence") is True
                for event in event_mappings
            ),
        }
    )


def _event_attributes(event: Mapping[str, object]) -> Mapping[str, object]:
    attributes = event.get("attributes")
    if not isinstance(attributes, Mapping):
        raise PathlightError("Pathlight trace is invalid")
    return attributes


def _matches_trace_filter(trace: Mapping[str, object], query: TraceFilter) -> bool:
    if query.status is not None and _root_status(trace) != query.status:
        return False
    events = trace["events"]
    if not isinstance(events, tuple):
        raise PathlightError("Pathlight trace is invalid")
    if query.kind is not None and not any(
        isinstance(event, Mapping) and event.get("kind") == query.kind
        for event in events
    ):
        return False
    return query.component_sha256 is None or any(
        isinstance(event, Mapping)
        and any(
            key in _COMPONENT_DIGEST_ATTRIBUTES and value == query.component_sha256
            for key, value in _event_attributes(event).items()
        )
        for event in events
    )


def _metric_projection(
    record: EvaluationRecord, contract: MetricContract
) -> Mapping[str, object]:
    projection = _freeze_json({**record.to_mapping(), "metric_name": contract.metric_name})
    if not isinstance(projection, Mapping):
        raise PathlightError("Pathlight evaluation record is invalid")
    return projection


def _matches_metric_filter(
    record: EvaluationRecord, contract: MetricContract, query: MetricFilter
) -> bool:
    if query.metric_name is not None and contract.metric_name != query.metric_name:
        return False
    return all(
        value is None or getattr(record, field_name) == value
        for field_name, value in (
            ("status", query.status),
            ("trace_sha256", query.trace_sha256),
            ("metric_contract_sha256", query.metric_contract_sha256),
            ("dataset_snapshot_sha256", query.dataset_snapshot_sha256),
            ("scope_sha256", query.scope_sha256),
        )
    )
