"""Admission of the fixed non-code resources for the Prime P1 application."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path
import stat
import threading
from typing import Final, NoReturn, SupportsIndex
from weakref import WeakKeyDictionary

from .authority_request_contract import canonical_prime_p1_request_contract_bytes
from .authority_resources import PrimeP1AuthorityResourceError


_TOKEN = object()
_PROTOCOL: Final = "asterion.prime-p1-application-resource-lock/v1"
_DESCRIPTOR_PARTS: Final = ("resources", "prime-p1-application-resource-lock.json")
_EXPECTED_PATHS: Final = (
    "applications/prime_agent/assemblies/prime-ipython-coding.json",
    "applications/prime_agent/operator/image/fixture/fixture-lock.json",
    "applications/prime_agent/operator/image/fixture/oracle/oracle.py",
    "applications/prime_agent/operator/image/fixture/starter/solution.py",
    "applications/prime_agent/operator/image/fixture/workload.json",
    "applications/prime_agent/operator/image/launcher.py",
    "capabilities/prime_agent/payload/capabilities/ipython-coding.json",
    "capabilities/prime_agent/payload/capability-package.json",
    "capabilities/prime_agent/payload/resources/prime-ipython-coding.fixture",
)
_RECEIPT_RESOURCE_PATHS: Final = {
    "assembly_sha256": "applications/prime_agent/assemblies/prime-ipython-coding.json",
    "package_manifest_sha256": "capabilities/prime_agent/payload/capability-package.json",
    "workload_sha256": "applications/prime_agent/operator/image/fixture/workload.json",
    "starter_sha256": "applications/prime_agent/operator/image/fixture/starter/solution.py",
    "oracle_sha256": "applications/prime_agent/operator/image/fixture/oracle/oracle.py",
}
_DIRECTORY_FLAGS: Final = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_FILE_FLAGS: Final = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_MAX_DESCRIPTOR_BYTES: Final = 64 * 1024
_MAX_RESOURCE_BYTES: Final = 1024 * 1024
_READ_BYTES: Final = 64 * 1024
_OS_CLOSE = os.close


@dataclass(frozen=True, slots=True, init=False, repr=False, eq=False, weakref_slot=True)
class _ApplicationReceiptProjection:
    """Private exact application identities retained for authority receipts."""

    assembly_sha256: str
    package_manifest_sha256: str
    workload_sha256: str
    starter_sha256: str
    oracle_sha256: str

    def __init__(self, values: dict[str, str], *, _token: object | None = None) -> None:
        if _token is not _TOKEN or set(values) != set(_RECEIPT_RESOURCE_PATHS):
            raise PrimeP1AuthorityResourceError() from None
        if any(not _valid_digest(value) for value in values.values()):
            raise PrimeP1AuthorityResourceError() from None
        for field, value in values.items():
            object.__setattr__(self, field, value)

    def __repr__(self) -> str:
        return "ApplicationReceiptProjection(redacted)"


_ISSUED_PROJECTIONS: WeakKeyDictionary[
    _ApplicationReceiptProjection, tuple[bytes, tuple[str, ...]]
] = WeakKeyDictionary()
_ISSUED_PROJECTIONS_LOCK = threading.Lock()


class AdmittedPrimeP1ApplicationResources:
    """Opaque, idempotently closeable proof of exact application resources."""

    __slots__ = ("_closed", "_identity", "_lock", "_projection")

    def __init__(
        self,
        identity: bytes | None = None,
        projection: _ApplicationReceiptProjection | None = None,
        *,
        _token: object | None = None,
    ) -> None:
        if type(self) is not AdmittedPrimeP1ApplicationResources or _token is not _TOKEN:
            raise PrimeP1AuthorityResourceError() from None
        self._closed = False
        self._identity = identity
        self._lock = threading.Lock()
        self._projection = projection

    def __repr__(self) -> str:
        return "AdmittedPrimeP1ApplicationResources(redacted)"

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
        """Return the opaque identity of this admitted fixed resource descriptor."""
        with self._lock:
            identity = self._identity
            if self._closed or type(identity) is not bytes or len(identity) != 32:
                raise ValueError
        return _canonical_contribution(b"application-resources", ((b"descriptor-sha256", identity),))

    def _receipt_projection(self) -> _ApplicationReceiptProjection:
        """Return exact internal receipt identities while this owner remains live."""
        with self._lock:
            projection = self._projection
            identity = self._identity
            if self._closed or not _valid_receipt_projection(projection, identity):
                raise ValueError
            assert type(projection) is _ApplicationReceiptProjection
        return projection


def admit_prime_p1_application_resources() -> AdmittedPrimeP1ApplicationResources:
    """Admit only the descriptor's fixed P1 application resource bytes."""
    admitted: AdmittedPrimeP1ApplicationResources | None = None
    try:
        identity, resources = _load_descriptor()
        _validate_contract_identity(identity)
        root = _asterion_root()
        for path, digest in resources:
            _read_verified_resource(root, path, digest)
        descriptor_identity = _descriptor_identity(identity, resources)
        admitted = AdmittedPrimeP1ApplicationResources(
            descriptor_identity,
            _application_receipt_projection(descriptor_identity, resources),
            _token=_TOKEN,
        )
    except BaseException:
        pass
    if admitted is None:
        raise PrimeP1AuthorityResourceError() from None
    return admitted


def _operator_root() -> Path:
    root = Path(__file__).resolve().parent
    if not root.is_dir():
        raise ValueError
    return root


def _asterion_root() -> Path:
    root = _operator_root().parents[2]
    if not root.is_dir():
        raise ValueError
    return root


def _descriptor_path() -> Path:
    return _operator_root().joinpath(*_DESCRIPTOR_PARTS)


def _load_descriptor() -> tuple[dict[str, str], tuple[tuple[str, str], ...]]:
    raw = _read_relative_file(_operator_root(), _DESCRIPTOR_PARTS, _MAX_DESCRIPTOR_BYTES)
    if raw.decode("utf-8").encode("utf-8") != raw:
        raise ValueError
    value = json.loads(raw)
    canonical = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if raw not in {canonical, canonical + b"\n"}:
        raise ValueError
    if type(value) is not dict or set(value) != {"protocol", "identity", "resources"}:
        raise ValueError
    if value["protocol"] != _PROTOCOL or type(value["identity"]) is not dict:
        raise ValueError
    identity = value["identity"]
    expected_identity = {
        "application_id", "application_version", "assembly_ref", "package_ref",
        "implementation_ref", "runtime_id", "workload_sha256", "oracle_sha256",
    }
    if set(identity) != expected_identity or any(type(item) is not str for item in identity.values()):
        raise ValueError
    values = value["resources"]
    if type(values) is not list or len(values) != len(_EXPECTED_PATHS):
        raise ValueError
    resources: list[tuple[str, str]] = []
    for item in values:
        if type(item) is not dict or set(item) != {"path", "sha256"}:
            raise ValueError
        path, digest = item["path"], item["sha256"]
        if not _valid_relative_path(path) or not _valid_digest(digest):
            raise ValueError
        resources.append((path, digest))
    if tuple(path for path, _ in resources) != _EXPECTED_PATHS:
        raise ValueError
    return identity, tuple(resources)


def _validate_contract_identity(identity: dict[str, str]) -> None:
    contract = json.loads(canonical_prime_p1_request_contract_bytes())
    expected = {key: contract["identity"][key] for key in (
        "application_id", "application_version", "assembly_ref", "package_ref",
        "implementation_ref", "runtime_id",
    )}
    expected["workload_sha256"] = contract["workload_sha256"]
    expected["oracle_sha256"] = contract["oracle_sha256"]
    if set(identity) != set(expected) or any(
        not hmac.compare_digest(identity[key], expected[key]) for key in expected
    ):
        raise ValueError


def _descriptor_identity(
    identity: dict[str, str], resources: tuple[tuple[str, str], ...]
) -> bytes:
    """Hash only the exact descriptor values already admitted by this module."""
    document = {"identity": identity, "resources": [dict(path=path, sha256=digest) for path, digest in resources]}
    return hashlib.sha256(
        json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")
    ).digest()


def _application_receipt_projection(
    descriptor_identity: bytes,
    resources: tuple[tuple[str, str], ...],
) -> _ApplicationReceiptProjection:
    digests = dict(resources)
    values = {
        field: digests[path]
        for field, path in _RECEIPT_RESOURCE_PATHS.items()
    }
    if type(descriptor_identity) is not bytes or len(descriptor_identity) != 32 or len(digests) != len(resources):
        raise ValueError
    projection = _ApplicationReceiptProjection(values, _token=_TOKEN)
    expected = tuple(values[field] for field in _RECEIPT_RESOURCE_PATHS)
    with _ISSUED_PROJECTIONS_LOCK:
        _ISSUED_PROJECTIONS[projection] = (descriptor_identity, expected)
    return projection


def _valid_receipt_projection(value: object, descriptor_identity: object) -> bool:
    if (
        type(value) is not _ApplicationReceiptProjection
        or type(descriptor_identity) is not bytes
        or len(descriptor_identity) != 32
    ):
        return False
    with _ISSUED_PROJECTIONS_LOCK:
        issued = _ISSUED_PROJECTIONS.get(value)
    if issued is None or issued[0] is not descriptor_identity:
        return False
    return all(
        type(getattr(value, field)) is str
        and hmac.compare_digest(getattr(value, field), expected)
        for field, expected in zip(_RECEIPT_RESOURCE_PATHS, issued[1], strict=True)
    )


def _canonical_contribution(kind: bytes, fields: tuple[tuple[bytes, bytes], ...]) -> bytes:
    ordered = tuple(sorted(fields))
    if not kind or ordered != fields or len({name for name, _ in fields}) != len(fields):
        raise ValueError
    return kind + b"\0" + b"".join(
        len(name).to_bytes(4, "big") + name + len(value).to_bytes(8, "big") + value
        for name, value in fields
    )


def _read_verified_resource(root: Path, path: str, digest: str) -> None:
    data = _read_relative_file(root, tuple(path.split("/")), _MAX_RESOURCE_BYTES)
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), digest):
        raise ValueError


def _read_relative_file(root: Path, parts: tuple[str, ...], maximum: int) -> bytes:
    if not parts or any(not part or part in {".", ".."} or "/" in part or "\x00" in part for part in parts):
        raise ValueError
    directory: int | None = None
    fd: int | None = None
    try:
        directory = os.open(root, _DIRECTORY_FLAGS)
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
    except OSError as error:
        raise ValueError from error
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
    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not info.st_mode & 0o022 and 0 <= info.st_size <= maximum


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _valid_relative_path(value: object) -> bool:
    return type(value) is str and value in _EXPECTED_PATHS


def _valid_digest(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _close_quietly(fd: int | None) -> None:
    if fd is not None:
        try:
            _OS_CLOSE(fd)
        except (OSError, OverflowError):
            pass
