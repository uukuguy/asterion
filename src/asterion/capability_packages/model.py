"""Source-neutral capability-package discovery and installation values."""

from __future__ import annotations

from collections.abc import Mapping
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


@dataclass(frozen=True, slots=True)
class CapabilityPackageCandidate:
    """Safe metadata discovered without importing a provider factory."""

    package_ref: CapabilityPackageRef
    source_id: str
    source_kind: str
    payload_sha256: str | None
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.source_kind not in SOURCE_KINDS:
            raise ValueError("capability package source kind is invalid")
        safe_metadata = MappingProxyType(
            {
                str(key): str(value)
                for key, value in sorted(self.metadata.items())
                if key in {"distribution_name", "distribution_version"}
            }
        )
        object.__setattr__(self, "metadata", safe_metadata)


@dataclass(frozen=True, slots=True)
class PortableCapabilityPayload:
    """A portable package manifest and its resource tree."""

    manifest: CapabilityPackageManifest
    payload_sha256: str
    resource_root: Traversable


@dataclass(frozen=True, slots=True)
class BenchmarkTaskBinding:
    """An opaque selected-provider benchmark implementation."""

    owner_package: CapabilityPackageRef
    binding_id: str
    implementation: object = field(repr=False)


@dataclass(frozen=True, slots=True)
class InstalledCapabilityPackage:
    """Source-neutral values returned after loading a selected provider."""

    package_ref: CapabilityPackageRef
    payload_sha256: str
    source_id: str
    source_kind: str
    catalog_roots: tuple[Path, ...]
    benchmark_suite_paths: tuple[Path, ...]
    implementations: tuple[CapabilityImplementationBinding, ...]
    benchmark_bindings: tuple[BenchmarkTaskBinding, ...]
