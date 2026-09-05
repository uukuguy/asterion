"""Linux-only, fail-closed bootstrap primitives for the Prime P1 authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import fcntl
import errno
import os
import socket
import struct
import sys
import threading
from typing import Any, NoReturn, cast

from .authority_config import load_operator_config
from .authority_protocol import AuthoritySession
from .authority_request_contract import prime_p1_request_contract_sha256
from .authority_resources import admit_production_authority_resources


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


class AdmittedAuthorityDescriptors:
    """Sole owner of admitted descriptors until each is explicitly consumed."""

    def __init__(
        self,
        connection: object,
        session_key_fd: int,
        config_fd: int,
        close_fd: Callable[[int], object],
    ) -> None:
        self._connection: object | None = connection
        self._session_key_fd: int | None = session_key_fd
        self._config_fd: int | None = config_fd
        self._close_fd = close_fd
        self._closed = False
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "AdmittedAuthorityDescriptors(redacted)"

    def consume_socket(self) -> object:
        return self._take("_connection")

    def consume_session_key_fd(self) -> int:
        return cast(int, self._take("_session_key_fd"))

    def consume_config_fd(self) -> int:
        return cast(int, self._take("_config_fd"))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            connection = self._connection
            self._connection = None
            fds = (self._session_key_fd, self._config_fd)
            self._session_key_fd = self._config_fd = None
        if connection is not None:
            try:
                _close_socket(connection)
            except BaseException:
                pass
        for fd in fds:
            if fd is not None:
                try:
                    self._close_fd(fd)
                except BaseException:
                    pass

    def _take(self, attribute: str) -> object:
        with self._lock:
            if self._closed:
                _unavailable()
            value = getattr(self, attribute)
            if value is None:
                _unavailable()
            setattr(self, attribute, None)
            return value


def _consume_session_key(
    descriptors: AdmittedAuthorityDescriptors,
    *,
    reader: Callable[[int, int], bytes] = os.read,
    close_fd: Callable[[int], object] = os.close,
) -> bytes:
    """Consume and close the private 32-byte authority session key descriptor."""
    fd: int | None = None
    result: bytes | None = None
    failed = False
    try:
        if not isinstance(descriptors, AdmittedAuthorityDescriptors):
            _unavailable()
        fd = descriptors.consume_session_key_fd()
        data = bytearray()
        interruptions = 0
        while len(data) < 32:
            try:
                chunk = reader(fd, 32 - len(data))
            except OSError as error:
                if error.errno == errno.EINTR and interruptions < 8:
                    interruptions += 1
                    continue
                raise
            if type(chunk) is not bytes or not chunk or len(chunk) > 32 - len(data):
                raise ValueError
            data.extend(chunk)
        while True:
            try:
                extra = reader(fd, 1)
                break
            except OSError as error:
                if error.errno == errno.EINTR and interruptions < 8:
                    interruptions += 1
                    continue
                raise
        if type(extra) is not bytes or extra != b"":
            raise ValueError
        result = bytes(data)
    except (OSError, OverflowError, TypeError, ValueError):
        failed = True
    finally:
        if fd is not None:
            try:
                close_fd(fd)
            except (OSError, OverflowError, TypeError):
                failed = True
    if failed or result is None:
        _unavailable()
    return result


def _receive_authority_packet(descriptors: AdmittedAuthorityDescriptors) -> bytes:
    """Receive one raw bounded authority packet and close its consumed socket."""
    connection: object | None = None
    result: bytes | None = None
    failed = False
    try:
        if not isinstance(descriptors, AdmittedAuthorityDescriptors):
            _unavailable()
        connection = descriptors.consume_socket()
        result = _receive_authority_packet_from_connection(connection)
    except (OSError, OverflowError, TypeError, ValueError):
        failed = True
    finally:
        if connection is not None:
            try:
                _close_socket(connection)
            except (OSError, OverflowError, TypeError):
                failed = True
    if failed or result is None:
        _unavailable()
    return result


def _receive_authority_packet_from_connection(connection: object) -> bytes:
    """Validate one raw packet without closing the caller-owned connection."""
    result: bytes | None = None
    failed = False
    try:
        capability = getattr(socket, "MSG_CMSG_CLOEXEC", None)
        if (
            isinstance(capability, bool)
            or not isinstance(capability, int)
            or not int(capability)
        ):
            raise ValueError
        interruptions = 0
        while True:
            try:
                received = _recvmsg(
                    connection,
                    8192,
                    socket.CMSG_SPACE(struct.calcsize("i")),
                    int(capability),
                )
                break
            except OSError as error:
                if error.errno == errno.EINTR and interruptions < 8:
                    interruptions += 1
                    continue
                raise
        if type(received) is not tuple or len(received) != 4:
            raise ValueError
        packet, ancillary, flags, _address = received
        _close_received_rights(ancillary)
        if (
            type(packet) is not bytes
            or not 1 <= len(packet) <= 8192
            or type(ancillary) is not list
            or ancillary
            or type(flags) is not int
            or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC)
        ):
            raise ValueError
        result = packet
    except (OSError, OverflowError, TypeError, ValueError):
        failed = True
    if failed or result is None:
        _unavailable()
    return result


def _send_authority_packet(connection: object, packet: bytes) -> None:
    """Send one raw authority packet without taking ownership of its socket."""
    failed = False
    try:
        capability = getattr(socket, "MSG_NOSIGNAL", None)
        if (
            type(packet) is not bytes
            or not 1 <= len(packet) <= 8192
            or isinstance(capability, bool)
            or not isinstance(capability, int)
            or not int(capability)
        ):
            raise ValueError
        interruptions = 0
        while True:
            try:
                sent = _sendmsg(connection, [packet], [], int(capability))
                break
            except OSError as error:
                if error.errno == errno.EINTR and interruptions < 8:
                    interruptions += 1
                    continue
                raise
        if type(sent) is not int or sent != len(packet):
            raise ValueError
    except (OSError, OverflowError, TypeError, ValueError):
        failed = True
    if failed:
        _unavailable()


def _run_ready_execute_exchange(
    descriptors: AdmittedAuthorityDescriptors,
    session_id: str,
) -> NoReturn:
    """Admit one authenticated execute packet, then stop unavailable.

    This deliberately performs no authority work beyond complete local resource
    admission, ready transport binding, and protocol-owned execute admission.
    """
    config_fd: int | None = None
    connection: object | None = None
    production_resources: object | None = None
    try:
        if (
            type(descriptors) is not AdmittedAuthorityDescriptors
            or type(session_id) is not str
        ):
            raise ValueError
        config_fd = descriptors.consume_config_fd()
        loader_owned_config_fd = config_fd
        config_fd = None
        config = load_operator_config(loader_owned_config_fd)
        production_resources = admit_production_authority_resources(config)
        resource_set_sha256 = production_resources._resource_set_sha256()
        session_key = _consume_session_key(descriptors)
        connection = descriptors.consume_socket()
        session = AuthoritySession(
            session_id,
            session_key,
            prime_p1_request_contract_sha256(),
            resource_set_sha256,
        )
        _send_authority_packet(connection, session.ready_packet())
        packet = _receive_authority_packet_from_connection(connection)
        session.accept_supervisor_packet(packet)
    except BaseException:
        pass
    finally:
        if connection is not None:
            try:
                _close_socket(connection)
            except BaseException:
                pass
        if production_resources is not None:
            try:
                production_resources.close()
            except BaseException:
                pass
        if config_fd is not None:
            try:
                descriptors._close_fd(config_fd)
            except BaseException:
                pass
        descriptor_mro = type.__getattribute__(type(descriptors), "__mro__")
        if any(base is AdmittedAuthorityDescriptors for base in descriptor_mro):
            try:
                AdmittedAuthorityDescriptors.close(descriptors)
            except BaseException:
                pass
    _unavailable()


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
    admitted = admit_retained_authority_descriptors(
        contract,
        platform_name=platform_name,
        effective_uid=effective_uid,
        process_id=process_id,
        socket_factory=socket_factory,
        get_fd_flags=get_fd_flags,
        peer_credentials=peer_credentials,
        close_fd=close_fd,
        seqpacket_type=seqpacket_type,
        peercred_option=peercred_option,
    )
    admitted.close()
    return AuthorityBootstrap()


def admit_retained_authority_descriptors(
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
) -> AdmittedAuthorityDescriptors:
    """Validate and transfer sole descriptor ownership to a narrow bundle."""
    fds = _unique_integer_fds(contract)
    connection: object | None = None
    retained = False
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
        admitted = AdmittedAuthorityDescriptors(
            opened, contract.session_key_fd, contract.config_fd, close_fd
        )
        retained = True
        return admitted
    except (MemoryError, OSError, OverflowError, TypeError, ValueError, struct.error):
        _unavailable()
    finally:
        if connection is not None and not retained:
            try:
                _close_socket(connection)
            except OSError:
                pass
        if not retained:
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


def _recvmsg(connection: object, size: int, ancillary_size: int, flags: int) -> object:
    return cast(Any, connection).recvmsg(size, ancillary_size, flags)


def _sendmsg(
    connection: object, buffers: list[bytes], ancillary: list[object], flags: int
) -> object:
    return cast(Any, connection).sendmsg(buffers, ancillary, flags)


def _close_received_rights(ancillary: object) -> None:
    if type(ancillary) is not list:
        return
    for item in ancillary:
        if type(item) is not tuple or len(item) != 3:
            continue
        level, kind, data = item
        if (
            level != socket.SOL_SOCKET
            or kind != socket.SCM_RIGHTS
            or type(data) is not bytes
        ):
            continue
        usable = len(data) - (len(data) % struct.calcsize("i"))
        for (fd,) in struct.iter_unpack("i", data[:usable]):
            os.close(fd)


def _close_socket(connection: object) -> None:
    cast(Any, connection).close()


def _unavailable() -> NoReturn:
    raise PrimeP1AuthorityBootstrapError() from None
