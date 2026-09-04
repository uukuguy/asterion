"""Strict, canonical completion protocol for the fixed P5 repair loop."""

from __future__ import annotations

from dataclasses import dataclass
import json

from asterion.applications.prime_agent.bounded_autonomy_receipt import (
    BoundedAutonomyReceiptError,
    BoundedAutonomyTrace,
    validate_bounded_autonomy_trace,
)


class BoundedAutonomyCompletionError(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class BoundedAutonomyCompletion:
    trace: BoundedAutonomyTrace

    def __repr__(self) -> str:
        return "BoundedAutonomyCompletion(redacted)"


_FIELDS = frozenset({"format", *BoundedAutonomyTrace.__dataclass_fields__})


def parse_bounded_autonomy_completion(payload: object) -> BoundedAutonomyCompletion:
    try:
        if (
            type(payload) is not dict
            or frozenset(payload) != _FIELDS
            or payload["format"] != "asterion.prime-bounded-autonomy/v1"
            or type(payload["tool_names"]) is not list
            or payload["tool_names"] != ["ipython"]
        ):
            raise ValueError
        values = {key: value for key, value in payload.items() if key != "format"}
        values["tool_names"] = ("ipython",)
        trace = BoundedAutonomyTrace(**values)
        validate_bounded_autonomy_trace(trace)
        return BoundedAutonomyCompletion(trace)
    except (KeyError, TypeError, ValueError, BoundedAutonomyReceiptError):
        raise BoundedAutonomyCompletionError(
            "bounded autonomy completion is invalid"
        ) from None


def canonical_bounded_autonomy_completion_bytes(
    completion: BoundedAutonomyCompletion,
) -> bytes:
    if type(completion) is not BoundedAutonomyCompletion:
        raise BoundedAutonomyCompletionError("bounded autonomy completion is invalid")
    payload: dict[str, object] = {"format": "asterion.prime-bounded-autonomy/v1"}
    payload.update(vars(completion.trace))
    payload["tool_names"] = list(completion.trace.tool_names)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
