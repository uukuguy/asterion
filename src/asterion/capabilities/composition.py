"""Deterministic static composition for portable framework capabilities."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass

from asterion.capabilities.protocol import validate_capability_manifest


class CapabilityCompositionError(ValueError):
    """Raised when portable capabilities cannot form one valid static graph."""


@dataclass(frozen=True, slots=True)
class CapabilityComposition:
    capability_ids: tuple[str, ...]
    provided_capabilities: tuple[str, ...]
    emitted_events: tuple[str, ...]
    produced_artifacts: tuple[str, ...]


def compose_capabilities(
    manifests: Iterable[Mapping[str, object]],
    *,
    host_capabilities: Set[str] = frozenset(),
    host_policies: Set[str] = frozenset(),
    host_events: Set[str] = frozenset(),
    host_artifacts: Set[str] = frozenset(),
) -> CapabilityComposition:
    """Validate and topologically order a portable capability graph."""

    capabilities: dict[str, Mapping[str, object]] = {}
    for value in manifests:
        manifest = validate_capability_manifest(value)
        capability_id = manifest["capability_id"]
        assert isinstance(capability_id, str)
        if capability_id in capabilities:
            raise CapabilityCompositionError("capability IDs must be unique")
        capabilities[capability_id] = manifest

    capability_providers: dict[str, str] = {}
    policy_providers: dict[str, str] = {}
    event_providers: dict[str, str] = {}
    artifact_providers: dict[str, str] = {}
    for capability_id, manifest in capabilities.items():
        if manifest["kind"] == "policy":
            _bind_provider(
                policy_providers,
                capability_id,
                capability_id,
                label="policy",
            )
        for capability in _edges(manifest, "provides_capabilities"):
            _bind_provider(
                capability_providers,
                capability,
                capability_id,
                label="capability",
            )
        for event in _edges(manifest, "emits_events"):
            _bind_provider(event_providers, event, capability_id, label="event")
        for artifact in _edges(manifest, "produces_artifacts"):
            _bind_provider(artifact_providers, artifact, capability_id, label="artifact")

    for providers, host_edges, label in (
        (capability_providers, host_capabilities, "capability"),
        (policy_providers, host_policies, "policy"),
        (event_providers, host_events, "event"),
        (artifact_providers, host_artifacts, "artifact"),
    ):
        if providers.keys() & host_edges:
            raise CapabilityCompositionError(f"{label} provider is ambiguous")

    dependencies: dict[str, set[str]] = {
        capability_id: set() for capability_id in capabilities
    }
    for capability_id, manifest in capabilities.items():
        for capability in _edges(manifest, "requires_capabilities"):
            if capability in host_capabilities:
                continue
            provider = capability_providers.get(capability)
            if provider is None:
                raise CapabilityCompositionError("required capability is unavailable")
            dependencies[capability_id].add(provider)
        for policy in _edges(manifest, "requires_policies"):
            if policy in host_policies:
                continue
            provider = policy_providers.get(policy)
            if provider is None:
                raise CapabilityCompositionError("required policy is unavailable")
            dependencies[capability_id].add(provider)
        _add_provider_dependencies(
            dependencies[capability_id],
            _edges(manifest, "consumes_events"),
            host_events,
            event_providers,
            "required event is unavailable",
        )
        _add_provider_dependencies(
            dependencies[capability_id],
            _edges(manifest, "consumes_artifacts"),
            host_artifacts,
            artifact_providers,
            "required artifact is unavailable",
        )
        dependencies[capability_id].discard(capability_id)

    ordered: list[str] = []
    remaining = {
        capability_id: set(values) for capability_id, values in dependencies.items()
    }
    while remaining:
        ready = sorted(
            capability_id for capability_id, required in remaining.items() if not required
        )
        if not ready:
            raise CapabilityCompositionError("capability dependency graph contains a cycle")
        for capability_id in ready:
            ordered.append(capability_id)
            remaining.pop(capability_id)
        for required in remaining.values():
            required.difference_update(ready)

    return CapabilityComposition(
        capability_ids=tuple(ordered),
        provided_capabilities=tuple(sorted(capability_providers)),
        emitted_events=tuple(sorted(event_providers)),
        produced_artifacts=tuple(sorted(artifact_providers)),
    )


def _edges(manifest: Mapping[str, object], field: str) -> tuple[str, ...]:
    values = manifest[field]
    assert isinstance(values, tuple) and all(isinstance(value, str) for value in values)
    return values


def _bind_provider(
    providers: dict[str, str],
    edge: str,
    capability_id: str,
    *,
    label: str,
) -> None:
    if edge in providers:
        raise CapabilityCompositionError(f"{label} provider is ambiguous")
    providers[edge] = capability_id


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
            raise CapabilityCompositionError(error)
        dependencies.add(provider)
