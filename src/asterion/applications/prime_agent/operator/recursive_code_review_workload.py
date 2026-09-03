"""Closed workload identity for the Prime P3 recursive code-review workflow."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Final


_MANIFEST: Final = {
    "child_role_ids": [
        "prime.recursive-workflow.implementation",
        "prime.recursive-workflow.review",
    ],
    "depth": 1,
    "format": "asterion.prime-recursive-code-review-workload/v1",
    "model_sha256": "sha256:" + "d" * 64,
    "oracle_sha256": "sha256:" + "e" * 64,
    "repository_sha256": "sha256:" + "f" * 64,
    "role_id": "prime.recursive-workflow",
    "scenario_id": "prime.recursive-workflow/v1",
    "schema_sha256": "sha256:" + "0" * 64,
}

RECURSIVE_CODE_REVIEW_P3_SCENARIO_ID: Final = _MANIFEST["scenario_id"]
RECURSIVE_CODE_REVIEW_P3_ROLE_ID: Final = _MANIFEST["role_id"]
RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS: Final = tuple(_MANIFEST["child_role_ids"])
RECURSIVE_CODE_REVIEW_P3_FOLLOW_UP_ROLE_ID: Final = RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS[1]
RECURSIVE_CODE_REVIEW_P3_DEPTH: Final = _MANIFEST["depth"]


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


_MANIFEST_BYTES: Final = _canonical(_MANIFEST)
RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST: Final = (
    "sha256:" + sha256(_MANIFEST_BYTES).hexdigest()
)


def recursive_code_review_workload_manifest_bytes() -> bytes:
    """Return the sole image-owned P3 workload declaration."""
    return _MANIFEST_BYTES


def is_recursive_code_review_workload(value: object) -> bool:
    """Return whether *value* is the exact P3 workload identity."""
    return type(value) is str and value == RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST
