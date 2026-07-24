"""Deterministic discovery for portable local framework packages."""

from __future__ import annotations

import errno
import json
import os
import stat
import sys
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from asterion.packages.protocol import PackageProtocolError, validate_package_manifest

if sys.platform == "darwin":
    import fcntl as _fcntl
else:
    _fcntl = None


class PackageCatalogError(ValueError):
    """Raised when local package discovery or selection is ambiguous or invalid."""


@dataclass(frozen=True, order=True)
class PackageRef:
    package_id: str
    version: str


@dataclass(frozen=True)
class CatalogEntry:
    ref: PackageRef
    source: Path
    manifest: Mapping[str, object]


@dataclass(frozen=True)
class PackageCatalog:
    entries: tuple[CatalogEntry, ...]

    def select(
        self, refs: Iterable[PackageRef]
    ) -> tuple[dict[str, object], ...]:
        """Return fresh manifests for exact package identities in stable order."""

        requested = list(refs)
        if len(requested) != len(set(requested)):
            raise PackageCatalogError("duplicate package selection")
        entries = {entry.ref: entry for entry in self.entries}
        missing = next((ref for ref in requested if ref not in entries), None)
        if missing is not None:
            raise PackageCatalogError(
                f"unknown package identity: {missing.package_id}@{missing.version}"
            )
        return tuple(
            _thaw_manifest(entries[ref].manifest) for ref in sorted(requested)
        )


@dataclass(frozen=True)
class _PinnedRoot:
    path: Path
    fd: int
    identity: tuple[int, int]


_PINNED_DISCOVERY_AVAILABLE = (
    sys.platform in {"darwin", "linux"}
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    and os.open in os.supports_dir_fd
    and os.listdir in os.supports_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
)


def discover_packages(roots: Iterable[Path]) -> PackageCatalog:
    """Discover validated direct JSON children under explicit local roots."""

    if not _PINNED_DISCOVERY_AVAILABLE:
        raise PackageCatalogError("secure package discovery is unavailable")

    entries: list[CatalogEntry] = []
    identities: set[PackageRef] = set()
    with _pin_roots(roots) as pinned_roots:
        for root in pinned_roots:
            try:
                children = sorted(os.listdir(root.fd))
            except OSError as error:
                raise PackageCatalogError(
                    f"catalog root is invalid: {root.path}"
                ) from error
            for name in children:
                if Path(name).suffix != ".json":
                    continue
                source = root.path / name
                manifest = _read_manifest(root, name, source)
                if manifest is None:
                    continue
                package_id = manifest["package_id"]
                version = manifest["version"]
                assert isinstance(package_id, str) and isinstance(version, str)
                ref = PackageRef(package_id, version)
                if ref in identities:
                    raise PackageCatalogError(
                        f"duplicate package identity: {package_id}@{version}"
                    )
                identities.add(ref)
                entries.append(
                    CatalogEntry(
                        ref=ref,
                        source=source,
                        manifest=_freeze_mapping(manifest),
                    )
                )
    return PackageCatalog(
        entries=tuple(sorted(entries, key=lambda entry: (entry.ref, str(entry.source))))
    )


@contextmanager
def _pin_roots(roots: Iterable[Path]):
    pinned: list[_PinnedRoot] = []
    paths: set[Path] = set()
    identities: set[tuple[int, int]] = set()
    try:
        for value in roots:
            root = Path(value)
            descriptor = _open_root(root)
            try:
                details = os.fstat(descriptor)
                if not stat.S_ISDIR(details.st_mode):
                    raise PackageCatalogError(f"catalog root is invalid: {root}")
                canonical = _path_from_descriptor(descriptor)
                identity = (details.st_dev, details.st_ino)
                if canonical in paths or identity in identities:
                    raise PackageCatalogError(
                        f"duplicate catalog root: {canonical}"
                    )
                paths.add(canonical)
                identities.add(identity)
                pinned.append(_PinnedRoot(canonical, descriptor, identity))
            except Exception:
                os.close(descriptor)
                raise
        yield tuple(sorted(pinned, key=lambda item: str(item.path)))
    finally:
        for root in pinned:
            os.close(root.fd)


def _open_root(root: Path) -> int:
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        return os.open(root, flags)
    except OSError as error:
        if error.errno == errno.ELOOP or (
            error.errno == errno.ENOTDIR and _is_symlink(root)
        ):
            raise PackageCatalogError(f"catalog root is a symlink: {root}") from error
        raise PackageCatalogError(f"catalog root is invalid: {root}") from error


def _is_symlink(path: Path) -> bool:
    try:
        return stat.S_ISLNK(os.stat(path, follow_symlinks=False).st_mode)
    except OSError:
        return False


def _path_from_descriptor(descriptor: int) -> Path:
    try:
        if sys.platform == "darwin":
            assert _fcntl is not None
            value = _fcntl.fcntl(descriptor, 50, b"\0" * 1024)
            encoded = value.split(b"\0", 1)[0]
            if not encoded:
                raise OSError("empty descriptor path")
            path = Path(os.fsdecode(encoded))
        elif sys.platform == "linux":
            value = os.readlink(f"/proc/self/fd/{descriptor}")
            if value.endswith(" (deleted)"):
                raise OSError("deleted descriptor path")
            path = Path(value)
        else:
            raise OSError("unsupported descriptor path")
    except OSError as error:
        raise PackageCatalogError(
            "secure package discovery is unavailable"
        ) from error
    if not path.is_absolute():
        raise PackageCatalogError("secure package discovery is unavailable")
    return path


def _read_manifest(
    root: _PinnedRoot,
    name: str,
    source: Path,
) -> dict[str, object] | None:
    try:
        details = os.stat(name, dir_fd=root.fd, follow_symlinks=False)
    except OSError as error:
        raise PackageCatalogError(f"package document is invalid: {source}") from error
    if stat.S_ISLNK(details.st_mode):
        raise PackageCatalogError(f"package document is a symlink: {source}")
    if not stat.S_ISREG(details.st_mode):
        return None

    flags = (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(name, flags, dir_fd=root.fd)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            return None
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            descriptor = -1
            manifest = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        if isinstance(error, OSError) and error.errno == errno.ELOOP:
            raise PackageCatalogError(
                f"package document is a symlink: {source}"
            ) from error
        raise PackageCatalogError(f"package document is invalid: {source}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if not isinstance(manifest, dict):
        raise PackageCatalogError(f"package document is invalid: {source}")
    try:
        validate_package_manifest(manifest)
    except PackageProtocolError as error:
        raise PackageCatalogError(f"package document is invalid: {source}") from error
    return manifest


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze(item) for key, item in value.items()})


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw_manifest(manifest: Mapping[str, object]) -> dict[str, object]:
    thawed = _thaw(manifest)
    assert isinstance(thawed, dict)
    return thawed


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value
