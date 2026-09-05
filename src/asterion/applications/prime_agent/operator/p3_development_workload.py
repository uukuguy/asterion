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
P3_EXPECTED_SOURCE_BYTES: Final = b"def in_range(value: int, low: int, high: int) -> bool:\n    return low <= value < high\n"
P3_EXPECTED_TEST_BYTES: Final = b"from solution import in_range\n\n\ndef test_interior_value() -> None:\n    assert in_range(3, 1, 5) is True\n\n\ndef test_upper_bound_is_exclusive() -> None:\n    assert in_range(5, 1, 5) is False\n"
P3_ORACLE_CASES: Final = ((5, 1, 5, False), (3, 1, 5, True))
P3_ROLE_MODEL_CALLBACKS: Final = MappingProxyType({"root": 2, "implementation": 2, "review": 4})
P3_ROLE_TOOL_CALLS: Final = MappingProxyType({"root": 1, "implementation": 1, "review": 2})
P3_CHILD_COUNT: Final = 2
P3_MAX_DEPTH: Final = 1

P3_IMPLEMENTATION_ARTIFACT: Final = {"format": "asterion.prime-p3-implementation/v1", "patched": True, "role": "implementation"}
P3_REVIEW_ARTIFACT: Final = {"format": "asterion.prime-p3-review/v1", "missing_case": "upper-exclusive", "role": "review"}
P3_FOLLOW_UP_ARTIFACT: Final = {"format": "asterion.prime-p3-review-follow-up/v1", "oracle_cases": [[5, 1, 5, False], [3, 1, 5, True]], "role": "review", "verified": True}
P3_AGGREGATE: Final = {"child_count": 2, "implementation": "patched", "max_depth": 1, "model_callback_count": 8, "remaining_child_count": 0, "retained_follow_up_count": 1, "review": "verified", "tool_call_count": 4}
P3_IMPLEMENTATION_BYTES: Final = _json(P3_IMPLEMENTATION_ARTIFACT)
P3_REVIEW_BYTES: Final = _json(P3_REVIEW_ARTIFACT)
P3_FOLLOW_UP_BYTES: Final = _json(P3_FOLLOW_UP_ARTIFACT)
P3_AGGREGATE_BYTES: Final = _json(P3_AGGREGATE)

P3_DEVELOPMENT_SCHEMA_BYTES: Final = _json({"format": "asterion.prime-p3-development/v1", "roles": ["implementation", "review", "root"]})
P3_DEVELOPMENT_WORKLOAD_BYTES: Final = _json({"aggregate_sha256": sha256(P3_AGGREGATE_BYTES).hexdigest(), "format": "asterion.prime-p3-development-workload/v1", "initial_source_sha256": sha256(P3_INITIAL_SOURCE_BYTES).hexdigest(), "initial_test_sha256": sha256(P3_INITIAL_TEST_BYTES).hexdigest(), "oracle_cases": [[5, 1, 5, False], [3, 1, 5, True]]})

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
    return dict(P3_AGGREGATE)


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
