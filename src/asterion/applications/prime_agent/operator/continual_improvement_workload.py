"""Closed identity for the fixed Prime P6 harness-refinement workload."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Final


P6_CONTINUAL_IMPROVEMENT_MODEL_SHA256: Final = "sha256:" + "d" * 64
P6_CONTINUAL_IMPROVEMENT_ORACLE_SHA256: Final = "sha256:" + "e" * 64
P6_CONTINUAL_IMPROVEMENT_SCHEMA_SHA256: Final = "sha256:" + "0" * 64

_MANIFEST: Final = {
    "action_ceiling": 3,
    "candidate_ceiling": 1,
    "crud_kind_coverage": ["memory", "prompt", "skill", "subagent"],
    "deadline_ms": 600_000,
    "fixture_sha256": "sha256:" + "f" * 64,
    "format": "asterion.prime-continual-improvement-workload/v1",
    "holdout_ceiling": 1,
    "model_sha256": P6_CONTINUAL_IMPROVEMENT_MODEL_SHA256,
    "model_tool_names": ["ipython"],
    "oracle_sha256": P6_CONTINUAL_IMPROVEMENT_ORACLE_SHA256,
    "rollback_ceiling": 1,
    "role_id": "prime.continual-improvement",
    "scenario_id": "prime.continual-improvement/v1",
    "schema_sha256": P6_CONTINUAL_IMPROVEMENT_SCHEMA_SHA256,
    "usage_ceiling": 256,
}

P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST: Final = "sha256:" + sha256(
    json.dumps(_MANIFEST, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()
_MANIFEST_BYTES: Final = json.dumps(
    _MANIFEST, sort_keys=True, separators=(",", ":")
).encode("utf-8")


def continual_improvement_workload_manifest_bytes() -> bytes:
    """Return the sole image-owned P6 workload declaration."""

    return _MANIFEST_BYTES


def is_continual_improvement_workload(value: object) -> bool:
    """Return whether *value* is the exact P6 workload identity."""

    return type(value) is str and value == P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST
