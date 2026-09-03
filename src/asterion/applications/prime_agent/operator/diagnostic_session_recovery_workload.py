"""Closed identity for the fixed Prime P4 diagnostic recovery workload."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Final


P4_DIAGNOSTIC_RECOVERY_MODEL_SHA256: Final = "sha256:" + "d" * 64
P4_DIAGNOSTIC_RECOVERY_ORACLE_SHA256: Final = "sha256:" + "e" * 64
P4_DIAGNOSTIC_RECOVERY_SCHEMA_SHA256: Final = "sha256:" + "0" * 64

_MANIFEST: Final = {
    "attach_count": 1,
    "child_action_ceiling": 2,
    "child_role_id": "prime.long-session-continuity.diagnostic-child",
    "child_usage_ceiling": 128,
    "compaction_count": 1,
    "detach_count": 1,
    "fixture_sha256": "sha256:" + "f" * 64,
    "format": "asterion.prime-diagnostic-session-recovery-workload/v1",
    "model_sha256": P4_DIAGNOSTIC_RECOVERY_MODEL_SHA256,
    "model_tool_names": ["ipython"],
    "oracle_sha256": P4_DIAGNOSTIC_RECOVERY_ORACLE_SHA256,
    "role_id": "prime.long-session-continuity",
    "root_action_ceiling": 3,
    "root_usage_ceiling": 256,
    "scenario_id": "prime.long-session-continuity/v1",
    "schema_sha256": P4_DIAGNOSTIC_RECOVERY_SCHEMA_SHA256,
    "supervisor_recovery_count": 1,
}

P4_DIAGNOSTIC_RECOVERY_SCENARIO_ID: Final = _MANIFEST["scenario_id"]
P4_DIAGNOSTIC_RECOVERY_ROLE_ID: Final = _MANIFEST["role_id"]


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


_MANIFEST_BYTES: Final = _canonical(_MANIFEST)
P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST: Final = (
    "sha256:" + sha256(_MANIFEST_BYTES).hexdigest()
)


def diagnostic_session_recovery_workload_manifest_bytes() -> bytes:
    """Return the sole image-owned P4 workload declaration."""

    return _MANIFEST_BYTES


def is_diagnostic_session_recovery_workload(value: object) -> bool:
    """Return whether *value* is the exact P4 workload identity."""

    return type(value) is str and value == P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST
