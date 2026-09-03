"""One-shot, digest-deduplicated quality-gate adapter for P5."""

from __future__ import annotations

from dataclasses import dataclass
import re


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class BoundedAutonomyGateError(ValueError):
    """Raised without exposing workspace or gate-private values."""


@dataclass(frozen=True, repr=False)
class BoundedAutonomyGateResult:
    workspace_sha256: str
    passed: bool
    result_sha256: str


async def run_bounded_autonomy_gate(
    gate: object, workspace_sha256: object, seen_workspaces: object
) -> BoundedAutonomyGateResult:
    """Run one host gate only for a new, digest-identified workspace."""

    try:
        if (
            type(workspace_sha256) is not str
            or _DIGEST.fullmatch(workspace_sha256) is None
            or type(seen_workspaces) is not frozenset
            or any(type(value) is not str or _DIGEST.fullmatch(value) is None for value in seen_workspaces)
            or workspace_sha256 in seen_workspaces
        ):
            raise ValueError
        passed, result_sha256 = await gate.evaluate(workspace_sha256)  # type: ignore[union-attr]
        if type(passed) is not bool or type(result_sha256) is not str or _DIGEST.fullmatch(result_sha256) is None:
            raise ValueError
        return BoundedAutonomyGateResult(workspace_sha256, passed, result_sha256)
    except (AttributeError, TypeError, ValueError):
        raise BoundedAutonomyGateError("bounded autonomy gate is invalid") from None
