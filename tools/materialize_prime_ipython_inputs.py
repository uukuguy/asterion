"""Plan or explicitly stage operator-specified Prime image release inputs."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
from typing import Iterable, Protocol, Sequence
from urllib.parse import urlsplit

from asterion.applications.prime_agent.operator.image_input_lock import (
    ImageArtifact, ImageInputLock, ImagePlatformDescriptor, PrimeImageInputLockError,
    ReleaseArtifact, ReleaseLockProposal, ReleaseSpecification,
    VerifiedImageInputArtifactSet, verify_image_input_artifact_set,
)
from asterion.applications.prime_agent.operator.release_recipe import (
    PRIME_IPYTHON_RELEASE_RECIPE,
    PrimeReleaseRecipeError,
    resolve_candidate_target,
)


class PrimeImageMaterializerError(ValueError):
    """Raised when an operator-selected materialization boundary is unsafe."""


class ReleaseResponse(Protocol):
    url: str
    content_length: int
    body: Iterable[bytes]


class ReleaseTransport(Protocol):
    def fetch(self, url: str) -> ReleaseResponse: ...


class _ReleaseAuthorization:
    """One-use release authority minted solely by the operator CLI boundary.

    This protects the normal module API.  It is not a defense against code
    already executing in this Python interpreter, which can inspect private
    module state.
    """

    __slots__ = ("_consumed",)

    def __init__(self, mint_key: object) -> None:
        if mint_key is not _RELEASE_AUTHORIZATION_MINT_KEY:
            raise TypeError("release authorization is minted by the operator CLI")
        self._consumed = False


_RELEASE_AUTHORIZATION_MINT_KEY = object()
_OPERATOR_RELEASE_ACTION = ("release-materialize",)


def _mint_release_authorization_from_operator_cli() -> _ReleaseAuthorization:
    """Mint the private one-use authority at the explicit operator CLI edge."""

    return _ReleaseAuthorization(_RELEASE_AUTHORIZATION_MINT_KEY)


def _consume_release_authorization(authorization: object) -> None:
    if type(authorization) is not _ReleaseAuthorization or authorization._consumed:
        raise ValueError
    authorization._consumed = True


def materialize_release_from_operator_cli(
    action: Sequence[str], output_root: Path, platform: ImagePlatformDescriptor,
    specification: ReleaseSpecification, transport: ReleaseTransport,
) -> ReleaseMaterializationResult:
    """Run staging only for the exact, explicitly selected operator CLI action.

    The narrow injected transport keeps this boundary testable and avoids
    embedding provider configuration or credentials in this tool.
    """

    if tuple(action) != _OPERATOR_RELEASE_ACTION:
        raise PrimeImageMaterializerError("Prime image materialization authorization is invalid")
    return materialize_authorized_release(
        output_root, platform, specification, transport,
        authorization=_mint_release_authorization_from_operator_cli(),
    )


@dataclass(frozen=True)
class MaterializationPlan:
    output_root: Path
    platform: ImagePlatformDescriptor
    lock_sha256: str
    commands: tuple[tuple[str, ...], ...]
    notice: str


@dataclass(frozen=True)
class ReleaseMaterializationResult:
    """Public-safe staging outcome; deliberately not verification evidence."""

    target_id: str
    platform: ImagePlatformDescriptor
    count: int
    digests: tuple[str, ...]
    proposal: ReleaseLockProposal


_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_MAX_BYTES = 1 << 30


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def lock_sha256() -> str:
    """Return the pinned dependency-lock identifier for a candidate release."""

    return PRIME_IPYTHON_RELEASE_RECIPE.python_dependency_lock_sha256


def plan_materialization(output_root: Path, platform: ImagePlatformDescriptor) -> MaterializationPlan:
    """Validate a new external target and return no executable side effect."""

    try:
        _validate_fresh_external_target(output_root)
        selected = resolve_candidate_target(platform)
    except (OSError, ValueError, PrimeImageInputLockError, PrimeReleaseRecipeError):
        raise PrimeImageMaterializerError("Prime image materialization target is invalid") from None
    return MaterializationPlan(
        output_root, selected, lock_sha256(),
        (("asterion-prime-authorized-release-materialize", "--lock-sha256", lock_sha256(), "--output-root", str(output_root)),),
        "This is only a command plan; a separately authorized release workflow must materialize and verify the artifact set.",
    )


def validate_release_specification(specification: object) -> ReleaseSpecification:
    """Fail closed unless every caller-injected release field is exact and safe."""

    if type(specification) is not ReleaseSpecification:
        raise ValueError("Prime image release specification is invalid")
    if (
        type(specification.source_commit) is not str
        or _COMMIT.fullmatch(specification.source_commit) is None
        or any(type(value) is not str or _SHA256.fullmatch(value) is None for value in (specification.source_tree_sha256, specification.source_package_lock_sha256))
        or not isinstance(specification.artifacts, tuple) or not specification.artifacts
    ):
        raise ValueError("Prime image release specification is invalid")
    resolve_candidate_target(specification.platform)
    artifacts = specification.artifacts
    if tuple(sorted(artifacts, key=lambda item: item.path)) != artifacts or len({item.url for item in artifacts}) != len(artifacts):
        raise ValueError("Prime image release specification is invalid")
    for artifact in artifacts:
        if type(artifact) is not ReleaseArtifact:
            raise ValueError("Prime image release specification is invalid")
        if type(artifact.url) is not str:
            raise ValueError("Prime image release specification is invalid")
        parsed = urlsplit(artifact.url)
        if (
            parsed.scheme != "https" or not parsed.netloc
            or parsed.username is not None or parsed.password is not None or parsed.fragment
            or _PATH.fullmatch(artifact.path) is None or "//" in artifact.path
            or any(part in {".", ".."} for part in artifact.path.split("/"))
            or type(artifact.size) is not int or artifact.size < 0 or artifact.size > _MAX_BYTES
            or type(artifact.sha256) is not str or _SHA256.fullmatch(artifact.sha256) is None
        ):
            raise ValueError("Prime image release specification is invalid")
    if len({item.path for item in artifacts}) != len(artifacts):
        raise ValueError("Prime image release specification is invalid")
    return specification


def materialize_authorized_release(
    output_root: Path, platform: ImagePlatformDescriptor, specification: ReleaseSpecification,
    transport: ReleaseTransport, *, authorization: object = None,
) -> ReleaseMaterializationResult:
    """Stage exact fetched bytes and issue only an untrusted lock proposal."""

    try:
        _consume_release_authorization(authorization)
    except (AttributeError, ValueError):
        raise PrimeImageMaterializerError("Prime image materialization authorization is invalid")
    try:
        spec = validate_release_specification(specification)
        selected = resolve_candidate_target(platform)
        if spec.platform != selected:
            raise ValueError
        canonical_root = _validate_fresh_external_target(output_root)
        if not hasattr(transport, "fetch"):
            raise ValueError
        canonical_root.mkdir(mode=0o700)
        if (canonical_root.stat().st_mode & 0o777) != 0o700:
            raise ValueError
        for artifact in spec.artifacts:
            response = transport.fetch(artifact.url)
            if response.url != artifact.url or response.content_length != artifact.size:
                raise ValueError
            _write_checked_file(canonical_root, artifact.path, response.body, artifact.size, artifact.sha256)
        proposal = ReleaseLockProposal(
            spec.source_commit, spec.source_tree_sha256, spec.source_package_lock_sha256, selected,
            tuple(ImageArtifact(item.kind, item.path, item.size, item.sha256) for item in spec.artifacts),
        )
        return ReleaseMaterializationResult(
            sha256(str(canonical_root).encode()).hexdigest(), selected,
            len(proposal.artifacts), tuple(item.sha256 for item in proposal.artifacts), proposal,
        )
    except (OSError, TypeError, ValueError, PrimeImageInputLockError):
        raise PrimeImageMaterializerError("Prime image materialization target is invalid") from None


def _validate_fresh_external_target(output_root: Path) -> Path:
    if not isinstance(output_root, Path) or not output_root.is_absolute() or output_root.exists() or output_root.is_symlink():
        raise ValueError
    resolved = output_root.resolve(strict=False)
    repository = repository_root().resolve(strict=True)
    parent = resolved.parent.resolve(strict=True)
    if not parent.is_dir() or parent.is_symlink() or repository == resolved or repository in resolved.parents or repository.parent in resolved.parents:
        raise ValueError
    return resolved


def _write_checked_file(root: Path, relative: str, chunks: Iterable[bytes], expected_size: int, expected_sha256: str) -> None:
    destination = root / relative
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # All directories below ``root`` were just created from the validated
    # relative path; do not mistake the platform's own /var compatibility link
    # for a caller-controlled staging symlink.
    if destination.parent.is_symlink():
        raise ValueError
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        digest = sha256()
        size = 0
        for chunk in chunks:
            if type(chunk) is not bytes or size + len(chunk) > expected_size or size + len(chunk) > _MAX_BYTES:
                raise ValueError
            _write_all(descriptor, chunk)
            digest.update(chunk)
            size += len(chunk)
        if size != expected_size or digest.hexdigest() != expected_sha256:
            raise ValueError
    finally:
        os.close(descriptor)
    descriptor = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        digest = sha256()
        while chunk := os.read(descriptor, 65536):
            digest.update(chunk)
        if not stat.S_ISREG(info.st_mode) or info.st_size != expected_size or digest.hexdigest() != expected_sha256:
            raise ValueError
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, chunk: bytes) -> None:
    """Write a transport chunk completely; short writes never truncate a digest."""

    view = memoryview(chunk)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def verify_external_materialization(
    output_root: Path, reviewed_lock: ImageInputLock
) -> VerifiedImageInputArtifactSet:
    """Verify an existing result against an explicitly reviewed lock; never download."""

    try:
        return verify_image_input_artifact_set(output_root, reviewed_lock)
    except PrimeImageInputLockError as error:
        raise PrimeImageMaterializerError("Prime image materialization target is invalid") from error
