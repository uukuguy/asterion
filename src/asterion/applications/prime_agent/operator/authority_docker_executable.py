"""Authority-only admission of the configured Prime P1 Docker executable."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import stat
import threading
from typing import Final, SupportsIndex

from .authority_config import PrimeP1OperatorConfig


_ADMITTED_DOCKER_EXECUTABLE_TOKEN = object()
_DIRECTORY_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_EXECUTABLE_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_MAX_EXECUTABLE_BYTES: Final = 128 * 1024 * 1024
_READ_BYTES: Final = 64 * 1024


class PrimeP1DockerExecutableError(ValueError):
    """Single public-safe Docker executable resource failure category."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 Docker executable resource is unavailable")


@dataclass(frozen=True, repr=False, slots=True)
class _ExecutableIdentity:
    device: int
    inode: int
    mode: int
    owner: int
    group: int
    size: int
    mtime_ns: int


class AdmittedPrimeP1DockerExecutable:
    """Opaque owner of one verified Docker executable descriptor."""

    __slots__ = ("_digest", "_fd", "_identity", "_lock")

    def __init__(
        self,
        fd: int,
        identity: _ExecutableIdentity,
        digest: bytes,
        *,
        _token: object | None = None,
    ) -> None:
        if (
            type(self) is not AdmittedPrimeP1DockerExecutable
            or _token is not _ADMITTED_DOCKER_EXECUTABLE_TOKEN
        ):
            raise PrimeP1DockerExecutableError() from None
        self._fd: int | None = fd
        self._identity = identity
        self._digest = digest
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "AdmittedPrimeP1DockerExecutable(redacted)"

    def __reduce__(self) -> object:
        raise TypeError("prime P1 Docker executable resource is unavailable")

    def __reduce_ex__(self, _: SupportsIndex) -> object:
        raise TypeError("prime P1 Docker executable resource is unavailable")

    def __copy__(self) -> object:
        raise TypeError("prime P1 Docker executable resource is unavailable")

    def __deepcopy__(self, _: object) -> object:
        raise TypeError("prime P1 Docker executable resource is unavailable")

    def close(self) -> None:
        """Release the retained descriptor exactly once."""
        with self._lock:
            fd = self._fd
            self._fd = None
        _close_quietly(fd)

    def revalidate_for_spawn(self) -> None:
        """Fail closed unless the retained executable is byte-for-byte unchanged."""
        failed = False
        try:
            if type(self) is not AdmittedPrimeP1DockerExecutable:
                raise ValueError
            with self._lock:
                fd = self._fd
                if fd is None or _identity_for_fd(fd) != self._identity:
                    raise ValueError
                if _digest_fd(fd, self._identity) != self._digest:
                    raise ValueError
        except BaseException:
            failed = True
        if failed:
            raise PrimeP1DockerExecutableError() from None


def admit_docker_executable(config: object) -> AdmittedPrimeP1DockerExecutable:
    """Admit only the exact configured Docker executable without retaining its path."""
    fd: int | None = None
    result: AdmittedPrimeP1DockerExecutable | None = None
    try:
        if type(config) is not PrimeP1OperatorConfig:
            raise ValueError
        fd = _open_absolute_executable_without_symlinks(
            config._values["ASTERION_PRIME_P1_DOCKER_EXECUTABLE"]
        )
        identity = _identity_for_fd(fd)
        digest = _digest_fd(fd, identity)
        result = AdmittedPrimeP1DockerExecutable(
            fd, identity, digest, _token=_ADMITTED_DOCKER_EXECUTABLE_TOKEN
        )
        fd = None
    except BaseException:
        pass
    finally:
        _close_quietly(fd)
    if result is None:
        raise PrimeP1DockerExecutableError() from None
    return result


def _open_absolute_executable_without_symlinks(path: object) -> int:
    """Walk a canonical absolute path from `/` without following symlinks."""
    if type(path) is not str or not path.startswith("/") or "\x00" in path:
        raise ValueError
    components = path.split("/")[1:]
    if not components or any(not part or part in {".", ".."} for part in components):
        raise ValueError
    directory: int | None = os.open("/", _DIRECTORY_FLAGS)
    try:
        for component in components[:-1]:
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=directory)
            _close_quietly(directory)
            directory = child
        result = os.open(components[-1], _EXECUTABLE_FLAGS, dir_fd=directory)
        return result
    finally:
        _close_quietly(directory)


def _identity_for_fd(fd: int) -> _ExecutableIdentity:
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or info.st_mode & 0o022
        or not info.st_mode & 0o111
        or not 0 <= info.st_size <= _MAX_EXECUTABLE_BYTES
    ):
        raise ValueError
    return _ExecutableIdentity(
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_size,
        info.st_mtime_ns,
    )


def _digest_fd(fd: int, identity: _ExecutableIdentity) -> bytes:
    if os.lseek(fd, 0, os.SEEK_SET) != 0:
        raise ValueError
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(fd, _READ_BYTES)
        if type(chunk) is not bytes:
            raise ValueError
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_EXECUTABLE_BYTES:
            raise ValueError
        digest.update(chunk)
    if total != identity.size or _identity_for_fd(fd) != identity:
        raise ValueError
    return digest.digest()


def _close_quietly(fd: int | None) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except (OSError, OverflowError):
            pass
