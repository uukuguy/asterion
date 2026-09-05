"""Authority-only admission of the configured Prime P1 Docker Unix socket."""

from __future__ import annotations

from dataclasses import dataclass
import os
import stat
import sys
import threading
from typing import SupportsIndex


_ADMITTED_DOCKER_SOCKET_TOKEN = object()


class PrimeP1DockerSocketError(ValueError):
    """Single public-safe Docker socket resource failure category."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 Docker socket resource is unavailable")


@dataclass(frozen=True, repr=False, slots=True)
class _Identity:
    device: int
    inode: int
    mode: int
    owner: int
    group: int


class AdmittedPrimeP1DockerSocket:
    """Opaque owner of the admitted socket's verified parent descriptor."""

    __slots__ = ("_components", "_identities", "_lock", "_parent_fd", "_socket")

    def __init__(
        self,
        parent_fd: int,
        components: tuple[str, ...],
        identities: tuple[_Identity, ...],
        socket_identity: _Identity,
        *,
        _token: object | None = None,
    ) -> None:
        if (
            type(self) is not AdmittedPrimeP1DockerSocket
            or _token is not _ADMITTED_DOCKER_SOCKET_TOKEN
        ):
            raise PrimeP1DockerSocketError() from None
        self._parent_fd: int | None = parent_fd
        self._components = components
        self._identities = identities
        self._socket = socket_identity
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "AdmittedPrimeP1DockerSocket(redacted)"

    def __reduce__(self) -> object:
        raise TypeError("prime P1 Docker socket resource is unavailable")

    def __reduce_ex__(self, _: SupportsIndex) -> object:
        raise TypeError("prime P1 Docker socket resource is unavailable")

    def __copy__(self) -> object:
        raise TypeError("prime P1 Docker socket resource is unavailable")

    def __deepcopy__(self, _: object) -> object:
        raise TypeError("prime P1 Docker socket resource is unavailable")

    def close(self) -> None:
        """Release the retained parent descriptor exactly once."""
        with self._lock:
            fd = self._parent_fd
            self._parent_fd = None
        _close_quietly(fd)

    def revalidate_path(self) -> None:
        """Fail closed unless the complete descriptor-relative path is unchanged."""
        failed = False
        try:
            if type(self) is not AdmittedPrimeP1DockerSocket:
                raise ValueError
            _require_linux_posix()
            with self._lock:
                parent_fd = self._parent_fd
                if parent_fd is None or _identity_for_fd(parent_fd) != self._identities[-1]:
                    raise ValueError
                fresh_fd, identities = _open_parent(self._components)
                try:
                    if identities != self._identities:
                        raise ValueError
                    if _identity_for_fd(fresh_fd) != self._identities[-1]:
                        raise ValueError
                    if _socket_identity(fresh_fd, self._components[-1]) != self._socket:
                        raise ValueError
                    if _identity_for_fd(parent_fd) != self._identities[-1]:
                        raise ValueError
                finally:
                    _close_quietly(fresh_fd)
        except BaseException:
            failed = True
        if failed:
            raise PrimeP1DockerSocketError() from None


def admit_docker_socket(config: object) -> AdmittedPrimeP1DockerSocket:
    """Admit a configured socket as an opaque resource without connecting to it."""
    parent_fd: int | None = None
    result: AdmittedPrimeP1DockerSocket | None = None
    try:
        _require_linux_posix()
        from .authority_config import PrimeP1OperatorConfig

        if type(config) is not PrimeP1OperatorConfig:
            raise ValueError
        values = config._values
        components = _path_components(values["ASTERION_PRIME_P1_DOCKER_SOCKET"])
        parent_fd, identities = _open_parent(components)
        socket_identity = _socket_identity(parent_fd, components[-1])
        if (
            socket_identity.owner != int(values["ASTERION_PRIME_P1_DOCKER_SOCKET_OWNER_UID"])
            or socket_identity.group != int(values["ASTERION_PRIME_P1_DOCKER_SOCKET_GROUP_GID"])
            or stat.S_IMODE(socket_identity.mode)
            != int(values["ASTERION_PRIME_P1_DOCKER_SOCKET_MODE"], 8)
            or _identity_for_fd(parent_fd) != identities[-1]
        ):
            raise ValueError
        result = AdmittedPrimeP1DockerSocket(
            parent_fd,
            components,
            identities,
            socket_identity,
            _token=_ADMITTED_DOCKER_SOCKET_TOKEN,
        )
        parent_fd = None
    except BaseException:
        pass
    finally:
        _close_quietly(parent_fd)
    if result is None:
        raise PrimeP1DockerSocketError() from None
    return result


def _require_linux_posix() -> None:
    if sys.platform != "linux" or os.name != "posix":
        raise ValueError


def _path_components(path: object) -> tuple[str, ...]:
    if type(path) is not str or not path.startswith("/") or "\x00" in path:
        raise ValueError
    components = tuple(path.split("/")[1:])
    if not components or any(not part or part in {".", ".."} for part in components):
        raise ValueError
    return components


def _open_parent(components: tuple[str, ...]) -> tuple[int, tuple[_Identity, ...]]:
    """Open each ancestor from slash without following symlinks, retaining parent."""
    _require_linux_posix()
    flags = _directory_flags()
    directory: int | None = os.open("/", flags)
    identities: list[_Identity] = []
    try:
        identities.append(_safe_directory_identity(directory))
        for component in components[:-1]:
            child = os.open(component, flags, dir_fd=directory)
            _close_quietly(directory)
            directory = child
            identities.append(_safe_directory_identity(directory))
        if directory is None:
            raise ValueError
        result = directory
        directory = None
        return result, tuple(identities)
    finally:
        _close_quietly(directory)


def _safe_directory_identity(fd: int) -> _Identity:
    identity = _identity_for_fd(fd)
    if (
        not stat.S_ISDIR(identity.mode)
        or identity.owner != 0
        or identity.mode & 0o022
    ):
        raise ValueError
    return identity


def _directory_flags() -> int:
    values = tuple(
        getattr(os, name, None)
        for name in ("O_RDONLY", "O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
    )
    if any(type(value) is not int for value in values):
        raise ValueError
    readonly, directory, nofollow, cloexec = values
    return readonly | directory | nofollow | cloexec


def _socket_identity(parent_fd: int, name: str) -> _Identity:
    info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    identity = _identity_from_stat(info)
    if not stat.S_ISSOCK(identity.mode):
        raise ValueError
    return identity


def _identity_for_fd(fd: int) -> _Identity:
    return _identity_from_stat(os.fstat(fd))


def _identity_from_stat(info: os.stat_result) -> _Identity:
    return _Identity(info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)


def _close_quietly(fd: int | None) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except (OSError, OverflowError):
            pass
