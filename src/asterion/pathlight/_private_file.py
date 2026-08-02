"""Descriptor-relative private-file primitives for Pathlight persistence."""

from __future__ import annotations

import os
import stat
from pathlib import Path


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


def _is_private_regular(metadata: os.stat_result) -> bool:
    return stat.S_ISREG(metadata.st_mode) and stat.S_IMODE(metadata.st_mode) == 0o600


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
