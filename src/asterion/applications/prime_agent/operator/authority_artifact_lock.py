"""Admission of the fixed, packaged Prime P1 authority source set."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
import stat
import threading
from typing import Final, NoReturn, SupportsIndex

from .authority_resources import PrimeP1AuthorityResourceError


_TOKEN = object()
_PROTOCOL: Final = "asterion.prime-p1-authority-artifact-lock/v1"
_DESCRIPTOR_PATH: Final = ("resources", "authority-artifact-lock.json")
_EXPECTED_ARTIFACT_PATHS: Final = (
    "authority_application_resources.py",
    "authority_artifact_lock.py",
    "authority_config.py",
    "authority_docker_executable.py",
    "authority_docker_socket.py",
    "authority_evidence.py",
    "authority_executable_lock.py",
    "authority_process.py",
    "authority_protocol.py",
    "authority_receipt.py",
    "authority_request_contract.py",
    "authority_resources.py",
    "authority_seccomp.py",
)
_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_MAX_DESCRIPTOR_BYTES: Final = 64 * 1024
_MAX_ARTIFACT_BYTES: Final = 1024 * 1024
_READ_BYTES: Final = 64 * 1024
_OS_CLOSE = os.close


@dataclass(frozen=True, slots=True)
class _Artifact:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class _Descriptor:
    authority_version: str
    artifacts: tuple[_Artifact, ...]


class AdmittedPrimeP1AuthorityArtifacts:
    """Opaque, idempotently closeable proof of local artifact admission."""

    __slots__ = ("_closed", "_identity", "_lock")

    def __init__(self, identity: bytes | None = None, *, _token: object | None = None) -> None:
        if type(self) is not AdmittedPrimeP1AuthorityArtifacts or _token is not _TOKEN:
            raise PrimeP1AuthorityResourceError() from None
        self._closed = False
        self._identity = identity
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "AdmittedPrimeP1AuthorityArtifacts(redacted)"

    def __reduce__(self) -> NoReturn:
        raise TypeError("prime P1 authority resource is unavailable")

    def __reduce_ex__(self, _: SupportsIndex) -> NoReturn:
        raise TypeError("prime P1 authority resource is unavailable")

    def __copy__(self) -> object:
        raise TypeError("prime P1 authority resource is unavailable")

    def __deepcopy__(self, _: object) -> object:
        raise TypeError("prime P1 authority resource is unavailable")

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _resource_set_contribution(self) -> bytes:
        """Return the retained descriptor identity without exposing its contents."""
        with self._lock:
            identity = self._identity
            if self._closed or type(identity) is not bytes or len(identity) != 32:
                raise ValueError
        return _canonical_contribution(b"authority-artifacts", ((b"descriptor-sha256", identity),))


def admit_authority_artifact_lock() -> AdmittedPrimeP1AuthorityArtifacts:
    """Admit only the descriptor's exact, code-owned authority source set."""
    try:
        descriptor = _load_packaged_descriptor()
        root = _package_root()
        for artifact in descriptor.artifacts:
            _read_verified_artifact(root, artifact)
        return AdmittedPrimeP1AuthorityArtifacts(
            hashlib.sha256(_canonical_descriptor_bytes(descriptor)).digest(), _token=_TOKEN
        )
    except BaseException:
        raise PrimeP1AuthorityResourceError() from None


def _package_root() -> Path:
    root = Path(__file__).resolve().parent
    if not root.is_dir():
        raise ValueError
    return root


def _load_packaged_descriptor() -> _Descriptor:
    raw = _read_relative_file(_package_root(), _DESCRIPTOR_PATH, _MAX_DESCRIPTOR_BYTES)
    if raw.decode("utf-8").encode("utf-8") != raw:
        raise ValueError
    value = json.loads(raw)
    canonical = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if raw not in {canonical, canonical + b"\n"}:
        raise ValueError
    if type(value) is not dict or set(value) != {"protocol", "authority_version", "artifacts"}:
        raise ValueError
    if value["protocol"] != _PROTOCOL or value["authority_version"] != metadata.version("asterion"):
        raise ValueError
    artifacts_value = value["artifacts"]
    if type(artifacts_value) is not list or len(artifacts_value) != len(_EXPECTED_ARTIFACT_PATHS):
        raise ValueError
    artifacts: list[_Artifact] = []
    for item in artifacts_value:
        if type(item) is not dict or set(item) != {"path", "sha256"}:
            raise ValueError
        path, digest = item["path"], item["sha256"]
        if (
            type(path) is not str
            or type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError
        artifacts.append(_Artifact(path, digest))
    paths = tuple(artifact.path for artifact in artifacts)
    if paths != _EXPECTED_ARTIFACT_PATHS:
        raise ValueError
    return _Descriptor(value["authority_version"], tuple(artifacts))


def _canonical_descriptor_bytes(descriptor: _Descriptor) -> bytes:
    """Encode the admitted descriptor with fixed ordering and no paths released."""
    result = bytearray(
        _PROTOCOL.encode("ascii") + b"\0" + descriptor.authority_version.encode("ascii") + b"\0"
    )
    for artifact in descriptor.artifacts:
        result.extend(artifact.path.encode("ascii"))
        result.append(0)
        result.extend(bytes.fromhex(artifact.sha256))
    return bytes(result)


def _canonical_contribution(kind: bytes, fields: tuple[tuple[bytes, bytes], ...]) -> bytes:
    ordered = tuple(sorted(fields))
    if not kind or ordered != fields or len({name for name, _ in fields}) != len(fields):
        raise ValueError
    return kind + b"\0" + b"".join(
        len(name).to_bytes(4, "big") + name + len(value).to_bytes(8, "big") + value
        for name, value in fields
    )


def _read_verified_artifact(root: Path, artifact: _Artifact) -> None:
    data = _read_relative_file(root, tuple(artifact.path.split("/")), _MAX_ARTIFACT_BYTES)
    observed = hashlib.sha256(data).hexdigest()
    if not hmac.compare_digest(observed, artifact.sha256):
        raise ValueError


def _read_relative_file(root: Path, parts: tuple[str, ...], maximum: int) -> bytes:
    if not parts or any(not part or part in {".", ".."} or "/" in part or "\x00" in part for part in parts):
        raise ValueError
    directory: int | None = os.open(root, _DIRECTORY_FLAGS)
    fd: int | None = None
    try:
        for part in parts[:-1]:
            child = os.open(part, _DIRECTORY_FLAGS, dir_fd=directory)
            _close_quietly(directory)
            directory = child
        fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=directory)
        before = os.fstat(fd)
        if not _is_admissible_file(before, maximum):
            raise ValueError
        data = _read_bounded(fd, maximum)
        after = os.fstat(fd)
        if not _is_admissible_file(after, maximum) or _file_identity(before) != _file_identity(after):
            raise ValueError
        return data
    finally:
        _close_quietly(fd)
        _close_quietly(directory)


def _read_bounded(fd: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total <= maximum:
        chunk = os.read(fd, min(_READ_BYTES, maximum + 1 - total))
        if type(chunk) is not bytes:
            raise ValueError
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
    raise ValueError


def _is_admissible_file(info: os.stat_result, maximum: int) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and not info.st_mode & 0o022
        and 0 <= info.st_size <= maximum
    )


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _close_quietly(fd: int | None) -> None:
    if fd is not None:
        try:
            _OS_CLOSE(fd)
        except (OSError, OverflowError):
            pass
