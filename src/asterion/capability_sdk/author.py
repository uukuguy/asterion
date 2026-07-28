"""Public authoring helpers for portable capability packages."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from asterion.capability_packages.payload import open_portable_payload


def copy_portable_payload(source: Path, target: Path) -> str:
    """Copy one validated portable payload into a new target directory."""

    source_root = Path(source).resolve(strict=True)
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
    with tempfile.TemporaryDirectory(
        prefix=".asterion-payload-copy-",
        dir=parent,
    ) as temporary:
        staged = Path(temporary) / "payload"
        shutil.copytree(source_root, staged, symlinks=False)
        copied = open_portable_payload(staged)
        if (
            copied.manifest != payload.manifest
            or copied.payload_sha256 != payload.payload_sha256
        ):
            raise ValueError("portable payload copy changed identity")
        staged.replace(target_root)
    return payload.payload_sha256
