"""Strict, canonical completion protocol for the fixed P7 one-game subset."""

from __future__ import annotations

from dataclasses import dataclass
import json

from asterion.applications.prime_agent.arc_agi_3_receipt import (
    ArcAgi3ReceiptError,
    ArcAgi3Trace,
    validate_arc_agi_3_trace,
)


class ArcAgi3CompletionError(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class ArcAgi3Completion:
    trace: ArcAgi3Trace

    def __repr__(self) -> str:
        return "ArcAgi3Completion(redacted)"


_FIELDS = frozenset({"format", *ArcAgi3Trace.__dataclass_fields__})


def parse_arc_agi_3_completion(payload: object) -> ArcAgi3Completion:
    try:
        if (
            type(payload) is not dict
            or frozenset(payload) != _FIELDS
            or payload["format"] != "asterion.prime-arc-agi-3/v1"
            or type(payload["tool_names"]) is not list
            or payload["tool_names"] != ["ipython"]
        ):
            raise ValueError
        values = {key: value for key, value in payload.items() if key != "format"}
        values["tool_names"] = ("ipython",)
        trace = ArcAgi3Trace(**values)
        validate_arc_agi_3_trace(trace)
        return ArcAgi3Completion(trace)
    except (KeyError, TypeError, ValueError, ArcAgi3ReceiptError):
        raise ArcAgi3CompletionError("ARC-AGI-3 completion is invalid") from None


def canonical_arc_agi_3_completion_bytes(completion: ArcAgi3Completion) -> bytes:
    if type(completion) is not ArcAgi3Completion:
        raise ArcAgi3CompletionError("ARC-AGI-3 completion is invalid")
    try:
        validate_arc_agi_3_trace(completion.trace)
    except ArcAgi3ReceiptError:
        raise ArcAgi3CompletionError("ARC-AGI-3 completion is invalid") from None
    payload: dict[str, object] = {"format": "asterion.prime-arc-agi-3/v1"}
    payload.update(vars(completion.trace))
    payload["tool_names"] = list(completion.trace.tool_names)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
