"""Linux-only, fail-closed bootstrap primitives for the Prime P1 authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import fcntl
import os
import socket
import struct
import sys
from typing import Any, NoReturn, cast


class PrimeP1AuthorityBootstrapError(ValueError):
    """Single public-safe authority bootstrap failure category."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 authority bootstrap is unavailable")


@dataclass(frozen=True, repr=False)
class AuthorityLaunchContract:
    """Data supplied by the trusted service manager, never paths or settings."""

    socket_fd: int
    session_key_fd: int
    config_fd: int
    authority_uid: int
    authority_pid: int
    supervisor_uid: int
    supervisor_pid: int

    def __repr__(self) -> str:
        return "AuthorityLaunchContract(redacted)"


@dataclass(frozen=True, repr=False)
class AuthorityBootstrap:
    """A successful local admission only; this never creates a receipt or PASS."""

    def __repr__(self) -> str:
        return "AuthorityBootstrap(redacted)"


def admit_authority_launch(
    contract: AuthorityLaunchContract,
    *,
    platform_name: str | None = None,
    effective_uid: Callable[[], int] = os.geteuid,
    process_id: Callable[[], int] = os.getpid,
    socket_factory: Callable[[int], object] | None = None,
    get_fd_flags: Callable[[int], int] | None = None,
    peer_credentials: Callable[[object], tuple[int, int]] | None = None,
    close_fd: Callable[[int], object] = os.close,
    seqpacket_type: int | None = None,
    peercred_option: int | None = None,
) -> AuthorityBootstrap:
    """Admit only an authenticated Linux ``SOCK_SEQPACKET`` launch.

    All inherited descriptors are consumed and closed in every outcome.  The
    intentionally injectable calls are test seams, not application settings.
    """
    fds = _unique_integer_fds(contract)
    connection: object | None = None
    try:
        if platform_name is None:
            platform_name = sys.platform
        seqpacket = (
            getattr(socket, "SOCK_SEQPACKET", None)
            if seqpacket_type is None
            else seqpacket_type
        )
        peercred = (
            getattr(socket, "SO_PEERCRED", None)
            if peercred_option is None
            else peercred_option
        )
        if (
            os.name != "posix"
            or platform_name != "linux"
            or isinstance(seqpacket, bool)
            or not isinstance(seqpacket, int)
            or isinstance(peercred, bool)
            or not isinstance(peercred, int)
        ):
            _unavailable()
        _validate_contract(contract)
        flags = get_fd_flags or _get_fd_flags
        if not all(
            flags(fd) & fcntl.FD_CLOEXEC
            for fd in (contract.socket_fd, contract.session_key_fd, contract.config_fd)
        ):
            _unavailable()
        factory = socket_factory or _socket_from_fd
        opened = factory(contract.socket_fd)
        connection = opened
        if (
            getattr(opened, "family", None) != socket.AF_UNIX
            or _getsockopt(opened, socket.SOL_SOCKET, socket.SO_TYPE) != seqpacket
        ):
            _unavailable()
        if (
            effective_uid() != contract.authority_uid
            or process_id() != contract.authority_pid
        ):
            _unavailable()
        peer = (
            peer_credentials(opened)
            if peer_credentials is not None
            else _peer_credentials(opened, peercred)
        )
        if peer != (contract.supervisor_uid, contract.supervisor_pid):
            _unavailable()
        return AuthorityBootstrap()
    except (OSError, OverflowError, TypeError, ValueError, struct.error):
        _unavailable()
    finally:
        if connection is not None:
            try:
                _close_socket(connection)
            except OSError:
                pass
        for fd in fds:
            if connection is not None and fd == contract.socket_fd:
                continue
            try:
                close_fd(fd)
            except (OSError, OverflowError, TypeError):
                pass


def _unique_integer_fds(contract: object) -> tuple[int, ...]:
    if not isinstance(contract, AuthorityLaunchContract):
        return ()
    values = (contract.socket_fd, contract.session_key_fd, contract.config_fd)
    return tuple(
        dict.fromkeys(value for value in values if type(value) is int and value >= 0)
    )


def _validate_contract(contract: object) -> None:
    if not isinstance(contract, AuthorityLaunchContract):
        raise ValueError
    values = (
        contract.socket_fd,
        contract.session_key_fd,
        contract.config_fd,
        contract.authority_uid,
        contract.authority_pid,
        contract.supervisor_uid,
        contract.supervisor_pid,
    )
    if (
        any(type(value) is not int or value < 0 for value in values)
        or len({contract.socket_fd, contract.session_key_fd, contract.config_fd}) != 3
        or contract.authority_pid <= 0
        or contract.supervisor_pid <= 0
        or contract.authority_uid == contract.supervisor_uid
        or contract.authority_pid == contract.supervisor_pid
    ):
        raise ValueError


def _get_fd_flags(fd: int) -> int:
    return int(fcntl.fcntl(fd, fcntl.F_GETFD))


def _socket_from_fd(fd: int) -> socket.socket:
    return socket.socket(fileno=fd)


def _peer_credentials(connection: object, peercred_option: int) -> tuple[int, int]:
    raw = _getsockopt(
        connection, socket.SOL_SOCKET, peercred_option, struct.calcsize("iII")
    )
    if type(raw) is not bytes:
        raise ValueError
    pid, uid, _gid = struct.unpack("iII", raw)
    return uid, pid


def _getsockopt(connection: object, level: int, option: int, *args: int) -> object:
    return cast(Any, connection).getsockopt(level, option, *args)


def _close_socket(connection: object) -> None:
    cast(Any, connection).close()


def _unavailable() -> NoReturn:
    raise PrimeP1AuthorityBootstrapError()
