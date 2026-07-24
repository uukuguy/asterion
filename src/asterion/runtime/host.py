"""Public Python host contract for Agent Runtime Protocol v1."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from asterion.runtime.protocol import (
    PROTOCOL_VERSION,
    validate_event_stream,
    validate_run_request,
    validate_runtime_manifest,
)


@dataclass(frozen=True)
class RuntimeManifest:
    """Portable runtime identity and capability discovery."""

    runtime_id: str
    capabilities: tuple[str, ...]
    protocol: str = PROTOCOL_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> RuntimeManifest:
        validate_runtime_manifest(value)
        return cls(
            protocol=str(value["protocol"]),
            runtime_id=str(value["runtime_id"]),
            capabilities=tuple(value["capabilities"]),  # type: ignore[arg-type]
        )

    def to_mapping(self) -> dict[str, object]:
        value: dict[str, object] = {
            "protocol": self.protocol,
            "runtime_id": self.runtime_id,
            "capabilities": list(self.capabilities),
        }
        validate_runtime_manifest(value)
        return value


@dataclass(frozen=True)
class RunRequest:
    """Host-native value for one protocol run request."""

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
        validate_run_request(value)
        return value


@dataclass(frozen=True)
class RunEvent:
    """Host-native value for one normalized protocol event."""

    run_id: str
    sequence: int
    type: str
    payload: Mapping[str, object]
    protocol: str = PROTOCOL_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> RunEvent:
        payload = value["payload"]
        if not isinstance(payload, Mapping):
            raise TypeError("event payload must be a mapping")
        return cls(
            protocol=str(value["protocol"]),
            run_id=str(value["run_id"]),
            sequence=int(value["sequence"]),
            type=str(value["type"]),
            payload=dict(payload),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "protocol": self.protocol,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "type": self.type,
            "payload": dict(self.payload),
        }


def parse_event_stream(events: Iterable[Mapping[str, object]]) -> tuple[RunEvent, ...]:
    """Validate and parse one complete event stream into public values."""

    event_list = list(events)
    validate_event_stream(event_list)
    return tuple(RunEvent.from_mapping(event) for event in event_list)


class AgentRuntimeClient(Protocol):
    """Adapter-neutral asynchronous runtime client implemented by host bridges."""

    @property
    def manifest(self) -> RuntimeManifest: ...

    def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AsyncIterator[RunEvent]: ...


class CancellationSignal(Protocol):
    """Read-only cancellation state owned by the runtime caller."""

    @property
    def cancelled(self) -> bool: ...
