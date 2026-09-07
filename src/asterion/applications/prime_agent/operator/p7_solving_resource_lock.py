"""Closed verification for P7 solving inputs that are outside the P1 authority set."""

from __future__ import annotations

from pathlib import Path

from .p7_resource_lock import verify_p7_development_resources
from .p7_runtime_lock import verify_p7_development_runtime
from .p7_solving_workload import P7_SOLVING_GAME_ID, P7_SOLVING_RESOURCE_SHA256


class P7SolvingResourceLockError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 solving resources are invalid")


def verify_p7_solving_resources(root: object) -> dict[str, str]:
    """Verify the exact local LS20 resource and installed ARC runtime."""

    try:
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError
        resource = verify_p7_development_resources(
            root / "environment_files" / "ls20" / "9607627b"
        )
        runtime = verify_p7_development_runtime(root)
        if (
            resource.game_id != P7_SOLVING_GAME_ID
            or resource.resource_sha256 != P7_SOLVING_RESOURCE_SHA256
        ):
            raise ValueError
        return {
            "ls20_resource_sha256": resource.resource_sha256,
            "runtime_sha256": runtime.runtime_sha256,
        }
    except BaseException:
        raise P7SolvingResourceLockError() from None


__all__ = ("P7SolvingResourceLockError", "verify_p7_solving_resources")
