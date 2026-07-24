"""Reference validation for portable framework package manifests."""

from __future__ import annotations

import re
from collections.abc import Mapping


PACKAGE_PROTOCOL_VERSION = "dci.package/v1"
PACKAGE_KINDS = frozenset(
    {"capability", "workflow", "policy", "memory", "observability", "evaluation"}
)
EDGE_FIELDS = (
    "provides_capabilities",
    "requires_capabilities",
    "requires_policies",
    "emits_events",
    "consumes_events",
    "produces_artifacts",
    "consumes_artifacts",
)
REQUIRED_FIELDS = {
    "protocol",
    "package_id",
    "version",
    "kind",
    *EDGE_FIELDS,
}
PACKAGE_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
SEMANTIC_VERSION = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")


class PackageProtocolError(ValueError):
    """Raised when a package manifest violates dci.package/v1."""


def validate_package_manifest(manifest: Mapping[str, object]) -> None:
    """Validate one closed, portable package manifest."""

    if not isinstance(manifest, Mapping) or not all(
        isinstance(key, str) for key in manifest
    ):
        raise PackageProtocolError("package manifest must be an object")
    if manifest.keys() != REQUIRED_FIELDS:
        raise PackageProtocolError("package manifest fields are not recognized")
    if manifest["protocol"] != PACKAGE_PROTOCOL_VERSION:
        raise PackageProtocolError("package protocol is not dci.package/v1")
    package_id = manifest["package_id"]
    if not isinstance(package_id, str) or PACKAGE_ID.fullmatch(package_id) is None:
        raise PackageProtocolError("package_id is invalid")
    version = manifest["version"]
    if not isinstance(version, str) or SEMANTIC_VERSION.fullmatch(version) is None:
        raise PackageProtocolError("package version is invalid")
    if manifest["kind"] not in PACKAGE_KINDS:
        raise PackageProtocolError("package kind is invalid")
    for field in EDGE_FIELDS:
        values = manifest[field]
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) or not value for value in values)
            or values != sorted(set(values))
        ):
            raise PackageProtocolError(f"{field} must be a sorted unique string array")
