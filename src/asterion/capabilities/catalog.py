"""Deterministic discovery for portable local framework capabilities."""

from __future__ import annotations

import errno
import json
import os
import stat
import sys
from collections.abc import Iterable, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from asterion.capabilities.protocol import CapabilityProtocolError, validate_capability_manifest

if sys.platform == "darwin":
    import fcntl as _fcntl
else:
    _fcntl = None


class CapabilityCatalogError(ValueError):
    """Raised when local capability discovery or selection is ambiguous or invalid."""


@dataclass(frozen=True, order=True, slots=True)
class CapabilityRef:
    capability_id: str
    version: str

    @property
    def selector(self) -> str:
        return f"{self.capability_id}@{self.version}"


@dataclass(frozen=True)
class CatalogEntry:
    ref: CapabilityRef
    source: Path
    manifest: Mapping[str, object]


@dataclass(frozen=True)
class CapabilityCatalog:
    entries: tuple[CatalogEntry, ...]

    def select(
        self, refs: Iterable[CapabilityRef]
    ) -> tuple[dict[str, object], ...]:
        """Return fresh manifests for exact capability identities in stable order."""

        requested = list(refs)
        if len(requested) != len(set(requested)):
            raise CapabilityCatalogError("duplicate capability selection")
        entries = {entry.ref: entry for entry in self.entries}
        missing = next((ref for ref in requested if ref not in entries), None)
        if missing is not None:
            raise CapabilityCatalogError(
                f"unknown capability identity: {missing.capability_id}@{missing.version}"
            )
        return tuple(
            _thaw_manifest(entries[ref].manifest) for ref in sorted(requested)
        )


@dataclass(frozen=True)
class _PinnedRoot:
    path: Path
    fd: int
    identity: tuple[int, int]


_O_DIRECTORY = getattr(os, "O_DIRECTORY", None)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", None)
_O_CLOEXEC_VALUE = getattr(os, "O_CLOEXEC", 0)
_O_CLOEXEC = _O_CLOEXEC_VALUE if isinstance(_O_CLOEXEC_VALUE, int) else 0
_SUPPORTS_DIR_FD = getattr(os, "supports_dir_fd", frozenset())
_SUPPORTS_FD = getattr(os, "supports_fd", frozenset())
_SUPPORTS_FOLLOW_SYMLINKS = getattr(os, "supports_follow_symlinks", frozenset())

_PINNED_DISCOVERY_AVAILABLE = (
    sys.platform in {"darwin", "linux"}
    and isinstance(_O_DIRECTORY, int)
    and isinstance(_O_NOFOLLOW, int)
    and os.open in _SUPPORTS_DIR_FD
    and os.listdir in _SUPPORTS_FD
    and os.stat in _SUPPORTS_DIR_FD
    and os.stat in _SUPPORTS_FOLLOW_SYMLINKS
)


def discover_capabilities(roots: Iterable[Path]) -> CapabilityCatalog:
    """Discover validated direct JSON children under explicit local roots."""

    if not _PINNED_DISCOVERY_AVAILABLE:
        raise CapabilityCatalogError("secure capability discovery is unavailable")

    entries: list[CatalogEntry] = []
    identities: set[CapabilityRef] = set()
    with _pin_roots(roots) as pinned_roots:
        for root in pinned_roots:
            try:
                children = sorted(os.listdir(root.fd))
            except OSError as error:
                raise CapabilityCatalogError(
                    f"catalog root is invalid: {root.path}"
                ) from error
            for name in children:
                if Path(name).suffix != ".json":
                    continue
                source = root.path / name
                manifest = _read_manifest(root, name, source)
                if manifest is None:
                    continue
                capability_id = manifest["capability_id"]
                version = manifest["version"]
                assert isinstance(capability_id, str) and isinstance(version, str)
                ref = CapabilityRef(capability_id, version)
                if ref in identities:
                    raise CapabilityCatalogError(
                        f"duplicate capability identity: {capability_id}@{version}"
                    )
                identities.add(ref)
                entries.append(
                    CatalogEntry(
                        ref=ref,
                        source=source,
                        manifest=_freeze_mapping(manifest),
                    )
                )
    return CapabilityCatalog(
        entries=tuple(sorted(entries, key=lambda entry: (entry.ref, str(entry.source))))
    )


def _secure_directory_open_flags() -> int:
    if not isinstance(_O_DIRECTORY, int) or not isinstance(_O_NOFOLLOW, int):
        raise CapabilityCatalogError("secure capability discovery is unavailable")
    return os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC


def _secure_file_open_flags() -> int:
    if not isinstance(_O_NOFOLLOW, int):
        raise CapabilityCatalogError("secure capability discovery is unavailable")
    return os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC


@contextmanager
def _pin_roots(roots: Iterable[Path]):
    with ExitStack() as descriptors:
        pinned: list[_PinnedRoot] = []
        paths: set[Path] = set()
        identities: set[tuple[int, int]] = set()
        for value in roots:
            root = Path(value)
            descriptor = _open_root(root, descriptors)
            details = os.fstat(descriptor)
            if not stat.S_ISDIR(details.st_mode):
                raise CapabilityCatalogError(f"catalog root is invalid: {root}")
            canonical = _path_from_descriptor(descriptor)
            identity = (details.st_dev, details.st_ino)
            if canonical in paths or identity in identities:
                raise CapabilityCatalogError(f"duplicate catalog root: {canonical}")
            paths.add(canonical)
            identities.add(identity)
            pinned.append(_PinnedRoot(canonical, descriptor, identity))
        yield tuple(sorted(pinned, key=lambda item: str(item.path)))


def _open_root(root: Path, descriptors: ExitStack) -> int:
    components = root.parts[1:] if root.is_absolute() else root.parts
    if ".." in components:
        raise CapabilityCatalogError(f"catalog root is invalid: {root}")

    flags = _secure_directory_open_flags()
    anchor = "/" if root.is_absolute() else "."
    current = _open_directory(
        anchor,
        flags=flags,
        parent_fd=None,
        root=root,
        descriptors=descriptors,
    )
    for component in components:
        if component in {"", "."}:
            continue
        current = _open_directory(
            component,
            flags=flags,
            parent_fd=current,
            root=root,
            descriptors=descriptors,
        )
    return current


def _open_directory(
    name: str,
    *,
    flags: int,
    parent_fd: int | None,
    root: Path,
    descriptors: ExitStack,
) -> int:
    try:
        if parent_fd is None:
            descriptor = os.open(name, flags)
        else:
            descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        if error.errno == errno.ELOOP or (
            error.errno == errno.ENOTDIR
            and parent_fd is not None
            and _is_symlink_at(parent_fd, name)
        ):
            raise CapabilityCatalogError(f"catalog root is a symlink: {root}") from error
        raise CapabilityCatalogError(f"catalog root is invalid: {root}") from error
    descriptors.callback(os.close, descriptor)
    return descriptor


def _is_symlink_at(parent_fd: int, name: str) -> bool:
    try:
        details = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        return stat.S_ISLNK(details.st_mode)
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
        raise CapabilityCatalogError(
            "secure capability discovery is unavailable"
        ) from error
    if not path.is_absolute():
        raise CapabilityCatalogError("secure capability discovery is unavailable")
    return path


def _read_manifest(
    root: _PinnedRoot,
    name: str,
    source: Path,
) -> Mapping[str, object] | None:
    try:
        details = os.stat(name, dir_fd=root.fd, follow_symlinks=False)
    except OSError as error:
        raise CapabilityCatalogError(f"capability document is invalid: {source}") from error
    if stat.S_ISLNK(details.st_mode):
        raise CapabilityCatalogError(f"capability document is a symlink: {source}")
    if not stat.S_ISREG(details.st_mode):
        return None

    flags = _secure_file_open_flags() | getattr(os, "O_NONBLOCK", 0)
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
            raise CapabilityCatalogError(
                f"capability document is a symlink: {source}"
            ) from error
        raise CapabilityCatalogError(f"capability document is invalid: {source}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if not isinstance(manifest, dict):
        raise CapabilityCatalogError(f"capability document is invalid: {source}")
    try:
        return validate_capability_manifest(manifest)
    except CapabilityProtocolError as error:
        raise CapabilityCatalogError(f"capability document is invalid: {source}") from error


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
