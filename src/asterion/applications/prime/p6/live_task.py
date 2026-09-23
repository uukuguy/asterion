"""Fixed, data-only task for evaluating a model-proposed P6 candidate."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json


_TRAIN_INPUTS = (1, 4, 7)
_HOLDOUT_INPUTS = (-3, 2, 9)
_BASELINE_MULTIPLIER = 2
_BASELINE_OFFSET = 0
_MAX_PARAMETER = 16
_MAX_CANDIDATE_BYTES = 1024


class P6LiveTaskError(ValueError):
    def __init__(self) -> None:
        super().__init__("P6 live candidate is invalid")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _target(value: int) -> int:
    return 3 * value + 1


@dataclass(frozen=True, slots=True, repr=False)
class P6Candidate:
    multiplier: int
    offset: int
    body: bytes
    body_sha256: str

    def predict(self, value: int) -> int:
        return self.multiplier * value + self.offset

    def __repr__(self) -> str:
        return "<P6Candidate redacted>"


@dataclass(frozen=True, slots=True)
class P6HoldoutEvidence:
    baseline_error: int
    candidate_error: int
    improved: bool
    task_b_result_sha256: str


def parse_candidate(text: str) -> P6Candidate:
    """Accept only a small, canonical affine rule from the private model reply."""

    try:
        if type(text) is not str or len(text.encode("utf-8")) > _MAX_CANDIDATE_BYTES:
            raise ValueError
        value = json.loads(text)
        if type(value) is not dict or set(value) != {"multiplier", "offset"}:
            raise ValueError
        multiplier, offset = value["multiplier"], value["offset"]
        if any(
            type(part) is not int or abs(part) > _MAX_PARAMETER
            for part in (multiplier, offset)
        ):
            raise ValueError
        body = _canonical(value)
        return P6Candidate(multiplier, offset, body, sha256(body).hexdigest())
    except (TypeError, ValueError, UnicodeError):
        raise P6LiveTaskError() from None


def task_a_evidence(candidate: P6Candidate) -> str:
    """Digest actual candidate outputs on the visible training examples."""

    if type(candidate) is not P6Candidate:
        raise P6LiveTaskError()
    rows = [
        {"input": value, "expected": _target(value), "actual": candidate.predict(value)}
        for value in _TRAIN_INPUTS
    ]
    return sha256(_canonical(rows)).hexdigest()


def evaluate_holdout(candidate: P6Candidate) -> P6HoldoutEvidence:
    """Compare actual baseline and candidate results on untouched inputs."""

    if type(candidate) is not P6Candidate:
        raise P6LiveTaskError()
    rows = []
    baseline_error = candidate_error = 0
    for value in _HOLDOUT_INPUTS:
        expected = _target(value)
        baseline = _BASELINE_MULTIPLIER * value + _BASELINE_OFFSET
        actual = candidate.predict(value)
        baseline_error += abs(baseline - expected)
        candidate_error += abs(actual - expected)
        rows.append(
            {
                "input": value,
                "expected": expected,
                "baseline": baseline,
                "candidate": actual,
            }
        )
    return P6HoldoutEvidence(
        baseline_error=baseline_error,
        candidate_error=candidate_error,
        improved=candidate_error < baseline_error,
        task_b_result_sha256=sha256(
            _canonical({"candidate_body_sha256": candidate.body_sha256, "rows": rows})
        ).hexdigest(),
    )


__all__ = (
    "P6Candidate",
    "P6HoldoutEvidence",
    "P6LiveTaskError",
    "evaluate_holdout",
    "parse_candidate",
    "task_a_evidence",
)
