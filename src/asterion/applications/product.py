"""Immutable, provider-neutral capability discovery and verification values."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_ENVIRONMENT_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_VERSION = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
_COST_CLASSES = frozenset(
    {"provider-free", "bounded-provider-backed", "full-dataset"}
)
_STATUSES = frozenset({"PASS", "FAIL", "SKIP", "NOT RUN"})


class CapabilityProductError(ValueError):
    """Raised when a capability-product value is unsafe or inconsistent."""


@dataclass(frozen=True)
class ConfigurationRequirement:
    name: str
    purpose: str
    required_for: tuple[str, ...]
    secret: bool
    default: str | None
    hint: str


@dataclass(frozen=True)
class CapabilityFunction:
    function_id: str
    summary: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class VerificationProfile:
    level: str
    summary: str
    cost_class: str
    provider_backed_operation_count: int
    full_dataset: bool


@dataclass(frozen=True)
class CapabilityProductDescription:
    product_id: str
    version: str
    summary: str
    functions: tuple[CapabilityFunction, ...]
    configuration: tuple[ConfigurationRequirement, ...]
    profiles: tuple[VerificationProfile, ...]


@dataclass(frozen=True)
class VerificationRequest:
    level: str
    env_file: Path | None
    corpus_root: Path | None
    output_root: Path | None
    acceptance_root: Path | None


@dataclass(frozen=True)
class VerificationCheckResult:
    check_id: str
    summary: str
    status: str
    artifact_refs: tuple[str, ...] = ()
    counts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class VerificationResult:
    product_id: str
    level: str
    status: str
    checks: tuple[VerificationCheckResult, ...]
    provider_backed_operation_count: int
    full_dataset_ran: bool


class CapabilityVerifier(Protocol):
    def __call__(self, request: VerificationRequest) -> VerificationResult: ...


@dataclass(frozen=True)
class InstalledCapabilityProduct:
    description: CapabilityProductDescription
    verifier: CapabilityVerifier


def validate_capability_product(
    value: InstalledCapabilityProduct,
) -> InstalledCapabilityProduct:
    """Fail closed unless one installed product is immutable and safe to render."""

    if not isinstance(value, InstalledCapabilityProduct) or not callable(value.verifier):
        raise CapabilityProductError("installed capability product is invalid")
    item = value.description
    if (
        not isinstance(item, CapabilityProductDescription)
        or not _identifier(item.product_id)
        or not isinstance(item.version, str)
        or _VERSION.fullmatch(item.version) is None
        or not _safe_text(item.summary)
    ):
        raise CapabilityProductError("capability product description is invalid")
    if not _sorted_unique(item.functions, "function_id"):
        raise CapabilityProductError("capability functions are invalid")
    for function in item.functions:
        if (
            not isinstance(function, CapabilityFunction)
            or not _identifier(function.function_id)
            or not _safe_text(function.summary)
            or not isinstance(function.argv, tuple)
            or not function.argv
            or any(not _safe_argument(argument) for argument in function.argv)
        ):
            raise CapabilityProductError("capability function is invalid")
    if not _sorted_unique(item.configuration, "name"):
        raise CapabilityProductError("capability configuration is invalid")
    for requirement in item.configuration:
        if (
            not isinstance(requirement, ConfigurationRequirement)
            or _ENVIRONMENT_NAME.fullmatch(requirement.name) is None
            or not _safe_text(requirement.purpose)
            or not isinstance(requirement.required_for, tuple)
            or tuple(sorted(set(requirement.required_for))) != requirement.required_for
            or any(not _identifier(level) for level in requirement.required_for)
            or not isinstance(requirement.secret, bool)
            or (requirement.default is not None and not _safe_argument(requirement.default))
            or not _safe_text(requirement.hint)
        ):
            raise CapabilityProductError("capability configuration is invalid")
    if not _sorted_unique(item.profiles, "level"):
        raise CapabilityProductError("verification profiles are invalid")
    for profile in item.profiles:
        if (
            not isinstance(profile, VerificationProfile)
            or not _identifier(profile.level)
            or not _safe_text(profile.summary)
            or profile.cost_class not in _COST_CLASSES
            or not isinstance(profile.provider_backed_operation_count, int)
            or profile.provider_backed_operation_count < 0
            or not isinstance(profile.full_dataset, bool)
        ):
            raise CapabilityProductError("verification profile is invalid")
    return value


def validate_verification_result(
    value: VerificationResult, description: CapabilityProductDescription
) -> VerificationResult:
    """Validate a body-free aggregate result against its public description."""

    levels = {profile.level for profile in description.profiles}
    if (
        not isinstance(value, VerificationResult)
        or value.product_id != description.product_id
        or value.level not in levels
        or value.status not in _STATUSES
        or not isinstance(value.checks, tuple)
        or not isinstance(value.provider_backed_operation_count, int)
        or value.provider_backed_operation_count < 0
        or not isinstance(value.full_dataset_ran, bool)
    ):
        raise CapabilityProductError("verification result is invalid")
    if not _sorted_unique(value.checks, "check_id"):
        raise CapabilityProductError("verification checks are invalid")
    for check in value.checks:
        if (
            not isinstance(check, VerificationCheckResult)
            or not _identifier(check.check_id)
            or not _safe_text(check.summary)
            or check.status not in _STATUSES
            or not isinstance(check.artifact_refs, tuple)
            or any(not _safe_artifact(reference) for reference in check.artifact_refs)
            or not isinstance(check.counts, tuple)
            or tuple(sorted(set(check.counts))) != check.counts
            or any(
                not isinstance(count, tuple)
                or len(count) != 2
                or not _identifier(count[0])
                or not isinstance(count[1], int)
                or count[1] < 0
                for count in check.counts
            )
        ):
            raise CapabilityProductError("verification check is invalid")
    return value


def _sorted_unique(values: object, attribute: str) -> bool:
    if not isinstance(values, tuple) or not values:
        return False
    try:
        identities = tuple(getattr(value, attribute) for value in values)
    except AttributeError:
        return False
    return tuple(sorted(set(identities))) == identities


def _identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def _safe_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\n" not in value and "\r" not in value


def _safe_argument(value: object) -> bool:
    return isinstance(value, str) and bool(value) and "\x00" not in value and "\n" not in value


def _safe_artifact(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and path.as_posix() == value
