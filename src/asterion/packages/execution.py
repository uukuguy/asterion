"""Executable package values and exact implementation binding."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from asterion.packages.catalog import PackageRef
from asterion.runtime.host import AgentRuntimeClient, CancellationSignal

if TYPE_CHECKING:
    from asterion.assembly.protocol import AssemblyPlan


EXECUTABLE_PACKAGE_KINDS = frozenset(
    {"capability", "workflow", "memory", "observability", "evaluation"}
)


class PackageExecutionError(RuntimeError):
    """Raised when a package cannot execute through its declared boundary."""


@dataclass(frozen=True)
class PackageInvocation:
    package_ref: PackageRef
    manifest: Mapping[str, object]
    run_id: str
    input_text: str
    upstream_artifacts: tuple[Mapping[str, object], ...]
    runtime: AgentRuntimeClient
    host_services: Mapping[str, object]
    signal: CancellationSignal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest", _freeze_mapping(self.manifest))
        object.__setattr__(
            self,
            "upstream_artifacts",
            tuple(_freeze_mapping(artifact) for artifact in self.upstream_artifacts),
        )
        object.__setattr__(
            self, "host_services", MappingProxyType(dict(self.host_services))
        )


@dataclass(frozen=True)
class PackageExecutionResult:
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


class PackageImplementation(Protocol):
    async def execute(
        self, invocation: PackageInvocation
    ) -> PackageExecutionResult: ...


def validate_implementation_bindings(
    plan: AssemblyPlan,
    bindings: Iterable[tuple[PackageRef, PackageImplementation]],
) -> Mapping[PackageRef, PackageImplementation]:
    """Return complete exact bindings for every executable package."""

    resolved: dict[PackageRef, PackageImplementation] = {}
    for ref, implementation in bindings:
        if ref in resolved:
            raise PackageExecutionError("package implementation binding is duplicated")
        resolved[ref] = implementation

    expected = {
        PackageRef(str(manifest["package_id"]), str(manifest["version"]))
        for manifest in plan.package_manifests
        if manifest["kind"] in EXECUTABLE_PACKAGE_KINDS
    }
    if set(resolved) - expected:
        raise PackageExecutionError("package implementation binding is unknown")
    if expected - set(resolved):
        raise PackageExecutionError("package implementation binding is missing")
    return MappingProxyType(resolved)


def validate_package_result(
    manifest: Mapping[str, object], result: PackageExecutionResult
) -> None:
    """Validate one implementation result against its portable declarations."""

    declared_events = _string_tuple(manifest, "emits_events")
    declared_artifacts = _string_tuple(manifest, "produces_artifacts")
    for event in result.events:
        if event.keys() != {"type", "payload"}:
            raise PackageExecutionError("package output event is invalid")
        event_type = event["type"]
        if not isinstance(event_type, str) or event_type not in declared_events:
            raise PackageExecutionError("package output event is undeclared")
        if not isinstance(event["payload"], Mapping):
            raise PackageExecutionError("package output event is invalid")

    artifact_ids: set[str] = set()
    for artifact in result.artifacts:
        if artifact.keys() != {"artifact_id", "media_type", "value"}:
            raise PackageExecutionError("package output artifact is invalid")
        artifact_id = artifact["artifact_id"]
        if (
            not isinstance(artifact_id, str)
            or not artifact_id
            or artifact_id in artifact_ids
        ):
            raise PackageExecutionError("package output artifact identity is invalid")
        artifact_ids.add(artifact_id)
        media_type = artifact["media_type"]
        if not isinstance(media_type, str) or media_type not in declared_artifacts:
            raise PackageExecutionError("package output artifact is undeclared")
        if not isinstance(artifact["value"], Mapping):
            raise PackageExecutionError("package output artifact is invalid")


def _string_tuple(manifest: Mapping[str, object], field: str) -> tuple[str, ...]:
    values = manifest[field]
    if not isinstance(values, tuple) or not all(
        isinstance(value, str) for value in values
    ):
        raise PackageExecutionError("package declaration is invalid")
    return values


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze(item) for key, item in value.items()})


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value
