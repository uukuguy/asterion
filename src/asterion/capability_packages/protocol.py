"""Portable capability-package descriptor values and validation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeVar

from asterion.capabilities.catalog import CapabilityRef


CAPABILITY_PACKAGE_PROTOCOL_VERSION = "asterion.capability-package/v1"
IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
SEMANTIC_VERSION = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
MEDIA_TYPE = re.compile(r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_FIELDS = {
    "protocol",
    "package_id",
    "version",
    "capabilities",
    "benchmark_suites",
    "resources",
}


class CapabilityPackageProtocolError(ValueError):
    """Raised when a descriptor violates asterion.capability-package/v1."""


@dataclass(frozen=True, order=True, slots=True)
class CapabilityPackageRef:
    """Exact identity of one portable capability package."""

    package_id: str
    version: str

    @property
    def selector(self) -> str:
        return f"{self.package_id}@{self.version}"


@dataclass(frozen=True, order=True, slots=True)
class BenchmarkSuiteRef:
    """Exact identity of one package-owned benchmark suite."""

    suite_id: str
    version: str

    @property
    def selector(self) -> str:
        return f"{self.suite_id}@{self.version}"


@dataclass(frozen=True, order=True, slots=True)
class ResourceIdentity:
    """Content identity of one public package resource."""

    resource_id: str
    media_type: str
    sha256: str


@dataclass(frozen=True, slots=True)
class CapabilityPackageManifest:
    """Immutable validated snapshot of one portable package descriptor."""

    package_ref: CapabilityPackageRef
    capabilities: tuple[CapabilityRef, ...]
    benchmark_suites: tuple[BenchmarkSuiteRef, ...]
    resources: tuple[ResourceIdentity, ...]


_CanonicalValue = TypeVar(
    "_CanonicalValue",
    CapabilityRef,
    BenchmarkSuiteRef,
    ResourceIdentity,
)


def validate_capability_package_manifest(
    value: object,
) -> CapabilityPackageManifest:
    """Validate and snapshot one closed portable package descriptor."""

    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise CapabilityPackageProtocolError(
            "capability package manifest must be an object"
        )
    if value.keys() != REQUIRED_FIELDS:
        raise CapabilityPackageProtocolError(
            "capability package manifest fields are not recognized"
        )
    if value["protocol"] != CAPABILITY_PACKAGE_PROTOCOL_VERSION:
        raise CapabilityPackageProtocolError(
            "capability package protocol is invalid"
        )

    package_ref = CapabilityPackageRef(
        _identifier(value["package_id"], "package_id"),
        _version(value["version"], "package version"),
    )
    capabilities = _capability_refs(value["capabilities"])
    benchmark_suites = _benchmark_suite_refs(value["benchmark_suites"])
    resources = _resource_identities(value["resources"])
    return CapabilityPackageManifest(
        package_ref=package_ref,
        capabilities=capabilities,
        benchmark_suites=benchmark_suites,
        resources=resources,
    )


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise CapabilityPackageProtocolError(
            f"capability package {label} is invalid"
        )
    return value


def _version(value: object, label: str) -> str:
    if not isinstance(value, str) or SEMANTIC_VERSION.fullmatch(value) is None:
        raise CapabilityPackageProtocolError(
            f"capability package {label} is invalid"
        )
    return value


def _capability_refs(value: object) -> tuple[CapabilityRef, ...]:
    if not isinstance(value, list) or not value:
        raise CapabilityPackageProtocolError(
            "capability package capabilities must be a non-empty array"
        )
    refs: list[CapabilityRef] = []
    for item in value:
        if not isinstance(item, Mapping) or item.keys() != {
            "capability_id",
            "version",
        }:
            raise CapabilityPackageProtocolError(
                "capability package capability ref is invalid"
            )
        refs.append(
            CapabilityRef(
                _identifier(item["capability_id"], "capability ref"),
                _version(item["version"], "capability ref version"),
            )
        )
    return _canonical_tuple(
        refs,
        "capability package capability refs must be sorted and unique",
    )


def _benchmark_suite_refs(value: object) -> tuple[BenchmarkSuiteRef, ...]:
    if not isinstance(value, list):
        raise CapabilityPackageProtocolError(
            "capability package benchmark_suites must be an array"
        )
    refs: list[BenchmarkSuiteRef] = []
    for item in value:
        if not isinstance(item, Mapping) or item.keys() != {
            "suite_id",
            "version",
        }:
            raise CapabilityPackageProtocolError(
                "capability package benchmark suite ref is invalid"
            )
        refs.append(
            BenchmarkSuiteRef(
                _identifier(item["suite_id"], "benchmark suite ref"),
                _version(item["version"], "benchmark suite ref version"),
            )
        )
    return _canonical_tuple(
        refs,
        "capability package benchmark suite refs must be sorted and unique",
    )


def _resource_identities(value: object) -> tuple[ResourceIdentity, ...]:
    if not isinstance(value, list):
        raise CapabilityPackageProtocolError(
            "capability package resources must be an array"
        )
    resources: list[ResourceIdentity] = []
    for item in value:
        if not isinstance(item, Mapping) or item.keys() != {
            "resource_id",
            "media_type",
            "sha256",
        }:
            raise CapabilityPackageProtocolError(
                "capability package resource identity is invalid"
            )
        media_type = item["media_type"]
        digest = item["sha256"]
        if not isinstance(media_type, str) or MEDIA_TYPE.fullmatch(media_type) is None:
            raise CapabilityPackageProtocolError(
                "capability package resource media_type is invalid"
            )
        if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
            raise CapabilityPackageProtocolError(
                "capability package resource sha256 is invalid"
            )
        resources.append(
            ResourceIdentity(
                resource_id=_identifier(item["resource_id"], "resource_id"),
                media_type=media_type,
                sha256=digest,
            )
        )
    return _canonical_tuple(
        resources,
        "capability package resources must be sorted and unique",
    )


def _canonical_tuple(
    values: list[_CanonicalValue],
    message: str,
) -> tuple[_CanonicalValue, ...]:
    snapshot = tuple(values)
    if snapshot != tuple(sorted(set(snapshot))):
        raise CapabilityPackageProtocolError(message)
    return snapshot
