"""Closed declaration for the independent, unpromoted P7 game episode."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Final


def _canonical(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()


def _digest(value: object) -> str:
    return "sha256:" + sha256(_canonical(value)).hexdigest()


P7_DEVELOPMENT_SCOPE: Final = "p7-development"
P7_DEVELOPMENT_PROMOTION: Final = "unpromoted"
P7_DEVELOPMENT_GAME_ID: Final = "ls20-9607627b"
P7_DEVELOPMENT_GAME_SOURCE_SHA256: Final = "sha256:298c810da2850d557c95d92a2cbd846df29a45d7134e20888617bedf5dafcd92"
# Stable canonical projection of official metadata; volatile local path/time are excluded.
P7_DEVELOPMENT_GAME_METADATA_SHA256: Final = "sha256:71595f7ea98ef49e14f7ca972fabe649569302adc64958d70429a63e310a28de"
P7_DEVELOPMENT_ARC_AGI_WHEEL_SHA256: Final = "sha256:a0536df47b5ab93af16ba708083f74261cd1b7801bb2e0802824623c04d59e50"
P7_DEVELOPMENT_ARCENGINE_WHEEL_SHA256: Final = "sha256:5f9739d6d0055780a4581fd6fe09066bb08775c4c8212c9adcca2eb008aef59c"

_MODEL_DECLARATION: Final = {"format": "asterion.prime-p7-development-model/v1", "tools": ["ipython"]}
_ORACLE_DECLARATION: Final = {"format": "asterion.prime-p7-development-oracle/v1", "kind": "episode-replay"}
_SCHEMA_DECLARATION: Final = {
    "boolean_facts": ["episode_closed", "score_replayed", "broker_quiescent", "worker_destroyed", "full_cleanup"],
    "format": "asterion.prime-p7-development-receipt-schema/v1",
    "relations": ["broker_call_count=action_count+2", "action-limit=>action_count=4"],
    "strict_counts": ["game_count=1", "observation_count=1", "status_count=1", "prompt_count=3", "provider_callback_count=6", "ipython_call_count=3"],
    "terminal_reasons": ["action-limit", "engine-terminal"],
}
_RESOURCE_DECLARATION: Final = {
    "arc_agi": {"version": "0.9.9", "wheel_sha256": P7_DEVELOPMENT_ARC_AGI_WHEEL_SHA256},
    "arcengine": {"version": "0.9.3", "wheel_sha256": P7_DEVELOPMENT_ARCENGINE_WHEEL_SHA256},
    "game_id": P7_DEVELOPMENT_GAME_ID,
    "metadata_file": "metadata.json", "metadata_projection_sha256": P7_DEVELOPMENT_GAME_METADATA_SHA256,
    "source_file": "ls20.py", "source_sha256": P7_DEVELOPMENT_GAME_SOURCE_SHA256,
}
P7_DEVELOPMENT_MODEL_DIGEST: Final = _digest(_MODEL_DECLARATION)
P7_DEVELOPMENT_ORACLE_DIGEST: Final = _digest(_ORACLE_DECLARATION)
P7_DEVELOPMENT_SCHEMA_DIGEST: Final = _digest(_SCHEMA_DECLARATION)
P7_DEVELOPMENT_RESOURCE_DIGEST: Final = _digest(_RESOURCE_DECLARATION)

_MANIFEST: Final = {
    "action_ceiling": 4, "format": "asterion.prime-p7-development-workload/v1",
    "game_count": 1, "game_id": P7_DEVELOPMENT_GAME_ID, "ipython_call_count": 3,
    "model_sha256": P7_DEVELOPMENT_MODEL_DIGEST, "oracle_sha256": P7_DEVELOPMENT_ORACLE_DIGEST,
    "prompt_count": 3, "promotion": P7_DEVELOPMENT_PROMOTION,
    "provider_callback_count": 6, "resource_sha256": P7_DEVELOPMENT_RESOURCE_DIGEST,
    "receipt_schema": _SCHEMA_DECLARATION,
    "schema_sha256": P7_DEVELOPMENT_SCHEMA_DIGEST, "scope": P7_DEVELOPMENT_SCOPE,
    "seed": 0, "terminal_reasons": ["action-limit", "engine-terminal"], "tool_names": ["ipython"],
}
_MANIFEST_BYTES: Final = _canonical(_MANIFEST)
P7_DEVELOPMENT_WORKLOAD_DIGEST: Final = "sha256:" + sha256(_MANIFEST_BYTES).hexdigest()


def p7_development_workload_manifest_bytes() -> bytes:
    return _MANIFEST_BYTES


def is_p7_development_workload(value: object) -> bool:
    return type(value) is str and value == P7_DEVELOPMENT_WORKLOAD_DIGEST


__all__ = tuple(name for name in globals() if name.startswith("P7_")) + (
    "is_p7_development_workload", "p7_development_workload_manifest_bytes",
)
