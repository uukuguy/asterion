"""Closed public identity for the independent unpromoted P5 repair run."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Final


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _digest(value: object) -> str:
    return "sha256:" + sha256(_canonical(value)).hexdigest()


P5_DEVELOPMENT_SCOPE: Final = "p5-development"
P5_DEVELOPMENT_PROMOTION: Final = "unpromoted"
P5_DEVELOPMENT_MODEL_DIGEST: Final = _digest(
    {
        "format": "asterion.prime-p5-development-model/v1",
        "scope": P5_DEVELOPMENT_SCOPE,
        "tools": ["ipython"],
    }
)
P5_DEVELOPMENT_ORACLE_DIGEST: Final = _digest(
    {"format": "asterion.prime-p5-development-oracle/v1", "scope": P5_DEVELOPMENT_SCOPE}
)
P5_DEVELOPMENT_SCHEMA_DIGEST: Final = _digest(
    {
        "format": "asterion.prime-p5-development-receipt-schema/v1",
        "scope": P5_DEVELOPMENT_SCOPE,
    }
)

_MANIFEST: Final = {
    "child_count": 0,
    "compact_count": 0,
    "feedback_count": 1,
    "format": "asterion.prime-p5-development-workload/v1",
    "ipython_call_count": 2,
    "model_sha256": P5_DEVELOPMENT_MODEL_DIGEST,
    "oracle_sha256": P5_DEVELOPMENT_ORACLE_DIGEST,
    "promotion": P5_DEVELOPMENT_PROMOTION,
    "prompt_count": 2,
    "provider_callback_count": 4,
    "quality_gate_count": 2,
    "repair": "clamp-defect",
    "repair_count": 1,
    "result_gate_count": 2,
    "retry_count": 0,
    "schema_sha256": P5_DEVELOPMENT_SCHEMA_DIGEST,
    "scope": P5_DEVELOPMENT_SCOPE,
}
_MANIFEST_BYTES: Final = _canonical(_MANIFEST)
P5_DEVELOPMENT_WORKLOAD_DIGEST: Final = "sha256:" + sha256(_MANIFEST_BYTES).hexdigest()


def p5_development_workload_manifest_bytes() -> bytes:
    return _MANIFEST_BYTES


def is_p5_development_workload(value: object) -> bool:
    return type(value) is str and value == P5_DEVELOPMENT_WORKLOAD_DIGEST


__all__ = tuple(
    name
    for name in globals()
    if name.startswith("P5_")
    or name in {"is_p5_development_workload", "p5_development_workload_manifest_bytes"}
)
