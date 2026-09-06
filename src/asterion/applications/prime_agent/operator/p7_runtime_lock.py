"""Fail-closed lock for P7's operator-owned ARC runtime."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess

from .p7_development_workload import (
    P7_DEVELOPMENT_ARC_AGI_WHEEL_SHA256,
    P7_DEVELOPMENT_ARCENGINE_WHEEL_SHA256,
)


class P7DevelopmentRuntimeLockError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 development runtime is invalid")


_WHEELS = {
    "arc_agi": ("arc_agi-0.9.9-py3-none-any.whl", "arc-agi", "0.9.9", P7_DEVELOPMENT_ARC_AGI_WHEEL_SHA256),
    "arcengine": ("arcengine-0.9.3-py3-none-any.whl", "arcengine", "0.9.3", P7_DEVELOPMENT_ARCENGINE_WHEEL_SHA256),
}
_PROBE = r"""
import importlib.metadata as metadata
import json
from pathlib import Path
import sys
import arc_agi
import arcengine
print(json.dumps({
    "prefix": str(Path(sys.prefix).resolve()),
    "arc_agi": {"version": metadata.version("arc-agi"), "module": str(Path(arc_agi.__file__).resolve())},
    "arcengine": {"version": metadata.version("arcengine"), "module": str(Path(arcengine.__file__).resolve())},
}, allow_nan=False, separators=(",", ":"), sort_keys=True))
"""


def _canonical(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()


def _direct_directory(root: Path, name: str) -> Path:
    path = root / name
    try:
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
            raise ValueError
        return path
    except (OSError, ValueError):
        raise P7DevelopmentRuntimeLockError() from None


def _read_direct_regular(root: Path, name: str) -> bytes:
    path = root / name
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ValueError
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 64 * 1024):
                chunks.append(chunk)
            data = b"".join(chunks)
        finally:
            os.close(descriptor)
        after = path.lstat()
        if (before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size):
            raise ValueError
        return data
    except (OSError, ValueError):
        raise P7DevelopmentRuntimeLockError() from None


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@dataclass(frozen=True, repr=False)
class P7DevelopmentRuntimeSet:
    runtime_sha256: str

    def __repr__(self) -> str:
        return "P7DevelopmentRuntimeSet(redacted)"


def verify_p7_development_runtime(root: object) -> P7DevelopmentRuntimeSet:
    """Verify exact local wheels and imports through the selected venv only."""

    try:
        valid_root = isinstance(root, Path) and root.is_absolute() and root.resolve(strict=True) == root
    except OSError:
        valid_root = False
    if not valid_root:
        raise P7DevelopmentRuntimeLockError()
    venv = _direct_directory(root, "venv")
    wheels = _direct_directory(root, "wheels")
    interpreter = venv / "bin" / "python3"
    try:
        if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
            raise ValueError
        if {child.name for child in wheels.iterdir()} != {item[0] for item in _WHEELS.values()}:
            raise ValueError
        wheel_facts: dict[str, dict[str, str]] = {}
        for key, (filename, distribution, version, expected_sha256) in _WHEELS.items():
            data = _read_direct_regular(wheels, filename)
            digest = "sha256:" + sha256(data).hexdigest()
            if digest != expected_sha256:
                raise ValueError
            wheel_facts[key] = {"distribution": distribution, "filename": filename, "sha256": digest, "version": version}
        result = subprocess.run(
            [str(interpreter), "-I", "-c", _PROBE],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            env={"PATH": "/usr/bin:/bin"},
        )
        if len(result.stdout) > 8192:
            raise ValueError
        probe = json.loads(result.stdout.decode("utf-8", "strict"))
        venv_root = venv.resolve(strict=True)
        if type(probe) is not dict or set(probe) != {"prefix", "arc_agi", "arcengine"} or probe["prefix"] != str(venv_root):
            raise ValueError
        imports: dict[str, dict[str, str]] = {}
        for key, (_, _, version, _) in _WHEELS.items():
            item = probe[key]
            if type(item) is not dict or set(item) != {"version", "module"} or item["version"] != version or type(item["module"]) is not str:
                raise ValueError
            module = Path(item["module"])
            if not module.is_absolute() or not _inside(module, venv_root):
                raise ValueError
            imports[key] = {"module": str(module), "version": version}
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise P7DevelopmentRuntimeLockError() from None
    digest = "sha256:" + sha256(_canonical({"format": "asterion.prime-p7-development-runtime/v1", "imports": imports, "wheels": wheel_facts})).hexdigest()
    return P7DevelopmentRuntimeSet(digest)


__all__ = ("P7DevelopmentRuntimeLockError", "P7DevelopmentRuntimeSet", "verify_p7_development_runtime")
