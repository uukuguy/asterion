"""Closed promoted identities for the separately shipped Prime P1 authority ELF."""

from __future__ import annotations

from dataclasses import dataclass
import re
import threading
from typing import NoReturn, SupportsIndex

from .authority_resources import PrimeP1AuthorityResourceError
from .image_input_lock import ImagePlatformDescriptor, validate_image_platform_descriptor


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_SIZE = 2**32
_TOKEN = object()


@dataclass(frozen=True, slots=True)
class AuthorityExecutableLock:
    """One syntax-only, target-specific immutable authority executable identity."""

    target: ImagePlatformDescriptor
    format: str
    size: int
    sha256: str


class AdmittedPrimeP1AuthorityExecutable:
    """Opaque admission of one promoted authority executable identity."""

    __slots__ = ("_closed", "_identity", "_lock")

    def __init__(
        self, lock_record: AuthorityExecutableLock, *, _token: object | None = None
    ) -> None:
        if (
            type(self) is not AdmittedPrimeP1AuthorityExecutable
            or _token is not _TOKEN
            or not _valid(lock_record)
        ):
            raise PrimeP1AuthorityResourceError() from None
        self._identity = bytes.fromhex(lock_record.sha256)
        self._closed = False
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "AdmittedPrimeP1AuthorityExecutable(redacted)"

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
        with self._lock:
            identity = self._identity
            if self._closed or type(identity) is not bytes or len(identity) != 32:
                raise ValueError
        return (
            b"authority-executable\0"
            + len(b"sha256").to_bytes(4, "big")
            + b"sha256"
            + (32).to_bytes(8, "big")
            + identity
        )


# Promotion is intentionally empty until a separately released Linux ELF exists.
PRIME_P1_PROMOTED_AUTHORITY_EXECUTABLE_CATALOG: tuple[AuthorityExecutableLock, ...] = ()


def resolve_promoted_authority_executable_lock(
    target: object,
) -> AuthorityExecutableLock:
    """Select one exact promoted identity without inspecting this build host."""
    try:
        expected = validate_image_platform_descriptor(target)
        if expected.os != "linux" or expected.variant is not None:
            raise ValueError
        catalog = PRIME_P1_PROMOTED_AUTHORITY_EXECUTABLE_CATALOG
        if type(catalog) is not tuple:
            raise ValueError
        matches = tuple(lock for lock in catalog if _valid(lock) and lock.target == expected)
        if len(matches) != 1 or not _sorted_unique(catalog):
            raise ValueError
        return matches[0]
    except BaseException:
        raise PrimeP1AuthorityResourceError() from None


def admit_promoted_authority_executable(
    target: object,
) -> AdmittedPrimeP1AuthorityExecutable:
    """Admit only one exact target-specific promoted executable identity."""
    try:
        return AdmittedPrimeP1AuthorityExecutable(
            resolve_promoted_authority_executable_lock(target), _token=_TOKEN
        )
    except BaseException:
        raise PrimeP1AuthorityResourceError() from None


def _valid(value: object) -> bool:
    return (
        type(value) is AuthorityExecutableLock
        and _valid_target(value.target)
        and value.format == "elf"
        and type(value.size) is int
        and 0 < value.size <= _MAX_SIZE
        and type(value.sha256) is str
        and _SHA256.fullmatch(value.sha256) is not None
    )


def _valid_target(value: object) -> bool:
    try:
        target = validate_image_platform_descriptor(value)
        return target.os == "linux" and target.variant is None
    except BaseException:
        return False


def _sorted_unique(catalog: tuple[AuthorityExecutableLock, ...]) -> bool:
    keys = tuple((lock.target.os, lock.target.architecture, lock.target.variant or "") for lock in catalog)
    return all(_valid(lock) for lock in catalog) and keys == tuple(sorted(keys)) and len(set(keys)) == len(keys)
