"""Reference validation for portable capability-package manifests."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.protocol import CAPABILITY_ID, SEMANTIC_VERSION


if TYPE_CHECKING:

    class BenchmarkSuiteRef(Protocol):
        """The benchmark-suite reference introduced by the next protocol task."""

        suite_id: str
        version: str


CAPABILITY_PACKAGE_PROTOCOL_VERSION = "asterion.capability-package/v1"
REQUIRED_FIELDS = {
    "protocol",
    "package_id",
    "version",
    "capabilities",
    "benchmark_suites",
    "resources",
}
MEDIA_TYPE = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CapabilityPackageProtocolError(ValueError):
    """Raised when a capability package violates its portable protocol."""


@dataclass(frozen=True, order=True, slots=True)
class CapabilityPackageRef:
    package_id: str
    version: str


@dataclass(frozen=True, order=True, slots=True)
class ResourceIdentity:
    resource_id: str
    media_type: str
    sha256: str


@dataclass(frozen=True, slots=True)
class CapabilityPackageManifest:
    package_ref: CapabilityPackageRef
    capabilities: tuple[CapabilityRef, ...]
    benchmark_suites: tuple["BenchmarkSuiteRef", ...]
    resources: tuple[ResourceIdentity, ...]


def validate_capability_package_manifest(value: object) -> CapabilityPackageManifest:
    """Validate one closed, portable capability-package manifest."""

    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise CapabilityPackageProtocolError("capability package must be an object")
    if value.keys() != REQUIRED_FIELDS:
        raise CapabilityPackageProtocolError("capability package fields are not recognized")
    if value["protocol"] != CAPABILITY_PACKAGE_PROTOCOL_VERSION:
        raise CapabilityPackageProtocolError("capability package protocol is invalid")
    package_ref = CapabilityPackageRef(
        _identity(value["package_id"], "package identifier"),
        _version(value["version"], "package version"),
    )
    capabilities = _capability_refs(value["capabilities"])
    benchmark_suites = _empty_benchmark_suites(value["benchmark_suites"])
    resources = _resource_identities(value["resources"])
    return CapabilityPackageManifest(
        package_ref=package_ref,
        capabilities=capabilities,
        benchmark_suites=benchmark_suites,
        resources=resources,
    )


def _identity(value: object, label: str) -> str:
    if not isinstance(value, str) or CAPABILITY_ID.fullmatch(value) is None:
        raise CapabilityPackageProtocolError(f"{label} is invalid")
    return value


def _version(value: object, label: str) -> str:
    if not isinstance(value, str) or SEMANTIC_VERSION.fullmatch(value) is None:
        raise CapabilityPackageProtocolError(f"{label} is invalid")
    return value


def _capability_refs(value: object) -> tuple[CapabilityRef, ...]:
    if not isinstance(value, list):
        raise CapabilityPackageProtocolError("capability package capabilities are invalid")
    refs = tuple(
        CapabilityRef(
            _identity(
                _mapping_field(item, {"capability_id", "version"}, "capability_id"),
                "capability identifier",
            ),
            _version(
                _mapping_field(item, {"capability_id", "version"}, "version"),
                "capability version",
            ),
        )
        for item in value
    )
    if refs != tuple(sorted(refs)) or len(refs) != len(set(refs)):
        raise CapabilityPackageProtocolError(
            "capability package capabilities are not sorted and unique"
        )
    return refs


def _empty_benchmark_suites(value: object) -> tuple["BenchmarkSuiteRef", ...]:
    if not isinstance(value, list) or value:
        raise CapabilityPackageProtocolError("capability package benchmark suites are invalid")
    return ()


def _resource_identities(value: object) -> tuple[ResourceIdentity, ...]:
    if not isinstance(value, list):
        raise CapabilityPackageProtocolError("capability package resources are invalid")
    resources = tuple(
        ResourceIdentity(
            _identity(
                _mapping_field(
                    item,
                    {"resource_id", "media_type", "sha256"},
                    "resource_id",
                ),
                "resource identifier",
            ),
            _media_type(
                _mapping_field(
                    item,
                    {"resource_id", "media_type", "sha256"},
                    "media_type",
                )
            ),
            _sha256(
                _mapping_field(
                    item,
                    {"resource_id", "media_type", "sha256"},
                    "sha256",
                )
            ),
        )
        for item in value
    )
    if (
        resources != tuple(sorted(resources))
        or len(resources) != len({resource.resource_id for resource in resources})
    ):
        raise CapabilityPackageProtocolError(
            "capability package resources are not sorted and unique"
        )
    return resources


def _mapping_field(value: object, fields: set[str], name: str) -> object:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CapabilityPackageProtocolError("capability package member is invalid")
    return value[name]


def _media_type(value: object) -> str:
    if not isinstance(value, str) or MEDIA_TYPE.fullmatch(value) is None:
        raise CapabilityPackageProtocolError("resource media type is invalid")
    return value


def _sha256(value: object) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise CapabilityPackageProtocolError("resource digest is invalid")
    return value
