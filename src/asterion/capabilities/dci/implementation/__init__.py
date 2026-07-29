"""Package-owned DCI implementation and safe resource access."""

from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import PurePosixPath


class DciPackageResourceError(ValueError):
    """Raised when a DCI package resource name is unsafe."""


def package_resource(name: str) -> Traversable:
    """Return one package-relative DCI resource without allowing path escape."""

    if type(name) is not str or not name:
        raise DciPackageResourceError("DCI package resource is invalid")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise DciPackageResourceError("DCI package resource is invalid")
    return resources.files("asterion.capabilities.dci.resources").joinpath(
        *path.parts
    )


__all__ = (
    "DciPackageResourceError",
    "package_resource",
)
