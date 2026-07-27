"""Reference validation for portable framework capability manifests."""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType

from asterion.protocol_ordering import is_sorted_unique_scalar_strings


CAPABILITY_PROTOCOL_VERSION = "asterion.capability/v1"
CAPABILITY_KINDS = frozenset(
    {
        "capability",
        "evaluation",
        "memory",
        "observability",
        "policy",
        "research",
        "workflow",
    }
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
    "capability_id",
    "version",
    "kind",
    *EDGE_FIELDS,
}
CAPABILITY_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
SEMANTIC_VERSION = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")


class CapabilityProtocolError(ValueError):
    """Raised when a capability manifest violates asterion.capability/v1."""


def validate_capability_manifest(value: object) -> Mapping[str, object]:
    """Validate and return one immutable capability-manifest snapshot."""

    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise CapabilityProtocolError("capability manifest must be an object")
    if value.keys() != REQUIRED_FIELDS:
        raise CapabilityProtocolError("capability manifest fields are not recognized")
    if value.get("protocol") != CAPABILITY_PROTOCOL_VERSION:
        raise CapabilityProtocolError("capability protocol is invalid")
    capability_id = value["capability_id"]
    if (
        not isinstance(capability_id, str)
        or CAPABILITY_ID.fullmatch(capability_id) is None
    ):
        raise CapabilityProtocolError("capability_id is invalid")
    version = value["version"]
    if not isinstance(version, str) or SEMANTIC_VERSION.fullmatch(version) is None:
        raise CapabilityProtocolError("capability version is invalid")
    if value["kind"] not in CAPABILITY_KINDS:
        raise CapabilityProtocolError("capability kind is invalid")
    for field in EDGE_FIELDS:
        values = value[field]
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) or not value for value in values)
            or not is_sorted_unique_scalar_strings(values)
        ):
            raise CapabilityProtocolError(f"{field} must be a sorted unique string array")
    return MappingProxyType(
        {
            key: tuple(item) if key in EDGE_FIELDS else item
            for key, item in value.items()
        }
    )
