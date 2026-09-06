"""Public Python host contract for Agent Runtime Protocol v1."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from asterion.runtime.protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    _validate_event,
    validate_event_stream,
    validate_run_request,
    validate_runtime_manifest,
)


class _FrozenList(Sequence[object]):
    """An immutable JSON array which retains normal list equality semantics."""

    __slots__ = ("_values",)

    def __init__(self, values: Iterable[object]) -> None:
        self._values = tuple(values)

    def __getitem__(self, index: int | slice) -> object:
        return self._values[index]

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Sequence) and not isinstance(other, (str, bytes)):
            return list(self) == list(other)
        return False

    def __repr__(self) -> str:
        return repr(list(self))


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return _FrozenList(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("JSON value is invalid")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, _FrozenList):
        return [_thaw_json(item) for item in value]
    return value


def _snapshot_capabilities(value: object, *, error: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes)):
        raise ProtocolError(error)
    try:
        return tuple(value)  # type: ignore[arg-type]
    except Exception:
        raise ProtocolError(error) from None


@dataclass(frozen=True)
class RuntimeManifest:
    """Portable runtime identity and capability discovery."""

    runtime_id: str
    capabilities: tuple[str, ...]
    protocol: str = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        capabilities = _snapshot_capabilities(
            self.capabilities, error="runtime manifest capabilities are invalid"
        )
        object.__setattr__(self, "capabilities", capabilities)
        validate_runtime_manifest(self.to_mapping())

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

    def __post_init__(self) -> None:
        requested_capabilities = _snapshot_capabilities(
            self.requested_capabilities, error="requested capabilities are invalid"
        )
        object.__setattr__(self, "requested_capabilities", requested_capabilities)
        validate_run_request(self.to_mapping())

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

    def __post_init__(self) -> None:
        frozen_payload = _freeze_json(self.payload)
        if not isinstance(frozen_payload, Mapping):
            raise TypeError("event payload must be a mapping")
        object.__setattr__(self, "payload", frozen_payload)
        _validate_event(self.to_mapping())

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> RunEvent:
        payload = value["payload"]
        if not isinstance(payload, Mapping):
            raise TypeError("event payload must be a mapping")
        return cls(
            protocol=value["protocol"],  # type: ignore[arg-type]
            run_id=value["run_id"],  # type: ignore[arg-type]
            sequence=value["sequence"],  # type: ignore[arg-type]
            type=value["type"],  # type: ignore[arg-type]
            payload=payload,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "protocol": self.protocol,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "type": self.type,
            "payload": _thaw_json(self.payload),
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
