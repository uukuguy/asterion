"""Package-owned runtime helpers for DCI capability implementations."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


PROTOCOL_VERSION = "asterion.agent-runtime/v1"
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
IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")


class RuntimeEventError(ValueError):
    """Raised when a runtime stream violates the public event contract."""


@dataclass(frozen=True, slots=True)
class RuntimeRequest:
    run_id: str
    input_text: str
    requested_capabilities: tuple[str, ...] = ()
    deadline_ms: int | None = None
    protocol: str = PROTOCOL_VERSION

    def to_mapping(self) -> dict[str, object]:
        value: dict[str, object] = {
            "protocol": self.protocol,
            "run_id": self.run_id,
            "input": {"text": self.input_text},
        }
        if self.requested_capabilities:
            value["requested_capabilities"] = list(self.requested_capabilities)
        if self.deadline_ms is not None:
            value["deadline_ms"] = self.deadline_ms
        return value


def event_mappings(events: Iterable[object]) -> tuple[Mapping[str, object], ...]:
    values: list[Mapping[str, object]] = []
    for event in events:
        to_mapping = getattr(event, "to_mapping", None)
        value = to_mapping() if callable(to_mapping) else event
        if not isinstance(value, Mapping):
            raise RuntimeEventError("runtime event is invalid")
        values.append(value)
    validate_event_stream(values)
    return tuple(values)


def validate_event_stream(events: Sequence[Mapping[str, object]]) -> None:
    if not events:
        raise RuntimeEventError("runtime event stream is invalid")
    run_id: str | None = None
    calls: set[str] = set()
    results: set[str] = set()
    terminal_seen = False
    for expected_sequence, event in enumerate(events, start=1):
        current_run_id = _event_identity(event, expected_sequence)
        event_type = event["type"]
        assert isinstance(event_type, str)
        if run_id is None:
            run_id = current_run_id
        elif current_run_id != run_id:
            raise RuntimeEventError("runtime event stream is invalid")
        if terminal_seen:
            raise RuntimeEventError("runtime event stream is invalid")
        if expected_sequence == 1 and event_type != "run.started":
            raise RuntimeEventError("runtime event stream is invalid")
        if expected_sequence > 1 and event_type == "run.started":
            raise RuntimeEventError("runtime event stream is invalid")
        payload = event["payload"]
        assert isinstance(payload, Mapping)
        if event_type == "tool.call":
            call_id = payload["call_id"]
            assert isinstance(call_id, str)
            if call_id in calls:
                raise RuntimeEventError("runtime event stream is invalid")
            calls.add(call_id)
        elif event_type == "tool.result":
            call_id = payload["call_id"]
            assert isinstance(call_id, str)
            if call_id not in calls or call_id in results:
                raise RuntimeEventError("runtime event stream is invalid")
            results.add(call_id)
        if event_type in TERMINAL_EVENT_TYPES:
            terminal_seen = True
    if not terminal_seen or calls != results:
        raise RuntimeEventError("runtime event stream is invalid")


def _event_identity(event: Mapping[str, object], sequence: int) -> str:
    if set(event) != {"protocol", "run_id", "sequence", "type", "payload"}:
        raise RuntimeEventError("runtime event is invalid")
    if event["protocol"] != PROTOCOL_VERSION:
        raise RuntimeEventError("runtime event is invalid")
    run_id = event["run_id"]
    if not isinstance(run_id, str) or not run_id:
        raise RuntimeEventError("runtime event is invalid")
    if event["sequence"] != sequence:
        raise RuntimeEventError("runtime event stream is invalid")
    event_type = event["type"]
    if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
        raise RuntimeEventError("runtime event is invalid")
    payload = event["payload"]
    if not isinstance(payload, Mapping):
        raise RuntimeEventError("runtime event is invalid")
    _validate_payload(event_type, payload)
    return run_id


def _validate_payload(event_type: str, payload: Mapping[str, object]) -> None:
    if event_type == "run.started":
        _keys(payload, {"capabilities"})
        capabilities = payload["capabilities"]
        if (
            not isinstance(capabilities, list)
            or capabilities != sorted(set(capabilities))
            or any(not isinstance(item, str) or IDENTIFIER.fullmatch(item) is None for item in capabilities)
        ):
            raise RuntimeEventError("runtime event is invalid")
    elif event_type == "artifact.created":
        _keys(payload, {"artifact"})
        artifact = payload["artifact"]
        if not isinstance(artifact, Mapping):
            raise RuntimeEventError("runtime event is invalid")
        required = {"artifact_id", "kind", "media_type"}
        if not required.issubset(artifact.keys()):
            raise RuntimeEventError("runtime event is invalid")
        for field in required:
            if not isinstance(artifact[field], str) or not artifact[field]:
                raise RuntimeEventError("runtime event is invalid")
    elif event_type == "run.completed":
        _keys(payload, {"status"})
        if payload["status"] not in {"completed", "cancelled"}:
            raise RuntimeEventError("runtime event is invalid")
    elif event_type == "run.failed":
        _keys(payload, {"code", "message"})
        if not all(isinstance(payload[field], str) and payload[field] for field in ("code", "message")):
            raise RuntimeEventError("runtime event is invalid")
    elif event_type == "tool.call":
        _keys(payload, {"call_id", "name", "arguments"})
        if (
            not isinstance(payload["call_id"], str)
            or not payload["call_id"]
            or not isinstance(payload["name"], str)
            or not payload["name"]
            or not isinstance(payload["arguments"], Mapping)
        ):
            raise RuntimeEventError("runtime event is invalid")
    elif event_type == "tool.result":
        _keys(payload, {"call_id", "output", "is_error"})
        if not isinstance(payload["call_id"], str) or not payload["call_id"] or not isinstance(payload["is_error"], bool):
            raise RuntimeEventError("runtime event is invalid")
    elif event_type == "usage.reported":
        _keys(payload, {"input_tokens", "output_tokens"})
        for field in ("input_tokens", "output_tokens"):
            value = payload[field]
            if type(value) is not int or value < 0:
                raise RuntimeEventError("runtime event is invalid")
    elif event_type == "text.delta":
        _keys(payload, {"text"})
        if not isinstance(payload["text"], str) or not payload["text"]:
            raise RuntimeEventError("runtime event is invalid")


def _keys(payload: Mapping[str, object], required: set[str]) -> None:
    if set(payload) != required:
        raise RuntimeEventError("runtime event is invalid")


__all__ = ("RuntimeEventError", "RuntimeRequest", "event_mappings")
