"""Closed, private fixed inputs and oracle facts for P3 development."""

from __future__ import annotations

from hashlib import sha256
import json
from types import MappingProxyType
from typing import Final


class PrimeP3DevelopmentWorkloadError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P3 development workload is unavailable")


def _json(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"


P3_INITIAL_SOURCE_BYTES: Final = b"def in_range(value: int, low: int, high: int) -> bool:\n    return low <= value <= high\n"
P3_INITIAL_TEST_BYTES: Final = b"from solution import in_range\n\n\ndef test_interior_value() -> None:\n    assert in_range(3, 1, 5) is True\n"
P3_SEED_FILENAMES: Final = ("solution.py", "test_solution.py")
P3_ARTIFACT_FILENAMES: Final = (
    "implementation.json", "review.json", "review-follow-up.json", "aggregate.json",
)
P3_ROOT_PROMPT: Final = """You are the root coordinator for one fixed verification in /workspace.
On your first turn, call ipython exactly once. In that single cell import
asterion_rlm and execute this exact order: spawn('implementation'),
wait('implementation'), spawn('review'), wait('review'), follow_up(),
delete('implementation'), delete('review'), then list_children(). Require every
operation to report completion and the final list to equal {'subagents': []}.
Read implementation.json, review.json, and review-follow-up.json and require
their exact fixed role/format fields. Then write aggregate.json as canonical
sorted compact JSON plus one newline with exactly these facts: child_count 2,
implementation 'patched', max_depth 1, model_callback_count 10,
remaining_child_count 0, retained_follow_up_count 1, review 'verified', and
tool_call_count 4. Do not print file contents. After the tool result, and on
each later child terminal notice, reply only: P3 root complete. Never call a
second tool and never create a child except through that first cell."""
P3_IMPLEMENTATION_PROMPT: Final = """You are the implementation child in /workspace.
Call ipython exactly once. Read solution.py and test_solution.py. Change only
the upper-bound comparison in in_range from <= high to < high, preserving the
function signature, other whitespace, and final newline. Require in_range(5,
1, 5) is False and in_range(3, 1, 5) is True. Do not change test_solution.py.
Write implementation.json as canonical sorted compact JSON plus one newline:
{'format':'asterion.prime-p3-implementation/v1','patched':true,
'role':'implementation'}. After the tool result reply only:
P3 implementation complete. Do not send a parent message."""
P3_REVIEW_PROMPT: Final = """You are the retained review child in /workspace.
Call ipython exactly once. Read the repaired solution.py, the still-initial
test_solution.py, and implementation.json. Confirm the source uses an
exclusive upper bound and the tests omit the upper-bound case. Do not modify
source or tests. Write review.json as canonical sorted compact JSON plus one
newline: {'format':'asterion.prime-p3-review/v1',
'missing_case':'upper-exclusive','role':'review'}. After the tool result reply
only: P3 review complete. Remain available for one follow-up and do not send a
parent message."""
P3_FOLLOW_UP_PROMPT: Final = """Continue in the same review session in /workspace.
Call ipython exactly once. Require review.json to contain the fixed prior
review. Append exactly one test named test_upper_bound_is_exclusive asserting
in_range(5, 1, 5) is False, preserving the exact existing test and final
newline. Load solution.py and the updated tests in fresh namespaces, run the
fixed cases (5,1,5)->False and (3,1,5)->True, and call both test functions.
Write review-follow-up.json as canonical sorted compact JSON plus one newline
with format asterion.prime-p3-review-follow-up/v1, oracle_cases
[[5,1,5,false],[3,1,5,true]], role review, verified true. After the tool result
reply only: P3 review verified. Do not send a parent message."""
P3_EXPECTED_SOURCE_BYTES: Final = b"def in_range(value: int, low: int, high: int) -> bool:\n    return low <= value < high\n"
P3_EXPECTED_TEST_BYTES: Final = b"from solution import in_range\n\n\ndef test_interior_value() -> None:\n    assert in_range(3, 1, 5) is True\n\n\ndef test_upper_bound_is_exclusive() -> None:\n    assert in_range(5, 1, 5) is False\n"
P3_ORACLE_CASES: Final = ((5, 1, 5, False), (3, 1, 5, True))
P3_ROLE_MODEL_CALLBACKS: Final = MappingProxyType({"root": 4, "implementation": 2, "review": 4})
P3_ROLE_TOOL_CALLS: Final = MappingProxyType({"root": 1, "implementation": 1, "review": 2})
P3_CHILD_COUNT: Final = 2
P3_MAX_DEPTH: Final = 1

_IMPLEMENTATION_ARTIFACT = {"format": "asterion.prime-p3-implementation/v1", "patched": True, "role": "implementation"}
_REVIEW_ARTIFACT = {"format": "asterion.prime-p3-review/v1", "missing_case": "upper-exclusive", "role": "review"}
_FOLLOW_UP_ARTIFACT = {"format": "asterion.prime-p3-review-follow-up/v1", "oracle_cases": ((5, 1, 5, False), (3, 1, 5, True)), "role": "review", "verified": True}
_AGGREGATE = {"child_count": 2, "implementation": "patched", "max_depth": 1, "model_callback_count": 10, "remaining_child_count": 0, "retained_follow_up_count": 1, "review": "verified", "tool_call_count": 4}
P3_IMPLEMENTATION_ARTIFACT: Final = MappingProxyType(_IMPLEMENTATION_ARTIFACT)
P3_REVIEW_ARTIFACT: Final = MappingProxyType(_REVIEW_ARTIFACT)
P3_FOLLOW_UP_ARTIFACT: Final = MappingProxyType(_FOLLOW_UP_ARTIFACT)
P3_AGGREGATE: Final = MappingProxyType(_AGGREGATE)
P3_IMPLEMENTATION_BYTES: Final = _json(_IMPLEMENTATION_ARTIFACT)
P3_REVIEW_BYTES: Final = _json(_REVIEW_ARTIFACT)
P3_FOLLOW_UP_BYTES: Final = _json(_FOLLOW_UP_ARTIFACT)
P3_AGGREGATE_BYTES: Final = _json(_AGGREGATE)

P3_DEVELOPMENT_SCHEMA_BYTES: Final = _json({"format": "asterion.prime-p3-development/v1", "roles": ["implementation", "review", "root"]})
P3_ARTIFACT_SCHEMA_BYTES: Final = _json({"filenames": list(P3_ARTIFACT_FILENAMES), "format": "asterion.prime-p3-artifacts/v1"})
P3_DEVELOPMENT_WORKLOAD_BYTES: Final = _json({"aggregate_sha256": sha256(P3_AGGREGATE_BYTES).hexdigest(), "artifact_schema_sha256": sha256(P3_ARTIFACT_SCHEMA_BYTES).hexdigest(), "expected_source_sha256": sha256(P3_EXPECTED_SOURCE_BYTES).hexdigest(), "expected_test_sha256": sha256(P3_EXPECTED_TEST_BYTES).hexdigest(), "follow_up_artifact_sha256": sha256(P3_FOLLOW_UP_BYTES).hexdigest(), "format": "asterion.prime-p3-development-workload/v1", "implementation_artifact_sha256": sha256(P3_IMPLEMENTATION_BYTES).hexdigest(), "initial_source_sha256": sha256(P3_INITIAL_SOURCE_BYTES).hexdigest(), "initial_test_sha256": sha256(P3_INITIAL_TEST_BYTES).hexdigest(), "oracle_cases": [[5, 1, 5, False], [3, 1, 5, True]], "prompts_sha256": {"follow_up": sha256(P3_FOLLOW_UP_PROMPT.encode()).hexdigest(), "implementation": sha256(P3_IMPLEMENTATION_PROMPT.encode()).hexdigest(), "review": sha256(P3_REVIEW_PROMPT.encode()).hexdigest(), "root": sha256(P3_ROOT_PROMPT.encode()).hexdigest()}, "role_model_callbacks": {"implementation": 2, "review": 4, "root": 4}, "role_tool_calls": {"implementation": 1, "review": 2, "root": 1}, "seed_sha256": {"solution.py": sha256(P3_INITIAL_SOURCE_BYTES).hexdigest(), "test_solution.py": sha256(P3_INITIAL_TEST_BYTES).hexdigest()}, "review_artifact_sha256": sha256(P3_REVIEW_BYTES).hexdigest(), "schema_sha256": sha256(P3_DEVELOPMENT_SCHEMA_BYTES).hexdigest()})

P3_DEVELOPMENT_WORKLOAD_DIGEST: Final = "sha256:" + sha256(P3_DEVELOPMENT_WORKLOAD_BYTES).hexdigest()
P3_DEVELOPMENT_SCHEMA_DIGEST: Final = "sha256:" + sha256(P3_DEVELOPMENT_SCHEMA_BYTES).hexdigest()
P3_INITIAL_SOURCE_DIGEST: Final = "sha256:" + sha256(P3_INITIAL_SOURCE_BYTES).hexdigest()
P3_INITIAL_TEST_DIGEST: Final = "sha256:" + sha256(P3_INITIAL_TEST_BYTES).hexdigest()
P3_EXPECTED_SOURCE_DIGEST: Final = "sha256:" + sha256(P3_EXPECTED_SOURCE_BYTES).hexdigest()
P3_EXPECTED_TEST_DIGEST: Final = "sha256:" + sha256(P3_EXPECTED_TEST_BYTES).hexdigest()
P3_ORACLE_DIGEST: Final = "sha256:" + sha256(_json({"cases": [[5, 1, 5, False], [3, 1, 5, True]]})).hexdigest()


def _exact(value: object, expected: bytes) -> None:
    if type(value) is not bytes or value != expected:
        raise PrimeP3DevelopmentWorkloadError()


def validate_p3_source_bytes(value: object) -> bytes:
    _exact(value, P3_EXPECTED_SOURCE_BYTES)
    return P3_EXPECTED_SOURCE_BYTES


def validate_p3_test_bytes(value: object) -> bytes:
    _exact(value, P3_EXPECTED_TEST_BYTES)
    return P3_EXPECTED_TEST_BYTES


def validate_p3_aggregate_bytes(value: object) -> dict[str, object]:
    _exact(value, P3_AGGREGATE_BYTES)
    return json.loads(P3_AGGREGATE_BYTES)


def validate_p3_artifact_bytes(*, role: object, value: object) -> bytes:
    if role == "implementation":
        expected = P3_IMPLEMENTATION_BYTES
    elif role == "review":
        expected = P3_REVIEW_BYTES
    elif role == "review-follow-up":
        expected = P3_FOLLOW_UP_BYTES
    else:
        raise PrimeP3DevelopmentWorkloadError()
    _exact(value, expected)
    return expected


__all__ = tuple(name for name in globals() if name.startswith("P3_") or name.startswith("validate_p3_") or name == "PrimeP3DevelopmentWorkloadError")
