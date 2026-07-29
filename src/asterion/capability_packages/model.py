"""Source-neutral capability-package values."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from importlib.resources.abc import Traversable
from pathlib import Path
from types import MappingProxyType
from typing import cast

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import (
    CapabilityImplementation,
    CapabilityImplementationBinding,
)
from asterion.capabilities.protocol import CAPABILITY_ID, SEMANTIC_VERSION
from asterion.capability_packages.protocol import (
    CAPABILITY_PACKAGE_PROTOCOL_VERSION,
    CapabilityPackageManifest,
    CapabilityPackageRef,
    validate_capability_package_manifest,
)


SOURCE_KINDS = (
    "archive",
    "builtin",
    "local-directory",
    "python-distribution",
    "registry",
)
_SAFE_METADATA_KEYS = ("distribution_name", "distribution_version")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CapabilityPackageModelError(ValueError):
    """Raised when source-neutral package values are malformed."""


@dataclass(frozen=True, slots=True)
class CapabilityPackageCandidate:
    package_ref: CapabilityPackageRef
    source_id: str
    source_kind: str
    payload_sha256: str | None
    metadata: Mapping[str, str] = field(repr=False)

    def __post_init__(self) -> None:
        _validate_package_ref(self.package_ref)
        _validate_identifier(self.source_id, "capability package source is invalid")
        _validate_source_kind(self.source_kind)
        if self.payload_sha256 is not None:
            _validate_digest(self.payload_sha256)
        object.__setattr__(self, "metadata", _safe_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class PortableCapabilityPayload:
    manifest: CapabilityPackageManifest
    payload_sha256: str
    resource_root: Traversable = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest", _snapshot_manifest(self.manifest))
        _validate_digest(self.payload_sha256)


@dataclass(frozen=True, slots=True)
class BenchmarkTaskBinding:
    owner_package: CapabilityPackageRef
    binding_id: str
    implementation: object = field(repr=False)

    def __post_init__(self) -> None:
        _validate_package_ref(self.owner_package)
        _validate_identifier(self.binding_id, "benchmark task binding is invalid")


@dataclass(frozen=True, slots=True)
class InstalledCapabilityPackage:
    package_ref: CapabilityPackageRef
    payload_sha256: str
    source_id: str
    source_kind: str
    catalog_roots: tuple[Path, ...] = field(repr=False)
    benchmark_suite_paths: tuple[Path, ...] = field(repr=False)
    implementations: tuple[CapabilityImplementationBinding, ...] = field(repr=False)
    benchmark_bindings: tuple[BenchmarkTaskBinding, ...] = field(repr=False)

    def __post_init__(self) -> None:
        _validate_package_ref(self.package_ref)
        _validate_digest(self.payload_sha256)
        _validate_identifier(self.source_id, "installed capability source is invalid")
        _validate_source_kind(self.source_kind)
        object.__setattr__(self, "catalog_roots", _path_tuple(self.catalog_roots))
        object.__setattr__(
            self,
            "benchmark_suite_paths",
            _path_tuple(self.benchmark_suite_paths),
        )
        object.__setattr__(
            self,
            "implementations",
            _implementation_binding_tuple(self.implementations),
        )
        object.__setattr__(
            self,
            "benchmark_bindings",
            _benchmark_binding_tuple(self.benchmark_bindings),
        )


def _snapshot_manifest(manifest: CapabilityPackageManifest) -> CapabilityPackageManifest:
    if not isinstance(manifest, CapabilityPackageManifest):
        raise CapabilityPackageModelError("capability package manifest is invalid")
    snapshot: CapabilityPackageManifest | None = None
    failed = False
    try:
        snapshot = validate_capability_package_manifest(
            {
                "protocol": CAPABILITY_PACKAGE_PROTOCOL_VERSION,
                "package_id": manifest.package_ref.package_id,
                "version": manifest.package_ref.version,
                "capabilities": [
                    {
                        "capability_id": capability.capability_id,
                        "version": capability.version,
                    }
                    for capability in tuple(manifest.capabilities)
                ],
                "benchmark_suites": [
                    {
                        "suite_id": suite.suite_id,
                        "version": suite.version,
                    }
                    for suite in tuple(manifest.benchmark_suites)
                ],
                "resources": [
                    {
                        "resource_id": resource.resource_id,
                        "media_type": resource.media_type,
                        "sha256": resource.sha256,
                    }
                    for resource in tuple(manifest.resources)
                ],
                "conformance": [
                    {
                        "resource_id": resource.resource_id,
                        "media_type": resource.media_type,
                        "sha256": resource.sha256,
                    }
                    for resource in tuple(manifest.conformance)
                ],
            }
        )
    except Exception:
        failed = True
    if failed or snapshot is None:
        raise CapabilityPackageModelError("capability package manifest is invalid")
    return snapshot


def _safe_metadata(metadata: Mapping[str, object]) -> Mapping[str, str]:
    if not isinstance(metadata, Mapping):
        raise CapabilityPackageModelError("capability package metadata is invalid")
    failed = False
    safe_metadata: dict[str, str] = {}
    try:
        for key in _SAFE_METADATA_KEYS:
            try:
                value = metadata[key]
            except KeyError:
                continue
            safe_metadata[key] = str(value)
    except Exception:
        failed = True
    if failed:
        raise CapabilityPackageModelError("capability package metadata is invalid")
    return MappingProxyType(safe_metadata)


def _path_tuple(paths: Iterable[Path]) -> tuple[Path, ...]:
    try:
        return tuple(Path(path) for path in paths)
    except TypeError:
        raise CapabilityPackageModelError("capability package paths are invalid") from None


def _implementation_binding_tuple(
    bindings: Iterable[CapabilityImplementationBinding | tuple[object, object]],
) -> tuple[CapabilityImplementationBinding, ...]:
    try:
        values = tuple(bindings)
    except TypeError:
        raise CapabilityPackageModelError(
            "capability implementation bindings are invalid"
        ) from None
    converted: list[CapabilityImplementationBinding] = []
    for binding in values:
        if isinstance(binding, CapabilityImplementationBinding):
            converted.append(binding)
            continue
        if (
            isinstance(binding, tuple)
            and len(binding) == 2
            and isinstance(binding[0], CapabilityRef)
        ):
            converted.append(
                CapabilityImplementationBinding(
                    binding[0],
                    cast(CapabilityImplementation, binding[1]),
                )
            )
            continue
        raise CapabilityPackageModelError(
            "capability implementation bindings are invalid"
        )
    return tuple(converted)


def _benchmark_binding_tuple(
    bindings: Iterable[BenchmarkTaskBinding],
) -> tuple[BenchmarkTaskBinding, ...]:
    try:
        values = tuple(bindings)
    except TypeError:
        raise CapabilityPackageModelError("benchmark task bindings are invalid") from None
    if not all(isinstance(binding, BenchmarkTaskBinding) for binding in values):
        raise CapabilityPackageModelError("benchmark task bindings are invalid")
    return values


def _validate_package_ref(value: CapabilityPackageRef) -> None:
    if not isinstance(value, CapabilityPackageRef):
        raise CapabilityPackageModelError("capability package identity is invalid")
    _validate_identifier(value.package_id, "capability package identity is invalid")
    _validate_version(value.version)


def _validate_source_kind(value: str) -> None:
    if not isinstance(value, str) or value not in SOURCE_KINDS:
        raise CapabilityPackageModelError("capability package source kind is invalid")


def _validate_digest(value: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise CapabilityPackageModelError("capability package digest is invalid")


def _validate_identifier(value: str, message: str) -> None:
    if not isinstance(value, str) or CAPABILITY_ID.fullmatch(value) is None:
        raise CapabilityPackageModelError(message)


def _validate_version(value: str) -> None:
    if not isinstance(value, str) or SEMANTIC_VERSION.fullmatch(value) is None:
        raise CapabilityPackageModelError("capability package identity is invalid")


__all__ = (
    "SOURCE_KINDS",
    "BenchmarkTaskBinding",
    "CapabilityPackageCandidate",
    "CapabilityPackageModelError",
    "InstalledCapabilityPackage",
    "PortableCapabilityPayload",
)
