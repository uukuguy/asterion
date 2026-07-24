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
    event_providers: dict[str, set[str]] = {}
    artifact_providers: dict[str, set[str]] = {}
    policy_providers = {
        package_id
        for package_id, manifest in packages.items()
        if manifest["kind"] == "policy"
    }
    for package_id, manifest in packages.items():
        for capability in _edges(manifest, "provides_capabilities"):
            if capability in capability_providers:
                raise PackageCompositionError("capability provider is ambiguous")
            capability_providers[capability] = package_id
        for event in _edges(manifest, "emits_events"):
            event_providers.setdefault(event, set()).add(package_id)
        for artifact in _edges(manifest, "produces_artifacts"):
            artifact_providers.setdefault(artifact, set()).add(package_id)

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
            if policy not in policy_providers:
                raise PackageCompositionError("required policy is unavailable")
            dependencies[package_id].add(policy)
        _add_multi_dependencies(
            dependencies[package_id],
            _edges(manifest, "consumes_events"),
            host_events,
            event_providers,
            "required event is unavailable",
        )
        _add_multi_dependencies(
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


def _add_multi_dependencies(
    dependencies: set[str],
    required_edges: Iterable[str],
    host_edges: Set[str],
    providers: Mapping[str, set[str]],
    error: str,
) -> None:
    for edge in required_edges:
        if edge in host_edges:
            continue
        edge_providers = providers.get(edge)
        if not edge_providers:
            raise PackageCompositionError(error)
        dependencies.update(edge_providers)
