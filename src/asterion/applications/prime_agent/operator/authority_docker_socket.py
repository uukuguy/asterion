"""Authority-only admission of the configured Prime P1 Docker Unix socket."""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import json
import math
import os
import socket
import stat
import sys
import threading
from typing import SupportsIndex


_ADMITTED_DOCKER_SOCKET_TOKEN = object()
_DAEMON_RESPONSE_LIMIT = 16 * 1024
_DAEMON_HEADER_LIMIT = 4 * 1024
_VERSION_REQUEST = b"GET /version HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n"


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

    __slots__ = (
        "_components", "_expected_api_version", "_expected_version", "_identities",
        "_lock", "_parent_fd", "_probe_lock", "_socket",
    )

    def __init__(
        self,
        parent_fd: int,
        components: tuple[str, ...],
        identities: tuple[_Identity, ...],
        socket_identity: _Identity,
        expected_api_version: str = "",
        expected_version: str = "",
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
        self._expected_api_version = expected_api_version
        self._expected_version = expected_version
        self._identities = identities
        self._socket = socket_identity
        self._lock = threading.Lock()
        self._probe_lock = asyncio.Lock()

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

    def _resource_set_contribution(self) -> bytes:
        """Bind retained socket and expected daemon identities without its pathname."""
        self.revalidate_path()
        with self._lock:
            parent_fd = self._parent_fd
            identities = self._identities
            socket_identity = self._socket
            api_version = self._expected_api_version
            version = self._expected_version
            if (
                parent_fd is None
                or type(socket_identity) is not _Identity
                or type(identities) is not tuple
                or not identities
                or any(type(identity) is not _Identity for identity in identities)
                or type(api_version) is not str
                or type(version) is not str
                or _identity_for_fd(parent_fd) != identities[-1]
            ):
                raise ValueError
        return _canonical_contribution(
            b"docker-socket",
            (
                (b"daemon-api", api_version.encode("ascii")),
                (b"daemon-version", version.encode("ascii")),
                (b"parent-chain", b"".join(_identity_bytes(identity) for identity in identities)),
                (b"socket", _identity_bytes(socket_identity)),
            ),
        )

    async def _verify_daemon_projection(self, deadline: float) -> None:
        """Privately verify the admitted daemon's fixed /version projection."""
        client: socket.socket | None = None
        failed = False
        try:
            if type(self) is not AdmittedPrimeP1DockerSocket or not _valid_deadline(deadline):
                raise ValueError
            async with asyncio.timeout_at(deadline):
                async with self._probe_lock:
                    self.revalidate_path()
                    client = _new_daemon_client()
                    loop = asyncio.get_running_loop()
                    await loop.sock_connect(client, "/" + "/".join(self._components))
                    self.revalidate_path()
                    await loop.sock_sendall(client, _VERSION_REQUEST)
                    response = await _read_daemon_response(loop, client)
                    _verify_daemon_projection(
                        response, self._expected_version, self._expected_api_version
                    )
                    self.revalidate_path()
        except asyncio.CancelledError:
            raise
        except BaseException:
            failed = True
        finally:
            if client is not None:
                try:
                    client.close()
                except BaseException:
                    pass
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
            values["ASTERION_PRIME_P1_DOCKER_SERVER_API_VERSION"],
            values["ASTERION_PRIME_P1_DOCKER_SERVER_VERSION"],
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


def _identity_bytes(identity: _Identity) -> bytes:
    return b"".join(value.to_bytes(8, "big", signed=False) for value in (
        identity.device, identity.inode, identity.mode, identity.owner, identity.group
    ))


def _canonical_contribution(kind: bytes, fields: tuple[tuple[bytes, bytes], ...]) -> bytes:
    if tuple(sorted(fields)) != fields or len({name for name, _ in fields}) != len(fields):
        raise ValueError
    return kind + b"\0" + b"".join(
        len(name).to_bytes(4, "big") + name + len(value).to_bytes(8, "big") + value
        for name, value in fields
    )


def _close_quietly(fd: int | None) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except (OSError, OverflowError):
            pass


def _valid_deadline(value: object) -> bool:
    return type(value) is float and math.isfinite(value)


def _new_daemon_client() -> socket.socket:
    cloexec = getattr(socket, "SOCK_CLOEXEC", None)
    nonblock = getattr(socket, "SOCK_NONBLOCK", None)
    if (
        not isinstance(cloexec, int)
        or not isinstance(nonblock, int)
        or not cloexec
        or not nonblock
    ):
        raise ValueError
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | cloexec | nonblock)
    try:
        client.setblocking(False)
        client.set_inheritable(False)
        return client
    except BaseException:
        client.close()
        raise


async def _read_daemon_response(
    loop: asyncio.AbstractEventLoop, client: socket.socket
) -> bytes:
    response = bytearray()
    while True:
        chunk = await loop.sock_recv(client, 4096)
        if not chunk:
            return bytes(response)
        response.extend(chunk)
        if len(response) > _DAEMON_RESPONSE_LIMIT:
            raise ValueError


def _verify_daemon_projection(
    response: bytes, expected_version: str, expected_api_version: str
) -> None:
    header_end = response.find(b"\r\n\r\n")
    if header_end < 0 or header_end > _DAEMON_HEADER_LIMIT:
        raise ValueError
    lines = response[:header_end].split(b"\r\n")
    if not lines or not _valid_status_line(lines[0]):
        raise ValueError
    headers: dict[bytes, bytes] = {}
    for line in lines[1:]:
        if not line or b":" not in line:
            raise ValueError
        name, value = line.split(b":", 1)
        if (
            not _header_token(name)
            or not value
            or any(byte < 32 for byte in name)
            or any(byte < 32 for byte in value)
            or value[:1] in b" \t"
            or value[-1:] in b" \t"
        ):
            raise ValueError
        name = name.lower()
        if name in headers:
            raise ValueError
        headers[name] = value
    if headers.get(b"content-type") != b"application/json":
        raise ValueError
    content_length = headers.get(b"content-length")
    transfer_encoding = headers.get(b"transfer-encoding")
    if (content_length is None) == (transfer_encoding is None):
        raise ValueError
    wire_body = response[header_end + 4 :]
    if content_length is not None:
        if not content_length.isdigit() or (len(content_length) > 1 and content_length[:1] == b"0"):
            raise ValueError
        length = int(content_length)
        if length != len(wire_body):
            raise ValueError
        body = wire_body
    else:
        if transfer_encoding != b"chunked":
            raise ValueError
        body = _decode_chunked_body(wire_body)
    try:
        document = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_no_duplicate_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError from None
    if (
        type(document) is not dict
        or not _json_within_limits(document)
        or type(document.get("Version")) is not str
        or type(document.get("ApiVersion")) is not str
        or document["Version"] != expected_version
        or document["ApiVersion"] != expected_api_version
    ):
        raise ValueError


def _json_within_limits(value: object) -> bool:
    pending: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 1024 or depth > 64:
            return False
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
    return True


def _valid_status_line(line: bytes) -> bool:
    fields = line.split(b" ", 2)
    return (
        len(fields) == 3
        and fields[0] == b"HTTP/1.1"
        and fields[1] == b"200"
        and bool(fields[2])
        and all(32 <= byte <= 126 and byte != 127 for byte in fields[2])
    )


def _header_token(value: bytes) -> bool:
    return bool(value) and all(
        48 <= byte <= 57
        or 65 <= byte <= 90
        or 97 <= byte <= 122
        or byte in b"!#$%&'*+-.^_`|~"
        for byte in value
    )


def _decode_chunked_body(wire: bytes) -> bytes:
    output = bytearray()
    position = 0
    while True:
        line_end = wire.find(b"\r\n", position)
        if line_end < 0:
            raise ValueError
        size_text = wire[position:line_end]
        if not size_text or any(byte not in b"0123456789abcdefABCDEF" for byte in size_text):
            raise ValueError
        size = int(size_text, 16)
        position = line_end + 2
        if len(wire) < position + size + 2 or wire[position + size : position + size + 2] != b"\r\n":
            raise ValueError
        output.extend(wire[position : position + size])
        if len(output) > _DAEMON_RESPONSE_LIMIT:
            raise ValueError
        position += size + 2
        if size == 0:
            if position != len(wire):
                raise ValueError
            return bytes(output)


def _no_duplicate_object(pairs: list[tuple[object, object]]) -> dict[object, object]:
    result: dict[object, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_json_constant(_: str) -> None:
    raise ValueError
