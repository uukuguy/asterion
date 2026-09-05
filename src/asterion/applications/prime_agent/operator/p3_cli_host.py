"""Private P3 CLI host projection."""
from __future__ import annotations
from .p3_development_host import PrimeP3DevelopmentTrace
def project_p3_development_trace(trace: object) -> dict[str, str]:
    if type(trace) is not PrimeP3DevelopmentTrace:
        raise ValueError("prime P3 development host is unavailable")
    return {"scope": trace.scope, "promotion": trace.promotion, "trace_sha256": trace.trace_sha256}
