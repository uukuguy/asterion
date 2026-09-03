"""Redacted, one-game transcript validation for the P7 host broker."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Literal, cast


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_METHODS = frozenset({"observe", "act", "status"})


class ArcAgi3BrokerError(ValueError):
    """Raised without revealing game or action content."""


@dataclass(frozen=True, repr=False)
class ArcAgi3BrokerCall:
    method: Literal["observe", "act", "status"]
    sequence: int
    request_sha256: str | None
    response_sha256: str
    terminal_after: bool

    def __repr__(self) -> str:
        return "ArcAgi3BrokerCall(redacted)"


def validate_arc_agi_3_broker_calls(calls: object) -> None:
    """Validate a contiguous one-game broker transcript ending at status."""

    try:
        if type(calls) is not tuple or not calls:
            raise ValueError
        for expected, call in enumerate(calls, start=1):
            if (
                type(call) is not ArcAgi3BrokerCall
                or call.method not in _METHODS
                or type(call.sequence) is not int or call.sequence != expected
                or call.request_sha256 is not None and (
                    type(call.request_sha256) is not str
                    or _DIGEST.fullmatch(call.request_sha256) is None
                )
                or type(call.response_sha256) is not str
                or _DIGEST.fullmatch(call.response_sha256) is None
                or type(call.terminal_after) is not bool
                or call.method in {"observe", "status"} and call.request_sha256 is not None
                or call.method == "act" and call.request_sha256 is None
                or call.terminal_after and (
                    call.method != "status" or expected != len(calls)
                )
            ):
                raise ValueError
        if (
            calls[0].method != "observe"
            or calls[-1].method != "status"
            or calls[-1].terminal_after is not True
            or not any(call.method == "act" for call in calls)
        ):
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise ArcAgi3BrokerError("ARC-AGI-3 broker transcript is invalid") from None


def arc_agi_3_action_chain_sha256(calls: object) -> str:
    """Return the canonical redacted action-chain identity."""

    validate_arc_agi_3_broker_calls(calls)
    typed_calls = cast(tuple[ArcAgi3BrokerCall, ...], calls)
    return "sha256:" + sha256(json.dumps([
        {"request_sha256": call.request_sha256, "response_sha256": call.response_sha256,
         "sequence": call.sequence} for call in typed_calls if call.method == "act"
    ], sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
