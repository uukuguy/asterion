"""Strict, canonical completion protocol for the fixed P6 continual harness."""

from __future__ import annotations

from dataclasses import dataclass
import json

from asterion.applications.prime_agent.continual_improvement_receipt import (
    ContinualImprovementReceiptError,
    ContinualImprovementTrace,
    validate_continual_improvement_trace,
)


class ContinualImprovementCompletionError(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class ContinualImprovementCompletion:
    trace: ContinualImprovementTrace

    def __repr__(self) -> str:
        return "ContinualImprovementCompletion(redacted)"


_FIELDS = frozenset({"format", *ContinualImprovementTrace.__dataclass_fields__})


def parse_continual_improvement_completion(
    payload: object,
) -> ContinualImprovementCompletion:
    try:
        if (
            type(payload) is not dict
            or frozenset(payload) != _FIELDS
            or payload["format"] != "asterion.prime-continual-improvement/v1"
            or type(payload["tool_names"]) is not list
            or payload["tool_names"] != ["ipython"]
        ):
            raise ValueError
        values = {key: value for key, value in payload.items() if key != "format"}
        values["tool_names"] = ("ipython",)
        trace = ContinualImprovementTrace(**values)
        validate_continual_improvement_trace(trace)
        return ContinualImprovementCompletion(trace)
    except (KeyError, TypeError, ValueError, ContinualImprovementReceiptError):
        raise ContinualImprovementCompletionError(
            "continual improvement completion is invalid"
        ) from None


def canonical_continual_improvement_completion_bytes(
    completion: ContinualImprovementCompletion,
) -> bytes:
    if type(completion) is not ContinualImprovementCompletion:
        raise ContinualImprovementCompletionError(
            "continual improvement completion is invalid"
        )
    try:
        validate_continual_improvement_trace(completion.trace)
    except ContinualImprovementReceiptError:
        raise ContinualImprovementCompletionError(
            "continual improvement completion is invalid"
        ) from None
    payload: dict[str, object] = {
        "format": "asterion.prime-continual-improvement/v1"
    }
    payload.update(vars(completion.trace))
    payload["tool_names"] = list(completion.trace.tool_names)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
