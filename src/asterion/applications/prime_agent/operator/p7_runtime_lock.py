"""Fail-closed lock for P7's operator-owned ARC runtime."""

from __future__ import annotations

import base64
import csv
from dataclasses import dataclass
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import zipfile

from .p7_development_workload import P7_DEVELOPMENT_ARC_AGI_WHEEL_SHA256, P7_DEVELOPMENT_ARCENGINE_WHEEL_SHA256


class P7DevelopmentRuntimeLockError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 development runtime is invalid")


_WHEELS = {
    "arc_agi": ("arc_agi-0.9.9-py3-none-any.whl", "arc-agi", "0.9.9", P7_DEVELOPMENT_ARC_AGI_WHEEL_SHA256),
    "arcengine": ("arcengine-0.9.3-py3-none-any.whl", "arcengine", "0.9.3", P7_DEVELOPMENT_ARCENGINE_WHEEL_SHA256),
}
_PROBE = r'''
import importlib.metadata as metadata
import json
from pathlib import Path
import sys
import sysconfig
import arc_agi
import arcengine
print(json.dumps({
    "prefix": str(Path(sys.prefix).resolve()),
    "site_packages": str(Path(sysconfig.get_path("purelib")).resolve()),
    "arc_agi": {"version": metadata.version("arc-agi"), "module": str(Path(arc_agi.__file__).resolve())},
    "arcengine": {"version": metadata.version("arcengine"), "module": str(Path(arcengine.__file__).resolve())},
}, allow_nan=False, separators=(",", ":"), sort_keys=True))
'''
_INSTALLER_GENERATED = frozenset({"INSTALLER", "REQUESTED"})


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
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_mode & 0o111:
            raise ValueError
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
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


def _wheel_members(wheel: bytes, distribution: str, version: str) -> dict[str, bytes]:
    """Return the wheel's closed, hash-verified installed member inventory."""
    dist_info = distribution.replace("-", "_") + f"-{version}.dist-info"
    record_name = f"{dist_info}/RECORD"
    try:
        archive = zipfile.ZipFile(io.BytesIO(wheel))
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or any(not name or name.startswith("/") or "\\" in name or ".." in name.split("/") for name in names):
            raise ValueError
        for item in infos:
            mode = item.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if item.is_dir():
                if file_type not in (0, stat.S_IFDIR):
                    raise ValueError
            elif file_type not in (0, stat.S_IFREG) or mode & 0o111:
                raise ValueError
        files = {item.filename: archive.read(item) for item in infos if not item.is_dir()}
        if record_name not in files or any(item.is_dir() and not item.filename.endswith("/") for item in infos):
            raise ValueError
        rows = list(csv.reader(io.StringIO(files[record_name].decode("utf-8", "strict"))))
        record: dict[str, tuple[str, str]] = {}
        for row in rows:
            if len(row) != 3 or row[0] in record or row[0] not in files:
                raise ValueError
            record[row[0]] = (row[1], row[2])
        if set(record) != set(files) or record[record_name] != ("", ""):
            raise ValueError
        for name, content in files.items():
            encoded, size = record[name]
            if name == record_name:
                continue
            expected = "sha256=" + base64.urlsafe_b64encode(sha256(content).digest()).rstrip(b"=").decode("ascii")
            if encoded != expected or size != str(len(content)):
                raise ValueError
        if any(not (name.endswith((".py", ".md", ".typed")) or name.endswith(("/WHEEL", "/METADATA", "/RECORD"))) for name in files):
            raise ValueError
        return files
    except (OSError, UnicodeDecodeError, ValueError, zipfile.BadZipFile):
        raise P7DevelopmentRuntimeLockError() from None


def _verify_installed_wheel(site_packages: Path, members: dict[str, bytes], distribution: str, version: str) -> dict[str, str]:
    """Compare the installed pure-Python package with its verified wheel inventory."""
    dist_info = distribution.replace("-", "_") + f"-{version}.dist-info"
    roots = {name.split("/", 1)[0] for name in members}
    if roots != {distribution.replace("-", "_"), dist_info}:
        raise P7DevelopmentRuntimeLockError()
    expected = set(members)
    observed: set[str] = set()
    installed_hashes: dict[str, str] = {}
    for top in sorted(roots):
        directory = _direct_directory(site_packages, top)
        for child in directory.iterdir():
            name = child.name
            relative = f"{top}/{name}"
            if name == "__pycache__" and top != dist_info:
                cache = _direct_directory(directory, name)
                for bytecode in cache.iterdir():
                    if bytecode.is_dir() or bytecode.is_symlink() or not bytecode.name.endswith(".pyc"):
                        raise P7DevelopmentRuntimeLockError()
                    _read_direct_regular(cache, bytecode.name)
                continue
            if top == dist_info and name in _INSTALLER_GENERATED:
                if child.is_dir() or child.is_symlink():
                    raise P7DevelopmentRuntimeLockError()
                _read_direct_regular(directory, name)
                continue
            if child.is_dir() or child.is_symlink() or relative not in expected:
                raise P7DevelopmentRuntimeLockError()
            observed.add(relative)
            data = _read_direct_regular(directory, name)
            if relative == f"{dist_info}/RECORD":
                rows = list(csv.reader(io.StringIO(data.decode("utf-8", "strict"))))
                names = {row[0] for row in rows if len(row) == 3}
                allowed = expected | {f"{dist_info}/{item}" for item in _INSTALLER_GENERATED}
                if len(rows) != len(names) or names != allowed:
                    raise P7DevelopmentRuntimeLockError()
                continue
            if data != members[relative]:
                raise P7DevelopmentRuntimeLockError()
            installed_hashes[relative] = "sha256:" + sha256(data).hexdigest()
    if observed != expected:
        raise P7DevelopmentRuntimeLockError()
    return {name: installed_hashes[name] for name in sorted(installed_hashes)}


@dataclass(frozen=True, repr=False)
class P7DevelopmentRuntimeSet:
    runtime_sha256: str

    def __repr__(self) -> str:
        return "P7DevelopmentRuntimeSet(redacted)"


def verify_p7_development_runtime(root: object) -> P7DevelopmentRuntimeSet:
    """Verify exact wheels and their installed pure-Python files in the selected venv."""
    try:
        valid_root = isinstance(root, Path) and root.is_absolute() and root.resolve(strict=True) == root
    except OSError:
        valid_root = False
    if not valid_root:
        raise P7DevelopmentRuntimeLockError()
    try:
        venv = _direct_directory(root, "venv")
        wheels = _direct_directory(root, "wheels")
        interpreter = venv / "bin" / "python3"
        if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
            raise ValueError
        if {child.name for child in wheels.iterdir()} != {item[0] for item in _WHEELS.values()}:
            raise ValueError
        wheel_facts: dict[str, dict[str, object]] = {}
        for key, (filename, distribution, version, expected_sha256) in _WHEELS.items():
            data = _read_direct_regular(wheels, filename)
            digest = "sha256:" + sha256(data).hexdigest()
            if digest != expected_sha256:
                raise ValueError
            wheel_facts[key] = {"files": _wheel_members(data, distribution, version), "sha256": digest}
        result = subprocess.run([str(interpreter), "-I", "-c", _PROBE], check=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, env={"PATH": "/usr/bin:/bin"})
        if len(result.stdout) > 8192:
            raise ValueError
        probe = json.loads(result.stdout.decode("utf-8", "strict"))
        venv_root = venv.resolve(strict=True)
        if type(probe) is not dict or set(probe) != {"prefix", "site_packages", "arc_agi", "arcengine"} or probe["prefix"] != str(venv_root):
            raise ValueError
        site_packages = Path(probe["site_packages"])
        if not site_packages.is_absolute() or not _inside(site_packages, venv_root):
            raise ValueError
        _direct_directory(site_packages.parent, site_packages.name)
        installed: dict[str, dict[str, object]] = {}
        for key, (_, distribution, version, _) in _WHEELS.items():
            item = probe[key]
            if type(item) is not dict or set(item) != {"version", "module"} or item["version"] != version or type(item["module"]) is not str:
                raise ValueError
            module = Path(item["module"])
            package = distribution.replace("-", "_")
            if not module.is_absolute() or not _inside(module, site_packages) or module != site_packages / package / "__init__.py":
                raise ValueError
            installed[key] = {"files": _verify_installed_wheel(site_packages, wheel_facts[key]["files"], distribution, version), "module": str(module), "version": version}
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise P7DevelopmentRuntimeLockError() from None
    digest = "sha256:" + sha256(_canonical({"format": "asterion.prime-p7-development-runtime/v2", "installed": installed, "wheels": {key: facts["sha256"] for key, facts in wheel_facts.items()}})).hexdigest()
    return P7DevelopmentRuntimeSet(digest)


__all__ = ("P7DevelopmentRuntimeLockError", "P7DevelopmentRuntimeSet", "verify_p7_development_runtime")
