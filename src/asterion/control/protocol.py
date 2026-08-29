"""Closed static contracts for long-running agent systems and providers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from types import MappingProxyType

from asterion.protocol_ordering import is_sorted_unique_scalar_strings


AGENT_SYSTEM_PROTOCOL = "asterion.agent-system/v1"
CONTROL_PLANE_PROTOCOL = "asterion.control-plane/v1"
AGENT_CONTROL_PROTOCOL = "asterion.agent-control/v1"

IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
SEMANTIC_VERSION = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
MEDIA_TYPE = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$"
)
COMPATIBILITY_ID = re.compile(r"^[a-z][a-z0-9.-]*/v[1-9][0-9]*$")
OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
UTC_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z$"
)

AGENT_SYSTEM_FIELDS = {
    "protocol",
    "system_id",
    "version",
    "control_plane",
    "applications",
    "policies",
    "host_capabilities",
    "control_capabilities",
}
CONTROL_PLANE_FIELDS = {
    "protocol",
    "control_plane_id",
    "version",
    "commands",
    "events",
    "capabilities",
    "continuation_media_type",
    "checkpoint_version",
    "compatibility_ids",
}
CONTROL_PLANE_REF_FIELDS = {"control_plane_id", "version"}
APPLICATION_REF_FIELDS = {
    "provider_id",
    "application_id",
    "version",
    "runtime_id",
}

CONTROL_COMMAND_TYPES = frozenset(
    {
        "action.resolve",
        "checkpoint.request",
        "input.submit",
        "session.attach",
        "session.cancel",
        "session.create",
        "session.detach",
        "session.pause",
        "session.resume",
    }
)
CONTROL_EVENT_TYPES = frozenset(
    {
        "action.proposed",
        "budget.reported",
        "checkpoint.created",
        "fault.raised",
        "goal.updated",
        "session.budget-limited",
        "session.cancelled",
        "session.completed",
        "session.created",
        "session.failed",
        "session.paused",
        "session.recovery-required",
        "session.running",
    }
)
CONTROL_COMMAND_FIELDS = {
    "protocol",
    "command_id",
    "session_id",
    "authority_revision",
    "type",
    "payload",
}
CONTROL_EVENT_FIELDS = {
    "protocol",
    "event_id",
    "session_id",
    "generation",
    "sequence",
    "emitted_at",
    "type",
    "payload",
}
TERMINAL_CONTROL_EVENT_TYPES = frozenset(
    {
        "session.budget-limited",
        "session.cancelled",
        "session.completed",
        "session.failed",
    }
)
ACTION_KINDS = frozenset(
    {
        "application.invoke",
        "checkpoint.create",
        "child.cancel",
        "child.message",
        "child.spawn",
        "goal.complete",
        "goal.fail",
        "input.request",
        "session.pause",
    }
)
ACTION_TARGET_KINDS = {
    "application.invoke": "application",
    "checkpoint.create": "checkpoint",
    "child.cancel": "child",
    "child.message": "child",
    "child.spawn": "child",
    "goal.complete": "goal",
    "goal.fail": "goal",
    "input.request": "input",
    "session.pause": "session",
}
ACTION_RESOLUTIONS = frozenset(
    {"admitted", "rejected", "succeeded", "failed", "cancelled", "uncertain"}
)
GOAL_STATUSES = frozenset(
    {
        "active",
        "paused",
        "needs_input",
        "budget_limited",
        "completed",
        "failed",
        "cancelled",
    }
)


class ControlProtocolError(ValueError):
    """Raised when a public agent-control contract is invalid."""


def validate_agent_system_manifest(value: object) -> Mapping[str, object]:
    """Validate one closed, canonical and authority-free system manifest."""

    manifest = _closed_mapping(value, AGENT_SYSTEM_FIELDS, "agent system")
    _require_protocol(manifest, AGENT_SYSTEM_PROTOCOL, "agent system")
    _require_identifier(manifest.get("system_id"), "agent system identity")
    _require_version(manifest.get("version"), "agent system version")

    control_plane = _closed_mapping(
        manifest.get("control_plane"),
        CONTROL_PLANE_REF_FIELDS,
        "agent system control plane",
    )
    _require_identifier(
        control_plane.get("control_plane_id"),
        "agent system control plane identity",
    )
    _require_version(
        control_plane.get("version"),
        "agent system control plane version",
    )

    applications = manifest.get("applications")
    if not isinstance(applications, list) or not applications:
        raise ControlProtocolError("agent system application portfolio is invalid")
    application_refs = tuple(
        _validate_application_ref(item) for item in applications
    )
    identities = tuple(
        (
            str(item["provider_id"]),
            str(item["application_id"]),
            str(item["version"]),
            str(item["runtime_id"]),
        )
        for item in application_refs
    )
    if identities != tuple(sorted(set(identities))):
        raise ControlProtocolError(
            "agent system application portfolio must be sorted and unique"
        )

    for field in ("policies", "host_capabilities", "control_capabilities"):
        _require_sorted_identifiers(manifest.get(field), f"agent system {field}")

    return _freeze_mapping(manifest)


def validate_control_plane_manifest(value: object) -> Mapping[str, object]:
    """Validate one closed, canonical provider compatibility manifest."""

    manifest = _closed_mapping(value, CONTROL_PLANE_FIELDS, "control plane")
    _require_protocol(manifest, CONTROL_PLANE_PROTOCOL, "control plane")
    _require_identifier(manifest.get("control_plane_id"), "control plane identity")
    _require_version(manifest.get("version"), "control plane version")
    _require_supported_types(
        manifest.get("commands"),
        CONTROL_COMMAND_TYPES,
        "control plane commands",
    )
    _require_supported_types(
        manifest.get("events"),
        CONTROL_EVENT_TYPES,
        "control plane events",
    )
    _require_sorted_identifiers(
        manifest.get("capabilities"), "control plane capabilities"
    )
    media_type = manifest.get("continuation_media_type")
    if not isinstance(media_type, str) or MEDIA_TYPE.fullmatch(media_type) is None:
        raise ControlProtocolError(
            "control plane continuation media type is invalid"
        )
    _require_version(
        manifest.get("checkpoint_version"), "control plane checkpoint version"
    )
    compatibility_ids = manifest.get("compatibility_ids")
    if (
        not isinstance(compatibility_ids, list)
        or not compatibility_ids
        or any(
            not isinstance(item, str)
            or COMPATIBILITY_ID.fullmatch(item) is None
            for item in compatibility_ids
        )
        or not is_sorted_unique_scalar_strings(compatibility_ids)
    ):
        raise ControlProtocolError(
            "control plane compatibility identities must be sorted and unique"
        )
    return _freeze_mapping(manifest)


def validate_control_command(value: object) -> Mapping[str, object]:
    """Validate one closed host-to-provider command and return a snapshot."""

    command = _closed_mapping(value, CONTROL_COMMAND_FIELDS, "control command")
    _require_protocol(command, AGENT_CONTROL_PROTOCOL, "control command")
    _require_opaque_id(command.get("command_id"), "control command identity")
    _require_opaque_id(command.get("session_id"), "control command session")
    _require_positive_integer(
        command.get("authority_revision"), "control command authority revision"
    )
    command_type = command.get("type")
    if not isinstance(command_type, str) or command_type not in CONTROL_COMMAND_TYPES:
        raise ControlProtocolError("control command type is invalid")
    payload = command.get("payload")
    _validate_command_payload(command_type, payload)
    return _freeze_mapping(command)


def validate_control_event(value: object) -> Mapping[str, object]:
    """Validate one closed provider-to-host event and return a snapshot."""

    event = _closed_mapping(value, CONTROL_EVENT_FIELDS, "control event")
    _require_protocol(event, AGENT_CONTROL_PROTOCOL, "control event")
    _require_opaque_id(event.get("event_id"), "control event identity")
    _require_opaque_id(event.get("session_id"), "control event session")
    _require_positive_integer(event.get("generation"), "control event generation")
    _require_positive_integer(event.get("sequence"), "control event sequence")
    _require_utc_timestamp(event.get("emitted_at"))
    event_type = event.get("type")
    if not isinstance(event_type, str) or event_type not in CONTROL_EVENT_TYPES:
        raise ControlProtocolError("control event type is invalid")
    _validate_event_payload(event_type, event.get("payload"))
    return _freeze_mapping(event)


def validate_control_event_stream(
    events: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    """Validate one complete generation with exactly one final terminal event."""

    if (
        not isinstance(events, Sequence)
        or isinstance(events, (str, bytes, bytearray))
        or not events
    ):
        raise ControlProtocolError("control event stream is invalid")
    snapshots = tuple(validate_control_event(event) for event in events)
    session_ids = {event["session_id"] for event in snapshots}
    generations = {event["generation"] for event in snapshots}
    event_ids = [event["event_id"] for event in snapshots]
    sequences = [event["sequence"] for event in snapshots]
    if len(session_ids) != 1 or len(generations) != 1:
        raise ControlProtocolError("control event stream identity is invalid")
    if len(set(event_ids)) != len(event_ids):
        raise ControlProtocolError("control event stream event identities are invalid")
    if sequences != list(range(1, len(snapshots) + 1)):
        raise ControlProtocolError("control event stream sequence is not contiguous")
    terminals = [
        index
        for index, event in enumerate(snapshots)
        if event["type"] in TERMINAL_CONTROL_EVENT_TYPES
    ]
    if terminals != [len(snapshots) - 1]:
        raise ControlProtocolError("control event stream terminal event is invalid")
    return snapshots


def _validate_command_payload(command_type: str, value: object) -> None:
    if command_type == "session.create":
        payload = _closed_mapping(
            value,
            {"system_id", "system_version", "goal_id", "goal_ref"},
            "session create payload",
        )
        _require_identifier(payload.get("system_id"), "session create system")
        _require_version(payload.get("system_version"), "session create version")
        _require_opaque_id(payload.get("goal_id"), "session create goal")
        _require_opaque_id(payload.get("goal_ref"), "session create goal reference")
        return
    if command_type == "session.attach":
        payload = _closed_mapping(value, {"cursor"}, "session attach payload")
        cursor = _closed_mapping(
            payload.get("cursor"), {"generation", "sequence"}, "event cursor"
        )
        _require_positive_integer(cursor.get("generation"), "event cursor generation")
        _require_nonnegative_integer(cursor.get("sequence"), "event cursor sequence")
        return
    if command_type == "input.submit":
        payload = _closed_mapping(
            value,
            {"input_id", "delivery", "content_ref"},
            "input submit payload",
        )
        _require_opaque_id(payload.get("input_id"), "input submit identity")
        if payload.get("delivery") not in {"direct", "steer", "follow_up"}:
            raise ControlProtocolError("input submit delivery is invalid")
        _require_opaque_id(payload.get("content_ref"), "input submit content reference")
        return
    if command_type in {
        "session.detach",
        "session.pause",
        "session.resume",
        "session.cancel",
    }:
        payload = _closed_mapping(value, {"reason_code"}, f"{command_type} payload")
        _require_identifier(payload.get("reason_code"), f"{command_type} reason")
        return
    if command_type == "checkpoint.request":
        payload = _closed_mapping(
            value, {"checkpoint_id"}, "checkpoint request payload"
        )
        _require_opaque_id(
            payload.get("checkpoint_id"), "checkpoint request identity"
        )
        return
    if command_type == "action.resolve":
        payload = _closed_mapping(
            value,
            {"action_id", "resolution", "reason_code", "receipt_ref"},
            "action resolution payload",
        )
        _require_opaque_id(payload.get("action_id"), "action resolution identity")
        resolution = payload.get("resolution")
        if resolution not in ACTION_RESOLUTIONS:
            raise ControlProtocolError("action resolution status is invalid")
        _require_identifier(payload.get("reason_code"), "action resolution reason")
        receipt_ref = payload.get("receipt_ref")
        if receipt_ref is not None:
            _require_opaque_id(receipt_ref, "action resolution receipt")
        if resolution == "succeeded" and receipt_ref is None:
            raise ControlProtocolError("succeeded action resolution receipt is missing")
        if resolution in {"admitted", "rejected"} and receipt_ref is not None:
            raise ControlProtocolError("action admission resolution receipt is invalid")
        return
    raise ControlProtocolError("control command type is invalid")


def _validate_event_payload(event_type: str, value: object) -> None:
    if event_type == "session.created":
        payload = _closed_mapping(
            value,
            {"goal_id", "authority_id", "authority_revision"},
            "session created payload",
        )
        _require_opaque_id(payload.get("goal_id"), "session created goal")
        _require_opaque_id(payload.get("authority_id"), "session created authority")
        _require_positive_integer(
            payload.get("authority_revision"), "session created authority revision"
        )
        return
    if event_type in {
        "session.running",
        "session.paused",
        "session.recovery-required",
        "session.completed",
        "session.failed",
        "session.cancelled",
        "session.budget-limited",
    }:
        payload = _closed_mapping(value, {"reason_code"}, f"{event_type} payload")
        _require_identifier(payload.get("reason_code"), f"{event_type} reason")
        return
    if event_type == "goal.updated":
        payload = _closed_mapping(
            value, {"goal_id", "status"}, "goal updated payload"
        )
        _require_opaque_id(payload.get("goal_id"), "goal updated identity")
        if payload.get("status") not in GOAL_STATUSES:
            raise ControlProtocolError("goal updated status is invalid")
        return
    if event_type == "action.proposed":
        _validate_action_proposal(value)
        return
    if event_type == "checkpoint.created":
        payload = _closed_mapping(
            value,
            {
                "checkpoint_id",
                "capsule_id",
                "capsule_digest",
                "control_plane_id",
                "control_plane_version",
                "checkpoint_version",
                "covered_sequence",
                "storage_ref",
            },
            "checkpoint created payload",
        )
        for field in ("checkpoint_id", "capsule_id", "storage_ref"):
            _require_opaque_id(payload.get(field), f"checkpoint created {field}")
        _require_sha256(payload.get("capsule_digest"), "checkpoint capsule digest")
        _require_identifier(
            payload.get("control_plane_id"), "checkpoint control plane identity"
        )
        _require_version(
            payload.get("control_plane_version"), "checkpoint control plane version"
        )
        _require_version(
            payload.get("checkpoint_version"), "checkpoint format version"
        )
        _require_positive_integer(
            payload.get("covered_sequence"), "checkpoint covered sequence"
        )
        return
    if event_type == "budget.reported":
        _validate_usage(value, "budget reported payload")
        return
    if event_type == "fault.raised":
        payload = _closed_mapping(
            value, {"code", "recoverable", "evidence_ref"}, "fault payload"
        )
        _require_identifier(payload.get("code"), "fault code")
        if not isinstance(payload.get("recoverable"), bool):
            raise ControlProtocolError("fault recoverable flag is invalid")
        evidence_ref = payload.get("evidence_ref")
        if evidence_ref is not None:
            _require_opaque_id(evidence_ref, "fault evidence reference")
        return
    raise ControlProtocolError("control event type is invalid")


def _validate_action_proposal(value: object) -> None:
    payload = _closed_mapping(
        value,
        {
            "action_id",
            "authority_revision",
            "idempotency_key",
            "kind",
            "target",
            "input_ref",
            "expected_artifacts",
            "budget",
            "causal_parent_ids",
        },
        "action proposal payload",
    )
    _require_opaque_id(payload.get("action_id"), "action proposal identity")
    _require_positive_integer(
        payload.get("authority_revision"), "action proposal authority revision"
    )
    _require_opaque_id(
        payload.get("idempotency_key"), "action proposal idempotency key"
    )
    action_kind = payload.get("kind")
    if not isinstance(action_kind, str) or action_kind not in ACTION_KINDS:
        raise ControlProtocolError("action proposal kind is invalid")
    target_kind = _validate_action_target(payload.get("target"))
    if target_kind != ACTION_TARGET_KINDS[action_kind]:
        raise ControlProtocolError("action proposal target does not match kind")
    _require_opaque_id(payload.get("input_ref"), "action proposal input reference")
    _require_sorted_identifiers(
        payload.get("expected_artifacts"), "action proposal expected artifacts"
    )
    _validate_budget(payload.get("budget"))
    _require_sorted_opaque_ids(
        payload.get("causal_parent_ids"), "action proposal causal parents"
    )


def _validate_action_target(value: object) -> str:
    if not isinstance(value, Mapping) or not isinstance(value.get("kind"), str):
        raise ControlProtocolError("action proposal target is invalid")
    kind = value["kind"]
    if kind == "application":
        target = _closed_mapping(
            value,
            {"kind", "provider_id", "application_id", "version", "runtime_id"},
            "application action target",
        )
        for field in ("provider_id", "application_id", "runtime_id"):
            _require_identifier(target.get(field), f"application target {field}")
        _require_version(target.get("version"), "application target version")
        return kind
    target_fields = {
        "child": "child_id",
        "checkpoint": "checkpoint_id",
        "goal": "goal_id",
        "input": "request_id",
        "session": "session_id",
    }
    identity_field = target_fields.get(kind)
    if identity_field is None:
        raise ControlProtocolError("action proposal target kind is invalid")
    target = _closed_mapping(value, {"kind", identity_field}, f"{kind} action target")
    _require_opaque_id(target.get(identity_field), f"{kind} action target identity")
    return kind


def _validate_budget(value: object) -> None:
    budget = _closed_mapping(
        value,
        {
            "controller_tokens",
            "application_tokens",
            "child_tokens",
            "aggregate_tokens",
            "cost_micros",
            "deadline_ms",
        },
        "action proposal budget",
    )
    for field in (
        "controller_tokens",
        "application_tokens",
        "child_tokens",
        "aggregate_tokens",
        "cost_micros",
    ):
        _require_nonnegative_integer(budget.get(field), f"action budget {field}")
    _require_positive_integer(budget.get("deadline_ms"), "action budget deadline")


def _validate_usage(value: object, label: str) -> None:
    usage = _closed_mapping(
        value,
        {
            "controller_tokens",
            "application_tokens",
            "child_tokens",
            "aggregate_tokens",
            "cost_micros",
        },
        label,
    )
    for field in usage:
        _require_nonnegative_integer(usage[field], f"{label} {field}")


def _validate_application_ref(value: object) -> Mapping[str, object]:
    reference = _closed_mapping(
        value, APPLICATION_REF_FIELDS, "agent system application reference"
    )
    for field in ("provider_id", "application_id", "runtime_id"):
        _require_identifier(
            reference.get(field), f"agent system application {field}"
        )
    _require_version(
        reference.get("version"), "agent system application version"
    )
    return reference


def _closed_mapping(
    value: object, fields: set[str], label: str
) -> Mapping[str, object]:
    if (
        not isinstance(value, Mapping)
        or not all(isinstance(key, str) for key in value)
        or set(value) != fields
    ):
        raise ControlProtocolError(f"{label} fields are invalid")
    return value


def _require_protocol(
    value: Mapping[str, object], expected: str, label: str
) -> None:
    if value.get("protocol") != expected:
        raise ControlProtocolError(f"{label} protocol is invalid")


def _require_identifier(value: object, label: str) -> None:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise ControlProtocolError(f"{label} is invalid")


def _require_version(value: object, label: str) -> None:
    if not isinstance(value, str) or SEMANTIC_VERSION.fullmatch(value) is None:
        raise ControlProtocolError(f"{label} is invalid")


def _require_opaque_id(value: object, label: str) -> None:
    if not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None:
        raise ControlProtocolError(f"{label} is invalid")


def _require_nonnegative_integer(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ControlProtocolError(f"{label} is invalid")


def _require_positive_integer(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ControlProtocolError(f"{label} is invalid")


def _require_utc_timestamp(value: object) -> None:
    if not isinstance(value, str) or UTC_TIMESTAMP.fullmatch(value) is None:
        raise ControlProtocolError("control event timestamp is invalid")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ControlProtocolError("control event timestamp is invalid") from None


def _require_sha256(value: object, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ControlProtocolError(f"{label} is invalid")


def _require_sorted_identifiers(value: object, label: str) -> None:
    if (
        not isinstance(value, list)
        or any(
            not isinstance(item, str) or IDENTIFIER.fullmatch(item) is None
            for item in value
        )
        or not is_sorted_unique_scalar_strings(value)
    ):
        raise ControlProtocolError(f"{label} must be sorted unique identifiers")


def _require_sorted_opaque_ids(value: object, label: str) -> None:
    if (
        not isinstance(value, list)
        or any(
            not isinstance(item, str) or OPAQUE_ID.fullmatch(item) is None
            for item in value
        )
        or not is_sorted_unique_scalar_strings(value)
    ):
        raise ControlProtocolError(f"{label} must be sorted and unique")


def _require_supported_types(
    value: object, supported: frozenset[str], label: str
) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or item not in supported for item in value)
        or not is_sorted_unique_scalar_strings(value)
    ):
        raise ControlProtocolError(f"{label} are invalid")


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze(item) for key, item in value.items()})


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(_freeze(item) for item in value)
    return value
