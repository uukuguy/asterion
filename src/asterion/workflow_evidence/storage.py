"""Explicit persistence for public-safe workflow observations."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from asterion.pathlight import PathlightError, validate_trace_graph
from asterion.workflow_evidence.collector import (
    WorkflowEvidenceError,
    validate_workflow_evidence,
)

_PROJECTION_SCHEMA = "asterion.workflow-observation-projection/v1"
_READABLE_BUNDLE_BASENAMES = frozenset(
    {
        "workflow-evidence.json",
        "workflow-evidence.provider-calls.offline.json",
    }
)


@dataclass(frozen=True, slots=True)
class WorkflowObservationBundle:
    """A verified, immutable workflow observation bundle."""

    records: tuple[Mapping[str, object], ...]
    pathlight_traces: tuple[Mapping[str, object], ...]
    bundle_sha256: str
    projection_sha256: str

    def __post_init__(self) -> None:
        try:
            self._validate_and_freeze_projection()
        except Exception:
            raise WorkflowEvidenceError(
                "workflow observation projection is invalid"
            ) from None

    def _validate_and_freeze_projection(self) -> None:
        if not isinstance(self.records, tuple) or not isinstance(
            self.pathlight_traces, tuple
        ):
            raise WorkflowEvidenceError("workflow observation projection is invalid")
        if any(not isinstance(record, Mapping) for record in self.records) or any(
            not isinstance(trace, Mapping) for trace in self.pathlight_traces
        ):
            raise WorkflowEvidenceError("workflow observation projection is invalid")
        object.__setattr__(
            self,
            "records",
            tuple(_freeze_mapping(record) for record in self.records),
        )
        object.__setattr__(
            self,
            "pathlight_traces",
            tuple(_freeze_mapping(trace) for trace in self.pathlight_traces),
        )
        validate_workflow_observation_bundle(self)


def _digest(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise WorkflowEvidenceError("workflow observation digest is invalid")
    try:
        int(value, 16)
    except ValueError:
        raise WorkflowEvidenceError("workflow observation digest is invalid") from None
    return value


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _projection_mapping(
    bundle_sha256: str,
    records: Sequence[Mapping[str, object]],
    pathlight_traces: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "schema": _PROJECTION_SCHEMA,
        "source_bundle_sha256": bundle_sha256,
        "records": [_json_copy(record) for record in records],
        "pathlight_traces": [_json_copy(trace) for trace in pathlight_traces],
    }


def _json_copy(value: object) -> object:
    try:
        return _json_copy_value(value)
    except Exception:
        raise WorkflowEvidenceError(
            "workflow observation projection is invalid"
        ) from None


def _json_copy_value(value: object) -> object:
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise WorkflowEvidenceError("workflow observation projection is invalid")
        return {key: _json_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_copy(item) for item in value]
    if value is None or type(value) in {str, int, bool}:
        return value
    raise WorkflowEvidenceError("workflow observation projection is invalid")


def _validate_projected_record(record: Mapping[str, object]) -> None:
    completed_fields = {
        "schema",
        "source_graph_sha256",
        "run_sha256",
        "input_sha256",
        "terminal_status",
        "tools",
        "usage",
        "artifacts",
    }
    failure_fields = {
        "schema",
        "source_graph_sha256",
        "run_sha256",
        "input_sha256",
        "terminal_status",
        "failure_class",
    }
    if record.get("schema") != "asterion.pathlight-workflow-summary/v1":
        raise WorkflowEvidenceError("workflow observation projection record is invalid")
    if set(record) == completed_fields:
        _validate_projected_completed_record(record)
    elif set(record) == failure_fields:
        _validate_projected_failure_record(record)
    else:
        raise WorkflowEvidenceError("workflow observation projection record is invalid")


def _validate_projected_completed_record(record: Mapping[str, object]) -> None:
    for field_name in (
        "source_graph_sha256",
        "run_sha256",
        "input_sha256",
    ):
        _digest(record[field_name])
    if record["terminal_status"] not in {"completed", "failed", "cancelled"}:
        raise WorkflowEvidenceError("workflow observation projection status is invalid")
    tools = record["tools"]
    usage = record["usage"]
    artifacts = record["artifacts"]
    if (
        not isinstance(tools, (list, tuple))
        or not isinstance(usage, Mapping)
        or not isinstance(artifacts, (list, tuple))
    ):
        raise WorkflowEvidenceError("workflow observation projection record is invalid")
    for tool in tools:
        if not isinstance(tool, Mapping) or set(tool) != {
            "tool_sha256",
            "calls",
            "errors",
        }:
            raise WorkflowEvidenceError(
                "workflow observation projection tool is invalid"
            )
        _digest(tool["tool_sha256"])
        calls = tool["calls"]
        errors = tool["errors"]
        if (
            type(calls) is not int
            or calls < 0
            or type(errors) is not int
            or errors < 0
            or errors > calls
        ):
            raise WorkflowEvidenceError(
                "workflow observation projection tool is invalid"
            )
    if set(usage) != {"input_tokens", "output_tokens"} or any(
        type(value) is not int or value < 0 for value in usage.values()
    ):
        raise WorkflowEvidenceError("workflow observation projection usage is invalid")
    for artifact in artifacts:
        if not isinstance(artifact, Mapping) or set(artifact) != {
            "artifact_id_sha256",
            "sha256",
        }:
            raise WorkflowEvidenceError(
                "workflow observation projection artifact is invalid"
            )
        _digest(artifact["artifact_id_sha256"])
        _digest(artifact["sha256"])


def _validate_projected_failure_record(record: Mapping[str, object]) -> None:
    for field_name in (
        "source_graph_sha256",
        "run_sha256",
        "input_sha256",
    ):
        _digest(record[field_name])
    if record["terminal_status"] not in {"failed", "cancelled"} or record[
        "failure_class"
    ] not in {"runtime-invocation-failed", "runtime-cancelled"}:
        raise WorkflowEvidenceError(
            "workflow observation projection failure is invalid"
        )


def validate_workflow_observation_bundle(bundle: WorkflowObservationBundle) -> None:
    """Validate one typed public-safe projection and its exact identity."""

    try:
        _validate_workflow_observation_bundle(bundle)
    except Exception:
        raise WorkflowEvidenceError(
            "workflow observation projection is invalid"
        ) from None


def _validate_workflow_observation_bundle(bundle: WorkflowObservationBundle) -> None:
    if not isinstance(bundle, WorkflowObservationBundle):
        raise WorkflowEvidenceError("workflow observation projection is invalid")
    records = getattr(bundle, "records", None)
    pathlight_traces = getattr(bundle, "pathlight_traces", None)
    bundle_sha256_value = getattr(bundle, "bundle_sha256", None)
    projection_sha256_value = getattr(bundle, "projection_sha256", None)
    if not isinstance(records, tuple) or not isinstance(pathlight_traces, tuple):
        raise WorkflowEvidenceError("workflow observation projection is invalid")
    bundle_sha256 = _digest(bundle_sha256_value)
    projection_sha256 = _digest(projection_sha256_value)
    for record in records:
        if not isinstance(record, Mapping):
            raise WorkflowEvidenceError(
                "workflow observation projection record is invalid"
            )
        _validate_projected_record(record)
    seen_trace_ids: set[str] = set()
    for trace in pathlight_traces:
        if not isinstance(trace, Mapping):
            raise WorkflowEvidenceError("Pathlight trace is invalid")
        thawed_trace = _json_copy(trace)
        if not isinstance(thawed_trace, Mapping):
            raise WorkflowEvidenceError("Pathlight trace is invalid")
        try:
            validate_trace_graph(thawed_trace)
        except (PathlightError, TypeError, ValueError):
            raise WorkflowEvidenceError("Pathlight trace is invalid") from None
        trace_id = thawed_trace["trace_id"]
        assert isinstance(trace_id, str)
        if trace_id in seen_trace_ids:
            raise WorkflowEvidenceError("Pathlight trace identity is duplicated")
        seen_trace_ids.add(trace_id)
    expected = _canonical_digest(
        _projection_mapping(bundle_sha256, records, pathlight_traces)
    )
    if not hmac.compare_digest(projection_sha256, expected):
        raise WorkflowEvidenceError("workflow observation projection digest mismatches")


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


def _validate_completed_observation(record: Mapping[str, object]) -> None:
    validate_workflow_evidence(record)
    if set(record) != {
        "schema",
        "run_id",
        "input_digest",
        "terminal_status",
        "tools",
        "usage",
        "artifacts",
        "graph_sha256",
    }:
        raise WorkflowEvidenceError("workflow observation record is invalid")
    tools = record["tools"]
    usage = record["usage"]
    artifacts = record["artifacts"]
    if (
        not isinstance(tools, list)
        or not isinstance(usage, Mapping)
        or not isinstance(artifacts, list)
    ):
        raise WorkflowEvidenceError("workflow observation record is invalid")
    for tool in tools:
        if not isinstance(tool, Mapping) or set(tool) != {"name", "calls", "errors"}:
            raise WorkflowEvidenceError("workflow observation tool is invalid")
        if not isinstance(tool["name"], str) or not tool["name"]:
            raise WorkflowEvidenceError("workflow observation tool is invalid")
        calls = tool["calls"]
        errors = tool["errors"]
        if (
            isinstance(calls, bool)
            or not isinstance(calls, int)
            or calls < 0
            or isinstance(errors, bool)
            or not isinstance(errors, int)
            or errors < 0
            or errors > calls
        ):
            raise WorkflowEvidenceError("workflow observation tool is invalid")
    if set(usage) != {"input_tokens", "output_tokens"}:
        raise WorkflowEvidenceError("workflow observation usage is invalid")
    for value in usage.values():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise WorkflowEvidenceError("workflow observation usage is invalid")
    for artifact in artifacts:
        if not isinstance(artifact, Mapping) or set(artifact) != {
            "artifact_id",
            "sha256",
        }:
            raise WorkflowEvidenceError("workflow observation artifact is invalid")
        if not isinstance(artifact["artifact_id"], str) or not artifact["artifact_id"]:
            raise WorkflowEvidenceError("workflow observation artifact is invalid")
        _digest(artifact["sha256"])


def _project_completed_observation(record: Mapping[str, object]) -> dict[str, object]:
    tools = record["tools"]
    usage = record["usage"]
    artifacts = record["artifacts"]
    run_id = record["run_id"]
    input_digest = record["input_digest"]
    source_graph_sha256 = record["graph_sha256"]
    terminal_status = record["terminal_status"]
    assert isinstance(tools, list)
    assert isinstance(usage, Mapping)
    assert isinstance(artifacts, list)
    assert isinstance(run_id, str)
    assert isinstance(input_digest, str)
    assert isinstance(source_graph_sha256, str)
    assert isinstance(terminal_status, str)
    projected_tools: list[dict[str, object]] = []
    for tool in tools:
        assert isinstance(tool, Mapping)
        name = tool["name"]
        assert isinstance(name, str)
        projected_tools.append(
            {
                "tool_sha256": _text_digest(name),
                "calls": tool["calls"],
                "errors": tool["errors"],
            }
        )
    projected_artifacts: list[dict[str, object]] = []
    for artifact in artifacts:
        assert isinstance(artifact, Mapping)
        artifact_id = artifact["artifact_id"]
        assert isinstance(artifact_id, str)
        projected_artifacts.append(
            {
                "artifact_id_sha256": _text_digest(artifact_id),
                "sha256": artifact["sha256"],
            }
        )
    return {
        "schema": "asterion.pathlight-workflow-summary/v1",
        "source_graph_sha256": source_graph_sha256,
        "run_sha256": _text_digest(run_id),
        "input_sha256": input_digest,
        "terminal_status": terminal_status,
        "tools": projected_tools,
        "usage": {
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
        },
        "artifacts": projected_artifacts,
    }


def _project_failure_observation(record: Mapping[str, object]) -> dict[str, object]:
    run_id = record["run_id"]
    input_digest = record["input_digest"]
    status = record["status"]
    failure_class = record["failure_class"]
    assert isinstance(run_id, str)
    assert isinstance(input_digest, str)
    assert isinstance(status, str)
    assert isinstance(failure_class, str)
    return {
        "schema": "asterion.pathlight-workflow-summary/v1",
        "source_graph_sha256": _canonical_digest(record),
        "run_sha256": _text_digest(run_id),
        "input_sha256": input_digest,
        "terminal_status": status,
        "failure_class": failure_class,
    }


def read_workflow_observation_bundle(path: Path) -> WorkflowObservationBundle:
    """Read one canonical observation bundle into a validated immutable value."""

    if path.name not in _READABLE_BUNDLE_BASENAMES:
        raise WorkflowEvidenceError("workflow observation source is invalid")
    document = _read_bundle_document(path)
    return _validate_and_freeze_bundle(document)


def _read_bundle_document(path: Path) -> object:
    """Read one regular file through no-follow descriptors for every component."""

    directory_fd = -1
    source_fd = -1
    try:
        absolute = path.absolute()
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise OSError("no-follow descriptor opening is unavailable")
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
        directory_fd = os.open(absolute.anchor, directory_flags)
        for component in absolute.parts[1:-1]:
            next_directory_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_directory_fd
        source_fd = os.open(path.name, os.O_RDONLY | nofollow, dir_fd=directory_fd)
        source_metadata = os.fstat(source_fd)
        if (
            not stat.S_ISREG(source_metadata.st_mode)
            or stat.S_IMODE(source_metadata.st_mode) != 0o600
        ):
            raise OSError("workflow observation source is not a regular file")
        with os.fdopen(source_fd, "rb") as source:
            source_fd = -1
            document = json.loads(source.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise WorkflowEvidenceError("workflow observation source is invalid") from error
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if directory_fd >= 0:
            os.close(directory_fd)
    return document


def _validate_and_freeze_bundle(document: object) -> WorkflowObservationBundle:
    if not isinstance(document, Mapping) or set(document) != {
        "schema",
        "records",
        "pathlight_traces",
        "bundle_sha256",
    }:
        raise WorkflowEvidenceError("workflow observation bundle is invalid")
    if document["schema"] != "asterion.workflow-observation-bundle/v1":
        raise WorkflowEvidenceError("workflow observation bundle schema is invalid")
    records = document["records"]
    pathlight_traces = document["pathlight_traces"]
    if not isinstance(records, list) or not isinstance(pathlight_traces, list):
        raise WorkflowEvidenceError(
            "workflow observation bundle collections are invalid"
        )
    bundle_sha256 = _digest(document["bundle_sha256"])
    expected_bundle_sha256 = hashlib.sha256(
        json.dumps(
            {
                "schema": document["schema"],
                "records": records,
                "pathlight_traces": pathlight_traces,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if not hmac.compare_digest(bundle_sha256, expected_bundle_sha256):
        raise WorkflowEvidenceError("workflow observation bundle digest mismatches")

    seen_run_ids: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise WorkflowEvidenceError("workflow observation record is invalid")
        if record.get("schema") == "asterion.workflow-evidence/v1":
            _validate_completed_observation(record)
        else:
            _validate_failure_observation(record)
        run_id = record["run_id"]
        assert isinstance(run_id, str)
        if run_id in seen_run_ids:
            raise WorkflowEvidenceError(
                "workflow observation run identity is duplicated"
            )
        seen_run_ids.add(run_id)

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

    projected_records = tuple(
        _project_completed_observation(record)
        if record["schema"] == "asterion.workflow-evidence/v1"
        else _project_failure_observation(record)
        for record in records
    )
    projection_sha256 = _canonical_digest(
        _projection_mapping(bundle_sha256, projected_records, pathlight_traces)
    )
    return WorkflowObservationBundle(
        records=projected_records,
        pathlight_traces=tuple(pathlight_traces),
        bundle_sha256=bundle_sha256,
        projection_sha256=projection_sha256,
    )


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    try:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    except Exception:
        raise WorkflowEvidenceError(
            "workflow observation projection is invalid"
        ) from None


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def read_workflow_observation_bundle_mapping(
    document: Mapping[str, object],
) -> WorkflowObservationBundle:
    """Validate an in-memory bundle through the canonical immutable reader."""

    try:
        detached = _json_copy(document)
        return _validate_and_freeze_bundle(detached)
    except WorkflowEvidenceError:
        raise
    except Exception:
        raise WorkflowEvidenceError("workflow observation bundle is invalid") from None


def build_workflow_observation_bundle(
    records: Sequence[Mapping[str, object]],
    *,
    pathlight_traces: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Build one detached canonical bundle without selecting a filesystem path."""

    serialized_records: list[dict[str, object]] = []
    seen_run_ids: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise WorkflowEvidenceError("workflow observation record is invalid")
        copied_record = _json_copy(record)
        if not isinstance(copied_record, dict):
            raise WorkflowEvidenceError("workflow observation record is invalid")
        if copied_record.get("schema") == "asterion.workflow-evidence/v1":
            validate_workflow_evidence(copied_record)
        else:
            _validate_failure_observation(copied_record)
        run_id = copied_record["run_id"]
        assert isinstance(run_id, str)
        if run_id in seen_run_ids:
            raise WorkflowEvidenceError(
                "workflow observation run identity is duplicated"
            )
        seen_run_ids.add(run_id)
        serialized_records.append(copied_record)

    serialized_traces: list[dict[str, object]] = []
    seen_trace_ids: set[str] = set()
    for trace in pathlight_traces:
        if not isinstance(trace, Mapping):
            raise WorkflowEvidenceError("Pathlight trace is invalid")
        copied_trace = _json_copy(trace)
        if not isinstance(copied_trace, dict):
            raise WorkflowEvidenceError("Pathlight trace is invalid")
        try:
            validate_trace_graph(copied_trace)
        except PathlightError:
            raise WorkflowEvidenceError("Pathlight trace is invalid") from None
        trace_id = copied_trace["trace_id"]
        assert isinstance(trace_id, str)
        if trace_id in seen_trace_ids:
            raise WorkflowEvidenceError("Pathlight trace identity is duplicated")
        seen_trace_ids.add(trace_id)
        serialized_traces.append(copied_trace)

    bundle: dict[str, object] = {
        "schema": "asterion.workflow-observation-bundle/v1",
        "records": serialized_records,
        "pathlight_traces": serialized_traces,
    }
    bundle["bundle_sha256"] = hashlib.sha256(
        json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    read_workflow_observation_bundle_mapping(bundle)
    return bundle


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
    bundle = build_workflow_observation_bundle(
        records, pathlight_traces=pathlight_traces
    )
    encoded = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        raise WorkflowEvidenceError(
            "workflow observation target is unavailable"
        ) from error
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
