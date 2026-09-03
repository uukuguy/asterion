"""Provider-free acceptance boundary for the fixed P5 loop."""

from __future__ import annotations

from asterion.applications.prime_agent.bounded_autonomy_receipt import (
    BoundedAutonomyTrace,
    validate_bounded_autonomy_trace,
)
from asterion.applications.prime_agent.bounded_autonomy_gate import (
    run_bounded_autonomy_gate,
)
from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel,
    PrimeEvidenceReceipt,
    validate_prime_evidence_receipt,
)


class BoundedAutonomyAcceptanceError(ValueError):
    """Raised without exposing gate, workspace, or trace contents."""


async def accept_bounded_autonomy(
    *, gate: object, first_workspace: object, second_workspace: object,
    trace: object, disposed: object, reaped: object,
) -> PrimeEvidenceReceipt:
    """Validate only a complete fake P5 chain and emit provider-free evidence."""

    try:
        if (
            type(trace) is not BoundedAutonomyTrace
            or disposed is not True
            or reaped is not True
        ):
            raise ValueError
        validate_bounded_autonomy_trace(trace)
        first = await run_bounded_autonomy_gate(gate, first_workspace, frozenset())
        second = await run_bounded_autonomy_gate(gate, second_workspace, frozenset({first_workspace}))
        if (
            first.workspace_sha256 != trace.initial_workspace_sha256
            or second.workspace_sha256 != trace.repaired_workspace_sha256
            or first.passed is not False
            or second.passed is not True
            or second.result_sha256 != trace.gate_result_sha256
        ):
            raise ValueError
        return validate_prime_evidence_receipt(PrimeEvidenceReceipt(
            "prime.bounded-autonomy/v1", PrimeEvidenceLevel.PROVIDER_FREE, "PASS"
        ))
    except (TypeError, ValueError):
        raise BoundedAutonomyAcceptanceError("bounded autonomy acceptance is invalid") from None
