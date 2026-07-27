"""Portable static application assembly contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from asterion.capabilities.catalog import CapabilityCatalog, CapabilityCatalogError, CapabilityRef
from asterion.capabilities.composition import (
    CapabilityComposition,
    CapabilityCompositionError,
    compose_capabilities,
)
from asterion.capability_packages.protocol import CapabilityPackageRef
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


def validate_assembly_manifest(value: Mapping[str, object]) -> None:
    """Validate one closed canonical asterion.application-assembly/v1 manifest."""

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

    capability_packages = value["capability_packages"]
    if not isinstance(capability_packages, list) or not capability_packages:
        raise AssemblyError(
            "assembly capability_packages must be a non-empty array"
        )
    capability_package_refs: list[CapabilityPackageRef] = []
    for package in capability_packages:
        if not isinstance(package, Mapping) or package.keys() != {
            "package_id",
            "version",
        }:
            raise AssemblyError("assembly capability package ref is invalid")
        package_id = package["package_id"]
        package_version = package["version"]
        if (
            not isinstance(package_id, str)
            or IDENTIFIER.fullmatch(package_id) is None
            or not isinstance(package_version, str)
            or SEMANTIC_VERSION.fullmatch(package_version) is None
        ):
            raise AssemblyError("assembly capability package ref is invalid")
        capability_package_refs.append(
            CapabilityPackageRef(package_id, package_version)
        )
    if capability_package_refs != sorted(set(capability_package_refs)):
        raise AssemblyError(
            "assembly capability package refs must be sorted and unique"
        )

    capabilities = value["capabilities"]
    if not isinstance(capabilities, list) or not capabilities:
        raise AssemblyError("assembly capabilities must be a non-empty array")
    capability_refs: list[CapabilityRef] = []
    for capability in capabilities:
        if not isinstance(capability, Mapping) or capability.keys() != {
            "capability_id",
            "version",
        }:
            raise AssemblyError("assembly capability ref is invalid")
        capability_id = capability["capability_id"]
        capability_version = capability["version"]
        if (
            not isinstance(capability_id, str)
            or IDENTIFIER.fullmatch(capability_id) is None
            or not isinstance(capability_version, str)
            or SEMANTIC_VERSION.fullmatch(capability_version) is None
        ):
            raise AssemblyError("assembly capability ref is invalid")
        capability_refs.append(CapabilityRef(capability_id, capability_version))
    if capability_refs != sorted(set(capability_refs)):
        raise AssemblyError(
            "assembly capability refs must be sorted and unique"
        )

    for field in EDGE_FIELDS:
        edges = value[field]
        if (
            not isinstance(edges, list)
            or any(not isinstance(edge, str) or not edge for edge in edges)
            or not is_sorted_unique_scalar_strings(edges)
        ):
            raise AssemblyError(f"assembly {field} must be sorted unique strings")


def resolve_assembly(
    assembly: Mapping[str, object],
    *,
    catalog: CapabilityCatalog,
    runtime_manifest: Mapping[str, object],
) -> AssemblyPlan:
    """Resolve portable identities and edges into a static composition plan."""

    validate_assembly_manifest(assembly)
    try:
        validate_runtime_manifest(runtime_manifest)
    except ProtocolError as error:
        raise AssemblyError("assembly runtime manifest is invalid") from error
    if runtime_manifest["runtime_id"] != assembly["runtime_id"]:
        raise AssemblyError("assembly runtime identity does not match")

    raw_capability_packages = assembly["capability_packages"]
    assert isinstance(raw_capability_packages, list)
    capability_package_refs = tuple(
        CapabilityPackageRef(package["package_id"], package["version"])
        for package in raw_capability_packages
        if isinstance(package, Mapping)
        and isinstance(package["package_id"], str)
        and isinstance(package["version"], str)
    )
    raw_capabilities = assembly["capabilities"]
    assert isinstance(raw_capabilities, list)
    capability_refs = tuple(
        CapabilityRef(capability["capability_id"], capability["version"])
        for capability in raw_capabilities
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
            | set(_string_edges(assembly, "host_capabilities")),
            host_policies=set(_string_edges(assembly, "host_policies")),
            host_events=set(_string_edges(assembly, "host_events")),
            host_artifacts=set(_string_edges(assembly, "host_artifacts")),
        )
    except CapabilityCompositionError as error:
        raise AssemblyError("assembly capability graph cannot compose") from error

    application_id = assembly["application_id"]
    version = assembly["version"]
    runtime_id = assembly["runtime_id"]
    assert isinstance(application_id, str)
    assert isinstance(version, str)
    assert isinstance(runtime_id, str)
    manifests_by_id = {
        manifest["capability_id"]: manifest for manifest in manifests
    }
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
        host_capabilities=tuple(_string_edges(assembly, "host_capabilities")),
        host_events=tuple(_string_edges(assembly, "host_events")),
        host_artifacts=tuple(_string_edges(assembly, "host_artifacts")),
    )


def _string_edges(assembly: Mapping[str, object], field: str) -> list[str]:
    values = assembly[field]
    assert isinstance(values, list) and all(isinstance(value, str) for value in values)
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
