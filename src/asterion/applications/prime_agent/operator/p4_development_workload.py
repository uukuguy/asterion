"""Closed public identity for the independent, unpromoted Prime P4 contract."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Final


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _digest(value: object) -> str:
    return "sha256:" + sha256(_canonical(value)).hexdigest()


P4_DEVELOPMENT_SCOPE: Final = "p4-development/unpromoted"
P4_DEVELOPMENT_MODEL_DIGEST: Final = _digest(
    {
        "format": "asterion.prime-p4-development-model/v1",
        "model_state": "settled",
        "tool_names": ["ipython"],
    }
)
P4_DEVELOPMENT_ORACLE_DIGEST: Final = _digest(
    {
        "format": "asterion.prime-p4-development-oracle/v1",
        "oracle_continuity": "same",
        "scope": P4_DEVELOPMENT_SCOPE,
    }
)
P4_DEVELOPMENT_SCHEMA_DIGEST: Final = _digest(
    {
        "format": "asterion.prime-p4-development-receipt-schema/v1",
        "receipt_kind": "native-direct-reattach",
        "scope": P4_DEVELOPMENT_SCOPE,
    }
)

_MANIFEST: Final = {
    "child_count": 0,
    "checkpoint_mode": "readback",
    "cleanup": "full",
    "daemon_restart_count": 0,
    "detach_count": 1,
    "format": "asterion.prime-p4-development-workload/v1",
    "initial_attach_count": 1,
    "ipython_call_count": 2,
    "kernel_identity_count": 1,
    "kernel_restart_count": 0,
    "manual_compact_count": 1,
    "model_sha256": P4_DEVELOPMENT_MODEL_DIGEST,
    "model_state": "settled",
    "oracle_continuity": "same",
    "oracle_sha256": P4_DEVELOPMENT_ORACLE_DIGEST,
    "prompt_count": 2,
    "provider_callback_count": 5,
    "reattach_count": 1,
    "recovery_mode": "native-direct-reattach",
    "replay_mode": "zero-gap-exact",
    "runtime_identity_count": 1,
    "schema_sha256": P4_DEVELOPMENT_SCHEMA_DIGEST,
    "scope": P4_DEVELOPMENT_SCOPE,
    "session_identity_count": 1,
    "supervisor_recovery_count": 0,
    "tool_state": "settled",
    "transcript_identity_count": 1,
}

_MANIFEST_BYTES: Final = _canonical(_MANIFEST)
P4_DEVELOPMENT_WORKLOAD_DIGEST: Final = "sha256:" + sha256(_MANIFEST_BYTES).hexdigest()


def p4_development_workload_manifest_bytes() -> bytes:
    """Return the sole public-safe P4 development workload declaration."""

    return _MANIFEST_BYTES


def is_p4_development_workload(value: object) -> bool:
    """Return whether *value* is the exact independent P4 identity."""

    return type(value) is str and value == P4_DEVELOPMENT_WORKLOAD_DIGEST


__all__ = (
    "P4_DEVELOPMENT_MODEL_DIGEST",
    "P4_DEVELOPMENT_ORACLE_DIGEST",
    "P4_DEVELOPMENT_SCHEMA_DIGEST",
    "P4_DEVELOPMENT_SCOPE",
    "P4_DEVELOPMENT_WORKLOAD_DIGEST",
    "is_p4_development_workload",
    "p4_development_workload_manifest_bytes",
)
