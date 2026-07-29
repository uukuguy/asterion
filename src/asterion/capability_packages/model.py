"""Source-neutral capability-package values."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from importlib.resources.abc import Traversable
from pathlib import Path
from types import MappingProxyType

from asterion.capabilities.execution import CapabilityImplementationBinding
from asterion.capability_packages.protocol import (
    CapabilityPackageManifest,
    CapabilityPackageRef,
)


SOURCE_KINDS = (
    "archive",
    "builtin",
    "local-directory",
    "python-distribution",
    "registry",
)
_SAFE_METADATA_KEYS = frozenset({"distribution_name", "distribution_version"})
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
        _validate_nonempty_string(self.source_id, "capability package source is invalid")
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
        _validate_digest(self.payload_sha256)


@dataclass(frozen=True, slots=True)
class BenchmarkTaskBinding:
    owner_package: CapabilityPackageRef
    binding_id: str
    implementation: object = field(repr=False)

    def __post_init__(self) -> None:
        _validate_package_ref(self.owner_package)
        _validate_nonempty_string(self.binding_id, "benchmark task binding is invalid")


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
        _validate_nonempty_string(self.source_id, "installed capability source is invalid")
        _validate_source_kind(self.source_kind)
        object.__setattr__(self, "catalog_roots", _path_tuple(self.catalog_roots))
        object.__setattr__(
            self,
            "benchmark_suite_paths",
            _path_tuple(self.benchmark_suite_paths),
        )
        object.__setattr__(self, "implementations", tuple(self.implementations))
        object.__setattr__(self, "benchmark_bindings", tuple(self.benchmark_bindings))


def _safe_metadata(metadata: Mapping[str, object]) -> Mapping[str, str]:
    if not isinstance(metadata, Mapping):
        raise CapabilityPackageModelError("capability package metadata is invalid")
    return MappingProxyType(
        {
            str(key): str(value)
            for key, value in sorted(metadata.items())
            if key in _SAFE_METADATA_KEYS
        }
    )


def _path_tuple(paths: Iterable[Path]) -> tuple[Path, ...]:
    try:
        return tuple(Path(path) for path in paths)
    except TypeError:
        raise CapabilityPackageModelError("capability package paths are invalid") from None


def _validate_package_ref(value: CapabilityPackageRef) -> None:
    if not isinstance(value, CapabilityPackageRef):
        raise CapabilityPackageModelError("capability package identity is invalid")


def _validate_source_kind(value: str) -> None:
    if not isinstance(value, str) or value not in SOURCE_KINDS:
        raise CapabilityPackageModelError("capability package source kind is invalid")


def _validate_digest(value: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise CapabilityPackageModelError("capability package digest is invalid")


def _validate_nonempty_string(value: str, message: str) -> None:
    if not isinstance(value, str) or not value:
        raise CapabilityPackageModelError(message)


__all__ = (
    "SOURCE_KINDS",
    "BenchmarkTaskBinding",
    "CapabilityPackageCandidate",
    "CapabilityPackageModelError",
    "InstalledCapabilityPackage",
    "PortableCapabilityPayload",
)
