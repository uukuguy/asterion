"""P3 host-side oracle and digest-only trace projection."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Literal, Mapping

from .p3_development_workload import P3_AGGREGATE_BYTES, P3_DEVELOPMENT_WORKLOAD_DIGEST, validate_p3_aggregate_bytes, validate_p3_source_bytes, validate_p3_test_bytes


class PrimeP3DevelopmentHostError(ValueError):
    def __init__(self, *_: object) -> None: super().__init__("prime P3 development host is unavailable")


@dataclass(frozen=True, repr=False)
class PrimeP3DevelopmentTrace:
    trace_sha256: str
    scope: Literal["p3-development"] = "p3-development"
    promotion: Literal["unpromoted"] = "unpromoted"
    def __post_init__(self) -> None:
        if not isinstance(self.trace_sha256, str) or len(self.trace_sha256) != 71 or not self.trace_sha256.startswith("sha256:"):
            raise PrimeP3DevelopmentHostError()


def validate_p3_development_oracle(*, source: object, tests: object, aggregate: object, observations: object) -> Mapping[str, object]:
    try:
        validate_p3_source_bytes(source)
        validate_p3_test_bytes(tests)
        answer = validate_p3_aggregate_bytes(aggregate)
    except BaseException:
        raise PrimeP3DevelopmentHostError() from None
    expected = {"child_count": 2, "max_depth": 1, "model_callback_count": 10, "remaining_child_count": 0, "retained_follow_up_count": 1, "tool_call_count": 4}
    if type(observations) is not dict or observations != expected or answer["model_callback_count"] != 10:
        raise PrimeP3DevelopmentHostError()
    return dict(expected)


def make_p3_development_trace(*, source: object, tests: object, aggregate: object, observations: object) -> PrimeP3DevelopmentTrace:
    facts = validate_p3_development_oracle(source=source, tests=tests, aggregate=aggregate, observations=observations)
    digest = sha256(json.dumps({"observations": facts, "aggregate_sha256": sha256(P3_AGGREGATE_BYTES).hexdigest(), "workload": P3_DEVELOPMENT_WORKLOAD_DIGEST}, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
    return PrimeP3DevelopmentTrace("sha256:" + digest)


__all__ = ("PrimeP3DevelopmentHostError", "PrimeP3DevelopmentTrace", "make_p3_development_trace", "validate_p3_development_oracle")
