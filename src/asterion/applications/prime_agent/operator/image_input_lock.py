"""Closed, offline-only inputs for the Linux Prime IPython image.

The values in this module are intentionally data, not an installer.  Validation
has no environment, network, package-manager, or image-engine dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .release_recipe import ReleaseRecipe


_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_RELATIVE_PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_FORMAT: Final = "asterion.image-input-lock/v1"
_KINDS: Final = frozenset(
    {
        "oci-config",
        "oci-layer",
        "oci-manifest",
        "node-archive",
        "node-modules",
        "python-wheel",
        "fixture",
        "frontend",
    }
)
_REQUIRED_KINDS: Final = frozenset(
    {
        "oci-config",
        "oci-layer",
        "oci-manifest",
        "node-archive",
        "node-modules",
        "python-wheel",
        "fixture",
        "frontend",
    }
)


class PrimeImageInputLockError(ValueError):
    """Raised when a Prime image input lock or artifact set is invalid."""


@dataclass(frozen=True)
class ImagePlatformDescriptor:
    """One exact OCI target; ``None`` is an explicit absent variant."""

    os: str
    architecture: str
    variant: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "architecture": self.architecture,
            "os": self.os,
            "variant": self.variant,
        }


def validate_image_platform_descriptor(value: object) -> ImagePlatformDescriptor:
    """Reject all non-canonical OCI target descriptors without host inspection."""

    if (
        type(value) is not ImagePlatformDescriptor
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
        raise PrimeImageInputLockError("Prime image platform descriptor is invalid")
    return value


_VERIFIED_IMAGE_INPUT_ARTIFACT_SET_TOKEN: Final = object()
_VERIFIED_CANDIDATE_ARTIFACT_SET_TOKEN: Final = object()
_PROMOTED_IMAGE_INPUT_TOKEN: Final = object()


@dataclass(frozen=True)
class ImageArtifact:
    """One immutable artifact in the closed input set."""

    kind: str
    path: str
    size: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "path": self.path,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(frozen=True)
class ReleaseArtifact:
    """An operator-supplied immutable release object and its staging destination.

    This is intentionally distinct from :class:`ImageArtifact`: the URL is
    release-local provenance, never a field in a promotable image input lock.
    """

    kind: str
    url: str
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ReleaseSpecification:
    """Exact, caller-injected release inputs; no bundled release is implied."""

    recipe: ReleaseRecipe
    platform: ImagePlatformDescriptor
    artifacts: tuple[ReleaseArtifact, ...]
    candidate_request: object | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ReleaseLockProposal:
    """A canonical but explicitly untrusted candidate for human promotion."""

    source_commit: str
    source_tree_sha256: str
    source_package_lock_sha256: str
    recipe_revision: str
    recipe_sha256: str
    platform: ImagePlatformDescriptor
    artifacts: tuple[ImageArtifact, ...]
    untrusted: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "format": "asterion.image-input-release-proposal/v1",
            "platform": self.platform.as_dict(),
            "recipe_revision": self.recipe_revision,
            "recipe_sha256": self.recipe_sha256,
            "source_commit": self.source_commit,
            "source_package_lock_sha256": self.source_package_lock_sha256,
            "source_tree_sha256": self.source_tree_sha256,
            "untrusted": self.untrusted,
        }


def canonical_release_lock_proposal_json(proposal: ReleaseLockProposal) -> str:
    """Return a canonical display/review form, never verification evidence."""

    if type(proposal) is not ReleaseLockProposal or proposal.untrusted is not True:
        raise PrimeImageInputLockError("Prime image release proposal is invalid")
    if (
        type(proposal.recipe_revision) is not str
        or not proposal.recipe_revision
        or type(proposal.recipe_sha256) is not str
        or _SHA256.fullmatch(proposal.recipe_sha256) is None
    ):
        raise PrimeImageInputLockError("Prime image release proposal is invalid")
    validate_image_platform_descriptor(proposal.platform)
    return json.dumps(proposal.as_dict(), separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True, init=False)
class VerifiedCandidateArtifactSet:
    """Untrusted candidate bytes, deliberately distinct from promoted evidence."""

    proposal: ReleaseLockProposal
    root: Path
    untrusted: bool

    def __init__(self, proposal: ReleaseLockProposal, root: Path, *, _token: object | None = None) -> None:
        if _token is not _VERIFIED_CANDIDATE_ARTIFACT_SET_TOKEN:
            raise PrimeImageInputLockError("Prime image input lock is invalid")
        object.__setattr__(self, "proposal", proposal)
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "untrusted", True)


@dataclass(frozen=True, init=False)
class PromotedImageInput:
    """Opaque authority for a lock selected by the code-owned catalog."""

    lock: ImageInputLock

    def __init__(self, lock: ImageInputLock, *, _token: object | None = None) -> None:
        if _token is not _PROMOTED_IMAGE_INPUT_TOKEN:
            raise PrimeImageInputLockError("Prime image input lock is invalid")
        object.__setattr__(self, "lock", lock)


@dataclass(frozen=True)
class ImageInputLock:
    """A syntactically valid, unmaterialized offline Linux input contract."""

    source_commit: str
    source_tree_sha256: str
    source_package_lock_sha256: str
    platform: ImagePlatformDescriptor
    artifacts: tuple[ImageArtifact, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "format": _FORMAT,
            "platform": self.platform.as_dict(),
            "source_commit": self.source_commit,
            "source_package_lock_sha256": self.source_package_lock_sha256,
            "source_tree_sha256": self.source_tree_sha256,
        }


@dataclass(frozen=True, init=False)
class VerifiedImageInputArtifactSet:
    """Evidence that one external root matched an input contract byte-for-byte."""

    contract: ImageInputLock
    root: Path

    def __init__(
        self, contract: ImageInputLock, root: Path, *, _token: object | None = None
    ) -> None:
        """Reject proof construction outside the completed verification path."""

        if _token is not _VERIFIED_IMAGE_INPUT_ARTIFACT_SET_TOKEN:
            raise PrimeImageInputLockError("Prime image input lock is invalid")
        object.__setattr__(self, "contract", contract)
        object.__setattr__(self, "root", root)


def _verified_image_input_artifact_set(
    contract: ImageInputLock, root: Path
) -> VerifiedImageInputArtifactSet:
    """Create verification evidence after the verifier has checked the full set."""

    return VerifiedImageInputArtifactSet(
        contract, root, _token=_VERIFIED_IMAGE_INPUT_ARTIFACT_SET_TOKEN
    )


@dataclass(frozen=True)
class PromotedImageInputCatalog:
    """Code-owned exact target-to-lock bindings, never host-selected."""

    locks: tuple[ImageInputLock, ...]


PRIME_IPYTHON_IMAGE_INPUT_CATALOG: Final = PromotedImageInputCatalog(())


def _platform_sort_key(platform: ImagePlatformDescriptor) -> tuple[str, str, bool, str]:
    return (
        platform.os,
        platform.architecture,
        platform.variant is not None,
        platform.variant or "",
    )


def resolve_promoted_image_input_lock(
    requested_platform: object,
) -> ImageInputLock:
    """Resolve one explicit descriptor from the code-owned catalog only."""

    requested = validate_image_platform_descriptor(requested_platform)
    catalog = PRIME_IPYTHON_IMAGE_INPUT_CATALOG
    if (
        type(catalog) is not PromotedImageInputCatalog
        or not isinstance(catalog.locks, tuple)
        or not catalog.locks
    ):
        raise PrimeImageInputLockError("Prime image input catalog is invalid")
    try:
        locks = catalog.locks
        if any(type(item) is not ImageInputLock for item in locks):
            raise ValueError
        platforms = tuple(
            validate_image_platform_descriptor(item.platform) for item in locks
        )
        if tuple(sorted(platforms, key=_platform_sort_key)) != platforms or len(
            set(platforms)
        ) != len(platforms):
            raise ValueError
        if any(
            _validate_image_input_lock_structure(item) is not item for item in locks
        ):
            raise ValueError
        matches = tuple(item for item in locks if item.platform == requested)
        if len(matches) != 1:
            raise ValueError
        return matches[0]
    except (TypeError, ValueError, PrimeImageInputLockError):
        raise PrimeImageInputLockError("Prime image input catalog is invalid") from None


def canonical_image_input_lock_json(lock: ImageInputLock) -> str:
    """Return the one canonical JSON encoding after strict static validation."""

    validate_image_input_lock(lock)
    return json.dumps(lock.as_dict(), separators=(",", ":"), sort_keys=True)


def image_input_lock_sha256(lock: ImageInputLock) -> str:
    """Return the stable identifier used by an explicit release command plan."""

    return sha256(canonical_image_input_lock_json(lock).encode()).hexdigest()


def image_input_lock_from_dict(value: object) -> ImageInputLock:
    """Parse an unmaterialized contract; this does not verify any artifacts."""

    if (
        not isinstance(value, dict)
        or frozenset(value)
        != {
            "format",
            "source_commit",
            "source_tree_sha256",
            "source_package_lock_sha256",
            "platform",
            "artifacts",
        }
        or value.get("format") != _FORMAT
    ):
        raise PrimeImageInputLockError("Prime image input lock is invalid")
    artifacts = value.get("artifacts")
    platform = value.get("platform")
    if (
        not isinstance(artifacts, list)
        or type(platform) is not dict
        or frozenset(platform) != {"os", "architecture", "variant"}
    ):
        raise PrimeImageInputLockError("Prime image input lock is invalid")
    if any(
        type(item) is not dict or frozenset(item) != {"kind", "path", "size", "sha256"}
        for item in artifacts
    ):
        raise PrimeImageInputLockError("Prime image input lock is invalid")
    try:
        parsed = ImageInputLock(
            value["source_commit"],
            value["source_tree_sha256"],
            value["source_package_lock_sha256"],
            ImagePlatformDescriptor(
                platform["os"], platform["architecture"], platform["variant"]
            ),
            tuple(
                ImageArtifact(item["kind"], item["path"], item["size"], item["sha256"])
                for item in artifacts
            ),
        )
    except (KeyError, TypeError):
        raise PrimeImageInputLockError("Prime image input lock is invalid") from None
    _validate_image_input_lock_structure(parsed)
    return parsed


def validate_image_input_lock(lock: object) -> ImageInputLock:
    """Validate an unmaterialized contract without reading files or invoking tools."""

    return _validate_image_input_lock_structure(lock)


def _validate_image_input_lock_structure(lock: object) -> ImageInputLock:
    """Reject malformed lock records before inspecting artifact fields."""

    if (
        type(lock) is not ImageInputLock
        or any(
            type(value) is not str
            for value in (
                lock.source_commit,
                lock.source_tree_sha256,
                lock.source_package_lock_sha256,
            )
        )
        or _COMMIT.fullmatch(lock.source_commit) is None
        or _SHA256.fullmatch(lock.source_tree_sha256) is None
        or _SHA256.fullmatch(lock.source_package_lock_sha256) is None
    ):
        raise PrimeImageInputLockError("Prime image input lock is invalid")
    validate_image_platform_descriptor(lock.platform)
    artifacts = lock.artifacts
    if (
        not isinstance(artifacts, tuple)
        or not artifacts
        or any(
            type(artifact) is not ImageArtifact
            or type(artifact.kind) is not str
            or type(artifact.path) is not str
            or type(artifact.size) is not int
            or type(artifact.sha256) is not str
            for artifact in artifacts
        )
    ):
        raise PrimeImageInputLockError("Prime image input lock is invalid")
    if tuple(sorted(artifacts, key=lambda artifact: artifact.path)) != artifacts:
        raise PrimeImageInputLockError("Prime image input lock is invalid")
    if len({artifact.path for artifact in artifacts}) != len(artifacts) or len(
        {artifact.sha256 for artifact in artifacts}
    ) != len(artifacts):
        raise PrimeImageInputLockError("Prime image input lock is invalid")
    if {artifact.kind for artifact in artifacts} != _REQUIRED_KINDS or not any(
        artifact.path.startswith("python/prime_agent_runtime-")
        for artifact in artifacts
    ):
        raise PrimeImageInputLockError("Prime image input lock is invalid")
    for artifact in artifacts:
        if (
            artifact.kind not in _KINDS
            or _RELATIVE_PATH.fullmatch(artifact.path) is None
            or "//" in artifact.path
            or any(part in {".", ".."} for part in artifact.path.split("/"))
            or artifact.size < 0
            or _SHA256.fullmatch(artifact.sha256) is None
        ):
            raise PrimeImageInputLockError("Prime image input lock is invalid")
    return lock


def verify_image_input_artifact_set(
    root: Path, lock: ImageInputLock
) -> VerifiedImageInputArtifactSet:
    """Return verification evidence only after no-follow checks of every artifact."""

    verified = validate_image_input_lock(lock)
    if not isinstance(root, Path) or not root.is_absolute() or root.is_symlink():
        raise PrimeImageInputLockError("Prime image input lock is invalid")
    try:
        resolved = root.resolve(strict=True)
        if resolved != root or not resolved.is_dir():
            raise ValueError
        expected = {artifact.path for artifact in verified.artifacts}
        expected_directories = {
            parent.as_posix()
            for artifact in verified.artifacts
            for parent in Path(artifact.path).parents
            if parent != Path(".")
        }
        actual: set[str] = set()
        actual_directories: set[str] = set()
        for directory, names, files in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            if not stat.S_ISDIR(directory_path.lstat().st_mode):
                raise ValueError
            if directory_path != root:
                actual_directories.add(directory_path.relative_to(root).as_posix())
            if any((directory_path / name).is_symlink() for name in names):
                raise ValueError
            for name in files:
                path = directory_path / name
                relative = path.relative_to(root).as_posix()
                if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                    raise ValueError
                actual.add(relative)
        if actual != expected or actual_directories != expected_directories:
            raise ValueError
        for artifact in verified.artifacts:
            path = root / artifact.path
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode) or info.st_size != artifact.size:
                    raise ValueError
                digest = sha256()
                while chunk := os.read(descriptor, 65536):
                    digest.update(chunk)
                if digest.hexdigest() != artifact.sha256:
                    raise ValueError
            finally:
                os.close(descriptor)
    except (OSError, ValueError):
        raise PrimeImageInputLockError("Prime image input lock is invalid") from None
    return _verified_image_input_artifact_set(verified, root)


def canonical_image_input_lock_json_unchecked(lock: ImageInputLock) -> str:
    return json.dumps(lock.as_dict(), separators=(",", ":"), sort_keys=True)
