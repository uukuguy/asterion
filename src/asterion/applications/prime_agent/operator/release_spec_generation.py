"""Pure, proposal-only generation for Prime IPython release specifications.

This module consumes records captured by an operator-controlled external
process.  It neither discovers releases nor promotes a proposal to image
evidence: its most favourable classification is ``candidate-native``.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Final, Literal, cast
from urllib.parse import urlsplit


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
    """Explicit requested or observed OCI-like target; never host-derived."""

    os: str
    architecture: str
    variant: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {"architecture": self.architecture, "os": self.os, "variant": self.variant}


@dataclass(frozen=True)
class PrimeSourceTriple:
    """The exact Prime source commit, tree, and package-lock hashes."""

    commit: str
    tree_sha256: str
    package_lock_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "commit": self.commit,
            "package_lock_sha256": self.package_lock_sha256,
            "tree_sha256": self.tree_sha256,
        }


PRIME_IPYTHON_SOURCE: Final = PrimeSourceTriple(
    "a18809e00ea30638584d87b3afea7285a9d7296c",
    "93a4b02ecc0cc114865fa3d336521cf214047cf4de471b36b51fe610c84ab686",
    "39ee303bca10c0933cf917275613c8f44099f50de1650a5c356e7cda02b701e8",
)


@dataclass(frozen=True)
class SubstrateObservation:
    """An injected observation, including its explicit execution substrate."""

    target: ExactTargetDescriptor
    substrate: Literal["native-linux", "desktop-vm", "emulated"]
    emulated: bool


@dataclass(frozen=True)
class AcquisitionCapture:
    """One externally captured metadata/object pair, before human review."""

    kind: str
    url: str
    path: str
    metadata_size: int
    metadata_sha256: str
    object_size: int
    object_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "metadata_sha256": self.metadata_sha256,
            "metadata_size": self.metadata_size,
            "object_sha256": self.object_sha256,
            "object_size": self.object_size,
            "path": self.path,
            "url": self.url,
        }

    def as_public_dict(self) -> dict[str, object]:
        """Return review-safe capture material without its injected locator."""

        return {
            "kind": self.kind,
            "metadata_sha256": self.metadata_sha256,
            "metadata_size": self.metadata_size,
            "object_sha256": self.object_sha256,
            "object_size": self.object_size,
            "path": self.path,
            "url_sha256": hashlib.sha256(self.url.encode("utf-8")).hexdigest(),
        }


@dataclass(frozen=True)
class ReleaseSpecGenerationRequest:
    """All injected inputs required for one deterministic proposal."""

    target: ExactTargetDescriptor
    source: PrimeSourceTriple
    observation: SubstrateObservation
    captures: tuple[AcquisitionCapture, ...]
    generator_revision: str


@dataclass(frozen=True)
class UntrustedAcquisitionLock:
    target: ExactTargetDescriptor
    source: PrimeSourceTriple
    captures: tuple[AcquisitionCapture, ...]
    untrusted: Literal[True] = True

    def as_dict(self) -> dict[str, object]:
        return {
            "captures": [capture.as_public_dict() for capture in self.captures],
            "format": "asterion.prime-ipython-acquisition-lock/v1",
            "source": self.source.as_dict(),
            "target": self.target.as_dict(),
            "untrusted": self.untrusted,
        }


@dataclass(frozen=True)
class UntrustedArtifactInventory:
    target: ExactTargetDescriptor
    source: PrimeSourceTriple
    artifacts: tuple[AcquisitionCapture, ...]
    untrusted: Literal[True] = True

    def as_dict(self) -> dict[str, object]:
        return {
            "artifacts": [artifact.as_public_dict() for artifact in self.artifacts],
            "format": "asterion.prime-ipython-artifact-inventory/v1",
            "source": self.source.as_dict(),
            "target": self.target.as_dict(),
            "untrusted": self.untrusted,
        }


@dataclass(frozen=True)
class UntrustedReleaseProposal:
    target: ExactTargetDescriptor
    source: PrimeSourceTriple
    artifacts: tuple[AcquisitionCapture, ...]
    untrusted: Literal[True] = True

    def as_dict(self) -> dict[str, object]:
        return {
            "artifacts": [artifact.as_public_dict() for artifact in self.artifacts],
            "format": "asterion.prime-ipython-release-proposal/v1",
            "source": self.source.as_dict(),
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
            "source": self.source.as_dict(),
            "target": self.target.as_dict(),
            "untrusted": self.untrusted,
        }


@dataclass(frozen=True)
class ReleaseSpecGenerationResult:
    """Public-safe review material, expressly not image or scenario evidence."""

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
    return PrimeReleaseSpecGenerationError("Prime release specification proposal is invalid")


def _validate_target(value: object) -> ExactTargetDescriptor:
    if (
        type(value) is not ExactTargetDescriptor
        or type(value.os) is not str
        or type(value.architecture) is not str
        or (value.variant is not None and type(value.variant) is not str)
        or re.fullmatch(r"[a-z0-9]+", value.os) is None
        or re.fullmatch(r"[a-z0-9]+", value.architecture) is None
        or (value.variant is not None and re.fullmatch(r"v[0-9]+", value.variant) is None)
    ):
        raise _invalid()
    return value


def _validate_source(value: object) -> PrimeSourceTriple:
    if (
        type(value) is not PrimeSourceTriple
        or any(type(part) is not str for part in (value.commit, value.tree_sha256, value.package_lock_sha256))
        or _COMMIT.fullmatch(value.commit) is None
        or _SHA256.fullmatch(value.tree_sha256) is None
        or _SHA256.fullmatch(value.package_lock_sha256) is None
        or value != PRIME_IPYTHON_SOURCE
    ):
        raise _invalid()
    return value


def _validate_observation(value: object) -> SubstrateObservation:
    if type(value) is not SubstrateObservation or type(value.emulated) is not bool:
        raise _invalid()
    _validate_target(value.target)
    if value.substrate not in {"native-linux", "desktop-vm", "emulated"}:
        raise _invalid()
    if (value.substrate == "emulated") != value.emulated:
        raise _invalid()
    return value


def _validate_capture(value: object) -> AcquisitionCapture:
    if (
        type(value) is not AcquisitionCapture
        or type(value.kind) is not str
        or type(value.url) is not str
        or type(value.path) is not str
        or type(value.metadata_size) is not int
        or type(value.object_size) is not int
        or type(value.metadata_sha256) is not str
        or type(value.object_sha256) is not str
        or _KIND.fullmatch(value.kind) is None
        or _PATH.fullmatch(value.path) is None
        or "//" in value.path
        or any(part in {".", ".."} for part in value.path.split("/"))
        or value.metadata_size < 0
        or value.object_size < 0
        or _SHA256.fullmatch(value.metadata_sha256) is None
        or _SHA256.fullmatch(value.object_sha256) is None
        or value.metadata_size != value.object_size
        or value.metadata_sha256 != value.object_sha256
    ):
        raise _invalid()
    parsed = urlsplit(value.url)
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
    if type(value) is not ReleaseSpecGenerationRequest or value.generator_revision != _GENERATOR_REVISION:
        raise _invalid()
    _validate_target(value.target)
    _validate_source(value.source)
    _validate_observation(value.observation)
    if not isinstance(value.captures, tuple) or not value.captures:
        raise _invalid()
    captures = tuple(_validate_capture(capture) for capture in value.captures)
    if captures != tuple(sorted(captures, key=lambda capture: capture.path)):
        raise _invalid()
    if len({capture.path for capture in captures}) != len(captures) or len({capture.url for capture in captures}) != len(captures):
        raise _invalid()
    return value


def generate_release_specification(request: object) -> ReleaseSpecGenerationResult:
    """Validate injected captures and make untrusted material for human review."""

    validated = _validate_request(request)
    status: Literal["candidate-native", "External-limited"] = "External-limited"
    if (
        validated.observation.target == validated.target
        and validated.target.os == "linux"
        and validated.observation.substrate == "native-linux"
        and not validated.observation.emulated
    ):
        status = "candidate-native"
    acquisition_lock = UntrustedAcquisitionLock(validated.target, validated.source, validated.captures)
    return ReleaseSpecGenerationResult(
        status,
        acquisition_lock,
        UntrustedArtifactInventory(validated.target, validated.source, validated.captures),
        UntrustedReleaseProposal(validated.target, validated.source, validated.captures),
        ProposalProvenance(validated.target, validated.source, validated.observation, validated.generator_revision),
    )


def canonical_release_spec_generation_json(result: object) -> str:
    """Return canonical review JSON.  This is not an ImageInputLock parser."""

    if type(result) is not ReleaseSpecGenerationResult:
        raise _invalid()
    # Revalidate through a fresh request, so handcrafted result records cannot be serialized.
    generated = generate_release_specification(
        ReleaseSpecGenerationRequest(
            result.acquisition_lock.target,
            result.acquisition_lock.source,
            result.provenance.observation,
            result.acquisition_lock.captures,
            result.provenance.generator_revision,
        )
    )
    if result != generated:
        raise _invalid()
    return json.dumps(result.as_dict(), separators=(",", ":"), sort_keys=True)


def release_spec_generation_request_from_dict(value: object) -> ReleaseSpecGenerationRequest:
    """Strictly parse caller-injected data without reading a file or host state."""

    try:
        if type(value) is not dict or set(value) != {"captures", "generator_revision", "observation", "source", "target"}:
            raise ValueError
        target_value = cast(dict[str, object], value["target"])
        source_value = cast(dict[str, object], value["source"])
        observation_value = cast(dict[str, object], value["observation"])
        observed_target_value = cast(dict[str, object], observation_value["target"])
        captures_value = value["captures"]
        if not isinstance(captures_value, list):
            raise ValueError
        if set(target_value) != {"architecture", "os", "variant"}:
            raise ValueError
        if set(observed_target_value) != {"architecture", "os", "variant"}:
            raise ValueError
        if set(source_value) != {"commit", "package_lock_sha256", "tree_sha256"}:
            raise ValueError
        if set(observation_value) != {"emulated", "substrate", "target"}:
            raise ValueError
        if any(
            type(item) is not dict
            or set(item) != {
                "kind", "metadata_sha256", "metadata_size", "object_sha256", "object_size", "path", "url",
            }
            for item in captures_value
        ):
            raise ValueError
        target = ExactTargetDescriptor(
            cast(str, target_value["os"]), cast(str, target_value["architecture"]),
            cast(str | None, target_value["variant"]),
        )
        observed_target = ExactTargetDescriptor(
            cast(str, observed_target_value["os"]), cast(str, observed_target_value["architecture"]),
            cast(str | None, observed_target_value["variant"]),
        )
        source = PrimeSourceTriple(
            cast(str, source_value["commit"]), cast(str, source_value["tree_sha256"]),
            cast(str, source_value["package_lock_sha256"]),
        )
        observation = SubstrateObservation(
            observed_target,
            cast(Literal["native-linux", "desktop-vm", "emulated"], observation_value["substrate"]),
            cast(bool, observation_value["emulated"]),
        )
        captures = tuple(AcquisitionCapture(
            cast(str, item["kind"]), cast(str, item["url"]), cast(str, item["path"]),
            cast(int, item["metadata_size"]), cast(str, item["metadata_sha256"]),
            cast(int, item["object_size"]), cast(str, item["object_sha256"]),
        ) for item in cast(list[dict[str, object]], captures_value))
        request = ReleaseSpecGenerationRequest(
            target, source, observation, captures, cast(str, value["generator_revision"])
        )
    except (KeyError, TypeError, ValueError):
        raise _invalid() from None
    return _validate_request(request)
