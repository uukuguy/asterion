"""Closed, platform-neutral inputs for candidate Prime image releases."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
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
class MetadataParserRevisions:
    """Exact revisions of the offline parsers used by one recipe."""

    node_shasums: str
    pypi_json: str
    oci_index: str
    oci_manifest: str
    recipe_output_manifest: str
    claim_binding: str


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
    fixture_recipe_sha256: str
    artifact_graph_revision: str
    metadata_parsers: MetadataParserRevisions


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
    "e7d1c4f41d328f3c602cd4f63d0d21aab6e4f1398aec2c03931e3da53ba39374",
    "f692e4caef89d47bb7e1d9f95f7bea4cd6d4fcbb3696f00de6e40f2a4f39f7b0",
    MetadataParserRevisions(
        "7b079ae3f8345f3073f8f9ad3ff8a0d1bc2c5778159999cf4f32af64b0f462f8",
        "88ca64b969e03b6037d3301f1b87a6e7bcf3b0c3a50105a044d08043bfb1423b",
        "f4c122e34fed7dbb76d3a83e9ea36c2caa29e2c540d7387992913bcd50f2f2b8",
        "2c6a81c2aec66e4de6d05a067d8e72a2c59740f10b51e0b798fc540952c29d75",
        "3a07ec4477aa8bd3668e0aa89b5a8e3311a065d15e0d11e5f9aed0616b92c1f8",
        "80a8d9c0c2a88fcb9ad847052b9bb777f6e7e3807982b5bfeb580454490d4d9b",
    ),
)
PRIME_IPYTHON_CANDIDATE_TARGET_POLICY: Final = CandidateTargetPolicy(
    (
        ImagePlatformDescriptor("linux", "arm64", None),
        ImagePlatformDescriptor("linux", "amd64", None),
    )
)


def _invalid() -> PrimeReleaseRecipeError:
    return PrimeReleaseRecipeError("Prime release recipe is invalid")


def _validate_recipe_structure(value: object) -> ReleaseRecipe:
    if type(value) is not ReleaseRecipe or type(value.source) is not PrimeSourceTriple:
        raise _invalid()
    parser_revisions = value.metadata_parsers
    if type(parser_revisions) is not MetadataParserRevisions:
        raise _invalid()
    scalar_values = (
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
        value.fixture_recipe_sha256,
        value.artifact_graph_revision,
        parser_revisions.node_shasums,
        parser_revisions.pypi_json,
        parser_revisions.oci_index,
        parser_revisions.oci_manifest,
        parser_revisions.recipe_output_manifest,
        parser_revisions.claim_binding,
    )
    if any(type(part) is not str for part in scalar_values):
        raise _invalid()
    if _COMMIT.fullmatch(value.source.commit) is None or any(
        _SHA256.fullmatch(part) is None
        for part in (
            value.source.tree_sha256,
            value.source.package_lock_sha256,
            value.python_dependency_lock_sha256,
            value.frontend_recipe_sha256,
            value.fixture_recipe_sha256,
            value.artifact_graph_revision,
            parser_revisions.node_shasums,
            parser_revisions.pypi_json,
            parser_revisions.oci_index,
            parser_revisions.oci_manifest,
            parser_revisions.recipe_output_manifest,
            parser_revisions.claim_binding,
        )
    ):
        raise _invalid()
    return value


def canonical_release_recipe_json(recipe: object) -> str:
    """Encode a structurally valid platform-neutral recipe canonically."""

    value = _validate_recipe_structure(recipe)
    return json.dumps(
        {
            "artifact_graph_revision": value.artifact_graph_revision,
            "base_distribution": value.base_distribution,
            "fixture_recipe_sha256": value.fixture_recipe_sha256,
            "frontend_recipe_sha256": value.frontend_recipe_sha256,
            "libc": value.libc,
            "metadata_parsers": {
                "claim_binding": value.metadata_parsers.claim_binding,
                "node_shasums": value.metadata_parsers.node_shasums,
                "oci_index": value.metadata_parsers.oci_index,
                "oci_manifest": value.metadata_parsers.oci_manifest,
                "pypi_json": value.metadata_parsers.pypi_json,
                "recipe_output_manifest": value.metadata_parsers.recipe_output_manifest,
            },
            "node_version": value.node_version,
            "python_dependency_lock_sha256": value.python_dependency_lock_sha256,
            "python_major_minor": value.python_major_minor,
            "recipe_revision": value.recipe_revision,
            "source": {
                "commit": value.source.commit,
                "package_lock_sha256": value.source.package_lock_sha256,
                "tree_sha256": value.source.tree_sha256,
            },
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def release_recipe_sha256(recipe: object) -> str:
    """Return the digest covering every platform-neutral recipe field."""

    return sha256(canonical_release_recipe_json(recipe).encode()).hexdigest()


def validate_release_recipe(value: object) -> ReleaseRecipe:
    """Accept only the code-owned, fully pinned platform-neutral recipe."""

    try:
        validated = _validate_recipe_structure(value)
    except PrimeReleaseRecipeError:
        raise
    if (
        validated is not PRIME_IPYTHON_RELEASE_RECIPE
        or validated.source is not PRIME_IPYTHON_SOURCE
        or validated.python_major_minor != "3.11"
        or validated.node_version != "22.8.0"
        or validated.base_distribution != "debian-bookworm"
        or validated.libc != "glibc"
    ):
        raise _invalid()
    return validated


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
