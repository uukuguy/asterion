"""Closed constants for the first bounded P7 ARC solving episode."""

from __future__ import annotations

from typing import Final

from .p7_development_workload import (
    P7_DEVELOPMENT_ARC_AGI_WHEEL_SHA256,
    P7_DEVELOPMENT_GAME_METADATA_SHA256,
    P7_DEVELOPMENT_RESOURCE_DIGEST,
)


P7_SOLVING_GAME_ID: Final = "ls20-9607627b"
P7_SOLVING_SEED: Final = 0
P7_SOLVING_ACTION_CAP: Final = 500
P7_SOLVING_BATCH_CAP: Final = 20
P7_SOLVING_BASELINE_ACTIONS: Final = (22, 123, 73, 84, 96, 192, 186)
P7_SOLVING_ARC_AGI_WHEEL_SHA256: Final = P7_DEVELOPMENT_ARC_AGI_WHEEL_SHA256
P7_SOLVING_METADATA_SHA256: Final = P7_DEVELOPMENT_GAME_METADATA_SHA256
P7_SOLVING_RESOURCE_SHA256: Final = P7_DEVELOPMENT_RESOURCE_DIGEST


__all__ = tuple(name for name in globals() if name.startswith("P7_SOLVING_"))
