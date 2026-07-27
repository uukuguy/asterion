"""Package-owned access to private in-process artifact values."""

from __future__ import annotations

from collections.abc import Mapping

from asterion.capabilities.execution import (
    InProcessArtifactPayload,
    project_public_value,
)


def create_private_artifact(
    *,
    private_value: Mapping[str, object],
    public_projection: Mapping[str, object],
) -> object:
    """Create one immutable in-process artifact without exporting its type."""

    return InProcessArtifactPayload(
        private_value=private_value,
        public_projection=public_projection,
    )


def private_artifact_value(value: object) -> Mapping[str, object]:
    """Return the private mapping from one exact package-owned artifact."""

    if not isinstance(value, InProcessArtifactPayload):
        raise TypeError
    return value.private_value


def safe_public_projection(value: object) -> object:
    """Project an arbitrary value through the framework's public-value rules."""

    return project_public_value(value)
