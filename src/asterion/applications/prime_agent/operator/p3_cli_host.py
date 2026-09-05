"""Private P3 CLI host projection."""

from __future__ import annotations
from .p3_development_host import PrimeP3DevelopmentTrace
from .p3_development_host import run_prime_p3_development


def project_p3_development_trace(trace: object) -> dict[str, str]:
    if type(trace) is not PrimeP3DevelopmentTrace:
        raise ValueError("prime P3 development host is unavailable")
    return {
        "scope": trace.scope,
        "promotion": trace.promotion,
        "trace_sha256": trace.trace_sha256,
    }


async def run_p3_cli(
    *,
    application_id: object,
    capability_id: object,
    preset: object,
    gateway: object,
    service: object,
    run_id: object,
    session_id: object,
) -> dict[str, str]:
    if (application_id, capability_id, preset) != (
        "prime.recursive-workflow@1.0.0",
        "prime.recursive-workflow@1.0.0",
        "fixed-small-verification",
    ):
        raise ValueError("prime P3 development host is unavailable")
    trace = await run_prime_p3_development(
        gateway=gateway,
        service=service,
        run_id=run_id,
        session_id=session_id,
        prompt="fixed-small-verification",
    )
    return project_p3_development_trace(trace)
