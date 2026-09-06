"""Offline verification of the operator-owned P7 game resource root."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import stat

from .p7_development_workload import (
    P7_DEVELOPMENT_GAME_ID, P7_DEVELOPMENT_GAME_METADATA_SHA256,
    P7_DEVELOPMENT_GAME_SOURCE_SHA256, P7_DEVELOPMENT_RESOURCE_DIGEST,
)


class P7DevelopmentResourceLockError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 development resources are invalid")


_METADATA_STABLE_FIELDS = {
    "game_id": P7_DEVELOPMENT_GAME_ID,
    "title": "LS20",
    "default_fps": 30,
    "tags": ["keyboard"],
    "baseline_actions": [22, 123, 73, 84, 96, 192, 186],
}
_METADATA_FIELDS = frozenset((*_METADATA_STABLE_FIELDS, "local_dir", "date_downloaded"))


def _canonical(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()


@dataclass(frozen=True, repr=False)
class P7DevelopmentResourceSet:
    root: Path
    game_id: str
    source_sha256: str
    metadata_sha256: str
    resource_sha256: str

    def __repr__(self) -> str:
        return "P7DevelopmentResourceSet(redacted)"


def _read_direct_regular(root: Path, name: str) -> bytes:
    path = root / name
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
            raise ValueError
        data = path.read_bytes()
        after = path.lstat()
        if (before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size):
            raise ValueError
        return data
    except (OSError, ValueError):
        raise P7DevelopmentResourceLockError() from None


def verify_p7_development_resources(root: object) -> P7DevelopmentResourceSet:
    """Verify one explicit local root without discovery, downloads, or traversal."""

    if not isinstance(root, Path) or not root.is_absolute() or root.is_symlink():
        raise P7DevelopmentResourceLockError()
    try:
        if root.resolve(strict=True) != root or not stat.S_ISDIR(root.lstat().st_mode) or {child.name for child in root.iterdir()} != {"ls20.py", "metadata.json"}:
            raise ValueError
    except (OSError, ValueError):
        raise P7DevelopmentResourceLockError() from None
    source, metadata = _read_direct_regular(root, "ls20.py"), _read_direct_regular(root, "metadata.json")
    if "sha256:" + sha256(source).hexdigest() != P7_DEVELOPMENT_GAME_SOURCE_SHA256:
        raise P7DevelopmentResourceLockError()
    try:
        identity = json.loads(metadata.decode("utf-8"))
        if (
            type(identity) is not dict
            or frozenset(identity) != _METADATA_FIELDS
            or any(type(identity[key]) is not type(expected) or identity[key] != expected for key, expected in _METADATA_STABLE_FIELDS.items())
            or type(identity["local_dir"]) is not str
            or type(identity["date_downloaded"]) is not str
            or not identity["date_downloaded"]
            or Path(identity["local_dir"]) != root
            or not Path(identity["local_dir"]).is_absolute()
            or Path(identity["local_dir"]).resolve(strict=True) != root
            or "sha256:" + sha256(_canonical(_METADATA_STABLE_FIELDS)).hexdigest() != P7_DEVELOPMENT_GAME_METADATA_SHA256
        ):
            raise ValueError
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise P7DevelopmentResourceLockError() from None
    return P7DevelopmentResourceSet(root, P7_DEVELOPMENT_GAME_ID, P7_DEVELOPMENT_GAME_SOURCE_SHA256, P7_DEVELOPMENT_GAME_METADATA_SHA256, P7_DEVELOPMENT_RESOURCE_DIGEST)


__all__ = ("P7DevelopmentResourceLockError", "P7DevelopmentResourceSet", "verify_p7_development_resources")
