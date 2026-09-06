"""Executable capability values and exact implementation binding."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePath
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from asterion.capabilities.catalog import CapabilityRef
from asterion.runtime.host import AgentRuntimeClient, CancellationSignal

if TYPE_CHECKING:
    from asterion.assembly.protocol import AssemblyPlan


EXECUTABLE_CAPABILITY_KINDS = frozenset(
    {
        "capability",
        "workflow",
        "memory",
        "observability",
        "evaluation",
        "research",
    }
)


class CapabilityExecutionError(RuntimeError):
    """Raised when a capability cannot execute through its declared boundary."""


class InProcessArtifactPayload:
    """Deeply immutable private stage data with one explicit safe projection."""

    __slots__ = ("_private_value", "_public_projection")

    def __init__(
        self,
        *,
        private_value: Mapping[str, object],
        public_projection: Mapping[str, object],
    ) -> None:
        if not isinstance(private_value, Mapping) or not isinstance(
            public_projection, Mapping
        ):
            raise CapabilityExecutionError("private artifact payload is invalid")
        try:
            frozen_private = _freeze_private_mapping(private_value)
            projected = project_public_value(public_projection)
            if not isinstance(projected, dict):
                raise TypeError
            frozen_public = _freeze_mapping(projected)
        except CapabilityExecutionError:
            raise
        except Exception:
            raise CapabilityExecutionError("private artifact payload is invalid") from None
        object.__setattr__(self, "_private_value", frozen_private)
        object.__setattr__(self, "_public_projection", frozen_public)

    @property
    def private_value(self) -> Mapping[str, object]:
        return self._private_value

    @property
    def public_projection(self) -> Mapping[str, object]:
        return self._public_projection

    def __repr__(self) -> str:
        return "<in-process private artifact payload>"

    __str__ = __repr__

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("private artifact payload is immutable")


@dataclass(frozen=True)
class CapabilityInvocation:
    capability_ref: CapabilityRef
    manifest: Mapping[str, object]
    run_id: str
    input_text: str
    upstream_artifacts: tuple[Mapping[str, object], ...]
    runtime: AgentRuntimeClient
    host_services: Mapping[str, object]
    upstream_events: tuple[Mapping[str, object], ...] = ()
    host_events: tuple[Mapping[str, object], ...] = ()
    host_artifacts: tuple[Mapping[str, object], ...] = ()
    signal: CancellationSignal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest", _freeze_mapping(self.manifest))
        object.__setattr__(
            self,
            "upstream_events",
            tuple(_freeze_mapping(event) for event in self.upstream_events),
        )
        object.__setattr__(
            self,
            "upstream_artifacts",
            tuple(_freeze_mapping(artifact) for artifact in self.upstream_artifacts),
        )
        object.__setattr__(
            self,
            "host_events",
            tuple(_freeze_mapping(event) for event in self.host_events),
        )
        object.__setattr__(
            self,
            "host_artifacts",
            tuple(_freeze_mapping(artifact) for artifact in self.host_artifacts),
        )
        object.__setattr__(
            self, "host_services", MappingProxyType(dict(self.host_services))
        )


@dataclass(frozen=True)
class CapabilityExecutionResult:
    events: tuple[Mapping[str, object], ...]
    artifacts: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "events", tuple(_freeze_mapping(event) for event in self.events)
        )
        object.__setattr__(
            self,
            "artifacts",
            tuple(_freeze_mapping(artifact) for artifact in self.artifacts),
        )


class CapabilityImplementation(Protocol):
    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult: ...


@dataclass(frozen=True, slots=True)
class CapabilityImplementationBinding:
    capability_ref: CapabilityRef
    implementation: CapabilityImplementation = field(repr=False)


def validate_implementation_bindings(
    plan: AssemblyPlan,
    bindings: Iterable[tuple[CapabilityRef, CapabilityImplementation]],
) -> Mapping[CapabilityRef, CapabilityImplementation]:
    """Return complete exact bindings for every executable capability."""

    resolved: dict[CapabilityRef, CapabilityImplementation] = {}
    for ref, implementation in bindings:
        try:
            execute = getattr(implementation, "execute")
        except Exception:
            raise CapabilityExecutionError(
                "capability implementation binding is invalid"
            ) from None
        if not callable(execute):
            raise CapabilityExecutionError(
                "capability implementation binding is invalid"
            )
        if ref in resolved:
            raise CapabilityExecutionError("capability implementation binding is duplicated")
        resolved[ref] = implementation

    expected = {
        CapabilityRef(str(manifest["capability_id"]), str(manifest["version"]))
        for manifest in plan.capability_manifests
        if manifest["kind"] in EXECUTABLE_CAPABILITY_KINDS
    }
    if set(resolved) - expected:
        raise CapabilityExecutionError("capability implementation binding is unknown")
    if expected - set(resolved):
        raise CapabilityExecutionError("capability implementation binding is missing")
    return MappingProxyType(resolved)


def validate_capability_result(
    manifest: Mapping[str, object], result: CapabilityExecutionResult
) -> None:
    """Validate one implementation result against its portable declarations."""

    declared_events = _string_tuple(manifest, "emits_events")
    declared_artifacts = _string_tuple(manifest, "produces_artifacts")
    for event in result.events:
        if event.keys() != {"type", "payload"}:
            raise CapabilityExecutionError("capability output event is invalid")
        event_type = event["type"]
        if not isinstance(event_type, str) or event_type not in declared_events:
            raise CapabilityExecutionError("capability output event is undeclared")
        if not isinstance(event["payload"], Mapping):
            raise CapabilityExecutionError("capability output event is invalid")

    artifact_ids: set[str] = set()
    for artifact in result.artifacts:
        if artifact.keys() != {"artifact_id", "media_type", "value"}:
            raise CapabilityExecutionError("capability output artifact is invalid")
        artifact_id = artifact["artifact_id"]
        if (
            not isinstance(artifact_id, str)
            or not artifact_id
            or artifact_id in artifact_ids
        ):
            raise CapabilityExecutionError("capability output artifact identity is invalid")
        artifact_ids.add(artifact_id)
        media_type = artifact["media_type"]
        if not isinstance(media_type, str) or media_type not in declared_artifacts:
            raise CapabilityExecutionError("capability output artifact is undeclared")
        if not isinstance(artifact["value"], Mapping):
            raise CapabilityExecutionError("capability output artifact is invalid")


def _string_tuple(manifest: Mapping[str, object], field: str) -> tuple[str, ...]:
    values = manifest[field]
    if not isinstance(values, tuple) or not all(
        isinstance(value, str) for value in values
    ):
        raise CapabilityExecutionError("capability declaration is invalid")
    return values


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze(item) for key, item in value.items()})


def _freeze(value: object) -> object:
    if isinstance(value, InProcessArtifactPayload):
        return value
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _freeze_private_mapping(
    value: Mapping[str, object],
) -> Mapping[str, object]:
    if not all(type(key) is str for key in value):
        raise TypeError
    return MappingProxyType(
        {key: _freeze_private(item) for key, item in value.items()}
    )


def _freeze_private(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_private_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_private(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_private(item) for item in value)
    if value is None or type(value) in {str, bool, int, float, bytes}:
        return value
    if isinstance(value, PurePath):
        return value
    raise TypeError


def project_public_value(value: object) -> object:
    """Return an explicit JSON-safe projection without rendering private values."""

    if isinstance(value, InProcessArtifactPayload):
        return project_public_value(value.public_projection)
    package_projection = _package_owned_public_projection(value)
    if package_projection is not None:
        return project_public_value(package_projection)
    if isinstance(value, Mapping):
        projected: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise CapabilityExecutionError(
                    "artifact public projection is invalid"
                )
            projected[key] = project_public_value(item)
        return projected
    if isinstance(value, (tuple, list)):
        return [project_public_value(item) for item in value]
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise CapabilityExecutionError("artifact public projection is invalid")


def _package_owned_public_projection(value: object) -> Mapping[str, object] | None:
    module_name = type(value).__module__
    if not module_name.startswith("asterion.capabilities."):
        return None
    sentinel = object()
    try:
        projection = getattr(value, "public_projection", sentinel)
    except Exception:
        raise CapabilityExecutionError("artifact public projection is invalid") from None
    if projection is sentinel:
        return None
    if not isinstance(projection, Mapping):
        raise CapabilityExecutionError("artifact public projection is invalid")
    return projection
