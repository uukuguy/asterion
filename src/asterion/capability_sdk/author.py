"""Public authoring helpers for validated portable capability payloads."""

from __future__ import annotations

import shutil
from importlib.resources.abc import Traversable
from pathlib import Path

from asterion.capability_packages.model import PortableCapabilityPayload
from asterion.capability_packages.payload import open_portable_payload


class CapabilityAuthorError(ValueError):
    """Raised when a portable payload cannot be materialized safely."""


def materialize_portable_payload(
    source_root: Path,
    destination_root: Path,
) -> PortableCapabilityPayload:
    """Copy one validated payload snapshot without overwriting a destination."""

    created = False
    try:
        if (
            not isinstance(source_root, Path)
            or not isinstance(destination_root, Path)
            or not destination_root.is_absolute()
            or destination_root.name in {"", ".", ".."}
        ):
            raise CapabilityAuthorError("capability payload materialization is invalid")
        parent = destination_root.parent
        if parent.resolve(strict=True) != parent or destination_root.exists():
            raise CapabilityAuthorError("capability payload materialization is invalid")

        payload = open_portable_payload(source_root)
        destination_root.mkdir(mode=0o755)
        created = True
        _write_snapshot(payload.resource_root, destination_root)
        materialized = open_portable_payload(destination_root)
        if materialized.payload_sha256 != payload.payload_sha256:
            raise CapabilityAuthorError("capability payload materialization is invalid")
        return materialized
    except CapabilityAuthorError:
        if created:
            shutil.rmtree(destination_root, ignore_errors=True)
        raise
    except Exception:
        if created:
            shutil.rmtree(destination_root, ignore_errors=True)
        raise CapabilityAuthorError(
            "capability payload materialization is invalid"
        ) from None


def _write_snapshot(source: Traversable, destination: Path) -> None:
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            target.mkdir(mode=0o755)
            _write_snapshot(child, target)
        elif child.is_file():
            target.write_bytes(child.read_bytes())
        else:
            raise CapabilityAuthorError("capability payload materialization is invalid")


__all__ = ("CapabilityAuthorError", "materialize_portable_payload")
