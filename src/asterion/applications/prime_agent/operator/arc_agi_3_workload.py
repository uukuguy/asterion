"""Closed identity for the fixed Prime P7 ARC-AGI-3 subset workload."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Final


P7_ARC_AGI_3_ACTION_CEILING: Final = 4
P7_ARC_AGI_3_USAGE_CEILING: Final = 256
P7_ARC_AGI_3_MODEL_SHA256: Final = "sha256:" + "a" * 64
P7_ARC_AGI_3_ORACLE_SHA256: Final = "sha256:" + "b" * 64
P7_ARC_AGI_3_SCHEMA_SHA256: Final = "sha256:" + "c" * 64

_MANIFEST: Final = {
    "action_ceiling": P7_ARC_AGI_3_ACTION_CEILING,
    "broker_call_ceiling": 8,
    "fixture_sha256": "sha256:" + "d" * 64,
    "format": "asterion.prime-arc-agi-3-workload/v1",
    "full_suite_sha256": "sha256:" + "e" * 64,
    "game_ceiling": 1,
    "model_sha256": P7_ARC_AGI_3_MODEL_SHA256,
    "model_tool_names": ["ipython"],
    "oracle_sha256": P7_ARC_AGI_3_ORACLE_SHA256,
    "role_id": "prime.arc-agi-3",
    "scenario_id": "prime.arc-agi-3/v1",
    "schema_sha256": P7_ARC_AGI_3_SCHEMA_SHA256,
    "usage_ceiling": P7_ARC_AGI_3_USAGE_CEILING,
}

P7_ARC_AGI_3_SCENARIO_ID: Final = _MANIFEST["scenario_id"]
P7_ARC_AGI_3_ROLE_ID: Final = _MANIFEST["role_id"]


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


_MANIFEST_BYTES: Final = _canonical(_MANIFEST)
P7_ARC_AGI_3_WORKLOAD_DIGEST: Final = "sha256:" + sha256(_MANIFEST_BYTES).hexdigest()


def arc_agi_3_workload_manifest_bytes() -> bytes:
    """Return the sole image-owned P7 workload declaration."""

    return _MANIFEST_BYTES


def is_arc_agi_3_workload(value: object) -> bool:
    """Return whether *value* is the exact P7 workload identity."""

    return type(value) is str and value == P7_ARC_AGI_3_WORKLOAD_DIGEST
