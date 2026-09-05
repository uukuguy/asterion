"""Code-owned, platform-keyed Prime P1 seccomp policy locks.

The promoted catalog is intentionally empty. This module defines no syscall
allowlist, candidate, or promotion mechanism; no candidate or promotion is
authority. It performs no host inspection.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Final

from .image_input_lock import ImagePlatformDescriptor, validate_image_platform_descriptor


_FORMAT: Final = "asterion.prime-p1-seccomp-policy-lock/v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ARCHITECTURE = re.compile(r"SCMP_ARCH_[A-Z0-9_]+\Z")
_SYSCALL = re.compile(r"[a-z0-9_]+\Z")
_LOCK_KEYS: Final = frozenset(
    {
        "allowed_rule_atoms",
        "build_input_sha256",
        "default_action",
        "image_config_digest",
        "launcher_sha256",
        "libseccomp_architecture",
        "oracle_sha256",
        "platform",
        "profile_sha256",
        "schema_version",
        "starter_sha256",
        "workload_sha256",
    }
)


class PrimeP1SeccompPolicyLockError(ValueError):
    """Single public-safe policy-lock failure category."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 seccomp policy lock is unavailable")


@dataclass(frozen=True, repr=False, slots=True)
class SeccompPolicyLock:
    """One exact, non-host-selected seccomp profile identity."""

    schema_version: str
    platform: ImagePlatformDescriptor
    libseccomp_architecture: str
    image_config_digest: str
    build_input_sha256: str
    launcher_sha256: str
    workload_sha256: str
    starter_sha256: str
    oracle_sha256: str
    default_action: str
    allowed_rule_atoms: tuple[str, ...]
    profile_sha256: str

    def __repr__(self) -> str:
        return "SeccompPolicyLock(redacted)"


@dataclass(frozen=True, repr=False, slots=True)
class PromotedSeccompPolicyCatalog:
    """Code-owned exact policy bindings; callers cannot supply a catalog."""

    locks: tuple[SeccompPolicyLock, ...]

    def __repr__(self) -> str:
        return "PromotedSeccompPolicyCatalog(redacted)"


PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG: Final = PromotedSeccompPolicyCatalog(())


def canonical_seccomp_policy_lock_bytes(lock: object) -> bytes:
    """Return canonical bytes for one strict, immutable policy lock."""
    try:
        value = _lock_mapping(lock)
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, PrimeP1SeccompPolicyLockError):
        raise PrimeP1SeccompPolicyLockError() from None


def seccomp_policy_lock_sha256(lock: object) -> str:
    """Return the SHA-256 of a canonical strict policy lock."""
    return hashlib.sha256(canonical_seccomp_policy_lock_bytes(lock)).hexdigest()


def parse_canonical_seccomp_policy_lock(data: object) -> SeccompPolicyLock:
    """Parse only an exact canonical policy-lock JSON byte sequence."""
    try:
        if type(data) is not bytes:
            raise ValueError
        decoded = json.loads(data.decode("utf-8"))
        if type(decoded) is not dict or set(decoded) != _LOCK_KEYS:
            raise ValueError
        platform = decoded["platform"]
        if type(platform) is not dict or set(platform) != {
            "architecture",
            "os",
            "variant",
        }:
            raise ValueError
        lock = SeccompPolicyLock(
            schema_version=decoded["schema_version"],
            platform=ImagePlatformDescriptor(
                platform["os"], platform["architecture"], platform["variant"]
            ),
            libseccomp_architecture=decoded["libseccomp_architecture"],
            image_config_digest=decoded["image_config_digest"],
            build_input_sha256=decoded["build_input_sha256"],
            launcher_sha256=decoded["launcher_sha256"],
            workload_sha256=decoded["workload_sha256"],
            starter_sha256=decoded["starter_sha256"],
            oracle_sha256=decoded["oracle_sha256"],
            default_action=decoded["default_action"],
            allowed_rule_atoms=tuple(decoded["allowed_rule_atoms"]),
            profile_sha256=decoded["profile_sha256"],
        )
        if canonical_seccomp_policy_lock_bytes(lock) != data:
            raise ValueError
        return lock
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        raise PrimeP1SeccompPolicyLockError() from None


def resolve_promoted_seccomp_policy(platform: object) -> SeccompPolicyLock:
    """Resolve one exact policy from the code-owned promoted catalog only."""
    try:
        requested = _platform(platform)
        catalog = PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG
        if type(catalog) is not PromotedSeccompPolicyCatalog or not catalog.locks:
            raise ValueError
        if type(catalog.locks) is not tuple:
            raise ValueError
        locks = tuple(_validated_lock(lock) for lock in catalog.locks)
        if len(set(lock.platform for lock in locks)) != len(locks):
            raise ValueError
        matches = tuple(lock for lock in locks if lock.platform == requested)
        if len(matches) != 1:
            raise ValueError
        return matches[0]
    except (TypeError, ValueError, PrimeP1SeccompPolicyLockError):
        raise PrimeP1SeccompPolicyLockError() from None


def _lock_mapping(lock: object) -> dict[str, object]:
    checked = _validated_lock(lock)
    return {
        "allowed_rule_atoms": list(checked.allowed_rule_atoms),
        "build_input_sha256": checked.build_input_sha256,
        "default_action": checked.default_action,
        "image_config_digest": checked.image_config_digest,
        "launcher_sha256": checked.launcher_sha256,
        "libseccomp_architecture": checked.libseccomp_architecture,
        "oracle_sha256": checked.oracle_sha256,
        "platform": {
            "architecture": checked.platform.architecture,
            "os": checked.platform.os,
            "variant": checked.platform.variant,
        },
        "profile_sha256": checked.profile_sha256,
        "schema_version": checked.schema_version,
        "starter_sha256": checked.starter_sha256,
        "workload_sha256": checked.workload_sha256,
    }


def _validated_lock(value: object) -> SeccompPolicyLock:
    if type(value) is not SeccompPolicyLock:
        raise PrimeP1SeccompPolicyLockError()
    platform = _platform(value.platform)
    hashes = (
        value.build_input_sha256,
        value.launcher_sha256,
        value.workload_sha256,
        value.starter_sha256,
        value.oracle_sha256,
        value.profile_sha256,
    )
    if (
        type(value.schema_version) is not str
        or value.schema_version != _FORMAT
        or type(value.libseccomp_architecture) is not str
        or value.libseccomp_architecture == "SCMP_ARCH_NATIVE"
        or _ARCHITECTURE.fullmatch(value.libseccomp_architecture) is None
        or type(value.image_config_digest) is not str
        or _IMAGE_DIGEST.fullmatch(value.image_config_digest) is None
        or any(type(item) is not str or _SHA256.fullmatch(item) is None for item in hashes)
        or value.default_action != "SCMP_ACT_ERRNO"
        or _normalized_atoms(value.allowed_rule_atoms) != value.allowed_rule_atoms
    ):
        raise PrimeP1SeccompPolicyLockError()
    if platform is not value.platform:
        raise PrimeP1SeccompPolicyLockError()
    return value


def _platform(value: object) -> ImagePlatformDescriptor:
    try:
        return validate_image_platform_descriptor(value)
    except ValueError:
        raise PrimeP1SeccompPolicyLockError() from None


def _normalized_atoms(value: object) -> tuple[str, ...]:
    if (
        type(value) is not tuple
        or not value
        or any(type(atom) is not str or _SYSCALL.fullmatch(atom) is None for atom in value)
        or tuple(sorted(set(value))) != value
    ):
        raise PrimeP1SeccompPolicyLockError()
    return value
