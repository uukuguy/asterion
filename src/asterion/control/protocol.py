"""Closed static contracts for long-running agent systems and providers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType

from asterion.protocol_ordering import is_sorted_unique_scalar_strings


AGENT_SYSTEM_PROTOCOL = "asterion.agent-system/v1"
CONTROL_PLANE_PROTOCOL = "asterion.control-plane/v1"

IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
SEMANTIC_VERSION = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
MEDIA_TYPE = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$"
)
COMPATIBILITY_ID = re.compile(r"^[a-z][a-z0-9.-]*/v[1-9][0-9]*$")

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
