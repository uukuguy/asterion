"""Validation for the closed, body-free Asterion client protocol."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from asterion.protocol_ordering import is_sorted_unique_scalar_strings


AGENT_CLIENT_PROTOCOL = "asterion.agent-client/v1"
CLIENT_INTENT_TYPES = frozenset(
    {
        "command.invoke",
        "export.request",
        "extension-ui.respond",
        "input.submit",
        "session.attach",
        "session.cancel",
        "session.create",
        "session.detach",
        "session.pause",
        "session.resume",
        "share.request",
    }
)
CLIENT_EVENT_TYPES = frozenset(
    {
        "artifact.available",
        "commands.changed",
        "export.created",
        "extension-ui.requested",
        "fault.raised",
        "message.available",
        "session.state",
        "session.terminal",
        "share.created",
        "tool.completed",
        "tool.started",
        "usage.reported",
    }
)
CLIENT_INTENT_PAYLOAD_FIELDS = MappingProxyType(
    {
        "command.invoke": ("arguments_ref", "command_name", "command_revision"),
        "export.request": (
            "destination_ref",
            "expires_at_ms",
            "export_id",
            "max_bytes",
            "media_type",
            "reference_ids",
            "visibility",
        ),
        "extension-ui.respond": ("cancelled", "request_id", "response_ref"),
        "input.submit": ("content_ref", "delivery", "input_id"),
        "session.attach": ("cursor",),
        "session.cancel": ("reason_code",),
        "session.create": ("goal_id", "goal_ref"),
        "session.detach": ("reason_code",),
        "session.pause": ("reason_code",),
        "session.resume": ("reason_code",),
        "share.request": ("expires_at_ms", "export_id", "share_id"),
    }
)
CLIENT_EVENT_PAYLOAD_FIELDS = MappingProxyType(
    {
        "artifact.available": (
            "artifact_id",
            "artifact_ref",
            "media_type",
            "sha256",
            "size",
        ),
        "commands.changed": ("commands", "revision"),
        "export.created": (
            "artifact_id",
            "artifact_ref",
            "export_id",
            "media_type",
            "sha256",
            "size",
            "visibility",
        ),
        "extension-ui.requested": ("deadline_ms", "method", "payload_ref", "request_id"),
        "fault.raised": ("code", "evidence_ref", "recoverable"),
        "message.available": (
            "content_ref",
            "media_type",
            "message_id",
            "role",
            "sha256",
            "size",
        ),
        "session.state": ("reason_code", "status"),
        "session.terminal": ("reason_code", "status"),
        "share.created": ("export_id", "share_id", "share_ref"),
        "tool.completed": (
            "call_id",
            "is_error",
            "media_type",
            "result_ref",
            "sha256",
            "size",
        ),
        "tool.started": ("arguments_ref", "call_id", "name", "sha256", "size"),
        "usage.reported": (
            "aggregate_tokens",
            "application_tokens",
            "child_tokens",
            "controller_tokens",
            "cost_micros",
        ),
    }
)

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MEDIA_TYPE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$")
_UTC_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z$"
)
_FORBIDDEN_BODY_FIELDS = frozenset(
    {"text", "prompt", "answer", "arguments", "output", "credential", "path", "destination"}
)
_TERMINAL_STATUSES = frozenset({"budget_limited", "cancelled", "completed", "failed"})
_SESSION_STATUSES = frozenset(
    {"creating", "idle", "needs_input", "paused", "running", *_TERMINAL_STATUSES}
)


class ClientProtocolError(ValueError):
    """Raised when a public client-protocol value is invalid."""


@dataclass(frozen=True)
class ClientCursor:
    generation: int
    sequence: int

    def __post_init__(self) -> None:
        _require_positive_integer(self.generation, "client cursor generation")
        _require_nonnegative_integer(self.sequence, "client cursor sequence")


@dataclass(frozen=True, repr=False)
class ClientIntent:
    protocol: str
    intent_id: str
    client_id: str
    session_id: str
    authority_revision: int
    type: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        _validate_intent_fields(self)
        object.__setattr__(self, "payload", _freeze_mapping(self.payload))

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ClientIntent:
        return _intent_from_mapping(value)

    def to_mapping(self) -> Mapping[str, object]:
        return _freeze_mapping(
            {
                "protocol": self.protocol,
                "intent_id": self.intent_id,
                "client_id": self.client_id,
                "session_id": self.session_id,
                "authority_revision": self.authority_revision,
                "type": self.type,
                "payload": self.payload,
            }
        )


@dataclass(frozen=True, repr=False)
class ClientEvent:
    protocol: str
    event_id: str
    session_id: str
    generation: int
    sequence: int
    emitted_at: str
    type: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        _validate_event_fields(self)
        object.__setattr__(self, "payload", _freeze_mapping(self.payload))

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ClientEvent:
        return _event_from_mapping(value)

    def to_mapping(self) -> Mapping[str, object]:
        return _freeze_mapping(
            {
                "protocol": self.protocol,
                "event_id": self.event_id,
                "session_id": self.session_id,
                "generation": self.generation,
                "sequence": self.sequence,
                "emitted_at": self.emitted_at,
                "type": self.type,
                "payload": self.payload,
            }
        )


def validate_client_intent(value: object) -> ClientIntent:
    """Validate and snapshot one client-to-host intent."""

    if isinstance(value, ClientIntent):
        return ClientIntent(**value.to_mapping())
    if not isinstance(value, Mapping):
        raise ClientProtocolError("client intent is invalid")
    return _intent_from_mapping(value)


def validate_client_event(value: object) -> ClientEvent:
    """Validate and snapshot one host-to-client public event."""

    if isinstance(value, ClientEvent):
        return ClientEvent(**value.to_mapping())
    if not isinstance(value, Mapping):
        raise ClientProtocolError("client event is invalid")
    return _event_from_mapping(value)


def validate_client_event_stream(value: object) -> tuple[ClientEvent, ...]:
    """Validate one contiguous public client event generation."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)) or not value:
        raise ClientProtocolError("client event stream is invalid")
    events = tuple(validate_client_event(item) for item in value)
    if len({event.session_id for event in events}) != 1 or len({event.generation for event in events}) != 1:
        raise ClientProtocolError("client event stream identity is invalid")
    if len({event.event_id for event in events}) != len(events):
        raise ClientProtocolError("client event stream event identities are invalid")
    if [event.sequence for event in events] != list(range(1, len(events) + 1)):
        raise ClientProtocolError("client event stream sequence is not contiguous")

    active_calls: set[str] = set()
    terminal_seen = False
    for index, event in enumerate(events):
        if terminal_seen:
            raise ClientProtocolError("client event stream has post-terminal event")
        if event.type == "tool.started":
            call_id = event.payload["call_id"]
            assert isinstance(call_id, str)
            if call_id in active_calls:
                raise ClientProtocolError("client event stream tool call is invalid")
            active_calls.add(call_id)
        elif event.type == "tool.completed":
            call_id = event.payload["call_id"]
            assert isinstance(call_id, str)
            if call_id not in active_calls:
                raise ClientProtocolError("client event stream tool call is invalid")
            active_calls.remove(call_id)
        elif event.type == "session.terminal":
            if index != len(events) - 1 or active_calls:
                raise ClientProtocolError("client event stream terminal event is invalid")
            terminal_seen = True
    if not terminal_seen:
        raise ClientProtocolError("client event stream terminal event is invalid")
    return events


def _intent_from_mapping(value: Mapping[str, object]) -> ClientIntent:
    mapping = _closed_mapping(
        value,
        {"protocol", "intent_id", "client_id", "session_id", "authority_revision", "type", "payload"},
        "client intent",
    )
    return ClientIntent(
        protocol=_string(mapping, "protocol", "client intent"),
        intent_id=_string(mapping, "intent_id", "client intent"),
        client_id=_string(mapping, "client_id", "client intent"),
        session_id=_string(mapping, "session_id", "client intent"),
        authority_revision=mapping["authority_revision"],
        type=_string(mapping, "type", "client intent"),
        payload=_mapping(mapping["payload"], "client intent payload"),
    )


def _event_from_mapping(value: Mapping[str, object]) -> ClientEvent:
    mapping = _closed_mapping(
        value,
        {"protocol", "event_id", "session_id", "generation", "sequence", "emitted_at", "type", "payload"},
        "client event",
    )
    return ClientEvent(
        protocol=_string(mapping, "protocol", "client event"),
        event_id=_string(mapping, "event_id", "client event"),
        session_id=_string(mapping, "session_id", "client event"),
        generation=mapping["generation"],
        sequence=mapping["sequence"],
        emitted_at=_string(mapping, "emitted_at", "client event"),
        type=_string(mapping, "type", "client event"),
        payload=_mapping(mapping["payload"], "client event payload"),
    )


def _validate_intent_fields(intent: ClientIntent) -> None:
    if intent.protocol != AGENT_CLIENT_PROTOCOL:
        raise ClientProtocolError("client intent protocol is invalid")
    for value, label in ((intent.intent_id, "identity"), (intent.client_id, "client"), (intent.session_id, "session")):
        _require_opaque_id(value, f"client intent {label}")
    _require_positive_integer(intent.authority_revision, "client intent authority revision")
    if intent.type not in CLIENT_INTENT_TYPES:
        raise ClientProtocolError("client intent type is invalid")
    _forbid_body_fields(intent.payload)
    _validate_intent_payload(intent.type, intent.payload)


def _validate_event_fields(event: ClientEvent) -> None:
    if event.protocol != AGENT_CLIENT_PROTOCOL:
        raise ClientProtocolError("client event protocol is invalid")
    _require_opaque_id(event.event_id, "client event identity")
    _require_opaque_id(event.session_id, "client event session")
    _require_positive_integer(event.generation, "client event generation")
    _require_positive_integer(event.sequence, "client event sequence")
    _require_utc_timestamp(event.emitted_at)
    if event.type not in CLIENT_EVENT_TYPES:
        raise ClientProtocolError("client event type is invalid")
    _forbid_body_fields(event.payload)
    _validate_event_payload(event.type, event.payload)


def _validate_intent_payload(intent_type: str, value: Mapping[str, object]) -> None:
    payload = _closed_mapping(value, set(CLIENT_INTENT_PAYLOAD_FIELDS[intent_type]), "client intent payload")
    if intent_type == "command.invoke":
        _require_opaque_id(payload["arguments_ref"], "command arguments reference")
        _require_identifier(payload["command_name"], "command name")
        _require_positive_integer(payload["command_revision"], "command revision")
    elif intent_type == "export.request":
        for field in ("destination_ref", "export_id"):
            _require_opaque_id(payload[field], f"export {field}")
        _require_positive_integer(payload["expires_at_ms"], "export expiry")
        _require_positive_integer(payload["max_bytes"], "export maximum size")
        _require_media_type(payload["media_type"], "export media type")
        _require_sorted_opaque_ids(payload["reference_ids"], "export references")
        _require_visibility(payload["visibility"], "export visibility")
    elif intent_type == "extension-ui.respond":
        if not isinstance(payload["cancelled"], bool):
            raise ClientProtocolError("extension response cancellation is invalid")
        _require_opaque_id(payload["request_id"], "extension response request")
        _require_opaque_id(payload["response_ref"], "extension response reference")
    elif intent_type == "input.submit":
        _require_opaque_id(payload["content_ref"], "input content reference")
        if payload["delivery"] not in {"direct", "steer", "follow_up"}:
            raise ClientProtocolError("input delivery is invalid")
        _require_opaque_id(payload["input_id"], "input identity")
    elif intent_type == "session.attach":
        cursor = _closed_mapping(payload["cursor"], {"generation", "sequence"}, "client cursor")
        _require_positive_integer(cursor["generation"], "client cursor generation")
        _require_nonnegative_integer(cursor["sequence"], "client cursor sequence")
    elif intent_type == "session.create":
        _require_opaque_id(payload["goal_id"], "session goal")
        _require_opaque_id(payload["goal_ref"], "session goal reference")
    elif intent_type in {"session.cancel", "session.detach", "session.pause", "session.resume"}:
        _require_identifier(payload["reason_code"], "session reason")
    elif intent_type == "share.request":
        _require_positive_integer(payload["expires_at_ms"], "share expiry")
        _require_opaque_id(payload["export_id"], "share export")
        _require_opaque_id(payload["share_id"], "share identity")


def _validate_event_payload(event_type: str, value: Mapping[str, object]) -> None:
    payload = _closed_mapping(value, set(CLIENT_EVENT_PAYLOAD_FIELDS[event_type]), "client event payload")
    if event_type in {"artifact.available", "export.created"}:
        for field in ("artifact_id", "artifact_ref"):
            _require_opaque_id(payload[field], f"artifact {field}")
        _require_media_type(payload["media_type"], "artifact media type")
        _require_sha256(payload["sha256"], "artifact digest")
        _require_nonnegative_integer(payload["size"], "artifact size")
        if event_type == "export.created":
            _require_opaque_id(payload["export_id"], "export identity")
            _require_visibility(payload["visibility"], "export visibility")
    elif event_type == "commands.changed":
        _require_sorted_identifiers(payload["commands"], "commands")
        _require_positive_integer(payload["revision"], "command revision")
    elif event_type == "extension-ui.requested":
        _require_positive_integer(payload["deadline_ms"], "extension deadline")
        _require_identifier(payload["method"], "extension method")
        _require_opaque_id(payload["payload_ref"], "extension payload reference")
        _require_opaque_id(payload["request_id"], "extension request")
    elif event_type == "fault.raised":
        _require_identifier(payload["code"], "fault code")
        _require_opaque_id(payload["evidence_ref"], "fault evidence reference")
        if not isinstance(payload["recoverable"], bool):
            raise ClientProtocolError("fault recoverable flag is invalid")
    elif event_type == "message.available":
        _require_opaque_id(payload["content_ref"], "message content reference")
        _require_media_type(payload["media_type"], "message media type")
        _require_opaque_id(payload["message_id"], "message identity")
        if payload["role"] not in {"assistant", "system", "tool", "user"}:
            raise ClientProtocolError("message role is invalid")
        _require_sha256(payload["sha256"], "message digest")
        _require_nonnegative_integer(payload["size"], "message size")
    elif event_type in {"session.state", "session.terminal"}:
        _require_identifier(payload["reason_code"], "session reason")
        statuses = _TERMINAL_STATUSES if event_type == "session.terminal" else _SESSION_STATUSES
        if payload["status"] not in statuses:
            raise ClientProtocolError("session status is invalid")
    elif event_type == "share.created":
        for field in ("export_id", "share_id", "share_ref"):
            _require_opaque_id(payload[field], f"share {field}")
    elif event_type in {"tool.completed", "tool.started"}:
        _require_opaque_id(payload["call_id"], "tool call identity")
        if event_type == "tool.completed":
            if not isinstance(payload["is_error"], bool):
                raise ClientProtocolError("tool result error flag is invalid")
            _require_media_type(payload["media_type"], "tool result media type")
            _require_opaque_id(payload["result_ref"], "tool result reference")
        else:
            _require_opaque_id(payload["arguments_ref"], "tool arguments reference")
            _require_identifier(payload["name"], "tool name")
        _require_sha256(payload["sha256"], "tool digest")
        _require_nonnegative_integer(payload["size"], "tool size")
    elif event_type == "usage.reported":
        for field in CLIENT_EVENT_PAYLOAD_FIELDS[event_type]:
            _require_nonnegative_integer(payload[field], f"usage {field}")


def _closed_mapping(value: object, fields: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value) or set(value) != fields:
        raise ClientProtocolError(f"{label} fields are invalid")
    return value


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ClientProtocolError(f"{label} is invalid")
    return value


def _string(value: Mapping[str, object], field: str, label: str) -> str:
    item = value[field]
    if not isinstance(item, str):
        raise ClientProtocolError(f"{label} is invalid")
    return item


def _require_identifier(value: object, label: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ClientProtocolError(f"{label} is invalid")


def _require_opaque_id(value: object, label: str) -> None:
    if not isinstance(value, str) or _OPAQUE_ID.fullmatch(value) is None:
        raise ClientProtocolError(f"{label} is invalid")


def _require_media_type(value: object, label: str) -> None:
    if not isinstance(value, str) or _MEDIA_TYPE.fullmatch(value) is None:
        raise ClientProtocolError(f"{label} is invalid")


def _require_sha256(value: object, label: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ClientProtocolError(f"{label} is invalid")


def _require_positive_integer(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ClientProtocolError(f"{label} is invalid")


def _require_nonnegative_integer(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ClientProtocolError(f"{label} is invalid")


def _require_sorted_identifiers(value: object, label: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or _IDENTIFIER.fullmatch(item) is None for item in value) or not is_sorted_unique_scalar_strings(value):
        raise ClientProtocolError(f"{label} is invalid")


def _require_sorted_opaque_ids(value: object, label: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or _OPAQUE_ID.fullmatch(item) is None for item in value) or not is_sorted_unique_scalar_strings(value):
        raise ClientProtocolError(f"{label} is invalid")


def _require_visibility(value: object, label: str) -> None:
    if value not in {"private", "public"}:
        raise ClientProtocolError(f"{label} is invalid")


def _require_utc_timestamp(value: object) -> None:
    if not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None:
        raise ClientProtocolError("client event timestamp is invalid")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ClientProtocolError("client event timestamp is invalid") from None


def _forbid_body_fields(value: Mapping[str, object]) -> None:
    for key, child in value.items():
        if key in _FORBIDDEN_BODY_FIELDS:
            raise ClientProtocolError("client value contains forbidden body field")
        if isinstance(child, Mapping):
            _forbid_body_fields(child)
        elif isinstance(child, Sequence) and not isinstance(child, (str, bytes, bytearray)):
            for item in child:
                if isinstance(item, Mapping):
                    _forbid_body_fields(item)


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze(item) for key, item in value.items()})


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    return value
