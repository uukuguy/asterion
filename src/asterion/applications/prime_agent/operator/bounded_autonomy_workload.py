"""Closed identity for the fixed Prime P5 IPython diagnostic repair loop."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Final


P5_BOUNDED_AUTONOMY_ACTION_CEILING: Final = 3
P5_BOUNDED_AUTONOMY_USAGE_CEILING: Final = 256
P5_BOUNDED_AUTONOMY_MODEL_SHA256: Final = "sha256:" + "d" * 64
P5_BOUNDED_AUTONOMY_ORACLE_SHA256: Final = "sha256:" + "e" * 64
P5_BOUNDED_AUTONOMY_SCHEMA_SHA256: Final = "sha256:" + "0" * 64

_MANIFEST: Final = {
    "action_ceiling": P5_BOUNDED_AUTONOMY_ACTION_CEILING,
    "feedback_ceiling": 1,
    "fixture_sha256": "sha256:" + "f" * 64,
    "format": "asterion.prime-bounded-autonomy-workload/v1",
    "gate_ceiling": 2,
    "model_sha256": P5_BOUNDED_AUTONOMY_MODEL_SHA256,
    "model_tool_names": ["ipython"],
    "oracle_sha256": P5_BOUNDED_AUTONOMY_ORACLE_SHA256,
    "role_id": "prime.bounded-autonomy",
    "scenario_id": "prime.bounded-autonomy/v1",
    "schema_sha256": P5_BOUNDED_AUTONOMY_SCHEMA_SHA256,
    "usage_ceiling": P5_BOUNDED_AUTONOMY_USAGE_CEILING,
}

P5_BOUNDED_AUTONOMY_SCENARIO_ID: Final = _MANIFEST["scenario_id"]
P5_BOUNDED_AUTONOMY_ROLE_ID: Final = _MANIFEST["role_id"]


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


_MANIFEST_BYTES: Final = _canonical(_MANIFEST)
P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST: Final = "sha256:" + sha256(
    _MANIFEST_BYTES
).hexdigest()


def bounded_autonomy_workload_manifest_bytes() -> bytes:
    """Return the sole image-owned P5 workload declaration."""

    return _MANIFEST_BYTES


def is_bounded_autonomy_workload(value: object) -> bool:
    """Return whether *value* is the exact P5 workload identity."""

    return type(value) is str and value == P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST
