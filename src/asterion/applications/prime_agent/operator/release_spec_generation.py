"""Pure, proposal-only generation for Prime IPython release specifications."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Final, Literal
from urllib.parse import urlsplit

from . import release_recipe
from . import release_metadata


_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_COMMIT: Final = re.compile(r"[0-9a-f]{40}")
_PATH: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_KIND: Final = re.compile(r"[a-z][a-z0-9-]*")
_GENERATOR_REVISION: Final = "prime-release-spec-generator/v1"
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
    declared_object_name: str

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
class ParsedMetadataCapture:
    """Private capture whose object declaration came from offline metadata."""

    artifact_kind: str
    artifact_path: str
    metadata_bytes: bytes = field(repr=False)
    declaration: release_metadata.ParsedMetadataDeclaration
    object: ObjectBlob


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


@dataclass(frozen=True)
class RecipeIdentity:
    """Stable identity of the code-owned recipe that produced a candidate."""

    revision: str
    sha256: str

    def as_dict(self) -> dict[str, str]:
        return {"revision": self.revision, "sha256": self.sha256}


def _recipe_identity(recipe: release_recipe.ReleaseRecipe) -> RecipeIdentity:
    return RecipeIdentity(recipe.recipe_revision, release_recipe.release_recipe_sha256(recipe))


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
    claims: tuple[ParsedMetadataCapture, ...]
    generator_revision: str


@dataclass(frozen=True)
class UntrustedAcquisitionLock:
    target: ExactTargetDescriptor
    source: PrimeSourceTriple
    recipe: RecipeIdentity
    claims: tuple[PublicMetadataObjectClaim, ...]
    untrusted: Literal[True] = True

    def as_dict(self) -> dict[str, object]:
        return {
            "claims": [claim.as_dict() for claim in self.claims],
            "format": "asterion.prime-ipython-acquisition-lock/v1",
            "recipe": self.recipe.as_dict(),
            "source": _source_dict(self.source),
            "target": self.target.as_dict(),
            "untrusted": self.untrusted,
        }


@dataclass(frozen=True)
class UntrustedArtifactInventory:
    target: ExactTargetDescriptor
    source: PrimeSourceTriple
    recipe: RecipeIdentity
    artifacts: tuple[PublicMetadataObjectClaim, ...]
    untrusted: Literal[True] = True

    def as_dict(self) -> dict[str, object]:
        return {
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "format": "asterion.prime-ipython-artifact-inventory/v1",
            "recipe": self.recipe.as_dict(),
            "source": _source_dict(self.source),
            "target": self.target.as_dict(),
            "untrusted": self.untrusted,
        }


@dataclass(frozen=True)
class UntrustedReleaseProposal:
    target: ExactTargetDescriptor
    source: PrimeSourceTriple
    recipe: RecipeIdentity
    artifacts: tuple[PublicMetadataObjectClaim, ...]
    untrusted: Literal[True] = True

    def as_dict(self) -> dict[str, object]:
        return {
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "format": "asterion.prime-ipython-release-proposal/v1",
            "recipe": self.recipe.as_dict(),
            "source": _source_dict(self.source),
            "target": self.target.as_dict(),
            "untrusted": self.untrusted,
        }


@dataclass(frozen=True)
class ProposalProvenance:
    target: ExactTargetDescriptor
    source: PrimeSourceTriple
    recipe: RecipeIdentity
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
            "recipe": self.recipe.as_dict(),
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
        type(value) is not ParsedMetadataCapture
        or type(value.artifact_kind) is not str
        or type(value.artifact_path) is not str
        or type(value.object) is not ObjectBlob
        or _KIND.fullmatch(value.artifact_kind) is None
        or _PATH.fullmatch(value.artifact_path) is None
        or "//" in value.artifact_path
        or any(part in {".", ".."} for part in value.artifact_path.split("/"))
    ):
        raise _invalid()
    try:
        declaration = release_metadata.validate_declaration_metadata_bytes(
            value.declaration, value.metadata_bytes
        )
    except release_metadata.PrimeReleaseMetadataError:
        raise _invalid() from None
    object_blob = value.object
    if (
        type(object_blob.url) is not str
        or type(object_blob.size) is not int
        or type(object_blob.sha256) is not str
        or object_blob.size < 0
        or _SHA256.fullmatch(object_blob.sha256) is None
        or object_blob.sha256 != declaration.declared_sha256
        or (
            declaration.declared_size is not None
            and object_blob.size != declaration.declared_size
        )
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
    return MetadataObjectClaim(
        value.artifact_kind,
        value.artifact_path,
        MetadataBlob(
            declaration.parser_revision,
            declaration.metadata_size,
            declaration.metadata_sha256,
        ),
        object_blob,
        declaration.declared_size if declaration.declared_size is not None else object_blob.size,
        declaration.declared_sha256,
        declaration.object_name,
    )


def _validate_python_wheel_closure(
    claims: tuple[MetadataObjectClaim, ...],
    recipe: release_recipe.ReleaseRecipe,
) -> None:
    """Require one parser-backed wheel claim for every committed lock entry."""

    requirements = release_recipe.prime_python_wheel_requirements()
    expected_paths = {
        f"python/{requirement.normalized_project}.whl": requirement
        for requirement in requirements
    }
    wheel_claims = {
        claim.artifact_path: claim
        for claim in claims
        if claim.artifact_kind == "python-wheel" and claim.artifact_path in expected_paths
    }
    if set(wheel_claims) != set(expected_paths):
        raise _invalid()
    for path, requirement in expected_paths.items():
        claim = wheel_claims[path]
        expected_filename_prefix = (
            f"{requirement.normalized_project.replace('-', '_')}-{requirement.version}-"
        )
        if (
            claim.metadata.parser_revision != recipe.metadata_parsers.pypi_json
            or not claim.declared_object_name.startswith(expected_filename_prefix)
            or not claim.declared_object_name.endswith(".whl")
        ):
            raise _invalid()


def _metadata_target(
    target: ExactTargetDescriptor,
) -> release_recipe.ImagePlatformDescriptor:
    return release_recipe.ImagePlatformDescriptor(
        target.os, target.architecture, target.variant
    )


def _require_parser_declaration(
    capture: ParsedMetadataCapture,
    declaration: release_metadata.ParsedMetadataDeclaration,
) -> None:
    if declaration != capture.declaration:
        raise _invalid()


def _validate_recipe_output_capture(
    capture: ParsedMetadataCapture,
    recipe: release_recipe.ReleaseRecipe,
    scope: Literal["target-specific", "recipe-shared"],
    target: ExactTargetDescriptor | None,
) -> None:
    try:
        _require_parser_declaration(
            capture,
            release_metadata.parse_recipe_output_manifest(
                capture.metadata_bytes,
                release_metadata.RecipeOutputSelector(
                    recipe,
                    scope,
                    None if target is None else _metadata_target(target),
                    capture.artifact_path,
                ),
            ),
        )
    except release_metadata.PrimeReleaseMetadataError:
        raise _invalid() from None


def _validate_complete_target_artifact_graph(
    captures: tuple[ParsedMetadataCapture, ...],
    claims: tuple[MetadataObjectClaim, ...],
    recipe: release_recipe.ReleaseRecipe,
    target: ExactTargetDescriptor,
) -> None:
    """Require the exact parsed closure for one candidate target."""

    captures_by_path = {capture.artifact_path: capture for capture in captures}
    claims_by_path = {claim.artifact_path: claim for claim in claims}
    metadata_target = _metadata_target(target)
    requirements = release_recipe.prime_python_wheel_requirements()
    expected_wheel_paths = {
        f"python/{requirement.normalized_project}.whl" for requirement in requirements
    }
    required_paths = {
        "build-frontend/launcher.mjs",
        "fixture/fixture-lock.json",
        "node/node.tar.xz",
        f"node/node-modules-{target.os}-{target.architecture}.tar",
        "oci/config.json",
        "oci/manifest.json",
        "python/prime_agent_runtime-0.1.0-py3-none-any.whl",
        *expected_wheel_paths,
    }
    layer_paths = {
        claim.artifact_path
        for claim in claims
        if claim.artifact_kind == "oci-layer"
    }
    if set(claims_by_path) != required_paths | layer_paths:
        raise _invalid()
    if set(captures_by_path) != set(claims_by_path):
        raise _invalid()

    def require(path: str, kind: str, parser_revision: str) -> tuple[
        ParsedMetadataCapture, MetadataObjectClaim
    ]:
        try:
            capture, claim = captures_by_path[path], claims_by_path[path]
        except KeyError:
            raise _invalid() from None
        if claim.artifact_kind != kind or claim.metadata.parser_revision != parser_revision:
            raise _invalid()
        return capture, claim

    node_capture, node_claim = require(
        "node/node.tar.xz", "node-archive", recipe.metadata_parsers.node_shasums
    )
    node_suffix = "arm64" if target.architecture == "arm64" else "x64"
    expected_node_name = f"node-v{recipe.node_version}-linux-{node_suffix}.tar.xz"
    try:
        _require_parser_declaration(
            node_capture,
            release_metadata.parse_node_shasums(
                node_capture.metadata_bytes,
                release_metadata.NodeShasumsSelector(recipe.node_version, metadata_target),
            ),
        )
    except release_metadata.PrimeReleaseMetadataError:
        raise _invalid() from None
    if node_claim.declared_object_name != expected_node_name:
        raise _invalid()

    modules_path = f"node/node-modules-{target.os}-{target.architecture}.tar"
    modules_capture, _ = require(
        modules_path, "node-modules", recipe.metadata_parsers.recipe_output_manifest
    )
    _validate_recipe_output_capture(modules_capture, recipe, "target-specific", target)

    runtime_capture, runtime_claim = require(
        "python/prime_agent_runtime-0.1.0-py3-none-any.whl",
        "python-wheel",
        recipe.metadata_parsers.recipe_output_manifest,
    )
    _validate_recipe_output_capture(runtime_capture, recipe, "recipe-shared", None)
    if runtime_claim.declared_object_name != runtime_claim.artifact_path:
        raise _invalid()
    for path, kind in (
        ("fixture/fixture-lock.json", "fixture"),
        ("build-frontend/launcher.mjs", "frontend"),
    ):
        capture, _ = require(path, kind, recipe.metadata_parsers.recipe_output_manifest)
        _validate_recipe_output_capture(capture, recipe, "recipe-shared", None)

    manifest_capture, manifest_claim = require(
        "oci/manifest.json", "oci-manifest", recipe.metadata_parsers.oci_index
    )
    try:
        _require_parser_declaration(
            manifest_capture,
            release_metadata.parse_oci_index_descriptor(
                manifest_capture.metadata_bytes,
                release_metadata.OCIIndexSelector(metadata_target),
            ),
        )
    except release_metadata.PrimeReleaseMetadataError:
        raise _invalid() from None
    if manifest_claim.declared_object_name != "child-manifest":
        raise _invalid()

    config_capture, config_claim = require(
        "oci/config.json", "oci-config", recipe.metadata_parsers.oci_manifest
    )
    if config_claim.metadata.sha256 != manifest_claim.object.sha256:
        raise _invalid()
    try:
        _require_parser_declaration(
            config_capture,
            release_metadata.parse_oci_manifest_descriptor(
                config_capture.metadata_bytes,
                release_metadata.OCIManifestSelector("config", None),
            ),
        )
    except release_metadata.PrimeReleaseMetadataError:
        raise _invalid() from None
    if config_claim.declared_object_name != "config":
        raise _invalid()

    layers: list[tuple[int, ParsedMetadataCapture, MetadataObjectClaim]] = []
    for path in layer_paths:
        capture, claim = require(path, "oci-layer", recipe.metadata_parsers.oci_manifest)
        match = re.fullmatch(r"oci/layer-([0-9]+)\.tar\.gz", path)
        name_match = re.fullmatch(r"layer/([0-9]+)", claim.declared_object_name)
        if (
            match is None
            or name_match is None
            or match.group(1) != name_match.group(1)
            or claim.metadata.sha256 != manifest_claim.object.sha256
        ):
            raise _invalid()
        ordinal = int(match.group(1))
        try:
            _require_parser_declaration(
                capture,
                release_metadata.parse_oci_manifest_descriptor(
                    capture.metadata_bytes,
                    release_metadata.OCIManifestSelector("layer", ordinal),
                ),
            )
        except release_metadata.PrimeReleaseMetadataError:
            raise _invalid() from None
        layers.append((ordinal, capture, claim))
    if not layers or {ordinal for ordinal, _, _ in layers} != set(range(len(layers))):
        raise _invalid()

    _validate_python_wheel_closure(claims, recipe)



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
    _validate_complete_target_artifact_graph(value.claims, claims, recipe, target)
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
    public_claims = tuple(
        _public_claim(_validate_claim(claim)) for claim in validated.claims
    )
    recipe_identity = _recipe_identity(validated.recipe)
    lock = UntrustedAcquisitionLock(
        validated.target, validated.source, recipe_identity, public_claims
    )
    return ReleaseSpecGenerationResult(
        status,
        lock,
        UntrustedArtifactInventory(
            validated.target, validated.source, recipe_identity, public_claims
        ),
        UntrustedReleaseProposal(
            validated.target, validated.source, recipe_identity, public_claims
        ),
        ProposalProvenance(
            validated.target,
            validated.source,
            recipe_identity,
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
            or lock.recipe != inventory.recipe
            or lock.recipe != proposal.recipe
            or lock.recipe != provenance.recipe
            or lock.claims != inventory.artifacts
            or lock.claims != proposal.artifacts
            or provenance.target != lock.target
            or provenance.source != lock.source
            or provenance.generator_revision != _GENERATOR_REVISION
            or _validate_source(lock.source) is not lock.source
            or _validate_target(lock.target) is not lock.target
            or _validate_observation(provenance.observation) is not provenance.observation
            or type(lock.recipe) is not RecipeIdentity
            or lock.recipe != _recipe_identity(release_recipe.PRIME_IPYTHON_RELEASE_RECIPE)
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
        or metadata.parser_revision not in {
            release_recipe.PRIME_IPYTHON_RELEASE_RECIPE.metadata_parsers.node_shasums,
            release_recipe.PRIME_IPYTHON_RELEASE_RECIPE.metadata_parsers.pypi_json,
            release_recipe.PRIME_IPYTHON_RELEASE_RECIPE.metadata_parsers.oci_index,
            release_recipe.PRIME_IPYTHON_RELEASE_RECIPE.metadata_parsers.oci_manifest,
            release_recipe.PRIME_IPYTHON_RELEASE_RECIPE.metadata_parsers.recipe_output_manifest,
        }
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
