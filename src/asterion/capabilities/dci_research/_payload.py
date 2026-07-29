"""Package-owned payload identity helpers for the DCI built-in provider."""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path


_ROOT_CHILDREN = frozenset(
    {
        "benchmark-suites",
        "capabilities",
        "capability-package.json",
        "conformance",
        "resources",
    }
)


def payload_sha256(root: Path) -> str:
    """Return the canonical location-independent digest for the shipped payload."""

    root = Path(root)
    if {child.name for child in root.iterdir()} != _ROOT_CHILDREN:
        raise ValueError("dci payload is invalid")
    contents = {"capability-package.json": _read_regular_file(root / "capability-package.json")}
    for directory_name in ("capabilities", "benchmark-suites", "resources", "conformance"):
        directory = root / directory_name
        if not _is_regular_directory(directory):
            raise ValueError("dci payload is invalid")
        for child in sorted(directory.iterdir(), key=lambda item: item.name):
            contents[f"{directory_name}/{child.name}"] = _read_regular_file(child)
    return _digest_contents(contents)


def _is_regular_directory(path: Path) -> bool:
    metadata = path.lstat()
    return stat.S_ISDIR(metadata.st_mode) and not path.is_symlink()


def _read_regular_file(path: Path) -> bytes:
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("dci payload is invalid")
    return path.read_bytes()


def _digest_contents(contents: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name in sorted(contents):
        encoded_name = name.encode("utf-8")
        content_digest = hashlib.sha256(contents[name]).digest()
        entry = encoded_name + b"\0" + content_digest
        digest.update(len(entry).to_bytes(8, "big"))
        digest.update(entry)
    return digest.hexdigest()


__all__ = ("payload_sha256",)
