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
    entries = [
        *( (f"prime/{relative}", path) for relative, path in _closed_files(source_root) ),
        *( (f"image/{relative}", path) for relative, path in _closed_files(assets) ),
    ]
    if not entries or len({name for name, _ in entries}) != len(entries):
        raise PrimeIpythonImageError("Prime image input is invalid")
    archive = io.BytesIO()
    try:
        with tarfile.open(fileobj=archive, mode="w", format=tarfile.GNU_FORMAT) as output:
            for name, path in sorted(entries):
                data = path.read_bytes()
                member = tarfile.TarInfo(name)
                member.size = len(data)
                member.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                member.uid = member.gid = member.mtime = 0
                member.uname = member.gname = ""
                output.addfile(member, io.BytesIO(data))
    except (OSError, tarfile.TarError) as error:
        raise PrimeIpythonImageError("Prime image input is invalid") from error
    tar_bytes = archive.getvalue()
    assets_digest = _digest_files(_closed_files(assets))
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
    target = args.context_output
    if not target.is_absolute() or target.is_symlink() or target.resolve(strict=False) == repository_root():
        raise PrimeIpythonImageError("Prime image input is invalid")
    target.write_bytes(context.tar_bytes)
    return 0


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


def _closed_files(root: Path) -> tuple[tuple[str, Path], ...]:
    files: list[tuple[str, Path]] = []
    try:
        for directory, names, file_names in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            names[:] = sorted(name for name in names if not _excluded_name(name))
            for name in sorted(file_names):
                path = directory_path / name
                if _excluded_name(name):
                    continue
                if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
                    raise ValueError
                files.append((path.relative_to(root).as_posix(), path))
    except (OSError, ValueError) as error:
        raise PrimeIpythonImageError("Prime image input is invalid") from error
    return tuple(sorted(files))


def _digest_files(files: tuple[tuple[str, Path], ...]) -> str:
    digest = sha256()
    for relative, path in files:
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _is_config_id(value: object) -> bool:
    return type(value) is str and len(value) == 71 and value.startswith("sha256:") and all(character in "0123456789abcdef" for character in value[7:])


def _excluded_name(name: str) -> bool:
    return name in _EXCLUDED_NAMES or name == ".env" or name.startswith(".env.")


if __name__ == "__main__":
    raise SystemExit(main())
