"""Explicit persistence for public-safe workflow observations."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from asterion.pathlight import PathlightError, validate_trace_graph
from asterion.workflow_evidence.collector import (
    WorkflowEvidenceError,
    validate_workflow_evidence,
)


def _digest(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise WorkflowEvidenceError("workflow observation digest is invalid")
    try:
        int(value, 16)
    except ValueError as error:
        raise WorkflowEvidenceError("workflow observation digest is invalid") from error
    return value


def _validate_failure_observation(record: Mapping[str, object]) -> None:
    if set(record) != {
        "schema",
        "run_id",
        "input_digest",
        "status",
        "failure_class",
    }:
        raise WorkflowEvidenceError("workflow observation failure record is invalid")
    if record["schema"] != "asterion.workflow-observation/v1":
        raise WorkflowEvidenceError("workflow observation failure schema is invalid")
    if not isinstance(record["run_id"], str) or not record["run_id"]:
        raise WorkflowEvidenceError("workflow observation failure identity is invalid")
    _digest(record["input_digest"])
    if record["status"] not in {"failed", "cancelled"}:
        raise WorkflowEvidenceError("workflow observation failure status is invalid")
    if record["failure_class"] not in {
        "runtime-invocation-failed",
        "runtime-cancelled",
    }:
        raise WorkflowEvidenceError("workflow observation failure class is invalid")


def write_workflow_observation_bundle(
    path: Path,
    records: Sequence[Mapping[str, object]],
    *,
    pathlight_traces: Sequence[Mapping[str, object]] = (),
) -> None:
    """Write validated records once to a caller-selected canonical target."""

    if (
        path.name != "workflow-evidence.json"
        or not path.parent.is_dir()
        or path.exists()
        or path.is_symlink()
    ):
        raise WorkflowEvidenceError("workflow observation target is invalid")
    serialized_records: list[dict[str, object]] = []
    seen_run_ids: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise WorkflowEvidenceError("workflow observation record is invalid")
        if record.get("schema") == "asterion.workflow-evidence/v1":
            validate_workflow_evidence(record)
        else:
            _validate_failure_observation(record)
        run_id = record["run_id"]
        assert isinstance(run_id, str)
        if run_id in seen_run_ids:
            raise WorkflowEvidenceError("workflow observation run identity is duplicated")
        seen_run_ids.add(run_id)
        serialized_records.append(dict(record))
    serialized_traces: list[dict[str, object]] = []
    seen_trace_ids: set[str] = set()
    for trace in pathlight_traces:
        if not isinstance(trace, Mapping):
            raise WorkflowEvidenceError("Pathlight trace is invalid")
        try:
            validate_trace_graph(trace)
        except PathlightError:
            raise WorkflowEvidenceError("Pathlight trace is invalid") from None
        trace_id = trace["trace_id"]
        assert isinstance(trace_id, str)
        if trace_id in seen_trace_ids:
            raise WorkflowEvidenceError("Pathlight trace identity is duplicated")
        seen_trace_ids.add(trace_id)
        serialized_traces.append(_serialize_pathlight_trace(trace))
    bundle: dict[str, object] = {
        "schema": "asterion.workflow-observation-bundle/v1",
        "records": serialized_records,
        "pathlight_traces": serialized_traces,
    }
    bundle["bundle_sha256"] = hashlib.sha256(
        json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    encoded = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        raise WorkflowEvidenceError("workflow observation target is unavailable") from error
    with os.fdopen(descriptor, "wb") as output:
        output.write(encoded)


def _serialize_pathlight_trace(trace: Mapping[str, object]) -> dict[str, object]:
    """Copy an already validated trace into standard JSON container types."""

    events = trace["events"]
    assert isinstance(events, list)
    serialized_events: list[dict[str, object]] = []
    for event in events:
        assert isinstance(event, Mapping)
        attributes = event["attributes"]
        links = event["links"]
        assert isinstance(attributes, Mapping)
        assert isinstance(links, Sequence)
        serialized_events.append(
            {
                "trace_id": event["trace_id"],
                "span_id": event["span_id"],
                "parent_span_id": event["parent_span_id"],
                "sequence": event["sequence"],
                "kind": event["kind"],
                "status": event["status"],
                "attributes": dict(attributes),
                "links": [dict(link) for link in links],
                "timestamp_ns": event["timestamp_ns"],
            }
        )
    return {
        "schema": trace["schema"],
        "trace_id": trace["trace_id"],
        "events": serialized_events,
        "trace_sha256": trace["trace_sha256"],
    }
