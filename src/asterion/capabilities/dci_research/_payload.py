"""Package-owned payload identity helpers for the DCI built-in provider."""

from __future__ import annotations

import hashlib
import json
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
    try:
        descriptor = _read_regular_file(root / "capability-package.json")
        manifest = json.loads(descriptor)
    except Exception:
        raise ValueError("dci payload is invalid") from None
    benchmark_suites = manifest.get("benchmark_suites")
    if not isinstance(benchmark_suites, list):
        raise ValueError("dci payload is invalid")
    expected_children = (
        _ROOT_CHILDREN
        if benchmark_suites
        else _ROOT_CHILDREN - {"benchmark-suites"}
    )
    children = {child.name for child in root.iterdir()}
    if children not in (_ROOT_CHILDREN, expected_children):
        raise ValueError("dci payload is invalid")
    contents = {"capability-package.json": descriptor}
    for directory_name in ("capabilities", "benchmark-suites", "resources", "conformance"):
        directory = root / directory_name
        if directory_name == "benchmark-suites" and not directory.exists():
            continue
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
