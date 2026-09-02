"""Create a closed, reproducible input archive for the Prime IPython image.

This module deliberately does not invoke an image engine.  An operator may pass
the resulting bytes to a separately authorized engine invocation, but normal
verification only constructs and inspects the deterministic input.
"""

from __future__ import annotations

from dataclasses import dataclass
import argparse
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import stat
import tarfile
from typing import Final

from asterion.applications.prime_agent.source_lock import (
    PrimeSourceLock,
    PrimeSourceLockError,
    verify_prime_source_lock,
)


_EXCLUDED_NAMES: Final = frozenset({".git", "node_modules", ".cache", "cache", ".pytest_cache", "__pycache__"})
_SOURCE_LOCK_EXCLUDED_NAMES: Final = frozenset({".git", "node_modules"})
_IMAGE_PREFIX: Final = "src/asterion/applications/prime_agent/operator/image"


class PrimeIpythonImageError(ValueError):
    """Raised when a closed image input or private operator record is invalid."""


@dataclass(frozen=True)
class PrimeIpythonBuildContext:
    """Canonical bytes and public-safe provenance for an operator build input."""

    tar_bytes: bytes
    build_input_sha256: str
    source_commit: str
    source_tree_sha256: str
    source_package_lock_sha256: str
    asset_sha256: str


@dataclass(frozen=True)
class _CapturedFile:
    relative: str
    data: bytes
    mode: int


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def image_root() -> Path:
    return repository_root() / _IMAGE_PREFIX


def canonical_build_context(root: Path, lock: PrimeSourceLock) -> PrimeIpythonBuildContext:
    """Return a canonical tar after exact source identity verification."""

    try:
        verified = verify_prime_source_lock(root, lock)
    except (PrimeSourceLockError, TypeError, ValueError) as error:
        raise PrimeIpythonImageError("Prime image input is invalid") from error
    source_root = _absolute_directory(root)
    assets = _absolute_directory(image_root())
    source_files = _capture_files(source_root, source=True)
    if _source_tree_digest(source_files) != verified.tree_sha256 or _package_lock_digest(source_files) != verified.package_lock_sha256:
        raise PrimeIpythonImageError("Prime image input is invalid")
    asset_files = _capture_files(assets, source=False)
    entries = [
        *((f"prime/{item.relative}", item) for item in source_files if not _context_excluded(item.relative)),
        *((f"image/{item.relative}", item) for item in asset_files if not _context_excluded(item.relative)),
    ]
    if not entries or len({name for name, _ in entries}) != len(entries):
        raise PrimeIpythonImageError("Prime image input is invalid")
    archive = io.BytesIO()
    try:
        with tarfile.open(fileobj=archive, mode="w", format=tarfile.GNU_FORMAT) as output:
            for name, captured in sorted(entries):
                member = tarfile.TarInfo(name)
                member.size = len(captured.data)
                member.mode = captured.mode
                member.uid = member.gid = member.mtime = 0
                member.uname = member.gname = ""
                output.addfile(member, io.BytesIO(captured.data))
    except (OSError, tarfile.TarError) as error:
        raise PrimeIpythonImageError("Prime image input is invalid") from error
    tar_bytes = archive.getvalue()
    assets_digest = _digest_files(asset_files)
    return PrimeIpythonBuildContext(
        tar_bytes=tar_bytes,
        build_input_sha256=sha256(tar_bytes).hexdigest(),
        source_commit=verified.commit,
        source_tree_sha256=verified.tree_sha256,
        source_package_lock_sha256=verified.package_lock_sha256,
        asset_sha256=assets_digest,
    )


def write_operator_image_config(target: Path, image_config_id: str) -> None:
    """Record the local config ID only in a caller-selected private location."""

    if not _is_config_id(image_config_id) or not isinstance(target, Path) or not target.is_absolute():
        raise PrimeIpythonImageError("Prime image input is invalid")
    try:
        resolved = target.resolve(strict=False)
        repository = repository_root().resolve(strict=True)
        if resolved == repository or repository in resolved.parents or target.name == ".env":
            raise ValueError
        parent = resolved.parent.resolve(strict=True)
        if not parent.is_dir() or parent.is_symlink():
            raise ValueError
        if target.exists() and (target.is_symlink() or not stat.S_ISREG(target.stat().st_mode)):
            raise ValueError
        descriptor = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, json.dumps({"image_config_id": image_config_id}, separators=(",", ":")).encode() + b"\n")
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as error:
        raise PrimeIpythonImageError("Prime image input is invalid") from error


def operator_build_command() -> tuple[str, ...]:
    """Return, but never run, the exact engine command for a tar on standard input."""

    return ("docker", "build", "--pull=never", "--file", "image/Dockerfile", "-")


def main() -> int:
    """Write only a caller-selected canonical context; engine execution is external."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tree-sha256", required=True)
    parser.add_argument("--package-lock-sha256", required=True)
    parser.add_argument("--context-output", required=True, type=Path)
    args = parser.parse_args()
    context = canonical_build_context(
        args.source_root,
        PrimeSourceLock(args.commit, args.tree_sha256, args.package_lock_sha256),
    )
    write_context_output(args.context_output, context.tar_bytes, _absolute_directory(args.source_root))
    return 0


def write_context_output(target: Path, payload: bytes, source_root: Path) -> None:
    """Create one private external context file without replacing any existing path."""

    if not isinstance(target, Path) or not isinstance(payload, bytes):
        raise PrimeIpythonImageError("Prime image input is invalid")
    source = _absolute_directory(source_root)
    try:
        if not target.is_absolute() or _unsafe_output_path(target):
            raise ValueError
        resolved = target.resolve(strict=False)
        repository = repository_root().resolve(strict=True)
        if _contained_by(resolved, repository) or _contained_by(resolved, source):
            raise ValueError
        parent = resolved.parent.resolve(strict=True)
        if not parent.is_dir() or parent.is_symlink() or target.exists():
            raise ValueError
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory = os.open(parent, directory_flags)
        try:
            descriptor = os.open(
                resolved.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            try:
                os.fchmod(descriptor, 0o600)
                offset = 0
                while offset < len(payload):
                    written = os.write(descriptor, payload[offset:])
                    if written <= 0:
                        raise OSError("incomplete write")
                    offset += written
            finally:
                os.close(descriptor)
        finally:
            os.close(directory)
    except (OSError, ValueError) as error:
        raise PrimeIpythonImageError("Prime image input is invalid") from error


def _absolute_directory(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        raise PrimeIpythonImageError("Prime image input is invalid")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise PrimeIpythonImageError("Prime image input is invalid") from error
    if path != resolved or not resolved.is_dir():
        raise PrimeIpythonImageError("Prime image input is invalid")
    return resolved


def source_tree_sha256(root: Path) -> str:
    """Return the source-lock tree digest from a no-follow byte snapshot."""

    return _source_tree_digest(_capture_files(_absolute_directory(root), source=True))


def _capture_files(root: Path, *, source: bool) -> tuple[_CapturedFile, ...]:
    files: list[_CapturedFile] = []
    try:
        for directory, names, file_names in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            for name in names:
                if not stat.S_ISDIR((directory_path / name).lstat().st_mode):
                    raise ValueError
            names[:] = sorted(
                name
                for name in names
                if not (name in _SOURCE_LOCK_EXCLUDED_NAMES if source else _excluded_name(name))
            )
            for name in sorted(file_names):
                path = directory_path / name
                relative = path.relative_to(root).as_posix()
                if not source and _context_excluded(relative):
                    continue
                files.append(_capture_file(path, relative))
    except (OSError, ValueError) as error:
        raise PrimeIpythonImageError("Prime image input is invalid") from error
    return tuple(sorted(files, key=lambda item: item.relative))


def _capture_file(path: Path, relative: str) -> _CapturedFile:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        after = path.lstat()
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
            raise ValueError
        return _CapturedFile(relative, b"".join(chunks), 0o755 if opened.st_mode & 0o111 else 0o644)
    finally:
        os.close(descriptor)


def _source_tree_digest(files: tuple[_CapturedFile, ...]) -> str:
    digest = sha256()
    for captured in files:
        if captured.relative.rsplit("/", 1)[-1] == "package-lock.json":
            continue
        digest.update(captured.relative.encode())
        digest.update(b"\0")
        digest.update(captured.data)
        digest.update(b"\0")
    return digest.hexdigest()


def _package_lock_digest(files: tuple[_CapturedFile, ...]) -> str:
    matches = [item for item in files if item.relative == "package-lock.json"]
    if len(matches) != 1:
        raise PrimeIpythonImageError("Prime image input is invalid")
    return sha256(matches[0].data).hexdigest()


def _digest_files(files: tuple[_CapturedFile, ...]) -> str:
    digest = sha256()
    for captured in files:
        digest.update(captured.relative.encode())
        digest.update(b"\0")
        digest.update(captured.data)
        digest.update(b"\0")
    return digest.hexdigest()


def _is_config_id(value: object) -> bool:
    return type(value) is str and len(value) == 71 and value.startswith("sha256:") and all(character in "0123456789abcdef" for character in value[7:])


def _contained_by(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _unsafe_output_path(path: Path) -> bool:
    if _excluded_name(path.name):
        return True
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if _excluded_name(component) or current.is_symlink():
            return True
    return False


def _excluded_name(name: str) -> bool:
    return name in _EXCLUDED_NAMES or name == ".env" or name.startswith(".env.")


def _context_excluded(relative: str) -> bool:
    return any(_excluded_name(component) for component in relative.split("/"))


if __name__ == "__main__":
    raise SystemExit(main())
