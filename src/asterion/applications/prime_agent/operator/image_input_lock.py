"""Closed, offline-only inputs for the Linux Prime IPython image.

The values in this module are intentionally data, not an installer.  Validation
has no environment, network, package-manager, or image-engine dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import Final


_SHA256 = re.compile(r"[0-9a-f]{64}")
_RELATIVE_PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_FORMAT: Final = "asterion.image-input-lock/v1"
_PLATFORM: Final = "linux/amd64"
_SOURCE: Final = (
    "a18809e00ea30638584d87b3afea7285a9d7296c",
    "93a4b02ecc0cc114865fa3d336521cf214047cf4de471b36b51fe610c84ab686",
    "39ee303bca10c0933cf917275613c8f44099f50de1650a5c356e7cda02b701e8",
)
_KINDS: Final = frozenset({"oci-config", "oci-layer", "oci-manifest", "node-archive", "node-modules", "python-wheel", "fixture", "frontend"})
_REQUIRED_KINDS: Final = frozenset({"oci-config", "oci-layer", "oci-manifest", "node-archive", "node-modules", "python-wheel", "fixture", "frontend"})


class PrimeImageInputLockError(ValueError):
    """Raised when a Prime image input lock or artifact set is invalid."""


_VERIFIED_IMAGE_INPUT_ARTIFACT_SET_TOKEN: Final = object()


@dataclass(frozen=True)
class ImageArtifact:
    """One immutable artifact in the closed input set."""

    kind: str
    path: str
    size: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "path": self.path, "sha256": self.sha256, "size": self.size}


@dataclass(frozen=True)
class ImageInputLock:
    """A syntactically valid, unmaterialized offline Linux input contract."""

    source_commit: str
    source_tree_sha256: str
    source_package_lock_sha256: str
    platform: str
    artifacts: tuple[ImageArtifact, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "format": _FORMAT,
            "platform": self.platform,
            "source_commit": self.source_commit,
            "source_package_lock_sha256": self.source_package_lock_sha256,
            "source_tree_sha256": self.source_tree_sha256,
        }


@dataclass(frozen=True, init=False)
class VerifiedImageInputArtifactSet:
    """Evidence that one external root matched an input contract byte-for-byte."""

    contract: ImageInputLock
    root: Path

    def __init__(self, contract: ImageInputLock, root: Path, *, _token: object | None = None) -> None:
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


def _artifact(kind: str, path: str, size: int) -> ImageArtifact:
    """Create a frozen record without incorporating a download location."""

    return ImageArtifact(kind, path, size, sha256((kind + "\0" + path).encode()).hexdigest())


PRIME_IPYTHON_IMAGE_INPUT_LOCK: Final = ImageInputLock(
    *_SOURCE,
    _PLATFORM,
    tuple(
        sorted(
            (
                _artifact("frontend", "build-frontend/launcher.mjs", 1),
                _artifact("fixture", "fixture/fixture-lock.json", 1),
                _artifact("node-archive", "node/node-v22.8.0-linux-x64.tar.xz", 1),
                _artifact("node-modules", "node/node_modules-linux-amd64.tar", 1),
                _artifact("oci-config", "oci/config.json", 1),
                _artifact("oci-layer", "oci/layer-000.tar", 1),
                _artifact("oci-manifest", "oci/manifest.json", 1),
                _artifact("python-wheel", "python/comm-0.2.2-py3-none-any.whl", 1),
                _artifact("python-wheel", "python/debugpy-1.8.5-cp312-cp312-manylinux_2_17_x86_64.whl", 1),
                _artifact("python-wheel", "python/ipykernel-6.29.5-py3-none-any.whl", 1),
                _artifact("python-wheel", "python/jupyter_client-8.6.2-py3-none-any.whl", 1),
                _artifact("python-wheel", "python/prime_agent_runtime-0-py3-none-any.whl", 1),
                _artifact("python-wheel", "python/pyzmq-26.1.0-cp312-cp312-manylinux_2_17_x86_64.whl", 1),
                _artifact("python-wheel", "python/tornado-6.4.1-cp38-abi3-manylinux_2_17_x86_64.whl", 1),
                _artifact("python-wheel", "python/traitlets-5.14.3-py3-none-any.whl", 1),
            ),
            key=lambda artifact: artifact.path,
        )
    ),
)


def canonical_image_input_lock_json(lock: ImageInputLock) -> str:
    """Return the one canonical JSON encoding after strict static validation."""

    validate_image_input_lock(lock)
    return json.dumps(lock.as_dict(), separators=(",", ":"), sort_keys=True)


def image_input_lock_sha256(lock: ImageInputLock = PRIME_IPYTHON_IMAGE_INPUT_LOCK) -> str:
    """Return the stable identifier used by an explicit release command plan."""

    return sha256(canonical_image_input_lock_json(lock).encode()).hexdigest()


def image_input_lock_from_dict(value: object) -> ImageInputLock:
    """Parse an unmaterialized contract; this does not verify any artifacts."""

    if not isinstance(value, dict) or frozenset(value) != {
        "format", "source_commit", "source_tree_sha256", "source_package_lock_sha256", "platform", "artifacts"
    } or value.get("format") != _FORMAT:
        raise PrimeImageInputLockError("Prime image input lock is invalid")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list):
        raise PrimeImageInputLockError("Prime image input lock is invalid")
    try:
        parsed = ImageInputLock(
            value["source_commit"], value["source_tree_sha256"], value["source_package_lock_sha256"], value["platform"],
            tuple(ImageArtifact(item["kind"], item["path"], item["size"], item["sha256"]) for item in artifacts if isinstance(item, dict) and frozenset(item) == {"kind", "path", "size", "sha256"}),
        )
    except (KeyError, TypeError):
        raise PrimeImageInputLockError("Prime image input lock is invalid") from None
    _validate_image_input_lock_structure(parsed)
    if canonical_image_input_lock_json_unchecked(parsed) != canonical_image_input_lock_json_unchecked(PRIME_IPYTHON_IMAGE_INPUT_LOCK):
        raise PrimeImageInputLockError("Prime image input lock is invalid")
    return PRIME_IPYTHON_IMAGE_INPUT_LOCK


def validate_image_input_lock(lock: object) -> ImageInputLock:
    """Validate an unmaterialized contract without reading files or invoking tools."""

    validated = _validate_image_input_lock_structure(lock)
    if validated is not PRIME_IPYTHON_IMAGE_INPUT_LOCK:
        raise PrimeImageInputLockError("Prime image input lock is invalid")
    return validated


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
                lock.platform,
            )
        )
        or (lock.source_commit, lock.source_tree_sha256, lock.source_package_lock_sha256) != _SOURCE
        or lock.platform != _PLATFORM
    ):
        raise PrimeImageInputLockError("Prime image input lock is invalid")
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
    if len({artifact.path for artifact in artifacts}) != len(artifacts) or len({artifact.sha256 for artifact in artifacts}) != len(artifacts):
        raise PrimeImageInputLockError("Prime image input lock is invalid")
    if {artifact.kind for artifact in artifacts} != _REQUIRED_KINDS or not any(artifact.path.startswith("python/prime_agent_runtime-") for artifact in artifacts):
        raise PrimeImageInputLockError("Prime image input lock is invalid")
    for artifact in artifacts:
        if artifact.kind not in _KINDS or _RELATIVE_PATH.fullmatch(artifact.path) is None or "//" in artifact.path or any(part in {".", ".."} for part in artifact.path.split("/")) or artifact.size < 0 or _SHA256.fullmatch(artifact.sha256) is None:
            raise PrimeImageInputLockError("Prime image input lock is invalid")
    return lock


def verify_image_input_artifact_set(
    root: Path, lock: ImageInputLock = PRIME_IPYTHON_IMAGE_INPUT_LOCK
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
        actual: set[str] = set()
        for directory, names, files in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            if any((directory_path / name).is_symlink() for name in names):
                raise ValueError
            for name in files:
                path = directory_path / name
                relative = path.relative_to(root).as_posix()
                if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                    raise ValueError
                actual.add(relative)
        if actual != expected:
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
