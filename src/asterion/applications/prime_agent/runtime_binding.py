"""Prime provider-owned runtime factory binding and application routes."""

from __future__ import annotations

from asterion.runtime.factory import (
    RuntimeFactoryBinding,
    RuntimeFactoryContext,
    RuntimeFactoryError,
)
from asterion.runtimes.prime_agent import (
    PRIME_IPYTHON_CAPABILITY,
    PRIME_RUNTIME_ID,
    PrimeAgentRuntimeClient,
    PrimeVerificationProfile,
)
from asterion.runtimes.prime_agent_host import PrimeSmallVerificationService


_ROUTES = {
    "prime.ipython-coding": (
        "prime.ipython-production",
        PrimeVerificationProfile(
            "p1-b-development",
            "prime.p1-b-development.trace",
            "p1-b-development",
            "application/vnd.asterion.prime.p1-development-trace+json",
        ),
    ),
    "prime.programmatic-long-context": (
        "prime.programmatic-long-context-development",
        PrimeVerificationProfile(
            "p2-development",
            "prime.p2-development.trace",
            "p2-development",
            "application/vnd.asterion.prime.p2-development-trace+json",
        ),
    ),
    "prime.recursive-workflow": (
        "prime.recursive-workflow-development",
        PrimeVerificationProfile(
            "p3-development",
            "prime.p3-development.trace",
            "p3-development",
            "application/vnd.asterion.prime.p3-development-trace+json",
        ),
    ),
    "prime.long-session-continuity": (
        "prime.long-session-continuity-development",
        PrimeVerificationProfile(
            "p4-development",
            "prime.p4-development.trace",
            "p4-development",
            "application/vnd.asterion.prime.p4-development-trace+json",
        ),
    ),
    "prime.bounded-autonomy": (
        "prime.bounded-autonomy-development",
        PrimeVerificationProfile(
            "p5-development",
            "prime.p5-development.trace",
            "p5-development",
            "application/vnd.asterion.prime.p5-development-trace+json",
        ),
    ),
    "prime.continual-improvement": (
        "prime.continual-improvement-development",
        PrimeVerificationProfile(
            "p6-development",
            "prime.p6-development.trace",
            "p6-development",
            "application/vnd.asterion.prime.p6-development-trace+json",
        ),
    ),
    "prime.arc-agi-3": (
        "prime.arc-agi-3-development",
        PrimeVerificationProfile(
            "p7-development",
            "prime.p7-development.trace",
            "p7-development",
            "application/vnd.asterion.prime.p7-development-trace+json",
        ),
    ),
}


def prime_runtime_binding() -> RuntimeFactoryBinding:
    return RuntimeFactoryBinding(PRIME_RUNTIME_ID, (PRIME_IPYTHON_CAPABILITY,), _create)


def prime_profile_for_application(application_id: str) -> PrimeVerificationProfile:
    try:
        return _ROUTES[application_id][1]
    except KeyError:
        raise RuntimeFactoryError("Prime runtime configuration is invalid") from None


def _create(context: RuntimeFactoryContext) -> PrimeAgentRuntimeClient:
    if (
        context.provider_id != "prime-agent"
        or context.application_version != "1.0.0"
        or context.runtime_id != PRIME_RUNTIME_ID
        or context.options
    ):
        raise RuntimeFactoryError("Prime runtime configuration is invalid")
    try:
        host_key, profile = _ROUTES[context.application_id]
    except KeyError:
        raise RuntimeFactoryError("Prime runtime configuration is invalid") from None
    if set(context.host_services) != {host_key} or not isinstance(
        context.host_services[host_key], PrimeSmallVerificationService
    ):
        raise RuntimeFactoryError("Prime runtime configuration is invalid")
    return PrimeAgentRuntimeClient(context.host_services[host_key], profile=profile)
