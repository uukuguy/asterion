"""Exact, read-only identity verification for the pinned Prime source."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import Final


_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REF_COMPONENT = re.compile(r"[A-Za-z0-9._-]+")
_LOCK_FIELDS: Final = frozenset({"commit", "tree_sha256", "package_lock_sha256"})
_EXCLUDED_SOURCE_NAMES: Final = frozenset({".git", "node_modules", "package-lock.json"})
_GENERATED_SOURCE_DIRECTORIES: Final = frozenset({"dist", "dist-chrome", "dist-firefox"})


class PrimeSourceLockError(ValueError):
    """Raised when the configured Prime source differs from its exact lock."""


@dataclass(frozen=True)
class PrimeSourceLock:
    """The exact Git commit and canonical source/package-lock digests."""

    commit: str
    tree_sha256: str
    package_lock_sha256: str


def verify_prime_source_lock(root: Path, lock: PrimeSourceLock) -> PrimeSourceLock:
    """Fail closed unless *root* exactly matches the declared immutable lock.

    The source digest covers regular tracked-source inputs only: all files below
    the root except Git metadata, installed dependencies, and the separately
    declared ``package-lock.json``.  Paths and bytes are delimited and sorted
    so platform directory iteration cannot affect the result.
    """

    _validate_lock(lock)
    source_root = _canonical_root(root)
    if _read_commit(source_root) != lock.commit:
        raise PrimeSourceLockError("Prime source lock is invalid")
    package_lock = source_root / "package-lock.json"
    if not _regular_file(package_lock) or _file_sha256(package_lock) != lock.package_lock_sha256:
        raise PrimeSourceLockError("Prime source lock is invalid")
    _validate_package_versions(source_root, package_lock)
    if _tree_sha256(source_root) != lock.tree_sha256:
        raise PrimeSourceLockError("Prime source lock is invalid")
    return lock


def _validate_lock(lock: object) -> None:
    if (
        type(lock) is not PrimeSourceLock
        or frozenset(vars(lock)) != _LOCK_FIELDS
        or type(lock.commit) is not str
        or _COMMIT.fullmatch(lock.commit) is None
        or type(lock.tree_sha256) is not str
        or _SHA256.fullmatch(lock.tree_sha256) is None
        or type(lock.package_lock_sha256) is not str
        or _SHA256.fullmatch(lock.package_lock_sha256) is None
    ):
        raise PrimeSourceLockError("Prime source lock is invalid")


def _canonical_root(root: object) -> Path:
    if not isinstance(root, Path) or root.is_symlink() or not root.is_absolute():
        raise PrimeSourceLockError("Prime source lock is invalid")
    try:
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise PrimeSourceLockError("Prime source lock is invalid") from error
    if root != resolved or not resolved.is_dir():
        raise PrimeSourceLockError("Prime source lock is invalid")
    return resolved


def _read_commit(root: Path) -> str:
    git_dir = root / ".git"
    head = git_dir / "HEAD"
    if not git_dir.is_dir() or git_dir.is_symlink() or not _regular_file(head):
        raise PrimeSourceLockError("Prime source lock is invalid")
    try:
        value = head.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise PrimeSourceLockError("Prime source lock is invalid") from error
    if value.startswith("ref: "):
        reference = value.removeprefix("ref: ")
        ref_path = _reference_path(git_dir, reference)
        if _regular_file(ref_path):
            try:
                value = ref_path.read_text(encoding="ascii").strip()
            except (OSError, UnicodeDecodeError) as error:
                raise PrimeSourceLockError("Prime source lock is invalid") from error
        else:
            value = _packed_ref(git_dir / "packed-refs", reference)
    if _COMMIT.fullmatch(value) is None:
        raise PrimeSourceLockError("Prime source lock is invalid")
    return value


def _reference_path(git_dir: Path, reference: str) -> Path:
    """Return a regular ref path only when it is contained in ``.git/refs``."""

    components = reference.split("/")
    if (
        len(components) < 2
        or components[0] != "refs"
        or any(
            component in {"", ".", ".."}
            or _REF_COMPONENT.fullmatch(component) is None
            for component in components[1:]
        )
    ):
        raise PrimeSourceLockError("Prime source lock is invalid")
    refs_root = git_dir / "refs"
    if not _directory(refs_root) or refs_root.is_symlink():
        raise PrimeSourceLockError("Prime source lock is invalid")
    ref_path = refs_root.joinpath(*components[1:])
    try:
        if refs_root.resolve(strict=True) not in ref_path.resolve(strict=False).parents:
            raise PrimeSourceLockError("Prime source lock is invalid")
    except OSError as error:
        raise PrimeSourceLockError("Prime source lock is invalid") from error
    return ref_path


def _packed_ref(path: Path, reference: str) -> str:
    if not _regular_file(path):
        raise PrimeSourceLockError("Prime source lock is invalid")
    try:
        for line in path.read_text(encoding="ascii").splitlines():
            commit, separator, name = line.partition(" ")
            if separator and name == reference and _COMMIT.fullmatch(commit):
                return commit
    except (OSError, UnicodeDecodeError) as error:
        raise PrimeSourceLockError("Prime source lock is invalid") from error
    raise PrimeSourceLockError("Prime source lock is invalid")


def _tree_sha256(root: Path) -> str:
    digest = sha256()
    files: list[Path] = []
    try:
        for directory, directory_names, file_names in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            for name in directory_names:
                if not _directory(directory_path / name):
                    raise PrimeSourceLockError("Prime source lock is invalid")
            directory_names[:] = sorted(
                name
                for name in directory_names
                if name not in _EXCLUDED_SOURCE_NAMES
                and name not in _GENERATED_SOURCE_DIRECTORIES
            )
            for name in sorted(file_names):
                path = directory_path / name
                if not _regular_file(path):
                    raise PrimeSourceLockError("Prime source lock is invalid")
                if path.name in _EXCLUDED_SOURCE_NAMES or path.name.endswith(".tsbuildinfo"):
                    continue
                files.append(path)
    except OSError as error:
        raise PrimeSourceLockError("Prime source lock is invalid") from error
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative_path = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative_path)
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError as error:
            raise PrimeSourceLockError("Prime source lock is invalid") from error
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_package_versions(root: Path, package_lock: Path) -> None:
    package_json = root / "package.json"
    if not _regular_file(package_json):
        raise PrimeSourceLockError("Prime source lock is invalid")
    try:
        package = json.loads(package_json.read_text(encoding="utf-8"))
        lock = json.loads(package_lock.read_text(encoding="utf-8"))
        package_version = package["version"]
        lock_version = lock["packages"][""]["version"]
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise PrimeSourceLockError("Prime source lock is invalid") from error
    if type(package_version) is not str or package_version != lock_version:
        raise PrimeSourceLockError("Prime source lock is invalid")


def _file_sha256(path: Path) -> str:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise PrimeSourceLockError("Prime source lock is invalid") from error


def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False
