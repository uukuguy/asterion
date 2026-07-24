"""Portable static application assembly contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from asterion.packages.catalog import PackageCatalog, PackageCatalogError, PackageRef
from asterion.packages.composition import (
    PackageComposition,
    PackageCompositionError,
    compose_packages,
)
from asterion.runtime.protocol import ProtocolError, validate_runtime_manifest


ASSEMBLY_PROTOCOL_VERSION = "dci.assembly/v1"
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
    "packages",
    *EDGE_FIELDS,
}


class AssemblyError(ValueError):
    """Raised when a static application assembly is invalid or unresolved."""


@dataclass(frozen=True)
class AssemblyPlan:
    application_id: str
    version: str
    runtime_id: str
    package_refs: tuple[PackageRef, ...]
    package_manifests: tuple[Mapping[str, object], ...]
    composition: PackageComposition
    runtime_capabilities: tuple[str, ...]
    host_capabilities: tuple[str, ...]


def validate_assembly_manifest(value: Mapping[str, object]) -> None:
    """Validate one closed canonical dci.assembly/v1 manifest."""

    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise AssemblyError("assembly manifest must be an object")
    if value.keys() != REQUIRED_FIELDS:
        raise AssemblyError("assembly manifest fields are not recognized")
    if value["protocol"] != ASSEMBLY_PROTOCOL_VERSION:
        raise AssemblyError("assembly protocol is not dci.assembly/v1")
    for field in ("application_id", "runtime_id"):
        item = value[field]
        if not isinstance(item, str) or IDENTIFIER.fullmatch(item) is None:
            raise AssemblyError(f"assembly {field} is invalid")
    version = value["version"]
    if not isinstance(version, str) or SEMANTIC_VERSION.fullmatch(version) is None:
        raise AssemblyError("assembly version is invalid")

    packages = value["packages"]
    if not isinstance(packages, list) or not packages:
        raise AssemblyError("assembly packages must be a non-empty array")
    refs: list[tuple[str, str]] = []
    for package in packages:
        if not isinstance(package, Mapping) or package.keys() != {
            "package_id",
            "version",
        }:
            raise AssemblyError("assembly package ref is invalid")
        package_id = package["package_id"]
        package_version = package["version"]
        if (
            not isinstance(package_id, str)
            or IDENTIFIER.fullmatch(package_id) is None
            or not isinstance(package_version, str)
            or SEMANTIC_VERSION.fullmatch(package_version) is None
        ):
            raise AssemblyError("assembly package ref is invalid")
        refs.append((package_id, package_version))
    if refs != sorted(set(refs)):
        raise AssemblyError("assembly package refs must be sorted and unique")

    for field in EDGE_FIELDS:
        edges = value[field]
        if (
            not isinstance(edges, list)
            or any(not isinstance(edge, str) or not edge for edge in edges)
            or edges != sorted(set(edges))
        ):
            raise AssemblyError(f"assembly {field} must be sorted unique strings")


def resolve_assembly(
    assembly: Mapping[str, object],
    *,
    catalog: PackageCatalog,
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

    raw_packages = assembly["packages"]
    assert isinstance(raw_packages, list)
    package_refs = tuple(
        PackageRef(package["package_id"], package["version"])
        for package in raw_packages
        if isinstance(package, Mapping)
        and isinstance(package["package_id"], str)
        and isinstance(package["version"], str)
    )
    try:
        manifests = catalog.select(package_refs)
    except PackageCatalogError as error:
        raise AssemblyError("assembly package selection is unavailable") from error

    runtime_capabilities = runtime_manifest["capabilities"]
    assert isinstance(runtime_capabilities, list)
    try:
        composition = compose_packages(
            manifests,
            host_capabilities=set(runtime_capabilities)
            | set(_string_edges(assembly, "host_capabilities")),
            host_policies=set(_string_edges(assembly, "host_policies")),
            host_events=set(_string_edges(assembly, "host_events")),
            host_artifacts=set(_string_edges(assembly, "host_artifacts")),
        )
    except PackageCompositionError as error:
        raise AssemblyError("assembly package graph cannot compose") from error

    application_id = assembly["application_id"]
    version = assembly["version"]
    runtime_id = assembly["runtime_id"]
    assert isinstance(application_id, str)
    assert isinstance(version, str)
    assert isinstance(runtime_id, str)
    manifests_by_id = {manifest["package_id"]: manifest for manifest in manifests}
    return AssemblyPlan(
        application_id=application_id,
        version=version,
        runtime_id=runtime_id,
        package_refs=package_refs,
        package_manifests=tuple(
            _freeze_mapping(manifests_by_id[package_id])
            for package_id in composition.package_ids
        ),
        composition=composition,
        runtime_capabilities=tuple(sorted(runtime_capabilities)),
        host_capabilities=tuple(_string_edges(assembly, "host_capabilities")),
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
