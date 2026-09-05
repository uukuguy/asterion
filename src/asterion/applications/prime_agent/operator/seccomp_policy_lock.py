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
_UNSIGNED_64_BIT_MAX: Final = 2**64 - 1
_COMPARISON_OPERATORS: Final = frozenset(
    {
        "SCMP_CMP_EQ",
        "SCMP_CMP_NE",
        "SCMP_CMP_LT",
        "SCMP_CMP_LE",
        "SCMP_CMP_GT",
        "SCMP_CMP_GE",
        "SCMP_CMP_MASKED_EQ",
    }
)
_PLATFORM_ARCHITECTURES: Final[dict[tuple[str, str, str | None], str]] = {
    ("linux", "amd64", None): "SCMP_ARCH_X86_64",
    ("linux", "arm64", None): "SCMP_ARCH_AARCH64",
}
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
        "maximum_profile_sha256",
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
class SeccompArgumentConstraint:
    """One exact libseccomp argument comparison atom."""

    index: int
    op: str
    value: int
    value_two: int | None

    def __repr__(self) -> str:
        return "SeccompArgumentConstraint(redacted)"


@dataclass(frozen=True, repr=False, slots=True)
class SeccompRuleAtom:
    """One syscall name and its exact, normalized argument constraints.

    Future policy-subset checks may only use exact atom equality or omission;
    partial argument matching is not a v1 semantic.
    """

    syscall: str
    arguments: tuple[SeccompArgumentConstraint, ...]

    def __repr__(self) -> str:
        return "SeccompRuleAtom(redacted)"


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
    allowed_rule_atoms: tuple[SeccompRuleAtom, ...]
    maximum_profile_sha256: str

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
        decoded = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
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
            allowed_rule_atoms=tuple(_parse_rule_atom(item) for item in decoded["allowed_rule_atoms"]),
            maximum_profile_sha256=decoded["maximum_profile_sha256"],
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
        "allowed_rule_atoms": [
            _rule_atom_mapping(atom) for atom in checked.allowed_rule_atoms
        ],
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
        "maximum_profile_sha256": checked.maximum_profile_sha256,
        "schema_version": checked.schema_version,
        "starter_sha256": checked.starter_sha256,
        "workload_sha256": checked.workload_sha256,
    }


def _rule_atom_mapping(atom: SeccompRuleAtom) -> dict[str, object]:
    return {
        "arguments": [
            {
                "index": constraint.index,
                "op": constraint.op,
                "value": constraint.value,
                "value_two": constraint.value_two,
            }
            for constraint in atom.arguments
        ],
        "syscall": atom.syscall,
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
        value.maximum_profile_sha256,
    )
    if (
        type(value.schema_version) is not str
        or value.schema_version != _FORMAT
        or type(value.libseccomp_architecture) is not str
        or _ARCHITECTURE.fullmatch(value.libseccomp_architecture) is None
        or value.libseccomp_architecture != _platform_architecture(platform)
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
        platform = validate_image_platform_descriptor(value)
        _platform_architecture(platform)
        return platform
    except ValueError:
        raise PrimeP1SeccompPolicyLockError() from None


def _platform_architecture(platform: ImagePlatformDescriptor) -> str:
    try:
        return _PLATFORM_ARCHITECTURES[(platform.os, platform.architecture, platform.variant)]
    except KeyError:
        raise PrimeP1SeccompPolicyLockError() from None


def _normalized_atoms(value: object) -> tuple[SeccompRuleAtom, ...]:
    if (
        type(value) is not tuple
        or not value
        or any(_validated_rule_atom(atom) is not atom for atom in value)
        or tuple(sorted(set(value), key=_rule_atom_key)) != value
    ):
        raise PrimeP1SeccompPolicyLockError()
    return value


def _validated_rule_atom(value: object) -> SeccompRuleAtom:
    if (
        type(value) is not SeccompRuleAtom
        or type(value.syscall) is not str
        or _SYSCALL.fullmatch(value.syscall) is None
        or _normalized_constraints(value.arguments) != value.arguments
    ):
        raise PrimeP1SeccompPolicyLockError()
    return value


def _normalized_constraints(value: object) -> tuple[SeccompArgumentConstraint, ...]:
    if (
        type(value) is not tuple
        or any(_validated_constraint(item) is not item for item in value)
        or tuple(sorted(set(value), key=_constraint_key)) != value
    ):
        raise PrimeP1SeccompPolicyLockError()
    return value


def _validated_constraint(value: object) -> SeccompArgumentConstraint:
    if (
        type(value) is not SeccompArgumentConstraint
        or type(value.index) is not int
        or isinstance(value.index, bool)
        or not 0 <= value.index <= 5
        or type(value.op) is not str
        or value.op not in _COMPARISON_OPERATORS
        or type(value.value) is not int
        or isinstance(value.value, bool)
        or not 0 <= value.value <= _UNSIGNED_64_BIT_MAX
        or (
            value.value_two is not None
            and (
                type(value.value_two) is not int
                or isinstance(value.value_two, bool)
                or not 0 <= value.value_two <= _UNSIGNED_64_BIT_MAX
            )
        )
        or (value.op == "SCMP_CMP_MASKED_EQ") != (value.value_two is not None)
    ):
        raise PrimeP1SeccompPolicyLockError()
    return value


def _rule_atom_key(value: SeccompRuleAtom) -> tuple[str, tuple[tuple[int, str, int, bool, int], ...]]:
    return value.syscall, tuple(_constraint_key(item) for item in value.arguments)


def _constraint_key(value: SeccompArgumentConstraint) -> tuple[int, str, int, bool, int]:
    return value.index, value.op, value.value, value.value_two is not None, value.value_two or 0


def _parse_rule_atom(value: object) -> SeccompRuleAtom:
    if type(value) is not dict or set(value) != {"arguments", "syscall"}:
        raise ValueError
    arguments = value["arguments"]
    if type(arguments) is not list:
        raise ValueError
    return SeccompRuleAtom(value["syscall"], tuple(_parse_constraint(item) for item in arguments))


def _parse_constraint(value: object) -> SeccompArgumentConstraint:
    if type(value) is not dict or set(value) != {"index", "op", "value", "value_two"}:
        raise ValueError
    return SeccompArgumentConstraint(
        value["index"], value["op"], value["value"], value["value_two"]
    )


def _without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_json_constant(_: str) -> None:
    raise ValueError
