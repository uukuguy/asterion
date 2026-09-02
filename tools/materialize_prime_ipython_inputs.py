"""Plan, but never execute, release materialization of Prime IPython inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asterion.applications.prime_agent.operator.image_input_lock import (
    PRIME_IPYTHON_IMAGE_INPUT_LOCK,
    PrimeImageInputLockError,
    VerifiedImageInputArtifactSet,
    image_input_lock_sha256,
    verify_image_input_artifact_set,
)


class PrimeImageMaterializerError(ValueError):
    """Raised when an operator-selected materialization boundary is unsafe."""


@dataclass(frozen=True)
class MaterializationPlan:
    """An inert command description for a separately authorized release flow."""

    output_root: Path
    lock_sha256: str
    commands: tuple[tuple[str, ...], ...]
    notice: str


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def lock_sha256() -> str:
    return image_input_lock_sha256(PRIME_IPYTHON_IMAGE_INPUT_LOCK)


def plan_materialization(output_root: Path) -> MaterializationPlan:
    """Validate a new external target and return no executable side effect."""

    if not isinstance(output_root, Path) or not output_root.is_absolute() or output_root.exists():
        raise PrimeImageMaterializerError("Prime image materialization target is invalid")
    try:
        resolved = output_root.resolve(strict=False)
        repository = repository_root().resolve(strict=True)
        parent = resolved.parent.resolve(strict=True)
        if resolved != output_root or output_root.is_symlink() or repository == resolved or repository in resolved.parents or repository.parent in resolved.parents or not parent.is_dir() or parent.is_symlink():
            raise ValueError
    except (OSError, ValueError):
        raise PrimeImageMaterializerError("Prime image materialization target is invalid") from None
    return MaterializationPlan(
        output_root=output_root,
        lock_sha256=lock_sha256(),
        commands=(("asterion-prime-authorized-release-materialize", "--lock-sha256", lock_sha256(), "--output-root", str(output_root)),),
        notice="This is only a command plan; a separately authorized release workflow must materialize and verify the artifact set.",
    )


def verify_external_materialization(output_root: Path) -> VerifiedImageInputArtifactSet:
    """Return verification evidence for an existing result; never download or build it."""

    try:
        return verify_image_input_artifact_set(output_root)
    except PrimeImageInputLockError as error:
        raise PrimeImageMaterializerError("Prime image materialization target is invalid") from error
