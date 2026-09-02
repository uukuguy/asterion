"""Closed, platform-neutral inputs for candidate Prime image releases."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final

from .image_input_lock import (
    ImagePlatformDescriptor,
    validate_image_platform_descriptor,
)


_COMMIT: Final = re.compile(r"[0-9a-f]{40}")
_SHA256: Final = re.compile(r"[0-9a-f]{64}")


class PrimeReleaseRecipeError(ValueError):
    """Raised when a Prime release recipe or target policy is invalid."""


@dataclass(frozen=True)
class PrimeSourceTriple:
    commit: str
    tree_sha256: str
    package_lock_sha256: str


@dataclass(frozen=True)
class ReleaseRecipe:
    source: PrimeSourceTriple
    recipe_revision: str
    python_major_minor: str
    node_version: str
    base_distribution: str
    libc: str
    python_dependency_lock_sha256: str
    frontend_recipe_sha256: str


@dataclass(frozen=True)
class CandidateTargetPolicy:
    targets: tuple[ImagePlatformDescriptor, ...]


PRIME_IPYTHON_SOURCE: Final = PrimeSourceTriple(
    "a18809e00ea30638584d87b3afea7285a9d7296c",
    "93a4b02ecc0cc114865fa3d336521cf214047cf4de471b36b51fe610c84ab686",
    "39ee303bca10c0933cf917275613c8f44099f50de1650a5c356e7cda02b701e8",
)
PRIME_IPYTHON_RELEASE_RECIPE: Final = ReleaseRecipe(
    PRIME_IPYTHON_SOURCE,
    "prime-ipython-release-recipe/v1",
    "3.11",
    "22.8.0",
    "debian-bookworm",
    "glibc",
    "c2b0455a4746b1b6274602b933b1492a7c04689288571f0dbd03347042c197f2",
    "60f9f4f3e26c14a3ac6fd0703400506835392b81d7b3d22755d7e68c1881ec84",
)
PRIME_IPYTHON_CANDIDATE_TARGET_POLICY: Final = CandidateTargetPolicy(
    (
        ImagePlatformDescriptor("linux", "arm64", None),
        ImagePlatformDescriptor("linux", "amd64", None),
    )
)


def _invalid() -> PrimeReleaseRecipeError:
    return PrimeReleaseRecipeError("Prime release recipe is invalid")


def validate_release_recipe(value: object) -> ReleaseRecipe:
    """Accept only the code-owned, fully pinned platform-neutral recipe."""

    if (
        type(value) is not ReleaseRecipe
        or type(value.source) is not PrimeSourceTriple
        or any(
            type(part) is not str
            for part in (
                value.source.commit,
                value.source.tree_sha256,
                value.source.package_lock_sha256,
                value.recipe_revision,
                value.python_major_minor,
                value.node_version,
                value.base_distribution,
                value.libc,
                value.python_dependency_lock_sha256,
                value.frontend_recipe_sha256,
            )
        )
        or _COMMIT.fullmatch(value.source.commit) is None
        or any(
            _SHA256.fullmatch(part) is None
            for part in (
                value.source.tree_sha256,
                value.source.package_lock_sha256,
                value.python_dependency_lock_sha256,
                value.frontend_recipe_sha256,
            )
        )
        or value is not PRIME_IPYTHON_RELEASE_RECIPE
        or value.source is not PRIME_IPYTHON_SOURCE
        or value.python_major_minor != "3.11"
        or value.node_version != "22.8.0"
        or value.base_distribution != "debian-bookworm"
        or value.libc != "glibc"
    ):
        raise _invalid()
    return value


def validate_candidate_target_policy(value: object) -> CandidateTargetPolicy:
    """Accept only the sorted, code-owned two-target candidate policy."""

    if type(value) is not CandidateTargetPolicy or type(value.targets) is not tuple:
        raise _invalid()
    try:
        if any(
            validate_image_platform_descriptor(target) is not target
            for target in value.targets
        ):
            raise ValueError
        expected = (
            ImagePlatformDescriptor("linux", "arm64", None),
            ImagePlatformDescriptor("linux", "amd64", None),
        )
        if value.targets != expected or len(set(value.targets)) != len(value.targets):
            raise ValueError
        if value is not PRIME_IPYTHON_CANDIDATE_TARGET_POLICY:
            raise ValueError
    except (TypeError, ValueError):
        raise _invalid() from None
    return value


def resolve_candidate_target(target: object) -> ImagePlatformDescriptor:
    """Resolve a declared candidate target without inspecting the host."""

    try:
        requested = validate_image_platform_descriptor(target)
        policy = validate_candidate_target_policy(PRIME_IPYTHON_CANDIDATE_TARGET_POLICY)
        matches = tuple(
            candidate for candidate in policy.targets if candidate == requested
        )
        if len(matches) != 1:
            raise ValueError
        return matches[0]
    except (TypeError, ValueError, PrimeReleaseRecipeError):
        raise _invalid() from None
