"""Public host-side values for the neutral long-running control protocol."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Protocol

from asterion.control.protocol import (
    AGENT_CONTROL_PROTOCOL,
    CONTROL_PLANE_PROTOCOL,
    validate_control_command,
    validate_control_event,
    validate_control_plane_manifest,
)


@dataclass(frozen=True)
class ControlPlaneManifest:
    """Portable compatibility declaration for one control provider."""

    control_plane_id: str
    version: str
    commands: tuple[str, ...]
    events: tuple[str, ...]
    capabilities: tuple[str, ...]
    continuation_media_type: str
    checkpoint_version: str
    compatibility_ids: tuple[str, ...]
    protocol: str = CONTROL_PLANE_PROTOCOL

    def __post_init__(self) -> None:
        snapshot = validate_control_plane_manifest(self._mapping())
        object.__setattr__(self, "commands", tuple(snapshot["commands"]))
        object.__setattr__(self, "events", tuple(snapshot["events"]))
        object.__setattr__(self, "capabilities", tuple(snapshot["capabilities"]))
        object.__setattr__(
            self, "compatibility_ids", tuple(snapshot["compatibility_ids"])
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ControlPlaneManifest:
        snapshot = validate_control_plane_manifest(value)
        return cls(
            protocol=str(snapshot["protocol"]),
            control_plane_id=str(snapshot["control_plane_id"]),
            version=str(snapshot["version"]),
            commands=tuple(snapshot["commands"]),
            events=tuple(snapshot["events"]),
            capabilities=tuple(snapshot["capabilities"]),
            continuation_media_type=str(snapshot["continuation_media_type"]),
            checkpoint_version=str(snapshot["checkpoint_version"]),
            compatibility_ids=tuple(snapshot["compatibility_ids"]),
        )

    def _mapping(self) -> dict[str, object]:
        return {
            "protocol": self.protocol,
            "control_plane_id": self.control_plane_id,
            "version": self.version,
            "commands": list(self.commands),
            "events": list(self.events),
            "capabilities": list(self.capabilities),
            "continuation_media_type": self.continuation_media_type,
            "checkpoint_version": self.checkpoint_version,
            "compatibility_ids": list(self.compatibility_ids),
        }

    def to_mapping(self) -> Mapping[str, object]:
        value = self._mapping()
        validate_control_plane_manifest(value)
        return value


@dataclass(frozen=True)
class ControlCommand:
    """Immutable host-native representation of one validated command."""

    command_id: str
    session_id: str
    authority_revision: int
    type: str
    payload: Mapping[str, object]
    protocol: str = AGENT_CONTROL_PROTOCOL

    def __post_init__(self) -> None:
        snapshot = validate_control_command(self._mapping())
        payload = snapshot["payload"]
        assert isinstance(payload, Mapping)
        object.__setattr__(self, "payload", payload)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ControlCommand:
        snapshot = validate_control_command(value)
        payload = snapshot["payload"]
        assert isinstance(payload, Mapping)
        return cls(
            protocol=str(snapshot["protocol"]),
            command_id=str(snapshot["command_id"]),
            session_id=str(snapshot["session_id"]),
            authority_revision=int(snapshot["authority_revision"]),
            type=str(snapshot["type"]),
            payload=payload,
        )

    def _mapping(self) -> dict[str, object]:
        return {
            "protocol": self.protocol,
            "command_id": self.command_id,
            "session_id": self.session_id,
            "authority_revision": self.authority_revision,
            "type": self.type,
            "payload": _to_json_value(self.payload),
        }

    def to_mapping(self) -> Mapping[str, object]:
        value = self._mapping()
        validate_control_command(value)
        return value


@dataclass(frozen=True)
class ControlEvent:
    """Immutable host-native representation of one validated control event."""

    event_id: str
    session_id: str
    generation: int
    sequence: int
    emitted_at: str
    type: str
    payload: Mapping[str, object]
    protocol: str = AGENT_CONTROL_PROTOCOL

    def __post_init__(self) -> None:
        snapshot = validate_control_event(self._mapping())
        payload = snapshot["payload"]
        assert isinstance(payload, Mapping)
        object.__setattr__(self, "payload", payload)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ControlEvent:
        snapshot = validate_control_event(value)
        payload = snapshot["payload"]
        assert isinstance(payload, Mapping)
        return cls(
            protocol=str(snapshot["protocol"]),
            event_id=str(snapshot["event_id"]),
            session_id=str(snapshot["session_id"]),
            generation=int(snapshot["generation"]),
            sequence=int(snapshot["sequence"]),
            emitted_at=str(snapshot["emitted_at"]),
            type=str(snapshot["type"]),
            payload=payload,
        )

    def _mapping(self) -> dict[str, object]:
        return {
            "protocol": self.protocol,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "generation": self.generation,
            "sequence": self.sequence,
            "emitted_at": self.emitted_at,
            "type": self.type,
            "payload": _to_json_value(self.payload),
        }

    def to_mapping(self) -> Mapping[str, object]:
        value = self._mapping()
        validate_control_event(value)
        return value


@dataclass(frozen=True)
class EventCursor:
    """Exact replay position within one provider session generation."""

    generation: int
    sequence: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation < 1
            or isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise ValueError("control event cursor is invalid")

    def to_mapping(self) -> Mapping[str, int]:
        return {"generation": self.generation, "sequence": self.sequence}


class ControlPlaneClient(Protocol):
    """Adapter-neutral asynchronous long-running control provider."""

    @property
    def manifest(self) -> ControlPlaneManifest:
        """Return the exact compatibility manifest for this client."""

    async def send(self, command: ControlCommand) -> None:
        """Persist and accept one host command idempotently."""

    def events(
        self, cursor: EventCursor | None = None
    ) -> AsyncIterator[ControlEvent]:
        """Yield validated events after an optional exact replay cursor."""

    async def close(self) -> None:
        """Release provider resources without changing canonical state."""


def _to_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_to_json_value(item) for item in value]
    return value
