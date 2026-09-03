"""Closed workload identity for the Prime P3 recursive code-review workflow."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Final


RECURSIVE_CODE_REVIEW_P3_CHILD_COUNT: Final = 2
RECURSIVE_CODE_REVIEW_P3_DEPTH: Final = 1
RECURSIVE_CODE_REVIEW_P3_MAX_FRAME_BYTES: Final = 4096
RECURSIVE_CODE_REVIEW_P3_DEADLINE_SECONDS: Final = 1
RECURSIVE_CODE_REVIEW_P3_ROOT_ACTION_CEILING: Final = 2
RECURSIVE_CODE_REVIEW_P3_CHILD_ACTION_CEILING: Final = 2
RECURSIVE_CODE_REVIEW_P3_ROOT_USAGE_CEILING: Final = 256
RECURSIVE_CODE_REVIEW_P3_CHILD_USAGE_CEILING: Final = 128
RECURSIVE_CODE_REVIEW_P3_MODEL_TOOL_NAMES: Final = ("ipython",)
RECURSIVE_CODE_REVIEW_P3_MODEL_SHA256: Final = "sha256:" + "d" * 64
RECURSIVE_CODE_REVIEW_P3_ORACLE_SHA256: Final = "sha256:" + "e" * 64
RECURSIVE_CODE_REVIEW_P3_SCHEMA_SHA256: Final = "sha256:" + "0" * 64


_MANIFEST: Final = {
    "child_action_ceiling": RECURSIVE_CODE_REVIEW_P3_CHILD_ACTION_CEILING,
    "child_count": RECURSIVE_CODE_REVIEW_P3_CHILD_COUNT,
    "child_role_ids": [
        "prime.recursive-workflow.implementation",
        "prime.recursive-workflow.review",
    ],
    "child_usage_ceiling": RECURSIVE_CODE_REVIEW_P3_CHILD_USAGE_CEILING,
    "deadline_seconds": RECURSIVE_CODE_REVIEW_P3_DEADLINE_SECONDS,
    "depth": RECURSIVE_CODE_REVIEW_P3_DEPTH,
    "format": "asterion.prime-recursive-code-review-workload/v1",
    "max_frame_bytes": RECURSIVE_CODE_REVIEW_P3_MAX_FRAME_BYTES,
    "model_tool_names": list(RECURSIVE_CODE_REVIEW_P3_MODEL_TOOL_NAMES),
    "model_sha256": RECURSIVE_CODE_REVIEW_P3_MODEL_SHA256,
    "oracle_sha256": RECURSIVE_CODE_REVIEW_P3_ORACLE_SHA256,
    "repository_sha256": "sha256:" + "f" * 64,
    "retained_child_role_id": "prime.recursive-workflow.review",
    "role_id": "prime.recursive-workflow",
    "root_action_ceiling": RECURSIVE_CODE_REVIEW_P3_ROOT_ACTION_CEILING,
    "root_usage_ceiling": RECURSIVE_CODE_REVIEW_P3_ROOT_USAGE_CEILING,
    "scenario_id": "prime.recursive-workflow/v1",
    "schema_sha256": RECURSIVE_CODE_REVIEW_P3_SCHEMA_SHA256,
}

RECURSIVE_CODE_REVIEW_P3_SCENARIO_ID: Final = _MANIFEST["scenario_id"]
RECURSIVE_CODE_REVIEW_P3_ROLE_ID: Final = _MANIFEST["role_id"]
RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS: Final = tuple(_MANIFEST["child_role_ids"])
RECURSIVE_CODE_REVIEW_P3_FOLLOW_UP_ROLE_ID: Final = RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS[1]


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
