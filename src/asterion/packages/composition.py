"""Deterministic static composition for portable framework packages."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass

from asterion.packages.protocol import validate_package_manifest


class PackageCompositionError(ValueError):
    """Raised when portable packages cannot form one valid static graph."""


@dataclass(frozen=True)
class PackageComposition:
    package_ids: tuple[str, ...]
    provided_capabilities: tuple[str, ...]
    emitted_events: tuple[str, ...]
    produced_artifacts: tuple[str, ...]


def compose_packages(
    manifests: Iterable[Mapping[str, object]],
    *,
    host_capabilities: Set[str] = frozenset(),
    host_policies: Set[str] = frozenset(),
    host_events: Set[str] = frozenset(),
    host_artifacts: Set[str] = frozenset(),
) -> PackageComposition:
    """Validate and topologically order a portable package graph."""

    packages: dict[str, Mapping[str, object]] = {}
    for manifest in manifests:
        validate_package_manifest(manifest)
        package_id = manifest["package_id"]
        assert isinstance(package_id, str)
        if package_id in packages:
            raise PackageCompositionError("package IDs must be unique")
        packages[package_id] = manifest

    capability_providers: dict[str, str] = {}
    policy_providers: dict[str, str] = {}
    event_providers: dict[str, str] = {}
    artifact_providers: dict[str, str] = {}
    for package_id, manifest in packages.items():
        if manifest["kind"] == "policy":
            _bind_provider(
                policy_providers,
                package_id,
                package_id,
                label="policy",
            )
        for capability in _edges(manifest, "provides_capabilities"):
            _bind_provider(
                capability_providers,
                capability,
                package_id,
                label="capability",
            )
        for event in _edges(manifest, "emits_events"):
            _bind_provider(event_providers, event, package_id, label="event")
        for artifact in _edges(manifest, "produces_artifacts"):
            _bind_provider(artifact_providers, artifact, package_id, label="artifact")

    for providers, host_edges, label in (
        (capability_providers, host_capabilities, "capability"),
        (policy_providers, host_policies, "policy"),
        (event_providers, host_events, "event"),
        (artifact_providers, host_artifacts, "artifact"),
    ):
        if providers.keys() & host_edges:
            raise PackageCompositionError(f"{label} provider is ambiguous")

    dependencies: dict[str, set[str]] = {package_id: set() for package_id in packages}
    for package_id, manifest in packages.items():
        for capability in _edges(manifest, "requires_capabilities"):
            if capability in host_capabilities:
                continue
            provider = capability_providers.get(capability)
            if provider is None:
                raise PackageCompositionError("required capability is unavailable")
            dependencies[package_id].add(provider)
        for policy in _edges(manifest, "requires_policies"):
            if policy in host_policies:
                continue
            provider = policy_providers.get(policy)
            if provider is None:
                raise PackageCompositionError("required policy is unavailable")
            dependencies[package_id].add(provider)
        _add_provider_dependencies(
            dependencies[package_id],
            _edges(manifest, "consumes_events"),
            host_events,
            event_providers,
            "required event is unavailable",
        )
        _add_provider_dependencies(
            dependencies[package_id],
            _edges(manifest, "consumes_artifacts"),
            host_artifacts,
            artifact_providers,
            "required artifact is unavailable",
        )
        dependencies[package_id].discard(package_id)

    ordered: list[str] = []
    remaining = {package_id: set(values) for package_id, values in dependencies.items()}
    while remaining:
        ready = sorted(
            package_id for package_id, required in remaining.items() if not required
        )
        if not ready:
            raise PackageCompositionError("package dependency graph contains a cycle")
        for package_id in ready:
            ordered.append(package_id)
            remaining.pop(package_id)
        for required in remaining.values():
            required.difference_update(ready)

    return PackageComposition(
        package_ids=tuple(ordered),
        provided_capabilities=tuple(sorted(capability_providers)),
        emitted_events=tuple(sorted(event_providers)),
        produced_artifacts=tuple(sorted(artifact_providers)),
    )


def _edges(manifest: Mapping[str, object], field: str) -> list[str]:
    values = manifest[field]
    assert isinstance(values, list) and all(isinstance(value, str) for value in values)
    return values


def _bind_provider(
    providers: dict[str, str],
    edge: str,
    package_id: str,
    *,
    label: str,
) -> None:
    if edge in providers:
        raise PackageCompositionError(f"{label} provider is ambiguous")
    providers[edge] = package_id


def _add_provider_dependencies(
    dependencies: set[str],
    required_edges: Iterable[str],
    host_edges: Set[str],
    providers: Mapping[str, str],
    error: str,
) -> None:
    for edge in required_edges:
        if edge in host_edges:
            continue
        provider = providers.get(edge)
        if provider is None:
            raise PackageCompositionError(error)
        dependencies.add(provider)
