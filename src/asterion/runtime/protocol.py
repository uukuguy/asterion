"""Reference validation for DCI Agent Runtime Protocol v1."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping


PROTOCOL_VERSION = "dci.agent-runtime/v1"
MAX_DEADLINE_MS = 86_400_000
EVENT_TYPES = {
    "run.started",
    "text.delta",
    "tool.call",
    "tool.result",
    "usage.reported",
    "artifact.created",
    "run.completed",
    "run.failed",
}
TERMINAL_EVENT_TYPES = {"run.completed", "run.failed"}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ProtocolError(ValueError):
    """Raised when a request or event stream violates the protocol contract."""


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProtocolError(f"{label} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ProtocolError(f"{label} keys must be strings")
    return value


def _require_keys(
    value: Mapping[str, object],
    *,
    label: str,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = required - value.keys()
    if missing:
        raise ProtocolError(f"{label} missing fields: {', '.join(sorted(missing))}")
    unexpected = value.keys() - required - optional
    if unexpected:
        raise ProtocolError(
            f"{label} has unknown fields: {', '.join(sorted(unexpected))}"
        )


def _require_non_empty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"{label} must be a non-empty string")
    return value


def _require_non_negative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProtocolError(f"{label} must be a non-negative integer")
    return value


def _validate_string_list(value: object, label: str) -> None:
    if not isinstance(value, list):
        raise ProtocolError(f"{label} must be an array")
    if any(not isinstance(item, str) or not item for item in value):
        raise ProtocolError(f"{label} entries must be non-empty strings")
    if len(set(value)) != len(value):
        raise ProtocolError(f"{label} entries must be unique")


def validate_runtime_manifest(manifest: Mapping[str, object]) -> None:
    """Validate one portable runtime capability manifest."""

    manifest = _require_mapping(manifest, "runtime manifest")
    _require_keys(
        manifest,
        label="runtime manifest",
        required={"protocol", "runtime_id", "capabilities"},
    )
    if manifest["protocol"] != PROTOCOL_VERSION:
        raise ProtocolError("runtime manifest protocol is not dci.agent-runtime/v1")
    _require_non_empty_string(manifest["runtime_id"], "runtime manifest runtime_id")
    _validate_string_list(manifest["capabilities"], "runtime manifest capabilities")


def validate_run_request(request: Mapping[str, object]) -> None:
    """Validate one normalized run request."""

    request = _require_mapping(request, "request")
    _require_keys(
        request,
        label="request",
        required={"protocol", "run_id", "input"},
        optional={"requested_capabilities", "deadline_ms"},
    )
    if request["protocol"] != PROTOCOL_VERSION:
        raise ProtocolError("request protocol is not dci.agent-runtime/v1")
    _require_non_empty_string(request["run_id"], "request run_id")

    input_value = _require_mapping(request["input"], "request input")
    _require_keys(input_value, label="request input", required={"text"})
    _require_non_empty_string(input_value["text"], "request input text")

    if "requested_capabilities" in request:
        _validate_string_list(
            request["requested_capabilities"], "requested_capabilities"
        )
    if "deadline_ms" in request:
        deadline_ms = request["deadline_ms"]
        if (
            isinstance(deadline_ms, bool)
            or not isinstance(deadline_ms, int)
            or not 1 <= deadline_ms <= MAX_DEADLINE_MS
        ):
            raise ProtocolError(
                f"deadline_ms must be an integer from 1 through {MAX_DEADLINE_MS}"
            )


def _validate_artifact(payload: Mapping[str, object]) -> None:
    _require_keys(payload, label="artifact.created payload", required={"artifact"})
    artifact = _require_mapping(payload["artifact"], "artifact")
    _require_keys(
        artifact,
        label="artifact",
        required={"artifact_id", "kind", "media_type"},
        optional={"uri", "sha256"},
    )
    for field in ("artifact_id", "kind", "media_type"):
        _require_non_empty_string(artifact[field], f"artifact {field}")
    if "uri" in artifact:
        _require_non_empty_string(artifact["uri"], "artifact uri")
    if "sha256" in artifact:
        sha256 = artifact["sha256"]
        if not isinstance(sha256, str) or SHA256_PATTERN.fullmatch(sha256) is None:
            raise ProtocolError("artifact sha256 must be 64 lowercase hexadecimal digits")


def _validate_event(event: Mapping[str, object]) -> tuple[str, str]:
    event = _require_mapping(event, "event")
    _require_keys(
        event,
        label="event",
        required={"protocol", "run_id", "sequence", "type", "payload"},
    )
    if event["protocol"] != PROTOCOL_VERSION:
        raise ProtocolError("event protocol is not dci.agent-runtime/v1")
    run_id = _require_non_empty_string(event["run_id"], "event run_id")
    sequence = event["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ProtocolError("event sequence must be a positive integer")
    event_type = event["type"]
    if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
        raise ProtocolError("event type is not recognized by protocol v1")
    payload = _require_mapping(event["payload"], f"{event_type} payload")

    if event_type == "run.started":
        _require_keys(payload, label="run.started payload", required={"capabilities"})
        _validate_string_list(payload["capabilities"], "run.started capabilities")
    elif event_type == "text.delta":
        _require_keys(payload, label="text.delta payload", required={"text"})
        _require_non_empty_string(payload["text"], "text.delta text")
    elif event_type == "tool.call":
        _require_keys(
            payload,
            label="tool.call payload",
            required={"call_id", "name", "arguments"},
        )
        _require_non_empty_string(payload["call_id"], "tool.call call_id")
        _require_non_empty_string(payload["name"], "tool.call name")
        _require_mapping(payload["arguments"], "tool.call arguments")
    elif event_type == "tool.result":
        _require_keys(
            payload,
            label="tool.result payload",
            required={"call_id", "output", "is_error"},
        )
        _require_non_empty_string(payload["call_id"], "tool.result call_id")
        if not isinstance(payload["is_error"], bool):
            raise ProtocolError("tool.result is_error must be a boolean")
    elif event_type == "usage.reported":
        _require_keys(
            payload,
            label="usage.reported payload",
            required={"input_tokens", "output_tokens"},
        )
        _require_non_negative_integer(
            payload["input_tokens"], "usage.reported input_tokens"
        )
        _require_non_negative_integer(
            payload["output_tokens"], "usage.reported output_tokens"
        )
    elif event_type == "artifact.created":
        _validate_artifact(payload)
    elif event_type == "run.completed":
        _require_keys(payload, label="run.completed payload", required={"status"})
        if payload["status"] not in {"completed", "cancelled"}:
            raise ProtocolError("run.completed status must be completed or cancelled")
    elif event_type == "run.failed":
        _require_keys(
            payload,
            label="run.failed payload",
            required={"code", "message"},
        )
        _require_non_empty_string(payload["code"], "run.failed code")
        _require_non_empty_string(payload["message"], "run.failed message")
    return run_id, event_type


def validate_event_stream(events: Iterable[Mapping[str, object]]) -> None:
    """Validate a complete protocol v1 event stream."""

    event_list = list(events)
    if not event_list:
        raise ProtocolError("event stream must not be empty")

    run_id: str | None = None
    calls: set[str] = set()
    results: set[str] = set()
    terminal_seen = False
    for expected_sequence, event in enumerate(event_list, start=1):
        current_run_id, event_type = _validate_event(event)
        if event["sequence"] != expected_sequence:
            raise ProtocolError(
                f"event sequence must be contiguous; expected {expected_sequence}"
            )
        if run_id is None:
            run_id = current_run_id
        elif current_run_id != run_id:
            raise ProtocolError("all events must use the same run_id")
        if terminal_seen:
            raise ProtocolError("event appears after the terminal event")
        if expected_sequence == 1 and event_type != "run.started":
            raise ProtocolError("first event must be run.started")
        if expected_sequence > 1 and event_type == "run.started":
            raise ProtocolError("run.started may appear only once")

        payload = event["payload"]
        if event_type == "tool.call":
            call_id = payload["call_id"]  # type: ignore[index]
            if call_id in calls:
                raise ProtocolError(f"duplicate tool.call call_id {call_id}")
            calls.add(call_id)  # type: ignore[arg-type]
        elif event_type == "tool.result":
            call_id = payload["call_id"]  # type: ignore[index]
            if call_id not in calls:
                raise ProtocolError(f"tool.result has no matching call_id {call_id}")
            if call_id in results:
                raise ProtocolError(f"duplicate tool.result call_id {call_id}")
            results.add(call_id)  # type: ignore[arg-type]
        if event_type in TERMINAL_EVENT_TYPES:
            terminal_seen = True

    if not terminal_seen:
        raise ProtocolError("event stream must end with one terminal event")
