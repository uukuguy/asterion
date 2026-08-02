"""Descriptor-relative private-file primitives for Pathlight persistence."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Mapping, Sequence


class PrivateFileError(Exception):
    """A context-free private-file trust-boundary failure."""


def write_private_file(path: Path, encoded: bytes) -> None:
    """Exclusively create one descriptor-relative mode-0600 private file."""

    valid = False
    try:
        valid = isinstance(path, Path) and bool(path.name) and type(encoded) is bytes
    except Exception:
        pass
    if not valid:
        raise PrivateFileError("private file target is unavailable")

    directory_fd = -1
    descriptor = -1
    failure = False
    try:
        directory_fd = _open_parent_directory(path)
        descriptor = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _nofollow_flag(),
            0o600,
            dir_fd=directory_fd,
        )
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, encoded)
    except Exception:
        failure = True
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except Exception:
                failure = True
        if directory_fd >= 0:
            try:
                os.close(directory_fd)
            except Exception:
                failure = True
    if failure:
        raise PrivateFileError("private file target is unavailable")


def read_private_file(path: Path, max_bytes: int) -> bytes:
    """Read exact bytes from one stable descriptor-verified private file."""

    valid = False
    try:
        valid = (
            isinstance(path, Path)
            and bool(path.name)
            and type(max_bytes) is int
            and max_bytes >= 0
        )
    except Exception:
        pass
    if not valid:
        raise PrivateFileError("private file source is invalid")

    directory_fd = -1
    descriptor = -1
    encoded: bytes | None = None
    failure = False
    try:
        directory_fd = _open_parent_directory(path)
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_NONBLOCK | _nofollow_flag(),
            dir_fd=directory_fd,
        )
        before = os.fstat(descriptor)
        if not _is_private_regular(before) or before.st_size > max_bytes:
            raise OSError("private file source is unsafe")
        candidate = _read_bounded(descriptor, max_bytes + 1)
        after = os.fstat(descriptor)
        if (
            not _is_private_regular(after)
            or len(candidate) > max_bytes
            or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or before.st_size != after.st_size
            or after.st_size != len(candidate)
        ):
            raise OSError("private file source changed while reading")
        encoded = candidate
    except Exception:
        failure = True
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except Exception:
                failure = True
        if directory_fd >= 0:
            try:
                os.close(directory_fd)
            except Exception:
                failure = True
    if failure or encoded is None:
        raise PrivateFileError("private file source is invalid")
    return encoded


def read_private_file_snapshot(
    root: Path,
    names: Sequence[str],
    max_bytes: Mapping[str, int],
) -> tuple[tuple[str, bytes], ...]:
    """Read exact private children through one stable directory descriptor."""

    valid = False
    try:
        valid = (
            isinstance(root, Path)
            and root.is_absolute()
            and bool(root.name)
            and type(names) in {tuple, list}
            and bool(names)
            and all(
                type(name) is str
                and bool(name)
                and "/" not in name
                and name not in {".", ".."}
                for name in names
            )
            and len(set(names)) == len(names)
            and type(max_bytes) is dict
            and set(max_bytes) == set(names)
            and all(type(limit) is int and limit >= 0 for limit in max_bytes.values())
        )
    except Exception:
        pass
    if not valid:
        raise PrivateFileError("private file snapshot is invalid")

    parent_fd = -1
    root_fd = -1
    descriptors: list[tuple[str, int, os.stat_result]] = []
    snapshot: tuple[tuple[str, bytes], ...] | None = None
    failure = False
    try:
        parent_fd = _open_parent_directory(root)
        root_fd = os.open(
            root.name,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _nofollow_flag(),
            dir_fd=parent_fd,
        )
        root_before = os.fstat(root_fd)
        root_entry_before = os.stat(root.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not _is_private_directory(root_before)
            or not _is_private_directory(root_entry_before)
            or (root_before.st_dev, root_before.st_ino)
            != (root_entry_before.st_dev, root_entry_before.st_ino)
        ):
            raise OSError("private file snapshot root is unsafe")
        contents: list[tuple[str, bytes]] = []
        for name in names:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_NONBLOCK | _nofollow_flag(),
                dir_fd=root_fd,
            )
            before = os.fstat(descriptor)
            if not _is_private_regular(before) or before.st_size > max_bytes[name]:
                os.close(descriptor)
                raise OSError("private file snapshot child is unsafe")
            descriptors.append((name, descriptor, before))
            contents.append((name, _read_bounded(descriptor, max_bytes[name] + 1)))
        if any(len(content) > max_bytes[name] for name, content in contents):
            raise OSError("private file snapshot child is oversized")
        content_by_name = dict(contents)
        for name, descriptor, before in descriptors:
            after = os.fstat(descriptor)
            entry_after = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            content = content_by_name[name]
            if (
                not _is_private_regular(after)
                or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
                or before.st_size != after.st_size
                or after.st_size != len(content)
                or (before.st_dev, before.st_ino)
                != (entry_after.st_dev, entry_after.st_ino)
            ):
                raise OSError("private file snapshot child changed while reading")
        root_after = os.fstat(root_fd)
        root_entry_after = os.stat(root.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not _is_private_directory(root_after)
            or not _is_private_directory(root_entry_after)
            or (root_before.st_dev, root_before.st_ino)
            != (root_after.st_dev, root_after.st_ino)
            or (root_before.st_dev, root_before.st_ino)
            != (root_entry_after.st_dev, root_entry_after.st_ino)
        ):
            raise OSError("private file snapshot root changed while reading")
        snapshot = tuple(contents)
    except Exception:
        failure = True
    finally:
        for _name, descriptor, _before in descriptors:
            try:
                os.close(descriptor)
            except Exception:
                failure = True
        if root_fd >= 0:
            try:
                os.close(root_fd)
            except Exception:
                failure = True
        if parent_fd >= 0:
            try:
                os.close(parent_fd)
            except Exception:
                failure = True
    if failure or snapshot is None:
        raise PrivateFileError("private file snapshot is invalid")
    return snapshot


def _is_private_regular(metadata: os.stat_result) -> bool:
    return stat.S_ISREG(metadata.st_mode) and stat.S_IMODE(metadata.st_mode) == 0o600


def _is_private_directory(metadata: os.stat_result) -> bool:
    return stat.S_ISDIR(metadata.st_mode) and stat.S_IMODE(metadata.st_mode) == 0o700


def _nofollow_flag() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if type(nofollow) is not int:
        raise OSError("no-follow descriptor opening is unavailable")
    return nofollow


def _open_parent_directory(path: Path) -> int:
    absolute = path.absolute()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _nofollow_flag()
    descriptor = -1
    failure = False
    try:
        descriptor = os.open(absolute.anchor, flags)
        for component in absolute.parts[1:-1]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            try:
                os.close(descriptor)
            except Exception:
                try:
                    os.close(next_descriptor)
                except Exception:
                    pass
                raise
            descriptor = next_descriptor
    except BaseException as error:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except Exception:
                pass
            descriptor = -1
        if not isinstance(error, Exception):
            raise
        failure = True
    if failure:
        raise OSError("private file parent is unavailable")
    return descriptor


def _read_bounded(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total < limit:
        chunk = os.read(descriptor, min(65_536, limit - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def _write_all(descriptor: int, encoded: bytes) -> None:
    remaining = memoryview(encoded)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("private file write is incomplete")
        remaining = remaining[written:]
