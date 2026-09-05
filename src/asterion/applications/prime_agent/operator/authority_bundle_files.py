"""Private descriptor-relative verification for authority bundle contents."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
import stat

from .authority_bundle import (
    AuthorityBundleError,
    AuthorityBundleFile,
    AuthorityExternalRuntimeFile,
)
from .image_input_lock import ImagePlatformDescriptor, validate_image_platform_descriptor


_PART = re.compile(r"[A-Za-z0-9_.-]+\Z")
_MODES = frozenset((0o444, 0o555, 0o644, 0o755))
_MAX_FILE_BYTES = 512 * 1024 * 1024
_READ_SIZE = 1024 * 1024
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedBundleFiles:
    """Verified identities; the caller owns and must close ``interpreter_fd``."""

    interpreter_fd: int
    root_identity: tuple[int, ...]
    interpreter_identity: tuple[int, ...]


def verify_authority_bundle_files(
    root_fd: int,
    files: tuple[AuthorityBundleFile, ...],
    interpreter_path: str,
    target: ImagePlatformDescriptor,
    inventory_identity: tuple[int, int],
) -> VerifiedBundleFiles:
    """Verify an exact private bundle tree without taking ownership of ``root_fd``."""
    interpreter_fd: int | None = None
    opened: list[int] = []
    try:
        _required_open_flags()
        _descriptor(root_fd)
        records = _bundle_records(files, interpreter_path)
        target = validate_image_platform_descriptor(target)
        if target not in (ImagePlatformDescriptor("linux", "arm64", None), ImagePlatformDescriptor("linux", "amd64", None)):
            raise ValueError
        if type(inventory_identity) is not tuple or len(inventory_identity) != 2 or any(type(value) is not int for value in inventory_identity):
            raise ValueError
        root_identity = _directory_identity(root_fd)
        if root_identity[:2] == inventory_identity:
            raise ValueError
        expected_dirs = _expected_directories(records)
        expected_children = _expected_children(records, expected_dirs)
        directories: dict[str, tuple[int, tuple[int, ...]]] = {"": (root_fd, root_identity)}
        for path in sorted(expected_dirs, key=lambda value: (value.count("/"), value)):
            parent, name = path.rsplit("/", 1) if "/" in path else ("", path)
            parent_fd, parent_identity = directories[parent]
            _same_directory(parent_fd, parent_identity)
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW | _CLOEXEC, dir_fd=parent_fd)
            opened.append(fd)
            identity = _directory_identity(fd)
            if identity[:2] == inventory_identity:
                raise ValueError
            directories[path] = (fd, identity)
            _same_directory(parent_fd, parent_identity)
        for path, (fd, identity) in directories.items():
            _same_directory(fd, identity)
            if identity[:2] == inventory_identity or set(os.listdir(fd)) != expected_children[path]:
                raise ValueError
            _same_directory(fd, identity)
        interpreter_identity: tuple[int, ...] | None = None
        for record in records:
            parent = record.path.rpartition("/")[0]
            parent_fd, parent_identity = directories[parent]
            _same_directory(parent_fd, parent_identity)
            fd = os.open(record.path.rpartition("/")[2], os.O_RDONLY | _NOFOLLOW | _CLOEXEC | _NONBLOCK, dir_fd=parent_fd)
            try:
                identity = _regular_identity(fd, record)
                if identity[:2] == inventory_identity or _digest_fd(fd, identity) != record.sha256:
                    raise ValueError
                if record.path == interpreter_path:
                    _elf_target(fd, target)
                    interpreter_fd, interpreter_identity = fd, identity
                    fd = -1
            finally:
                if fd >= 0:
                    _close(fd)
            _same_directory(parent_fd, parent_identity)
        for fd, identity in directories.values():
            _same_directory(fd, identity)
        if interpreter_fd is None or interpreter_identity is None:
            raise ValueError
        result = VerifiedBundleFiles(interpreter_fd, root_identity, interpreter_identity)
        interpreter_fd = None
        return result
    except Exception:
        raise AuthorityBundleError() from None
    finally:
        if interpreter_fd is not None:
            _close(interpreter_fd)
        for fd in reversed(opened):
            _close(fd)


def verify_external_runtime_files(files: tuple[AuthorityExternalRuntimeFile, ...]) -> None:
    """Verify the declared, canonical external runtime closure by descriptor."""
    try:
        _required_open_flags()
        if type(files) is not tuple or len(files) > 512:
            raise ValueError
        paths: set[str] = set()
        for record in files:
            if type(record) is not AuthorityExternalRuntimeFile or record.path in paths:
                raise ValueError
            paths.add(record.path)
            _external_record(record)
        if tuple(record.path for record in files) != tuple(sorted(paths)):
            raise ValueError
        for record in files:
            _verify_external(record)
    except Exception:
        raise AuthorityBundleError() from None


def verify_authority_bundle_bootstrap(root_fd: int, files: tuple[AuthorityBundleFile, ...], path: str, inventory_identity: tuple[int, int]) -> int:
    """Open the sole verified bootstrap through the already-admitted root."""
    descriptors: list[int] = []
    fd: int | None = None
    try:
        _required_open_flags()
        records = _bundle_records(files, "bin/python3")
        record = next(item for item in records if item.role == "bootstrap" and item.path == path)
        if sum(item.role == "bootstrap" for item in records) != 1:
            raise ValueError
        current = root_fd
        for component in path.split("/")[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW | _CLOEXEC, dir_fd=current)
            descriptors.append(child)
            _directory_identity(child)
            current = child
        fd = os.open(path.rsplit("/", 1)[1], os.O_RDONLY | _NOFOLLOW | _CLOEXEC | _NONBLOCK, dir_fd=current)
        identity = _regular_identity(fd, record)
        if identity[:2] == inventory_identity or _digest_fd(fd, identity) != record.sha256:
            raise ValueError
        result, fd = fd, None
        return result
    except Exception:
        raise AuthorityBundleError() from None
    finally:
        if fd is not None:
            _close(fd)
        for descriptor in reversed(descriptors):
            _close(descriptor)


def _bundle_records(files: object, interpreter_path: object) -> tuple[AuthorityBundleFile, ...]:
    if type(files) is not tuple or type(interpreter_path) is not str or not _relative_path(interpreter_path):
        raise ValueError
    records = tuple(files)
    if not records or len(records) > 100000 or tuple(record.path for record in records) != tuple(sorted(record.path for record in records)):
        raise ValueError
    if sum(record.path == interpreter_path and record.role == "interpreter" for record in records) != 1 or sum(record.role == "interpreter" for record in records) != 1 or sum(record.role == "bootstrap" for record in records) != 1:
        raise ValueError
    for record in records:
        if type(record) is not AuthorityBundleFile or not _relative_path(record.path) or record.role not in {"bootstrap", "interpreter", "python-source", "native-extension", "shared-library", "distribution-metadata", "data"}:
            raise ValueError
        if any(record.path.endswith(suffix) for suffix in (".pyc", ".pyo", ".pth", ".egg-link", "direct_url.json")) or record.path.endswith(("sitecustomize.py", "usercustomize.py")):
            raise ValueError
        _record_values(record)
    if len({record.path for record in records}) != len(records):
        raise ValueError
    if sum(record.size for record in records) > 2 * 1024 * 1024 * 1024:
        raise ValueError
    interpreter = next(record for record in records if record.role == "interpreter")
    if interpreter.mode not in {0o555, 0o755}:
        raise ValueError
    return records


def _external_record(record: AuthorityExternalRuntimeFile) -> None:
    if record.role not in {"elf-loader", "shared-library"} or not _absolute_path(record.path):
        raise ValueError
    _record_values(record)


def _record_values(record: AuthorityBundleFile | AuthorityExternalRuntimeFile) -> None:
    if type(record.mode) is not int or record.mode not in _MODES or type(record.size) is not int or not 0 <= record.size <= _MAX_FILE_BYTES or type(record.sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", record.sha256) is None:
        raise ValueError


def _expected_directories(records: tuple[AuthorityBundleFile, ...]) -> set[str]:
    return {"/".join(record.path.split("/")[:index]) for record in records for index in range(1, len(record.path.split("/")))}


def _expected_children(records: tuple[AuthorityBundleFile, ...], directories: set[str]) -> dict[str, set[str]]:
    children = {"": set()}
    children.update((directory, set()) for directory in directories)
    for directory in directories:
        parent, _, name = directory.rpartition("/")
        children[parent].add(name)
    for record in records:
        parent, _, name = record.path.rpartition("/")
        children[parent].add(name)
    return children


def _descriptor(fd: object) -> None:
    if type(fd) is not int or fd < 0:
        raise ValueError


def _directory_identity(fd: int) -> tuple[int, ...]:
    identity = _identity(os.fstat(fd))
    if not stat.S_ISDIR(identity[2]) or identity[3] != 0 or identity[2] & 0o022:
        raise ValueError
    return identity


def _same_directory(fd: int, identity: tuple[int, ...]) -> None:
    if _directory_identity(fd) != identity:
        raise ValueError


def _regular_identity(fd: int, record: AuthorityBundleFile | AuthorityExternalRuntimeFile) -> tuple[int, ...]:
    identity = _identity(os.fstat(fd))
    if not stat.S_ISREG(identity[2]) or identity[3] != 0 or identity[5] != 1 or stat.S_IMODE(identity[2]) != record.mode or identity[6] != record.size:
        raise ValueError
    return identity


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _digest_fd(fd: int, identity: tuple[int, ...]) -> str:
    digest, total = hashlib.sha256(), 0
    os.lseek(fd, 0, os.SEEK_SET)
    while chunk := os.read(fd, _READ_SIZE):
        total += len(chunk)
        if total > _MAX_FILE_BYTES:
            raise ValueError
        digest.update(chunk)
    if total != identity[6] or _identity(os.fstat(fd)) != identity:
        raise ValueError
    return digest.hexdigest()


def _elf_target(fd: int, target: ImagePlatformDescriptor) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    header = os.read(fd, 20)
    machine = 183 if target.architecture == "arm64" else 62
    if len(header) != 20 or header[:7] != b"\x7fELF\x02\x01\x01" or int.from_bytes(header[18:20], "little") != machine:
        raise ValueError


def _verify_external(record: AuthorityExternalRuntimeFile) -> None:
    descriptors: list[int] = []
    identities: list[tuple[int, ...]] = []
    try:
        current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW | _CLOEXEC)
        descriptors.append(current)
        identities.append(_directory_identity(current))
        for component in record.path[1:].split("/")[:-1]:
            _same_directory(descriptors[-1], identities[-1])
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW | _CLOEXEC, dir_fd=current)
            current = child
            descriptors.append(current)
            identities.append(_directory_identity(current))
            _same_directory(descriptors[-2], identities[-2])
        fd = os.open(record.path.rsplit("/", 1)[1], os.O_RDONLY | _NOFOLLOW | _CLOEXEC | _NONBLOCK, dir_fd=current)
        try:
            file_identity = _regular_identity(fd, record)
            if _digest_fd(fd, file_identity) != record.sha256:
                raise ValueError
        finally:
            _close(fd)
        for descriptor, identity in zip(descriptors, identities, strict=True):
            _same_directory(descriptor, identity)
    finally:
        for descriptor in reversed(descriptors):
            _close(descriptor)


def _relative_path(value: str) -> bool:
    return bool(value) and not value.startswith("/") and "\\" not in value and all(part not in {"", ".", ".."} and _PART.fullmatch(part) is not None for part in value.split("/"))


def _absolute_path(value: str) -> bool:
    return value.startswith("/") and "\\" not in value and all(part not in {"", ".", ".."} and _PART.fullmatch(part) is not None for part in value[1:].split("/"))


def _close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _required_open_flags() -> None:
    if not _NOFOLLOW or not _CLOEXEC or not _NONBLOCK:
        raise ValueError
