"""Closed promoted identities for the separately shipped Prime P1 authority ELF."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .authority_resources import PrimeP1AuthorityResourceError
from .image_input_lock import ImagePlatformDescriptor, validate_image_platform_descriptor


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_SIZE = 2**32


@dataclass(frozen=True, slots=True)
class AuthorityExecutableLock:
    """One syntax-only, target-specific immutable authority executable identity."""

    target: ImagePlatformDescriptor
    format: str
    size: int
    sha256: str


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
