"""Public authoring helpers for portable capability packages."""

from __future__ import annotations

import shutil
from pathlib import Path
from importlib.resources.abc import Traversable

from asterion.capability_packages.payload import open_portable_payload


def copy_portable_payload(source: Path, target: Path) -> str:
    """Copy one validated portable payload into a new target directory."""

    source_root = Path(source)
    target_root = Path(target)
    if (
        target_root.exists()
        or target_root.is_symlink()
        or not target_root.name
        or target_root.name in {".", ".."}
    ):
        raise ValueError("portable payload copy target is invalid")
    payload = open_portable_payload(source_root)
    parent = target_root.parent.resolve(strict=True)
    target_root = parent / target_root.name
    created_target = False
    try:
        target_root.mkdir()
        created_target = True
        _copy_snapshot(payload.resource_root, target_root)
        copied = open_portable_payload(target_root)
        if (
            copied.manifest != payload.manifest
            or copied.payload_sha256 != payload.payload_sha256
        ):
            raise ValueError("portable payload copy changed identity")
    except Exception:
        if created_target and target_root.exists() and not target_root.is_symlink():
            shutil.rmtree(target_root, ignore_errors=True)
        raise
    return payload.payload_sha256


def _copy_snapshot(source: Traversable, target: Path) -> None:
    for child in sorted(source.iterdir(), key=lambda item: item.name):
        destination = target / child.name
        if child.is_dir():
            destination.mkdir()
            _copy_snapshot(child, destination)
        elif child.is_file():
            with (
                child.open("rb") as input_stream,
                destination.open("xb") as output_stream,
            ):
                shutil.copyfileobj(input_stream, output_stream)
        else:
            raise ValueError("portable payload snapshot is invalid")
