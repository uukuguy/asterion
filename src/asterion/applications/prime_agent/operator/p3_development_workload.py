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
P3_ROOT_PROMPT: Final = r"""You are the root coordinator in /workspace. On the
first turn call ipython exactly once and copy this complete Python cell without
changing its operations or values:

import json
from pathlib import Path
import asterion_rlm as rlm

done = {"status": "completed"}
assert rlm.spawn("implementation") == done
assert rlm.wait("implementation") == done
assert rlm.spawn("review") == done
assert rlm.wait("review") == done
assert rlm.follow_up() == done
assert rlm.delete("implementation") == done
assert rlm.delete("review") == done
assert rlm.list_children() == {"subagents": []}
implementation = json.loads(Path("implementation.json").read_text())
review = json.loads(Path("review.json").read_text())
follow_up = json.loads(Path("review-follow-up.json").read_text())
assert implementation == {"format": "asterion.prime-p3-implementation/v1", "patched": True, "role": "implementation"}
assert review == {"format": "asterion.prime-p3-review/v1", "missing_case": "upper-exclusive", "role": "review"}
assert follow_up == {"format": "asterion.prime-p3-review-follow-up/v1", "oracle_cases": [[5, 1, 5, False], [3, 1, 5, True]], "role": "review", "verified": True}
aggregate = {"child_count": 2, "implementation": "patched", "max_depth": 1, "model_callback_count": 10, "remaining_child_count": 0, "retained_follow_up_count": 1, "review": "verified", "tool_call_count": 4}
Path("aggregate.json").write_text(json.dumps(aggregate, separators=(",", ":"), sort_keys=True) + "\n")

Do not print file contents. After this tool result, and on every later child
terminal notice, reply only `P3 root complete`. Never call a second tool."""
P3_IMPLEMENTATION_PROMPT: Final = r"""You are the implementation child in
/workspace. Call ipython exactly once and copy this complete Python cell:

import json
from pathlib import Path

source_path = Path("solution.py")
test_path = Path("test_solution.py")
source = source_path.read_text()
old = "    return low <= value <= high\n"
new = "    return low <= value < high\n"
assert source.count(old) == 1
source_path.write_text(source.replace(old, new))
assert test_path.read_bytes() == b"from solution import in_range\n\n\ndef test_interior_value() -> None:\n    assert in_range(3, 1, 5) is True\n"
namespace = {}
exec(compile(source_path.read_bytes(), "solution.py", "exec"), namespace)
assert namespace["in_range"](5, 1, 5) is False
assert namespace["in_range"](3, 1, 5) is True
artifact = {"format": "asterion.prime-p3-implementation/v1", "patched": True, "role": "implementation"}
Path("implementation.json").write_text(json.dumps(artifact, separators=(",", ":"), sort_keys=True) + "\n")

After the tool result reply only `P3 implementation complete`. Never call a
second tool and do not send a parent message."""
P3_REVIEW_PROMPT: Final = r"""You are the retained review child in /workspace.
Call ipython exactly once and copy this complete Python cell:

import json
from pathlib import Path

assert Path("solution.py").read_bytes() == b"def in_range(value: int, low: int, high: int) -> bool:\n    return low <= value < high\n"
assert Path("test_solution.py").read_bytes() == b"from solution import in_range\n\n\ndef test_interior_value() -> None:\n    assert in_range(3, 1, 5) is True\n"
assert json.loads(Path("implementation.json").read_text()) == {"format": "asterion.prime-p3-implementation/v1", "patched": True, "role": "implementation"}
artifact = {"format": "asterion.prime-p3-review/v1", "missing_case": "upper-exclusive", "role": "review"}
Path("review.json").write_text(json.dumps(artifact, separators=(",", ":"), sort_keys=True) + "\n")

After the tool result reply only `P3 review complete`. Never call a second tool,
remain available for one follow-up, and do not send a parent message."""
P3_FOLLOW_UP_PROMPT: Final = r"""Continue in the same review session in
/workspace. Call ipython exactly once and copy this complete Python cell:

import json
from pathlib import Path

assert json.loads(Path("review.json").read_text()) == {"format": "asterion.prime-p3-review/v1", "missing_case": "upper-exclusive", "role": "review"}
initial = b"from solution import in_range\n\n\ndef test_interior_value() -> None:\n    assert in_range(3, 1, 5) is True\n"
addition = b"\n\ndef test_upper_bound_is_exclusive() -> None:\n    assert in_range(5, 1, 5) is False\n"
test_path = Path("test_solution.py")
assert test_path.read_bytes() == initial
test_path.write_bytes(initial + addition)
source_namespace = {}
exec(compile(Path("solution.py").read_bytes(), "solution.py", "exec"), source_namespace)
assert source_namespace["in_range"](5, 1, 5) is False
assert source_namespace["in_range"](3, 1, 5) is True
test_namespace = {"in_range": source_namespace["in_range"]}
test_source = test_path.read_text().removeprefix("from solution import in_range\n\n\n")
exec(compile(test_source, "test_solution.py", "exec"), test_namespace)
test_namespace["test_interior_value"]()
test_namespace["test_upper_bound_is_exclusive"]()
artifact = {"format": "asterion.prime-p3-review-follow-up/v1", "oracle_cases": [[5, 1, 5, False], [3, 1, 5, True]], "role": "review", "verified": True}
Path("review-follow-up.json").write_text(json.dumps(artifact, separators=(",", ":"), sort_keys=True) + "\n")

After the tool result reply only `P3 review verified`. Never call another tool
and do not send a parent message."""
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
