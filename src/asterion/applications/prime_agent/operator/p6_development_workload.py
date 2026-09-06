"""Closed identity for the independent P6 development clamp refinement."""

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


P6_DEVELOPMENT_SCOPE: Final = "p6-development"
P6_DEVELOPMENT_PROMOTION: Final = "unpromoted"
P6_DEVELOPMENT_MODEL_DIGEST: Final = _digest(
    {"format": "asterion.prime-p6-development-model/v1", "tools": ["ipython"]}
)
P6_DEVELOPMENT_ORACLE_DIGEST: Final = _digest(
    {"format": "asterion.prime-p6-development-oracle/v1", "scope": "project"}
)
P6_DEVELOPMENT_SCHEMA_DIGEST: Final = _digest(
    {"format": "asterion.prime-p6-development-receipt-schema/v1"}
)

_BASELINE_SOURCE: Final = b"def clamp(value, lower, upper):\n    return min(upper, value)\n"
_CANDIDATE_SOURCE: Final = (
    b"def clamp(value, lower, upper):\n"
    b"    return min(max(value, lower), upper)\n"
)
_BAD_CANDIDATE_SOURCE: Final = (
    b"def clamp(value, lower, upper):\n"
    b"    return max(value, lower)\n"
)
P6_DEVELOPMENT_BASELINE_SNAPSHOT_SHA256: Final = "sha256:" + sha256(
    _BASELINE_SOURCE
).hexdigest()
P6_DEVELOPMENT_CANDIDATE_SNAPSHOT_SHA256: Final = "sha256:" + sha256(
    _CANDIDATE_SOURCE
).hexdigest()
P6_DEVELOPMENT_BAD_CANDIDATE_SNAPSHOT_SHA256: Final = "sha256:" + sha256(
    _BAD_CANDIDATE_SOURCE
).hexdigest()
P6_DEVELOPMENT_TASK_A_RESULT_SHA256: Final = _digest(
    {"fixture": "clamp-task-a/v1", "passed": False}
)
_PRESERVED_BRANCH: Final = {
    "candidate_source_sha256": P6_DEVELOPMENT_CANDIDATE_SNAPSHOT_SHA256,
    "final_source_sha256": P6_DEVELOPMENT_CANDIDATE_SNAPSHOT_SHA256,
    "holdout_result_sha256": _digest(
        {"fixture": "clamp-task-b/v1", "passed": True}
    ),
    "outcome_sha256": _digest({"outcome": "preserved", "rollback_count": 0}),
    "rollback_count": 0,
}
_ROLLED_BACK_BRANCH: Final = {
    "candidate_source_sha256": P6_DEVELOPMENT_BAD_CANDIDATE_SNAPSHOT_SHA256,
    "final_source_sha256": P6_DEVELOPMENT_BASELINE_SNAPSHOT_SHA256,
    "holdout_result_sha256": _digest(
        {"fixture": "clamp-task-b/v1", "passed": False}
    ),
    "outcome_sha256": _digest({"outcome": "rolled-back", "rollback_count": 1}),
    "rollback_count": 1,
}
_BRANCH_FACTS: Final = {
    "preserved": _PRESERVED_BRANCH,
    "rolled-back": _ROLLED_BACK_BRANCH,
}

_MANIFEST: Final = {
    "admitted_candidate_snapshot_sha256s": sorted((P6_DEVELOPMENT_CANDIDATE_SNAPSHOT_SHA256, P6_DEVELOPMENT_BAD_CANDIDATE_SNAPSHOT_SHA256)),
    "candidate_count": 1,
    "format": "asterion.prime-p6-development-workload/v1",
    "holdout_count": 1,
    "ipython_call_count": 3,
    "model_sha256": P6_DEVELOPMENT_MODEL_DIGEST,
    "oracle_sha256": P6_DEVELOPMENT_ORACLE_DIGEST,
    "prompt_count": 3,
    "promotion": P6_DEVELOPMENT_PROMOTION,
    "provider_callback_count": 6,
    "rollback_ceiling": 1,
    "schema_sha256": P6_DEVELOPMENT_SCHEMA_DIGEST,
    "scope": P6_DEVELOPMENT_SCOPE,
    "scope_kind": "project",
    "task_a_result_sha256": P6_DEVELOPMENT_TASK_A_RESULT_SHA256,
    "baseline_snapshot_sha256": P6_DEVELOPMENT_BASELINE_SNAPSHOT_SHA256,
    "tool_names": ["ipython"],
}
_MANIFEST_BYTES: Final = _canonical(_MANIFEST)
P6_DEVELOPMENT_WORKLOAD_DIGEST: Final = "sha256:" + sha256(_MANIFEST_BYTES).hexdigest()


def p6_development_workload_manifest_bytes() -> bytes:
    return _MANIFEST_BYTES


def p6_development_branch_facts(outcome: object) -> dict[str, object]:
    if type(outcome) is not str or outcome not in _BRANCH_FACTS:
        raise ValueError
    return dict(_BRANCH_FACTS[outcome])


def is_p6_development_workload(value: object) -> bool:
    return type(value) is str and value == P6_DEVELOPMENT_WORKLOAD_DIGEST


__all__ = tuple(
    name
    for name in globals()
    if name.startswith("P6_")
    or name
    in {
        "is_p6_development_workload",
        "p6_development_branch_facts",
        "p6_development_workload_manifest_bytes",
    }
)
