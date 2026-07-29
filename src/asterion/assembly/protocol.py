"""Portable static application assembly contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capabilities.catalog import CapabilityCatalog, CapabilityCatalogError, CapabilityRef
from asterion.capabilities.composition import (
    CapabilityComposition,
    CapabilityCompositionError,
    compose_capabilities,
)
from asterion.protocol_ordering import is_sorted_unique_scalar_strings
from asterion.runtime.protocol import ProtocolError, validate_runtime_manifest


APPLICATION_ASSEMBLY_PROTOCOL_VERSION = "asterion.application-assembly/v1"
IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
SEMANTIC_VERSION = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
EDGE_FIELDS = (
    "host_capabilities",
    "host_policies",
    "host_events",
    "host_artifacts",
)
REQUIRED_FIELDS = {
    "protocol",
    "application_id",
    "version",
    "runtime_id",
    "capability_packages",
    "capabilities",
    *EDGE_FIELDS,
}


class AssemblyError(ValueError):
    """Raised when a static application assembly is invalid or unresolved."""


@dataclass(frozen=True)
class AssemblyPlan:
    application_id: str
    version: str
    runtime_id: str
    capability_package_refs: tuple[CapabilityPackageRef, ...]
    capability_refs: tuple[CapabilityRef, ...]
    capability_manifests: tuple[Mapping[str, object], ...]
    composition: CapabilityComposition
    runtime_capabilities: tuple[str, ...]
    host_capabilities: tuple[str, ...]
    host_events: tuple[str, ...]
    host_artifacts: tuple[str, ...]


def validate_assembly_manifest(value: object) -> Mapping[str, object]:
    """Validate one closed canonical Asterion application assembly."""

    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise AssemblyError("assembly manifest must be an object")
    if value.keys() != REQUIRED_FIELDS:
        raise AssemblyError("assembly manifest fields are not recognized")
    if value["protocol"] != APPLICATION_ASSEMBLY_PROTOCOL_VERSION:
        raise AssemblyError("application assembly protocol is invalid")
    for field in ("application_id", "runtime_id"):
        item = value[field]
        if not isinstance(item, str) or IDENTIFIER.fullmatch(item) is None:
            raise AssemblyError(f"assembly {field} is invalid")
    version = value["version"]
    if not isinstance(version, str) or SEMANTIC_VERSION.fullmatch(version) is None:
        raise AssemblyError("assembly version is invalid")

    _validate_refs(
        value["capability_packages"],
        identity_field="package_id",
        label="capability package",
    )
    _validate_refs(
        value["capabilities"],
        identity_field="capability_id",
        label="capability",
    )

    for field in EDGE_FIELDS:
        edges = value[field]
        if (
            not isinstance(edges, list)
            or any(not isinstance(edge, str) or not edge for edge in edges)
            or not is_sorted_unique_scalar_strings(edges)
        ):
            raise AssemblyError(f"assembly {field} must be sorted unique strings")
    return _freeze_mapping(value)


def resolve_assembly(
    assembly: Mapping[str, object],
    *,
    catalog: CapabilityCatalog,
    runtime_manifest: Mapping[str, object],
) -> AssemblyPlan:
    """Resolve portable identities and edges into a static composition plan."""

    validated_assembly = validate_assembly_manifest(assembly)
    try:
        validate_runtime_manifest(runtime_manifest)
    except ProtocolError as error:
        raise AssemblyError("assembly runtime manifest is invalid") from error
    if runtime_manifest["runtime_id"] != validated_assembly["runtime_id"]:
        raise AssemblyError("assembly runtime identity does not match")

    raw_package_refs = validated_assembly["capability_packages"]
    assert isinstance(raw_package_refs, tuple)
    capability_package_refs = tuple(
        CapabilityPackageRef(package["package_id"], package["version"])
        for package in raw_package_refs
        if isinstance(package, Mapping)
        and isinstance(package["package_id"], str)
        and isinstance(package["version"], str)
    )
    raw_capability_refs = validated_assembly["capabilities"]
    assert isinstance(raw_capability_refs, tuple)
    capability_refs = tuple(
        CapabilityRef(capability["capability_id"], capability["version"])
        for capability in raw_capability_refs
        if isinstance(capability, Mapping)
        and isinstance(capability["capability_id"], str)
        and isinstance(capability["version"], str)
    )
    try:
        manifests = catalog.select(capability_refs)
    except CapabilityCatalogError as error:
        raise AssemblyError("assembly capability selection is unavailable") from error

    runtime_capabilities = runtime_manifest["capabilities"]
    assert isinstance(runtime_capabilities, list)
    try:
        composition = compose_capabilities(
            manifests,
            host_capabilities=set(runtime_capabilities)
            | set(_string_edges(validated_assembly, "host_capabilities")),
            host_policies=set(_string_edges(validated_assembly, "host_policies")),
            host_events=set(_string_edges(validated_assembly, "host_events")),
            host_artifacts=set(_string_edges(validated_assembly, "host_artifacts")),
        )
    except CapabilityCompositionError as error:
        raise AssemblyError("assembly capability graph cannot compose") from error

    application_id = validated_assembly["application_id"]
    version = validated_assembly["version"]
    runtime_id = validated_assembly["runtime_id"]
    assert isinstance(application_id, str)
    assert isinstance(version, str)
    assert isinstance(runtime_id, str)
    manifests_by_id = {manifest["capability_id"]: manifest for manifest in manifests}
    return AssemblyPlan(
        application_id=application_id,
        version=version,
        runtime_id=runtime_id,
        capability_package_refs=capability_package_refs,
        capability_refs=capability_refs,
        capability_manifests=tuple(
            _freeze_mapping(manifests_by_id[capability_id])
            for capability_id in composition.capability_ids
        ),
        composition=composition,
        runtime_capabilities=tuple(sorted(runtime_capabilities)),
        host_capabilities=tuple(
            _string_edges(validated_assembly, "host_capabilities")
        ),
        host_events=tuple(_string_edges(validated_assembly, "host_events")),
        host_artifacts=tuple(_string_edges(validated_assembly, "host_artifacts")),
    )


def _validate_refs(value: object, *, identity_field: str, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise AssemblyError(f"assembly {label} refs must be a non-empty array")
    refs: list[tuple[str, str]] = []
    for reference in value:
        if not isinstance(reference, Mapping) or reference.keys() != {
            identity_field,
            "version",
        }:
            raise AssemblyError(f"assembly {label} ref is invalid")
        identity = reference[identity_field]
        version = reference["version"]
        if (
            not isinstance(identity, str)
            or IDENTIFIER.fullmatch(identity) is None
            or not isinstance(version, str)
            or SEMANTIC_VERSION.fullmatch(version) is None
        ):
            raise AssemblyError(f"assembly {label} ref is invalid")
        refs.append((identity, version))
    if refs != sorted(set(refs)):
        raise AssemblyError(f"assembly {label} refs must be sorted and unique")


def _string_edges(assembly: Mapping[str, object], field: str) -> list[str] | tuple[str, ...]:
    values = assembly[field]
    assert isinstance(values, (list, tuple)) and all(
        isinstance(value, str) for value in values
    )
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
