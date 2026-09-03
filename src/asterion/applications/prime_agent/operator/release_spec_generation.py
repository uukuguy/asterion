"""Pure, proposal-only generation for Prime IPython release specifications."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Final, Literal, cast
from urllib.parse import urlsplit

from . import release_recipe


_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_COMMIT: Final = re.compile(r"[0-9a-f]{40}")
_PATH: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_KIND: Final = re.compile(r"[a-z][a-z0-9-]*")
_GENERATOR_REVISION: Final = "prime-release-spec-generator/v1"
_METADATA_PARSER_REVISION: Final = "prime-release-metadata-parser/v1"
_FORMAT: Final = "asterion.prime-ipython-release-spec-generation/v1"


class PrimeReleaseSpecGenerationError(ValueError):
    """Raised when injected release-capture records are not canonical."""


@dataclass(frozen=True)
class ExactTargetDescriptor:
    os: str
    architecture: str
    variant: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "architecture": self.architecture,
            "os": self.os,
            "variant": self.variant,
        }


PrimeSourceTriple = release_recipe.PrimeSourceTriple
PRIME_IPYTHON_SOURCE: Final = release_recipe.PRIME_IPYTHON_SOURCE


@dataclass(frozen=True)
class SubstrateObservation:
    target: ExactTargetDescriptor
    substrate: Literal["native-linux", "desktop-vm", "emulated"]
    emulated: bool


@dataclass(frozen=True)
class MetadataBlob:
    parser_revision: str
    size: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "parser_revision": self.parser_revision,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(frozen=True)
class ObjectBlob:
    url: str = field(repr=False)
    size: int
    sha256: str

    def as_public_dict(self) -> dict[str, object]:
        return {
            "sha256": self.sha256,
            "size": self.size,
            "url_sha256": hashlib.sha256(self.url.encode("utf-8")).hexdigest(),
        }


@dataclass(frozen=True)
class MetadataObjectClaim:
    artifact_kind: str
    artifact_path: str
    metadata: MetadataBlob
    object: ObjectBlob
    declared_object_size: int
    declared_object_sha256: str

    def as_public_dict(self) -> dict[str, object]:
        return {
            "artifact_kind": self.artifact_kind,
            "artifact_path": self.artifact_path,
            "declared_object_sha256": self.declared_object_sha256,
            "declared_object_size": self.declared_object_size,
            "metadata": self.metadata.as_dict(),
            "object": self.object.as_public_dict(),
        }


@dataclass(frozen=True)
class PublicObjectBlob:
    """Review-safe object evidence; capture locators never leave the request."""

    size: int
    sha256: str
    url_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "sha256": self.sha256,
            "size": self.size,
            "url_sha256": self.url_sha256,
        }


@dataclass(frozen=True)
class PublicMetadataObjectClaim:
    """A review-safe projection of an injected, untrusted metadata claim."""

    artifact_kind: str
    artifact_path: str
    metadata: MetadataBlob
    object: PublicObjectBlob
    declared_object_size: int
    declared_object_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "artifact_kind": self.artifact_kind,
            "artifact_path": self.artifact_path,
            "declared_object_sha256": self.declared_object_sha256,
            "declared_object_size": self.declared_object_size,
            "metadata": self.metadata.as_dict(),
            "object": self.object.as_dict(),
        }


def _public_claim(value: MetadataObjectClaim) -> PublicMetadataObjectClaim:
    return PublicMetadataObjectClaim(
        value.artifact_kind,
        value.artifact_path,
        value.metadata,
        PublicObjectBlob(
            value.object.size,
            value.object.sha256,
            hashlib.sha256(value.object.url.encode("utf-8")).hexdigest(),
        ),
        value.declared_object_size,
        value.declared_object_sha256,
    )


@dataclass(frozen=True)
class ReleaseSpecGenerationRequest:
    target: ExactTargetDescriptor
    source: PrimeSourceTriple
    observation: SubstrateObservation
    recipe: release_recipe.ReleaseRecipe
    claims: tuple[MetadataObjectClaim, ...]
    generator_revision: str


@dataclass(frozen=True)
class UntrustedAcquisitionLock:
    target: ExactTargetDescriptor
    source: PrimeSourceTriple
    claims: tuple[PublicMetadataObjectClaim, ...]
    untrusted: Literal[True] = True

    def as_dict(self) -> dict[str, object]:
        return {
            "claims": [claim.as_dict() for claim in self.claims],
            "format": "asterion.prime-ipython-acquisition-lock/v1",
            "source": _source_dict(self.source),
            "target": self.target.as_dict(),
            "untrusted": self.untrusted,
        }


@dataclass(frozen=True)
class UntrustedArtifactInventory:
    target: ExactTargetDescriptor
    source: PrimeSourceTriple
    artifacts: tuple[PublicMetadataObjectClaim, ...]
    untrusted: Literal[True] = True

    def as_dict(self) -> dict[str, object]:
        return {
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "format": "asterion.prime-ipython-artifact-inventory/v1",
            "source": _source_dict(self.source),
            "target": self.target.as_dict(),
            "untrusted": self.untrusted,
        }


@dataclass(frozen=True)
class UntrustedReleaseProposal:
    target: ExactTargetDescriptor
    source: PrimeSourceTriple
    artifacts: tuple[PublicMetadataObjectClaim, ...]
    untrusted: Literal[True] = True

    def as_dict(self) -> dict[str, object]:
        return {
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "format": "asterion.prime-ipython-release-proposal/v1",
            "source": _source_dict(self.source),
            "target": self.target.as_dict(),
            "untrusted": self.untrusted,
        }


@dataclass(frozen=True)
class ProposalProvenance:
    target: ExactTargetDescriptor
    source: PrimeSourceTriple
    observation: SubstrateObservation
    generator_revision: str
    untrusted: Literal[True] = True

    def as_dict(self) -> dict[str, object]:
        return {
            "format": "asterion.prime-ipython-release-provenance/v1",
            "generator_revision": self.generator_revision,
            "observation": {
                "emulated": self.observation.emulated,
                "substrate": self.observation.substrate,
                "target": self.observation.target.as_dict(),
            },
            "source": _source_dict(self.source),
            "target": self.target.as_dict(),
            "untrusted": self.untrusted,
        }


@dataclass(frozen=True)
class ReleaseSpecGenerationResult:
    status: Literal["candidate-native", "External-limited"]
    acquisition_lock: UntrustedAcquisitionLock
    artifact_inventory: UntrustedArtifactInventory
    release_proposal: UntrustedReleaseProposal
    provenance: ProposalProvenance

    def as_dict(self) -> dict[str, object]:
        return {
            "acquisition_lock": self.acquisition_lock.as_dict(),
            "artifact_inventory": self.artifact_inventory.as_dict(),
            "format": _FORMAT,
            "provenance": self.provenance.as_dict(),
            "release_proposal": self.release_proposal.as_dict(),
            "status": self.status,
        }


def _invalid() -> PrimeReleaseSpecGenerationError:
    return PrimeReleaseSpecGenerationError(
        "Prime release specification proposal is invalid"
    )


def _source_dict(source: PrimeSourceTriple) -> dict[str, str]:
    return {
        "commit": source.commit,
        "package_lock_sha256": source.package_lock_sha256,
        "tree_sha256": source.tree_sha256,
    }


def _validate_target(value: object) -> ExactTargetDescriptor:
    if (
        type(value) is not ExactTargetDescriptor
        or type(value.os) is not str
        or type(value.architecture) is not str
        or (value.variant is not None and type(value.variant) is not str)
        or re.fullmatch(r"[a-z0-9]+", value.os) is None
        or re.fullmatch(r"[a-z0-9]+", value.architecture) is None
        or (
            value.variant is not None
            and re.fullmatch(r"v[0-9]+", value.variant) is None
        )
    ):
        raise _invalid()
    return value


def _validate_source(value: object) -> PrimeSourceTriple:
    if (
        type(value) is not PrimeSourceTriple
        or any(
            type(part) is not str
            for part in (value.commit, value.tree_sha256, value.package_lock_sha256)
        )
        or _COMMIT.fullmatch(value.commit) is None
        or _SHA256.fullmatch(value.tree_sha256) is None
        or _SHA256.fullmatch(value.package_lock_sha256) is None
        or value is not PRIME_IPYTHON_SOURCE
    ):
        raise _invalid()
    return value


def _validate_observation(value: object) -> SubstrateObservation:
    if type(value) is not SubstrateObservation or type(value.emulated) is not bool:
        raise _invalid()
    _validate_target(value.target)
    if (
        value.substrate not in {"native-linux", "desktop-vm", "emulated"}
        or (value.substrate == "emulated") != value.emulated
    ):
        raise _invalid()
    return value


def _validate_claim(value: object) -> MetadataObjectClaim:
    if (
        type(value) is not MetadataObjectClaim
        or type(value.artifact_kind) is not str
        or type(value.artifact_path) is not str
        or type(value.metadata) is not MetadataBlob
        or type(value.object) is not ObjectBlob
        or type(value.declared_object_size) is not int
        or type(value.declared_object_sha256) is not str
        or _KIND.fullmatch(value.artifact_kind) is None
        or _PATH.fullmatch(value.artifact_path) is None
        or "//" in value.artifact_path
        or any(part in {".", ".."} for part in value.artifact_path.split("/"))
    ):
        raise _invalid()
    metadata, object_blob = value.metadata, value.object
    if (
        type(metadata.parser_revision) is not str
        or type(metadata.size) is not int
        or type(metadata.sha256) is not str
        or metadata.parser_revision != _METADATA_PARSER_REVISION
        or metadata.size < 0
        or _SHA256.fullmatch(metadata.sha256) is None
        or type(object_blob.url) is not str
        or type(object_blob.size) is not int
        or type(object_blob.sha256) is not str
        or object_blob.size < 0
        or _SHA256.fullmatch(object_blob.sha256) is None
        or value.declared_object_size < 0
        or _SHA256.fullmatch(value.declared_object_sha256) is None
        or value.declared_object_size != object_blob.size
        or value.declared_object_sha256 != object_blob.sha256
    ):
        raise _invalid()
    parsed = urlsplit(object_blob.url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        raise _invalid()
    return value


def _validate_request(value: object) -> ReleaseSpecGenerationRequest:
    if (
        type(value) is not ReleaseSpecGenerationRequest
        or value.generator_revision != _GENERATOR_REVISION
    ):
        raise _invalid()
    target = _validate_target(value.target)
    source = _validate_source(value.source)
    _validate_observation(value.observation)
    try:
        recipe = release_recipe.validate_release_recipe(value.recipe)
        resolved = release_recipe.resolve_candidate_target(
            release_recipe.ImagePlatformDescriptor(
                target.os, target.architecture, target.variant
            )
        )
    except (TypeError, ValueError, release_recipe.PrimeReleaseRecipeError):
        raise _invalid() from None
    if (
        recipe.source is not source
        or resolved.os != target.os
        or resolved.architecture != target.architecture
        or resolved.variant != target.variant
    ):
        raise _invalid()
    if not isinstance(value.claims, tuple) or not value.claims:
        raise _invalid()
    claims = tuple(_validate_claim(claim) for claim in value.claims)
    if (
        claims != tuple(sorted(claims, key=lambda claim: claim.artifact_path))
        or len({claim.artifact_path for claim in claims}) != len(claims)
        or len(
            {
                hashlib.sha256(claim.object.url.encode("utf-8")).hexdigest()
                for claim in claims
            }
        )
        != len(claims)
    ):
        raise _invalid()
    return value


def generate_release_specification(request: object) -> ReleaseSpecGenerationResult:
    """Validate injected claims and make untrusted material for human review."""
    validated = _validate_request(request)
    status: Literal["candidate-native", "External-limited"] = "External-limited"
    if (
        validated.observation.target == validated.target
        and validated.target.os == "linux"
        and validated.observation.substrate == "native-linux"
        and not validated.observation.emulated
    ):
        status = "candidate-native"
    public_claims = tuple(_public_claim(claim) for claim in validated.claims)
    lock = UntrustedAcquisitionLock(validated.target, validated.source, public_claims)
    return ReleaseSpecGenerationResult(
        status,
        lock,
        UntrustedArtifactInventory(
            validated.target, validated.source, public_claims
        ),
        UntrustedReleaseProposal(validated.target, validated.source, public_claims),
        ProposalProvenance(
            validated.target,
            validated.source,
            validated.observation,
            validated.generator_revision,
        ),
    )


def canonical_release_spec_generation_json(result: object) -> str:
    """Return canonical review JSON. This is not an ImageInputLock parser."""
    if type(result) is not ReleaseSpecGenerationResult:
        raise _invalid()
    if not _valid_public_result(result):
        raise _invalid()
    return json.dumps(result.as_dict(), separators=(",", ":"), sort_keys=True)


def _valid_public_result(result: ReleaseSpecGenerationResult) -> bool:
    """Validate public structure without reconstructing private capture locators."""
    try:
        if result.status not in {"candidate-native", "External-limited"}:
            return False
        lock, inventory, proposal, provenance = (
            result.acquisition_lock,
            result.artifact_inventory,
            result.release_proposal,
            result.provenance,
        )
        if (
            lock.untrusted is not True
            or inventory.untrusted is not True
            or proposal.untrusted is not True
            or provenance.untrusted is not True
            or lock.target != inventory.target
            or lock.target != proposal.target
            or lock.source != inventory.source
            or lock.source != proposal.source
            or lock.claims != inventory.artifacts
            or lock.claims != proposal.artifacts
            or provenance.target != lock.target
            or provenance.source != lock.source
            or provenance.generator_revision != _GENERATOR_REVISION
            or _validate_source(lock.source) is not lock.source
            or _validate_target(lock.target) is not lock.target
            or _validate_observation(provenance.observation) is not provenance.observation
        ):
            return False
        expected_status = (
            "candidate-native"
            if (
                provenance.observation.target == lock.target
                and lock.target.os == "linux"
                and provenance.observation.substrate == "native-linux"
                and not provenance.observation.emulated
            )
            else "External-limited"
        )
        if result.status != expected_status or not lock.claims:
            return False
        claims = tuple(_validate_public_claim(claim) for claim in lock.claims)
        if (
            claims != tuple(sorted(claims, key=lambda claim: claim.artifact_path))
            or len({claim.artifact_path for claim in claims}) != len(claims)
            or len({claim.object.url_sha256 for claim in claims}) != len(claims)
        ):
            return False
        return True
    except (AttributeError, TypeError, ValueError):
        return False


def _validate_public_claim(value: object) -> PublicMetadataObjectClaim:
    if (
        type(value) is not PublicMetadataObjectClaim
        or type(value.artifact_kind) is not str
        or type(value.artifact_path) is not str
        or type(value.metadata) is not MetadataBlob
        or type(value.object) is not PublicObjectBlob
        or type(value.declared_object_size) is not int
        or type(value.declared_object_sha256) is not str
        or _KIND.fullmatch(value.artifact_kind) is None
        or _PATH.fullmatch(value.artifact_path) is None
        or "//" in value.artifact_path
        or any(part in {".", ".."} for part in value.artifact_path.split("/"))
    ):
        raise ValueError
    metadata, object_blob = value.metadata, value.object
    if (
        type(metadata.parser_revision) is not str
        or type(metadata.size) is not int
        or type(metadata.sha256) is not str
        or metadata.parser_revision != _METADATA_PARSER_REVISION
        or metadata.size < 0
        or _SHA256.fullmatch(metadata.sha256) is None
        or type(object_blob.size) is not int
        or type(object_blob.sha256) is not str
        or type(object_blob.url_sha256) is not str
        or object_blob.size < 0
        or _SHA256.fullmatch(object_blob.sha256) is None
        or _SHA256.fullmatch(object_blob.url_sha256) is None
        or value.declared_object_size < 0
        or _SHA256.fullmatch(value.declared_object_sha256) is None
        or value.declared_object_size != object_blob.size
        or value.declared_object_sha256 != object_blob.sha256
    ):
        raise ValueError
    return value


def _parse_target(value: object) -> ExactTargetDescriptor:
    if type(value) is not dict or set(value) != {"architecture", "os", "variant"}:
        raise ValueError
    return ExactTargetDescriptor(
        cast(str, value["os"]),
        cast(str, value["architecture"]),
        cast(str | None, value["variant"]),
    )


def _parse_recipe(value: object) -> release_recipe.ReleaseRecipe:
    expected = release_recipe.PRIME_IPYTHON_RELEASE_RECIPE
    expected_dict = {
        "artifact_graph_revision": expected.artifact_graph_revision,
        "base_distribution": expected.base_distribution,
        "fixture_recipe_sha256": expected.fixture_recipe_sha256,
        "frontend_recipe_sha256": expected.frontend_recipe_sha256,
        "libc": expected.libc,
        "metadata_parsers": {
            "claim_binding": expected.metadata_parsers.claim_binding,
            "node_shasums": expected.metadata_parsers.node_shasums,
            "oci_index": expected.metadata_parsers.oci_index,
            "oci_manifest": expected.metadata_parsers.oci_manifest,
            "pypi_json": expected.metadata_parsers.pypi_json,
            "recipe_output_manifest": expected.metadata_parsers.recipe_output_manifest,
        },
        "node_version": expected.node_version,
        "python_dependency_lock_sha256": expected.python_dependency_lock_sha256,
        "python_major_minor": expected.python_major_minor,
        "recipe_revision": expected.recipe_revision,
        "source": _source_dict(expected.source),
    }
    if type(value) is not dict or value != expected_dict:
        raise ValueError
    return expected


def release_spec_generation_request_from_dict(
    value: object,
) -> ReleaseSpecGenerationRequest:
    """Strictly parse caller-injected data without reading a file or host state."""
    try:
        if type(value) is not dict or set(value) != {
            "claims",
            "generator_revision",
            "observation",
            "recipe",
            "source",
            "target",
        }:
            raise ValueError
        target = _parse_target(value["target"])
        source_value = cast(dict[str, object], value["source"])
        observation_value = cast(dict[str, object], value["observation"])
        claims_value = value["claims"]
        if (
            type(source_value) is not dict
            or set(source_value) != {"commit", "package_lock_sha256", "tree_sha256"}
            or type(observation_value) is not dict
            or set(observation_value) != {"emulated", "substrate", "target"}
            or not isinstance(claims_value, list)
        ):
            raise ValueError
        source = PrimeSourceTriple(
            cast(str, source_value["commit"]),
            cast(str, source_value["tree_sha256"]),
            cast(str, source_value["package_lock_sha256"]),
        )
        if source != PRIME_IPYTHON_SOURCE:
            raise ValueError
        observation = SubstrateObservation(
            _parse_target(observation_value["target"]),
            cast(
                Literal["native-linux", "desktop-vm", "emulated"],
                observation_value["substrate"],
            ),
            cast(bool, observation_value["emulated"]),
        )
        claims: list[MetadataObjectClaim] = []
        for item in claims_value:
            if type(item) is not dict or set(item) != {
                "artifact_kind",
                "artifact_path",
                "declared_object_sha256",
                "declared_object_size",
                "metadata",
                "object",
            }:
                raise ValueError
            metadata_value, object_value = item["metadata"], item["object"]
            if (
                type(metadata_value) is not dict
                or set(metadata_value) != {"parser_revision", "sha256", "size"}
                or type(object_value) is not dict
                or set(object_value) != {"sha256", "size", "url"}
            ):
                raise ValueError
            claims.append(
                MetadataObjectClaim(
                    cast(str, item["artifact_kind"]),
                    cast(str, item["artifact_path"]),
                    MetadataBlob(
                        cast(str, metadata_value["parser_revision"]),
                        cast(int, metadata_value["size"]),
                        cast(str, metadata_value["sha256"]),
                    ),
                    ObjectBlob(
                        cast(str, object_value["url"]),
                        cast(int, object_value["size"]),
                        cast(str, object_value["sha256"]),
                    ),
                    cast(int, item["declared_object_size"]),
                    cast(str, item["declared_object_sha256"]),
                )
            )
        request = ReleaseSpecGenerationRequest(
            target,
            PRIME_IPYTHON_SOURCE,
            observation,
            _parse_recipe(value["recipe"]),
            tuple(claims),
            cast(str, value["generator_revision"]),
        )
    except (KeyError, TypeError, ValueError):
        raise _invalid() from None
    return _validate_request(request)
