"""Provider-free P7 acceptance over an injected host-owned broker."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from asterion.applications.prime_agent.arc_agi_3_broker import (
    ArcAgi3BrokerCall,
    arc_agi_3_action_chain_sha256,
    validate_arc_agi_3_broker_calls,
)
from asterion.applications.prime_agent.arc_agi_3_receipt import (
    ArcAgi3Trace,
    validate_arc_agi_3_trace,
)
from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel, PrimeEvidenceReceipt, validate_prime_evidence_receipt,
)


class ArcAgi3AcceptanceError(ValueError):
    """Raised without disclosing private game data."""


async def accept_arc_agi_3(
    *, broker: object, trace: object, disposed: object, reaped: object
) -> PrimeEvidenceReceipt:
    """Accept one exact provider-free single-game causal chain."""

    try:
        if type(trace) is not ArcAgi3Trace or disposed is not True or reaped is not True:
            raise ValueError
        validate_arc_agi_3_trace(trace)
        calls = getattr(broker, "calls", None)
        replay_score = getattr(broker, "replay_score", None)
        if not callable(calls) or not callable(replay_score):
            raise ValueError
        transcript = await cast(Callable[[], Awaitable[object]], calls)()
        validate_arc_agi_3_broker_calls(transcript)
        typed_transcript = cast(tuple[ArcAgi3BrokerCall, ...], transcript)
        if (
            len(typed_transcript) != trace.broker_call_count
            or typed_transcript[0].response_sha256 != trace.initial_observation_sha256
            or typed_transcript[-1].response_sha256 != trace.terminal_status_sha256
            or arc_agi_3_action_chain_sha256(typed_transcript) != trace.action_chain_sha256
            or sum(call.method == "observe" for call in typed_transcript) != trace.observation_count
            or sum(call.method == "act" for call in typed_transcript) != trace.action_count
            or sum(call.method == "status" for call in typed_transcript) != trace.status_count
        ):
            raise ValueError
        score = await cast(Callable[[str], Awaitable[object]], replay_score)(trace.action_chain_sha256)
        if type(score) is not str or score != trace.score_sha256:
            raise ValueError
        return validate_prime_evidence_receipt(PrimeEvidenceReceipt(
            "prime.arc-agi-3/v1", PrimeEvidenceLevel.PROVIDER_FREE, "PASS"
        ))
    except Exception:
        raise ArcAgi3AcceptanceError("ARC-AGI-3 acceptance is invalid") from None
