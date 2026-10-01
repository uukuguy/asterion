"""Provider-owned dispatcher for the source-independent Asterion-prime runtime."""

from __future__ import annotations

from asterion.runtime.factory import (
    RuntimeFactoryBinding,
    RuntimeFactoryContext,
    RuntimeFactoryError,
)
from asterion.runtime.host import AgentRuntimeClient


_ERROR = "Asterion-prime runtime configuration is invalid"


def asterion_prime_runtime_binding() -> RuntimeFactoryBinding:
    """Publish the native peer runtime only with this selected provider."""

    return RuntimeFactoryBinding(
        runtime_id="asterion.prime",
        capabilities=("prime.tool.ipython",),
        factory=build_asterion_prime_runtime,
    )


def build_p7_runtime(context: RuntimeFactoryContext) -> AgentRuntimeClient:
    """Compatibility wrapper that loads the selected P7 binding lazily."""

    from asterion.applications.prime.p7.runtime_binding import build_p7_runtime as build

    return build(context)


def build_p7_gameplay_runtime(context: RuntimeFactoryContext) -> AgentRuntimeClient:
    """Compatibility wrapper that loads the selected P7 binding lazily."""

    from asterion.applications.prime.p7.runtime_binding import (
        build_p7_gameplay_runtime as build,
    )

    return build(context)


def build_asterion_prime_runtime(
    context: RuntimeFactoryContext,
) -> AgentRuntimeClient:
    """Dispatch one runtime binding by exact native Prime application key."""

    if type(context) is not RuntimeFactoryContext:
        raise RuntimeFactoryError(_ERROR)
    key = (context.application_id, context.application_version)
    if key == ("prime.ipython-coding", "1.0.0"):
        from asterion.applications.prime.p1.runtime_binding import build_p1_runtime

        return build_p1_runtime(context)
    if key == ("prime.programmatic-long-context", "1.0.0"):
        from asterion.applications.prime.p2.runtime_binding import build_p2_runtime

        return build_p2_runtime(context)
    if key == ("prime.recursive-workflow", "1.0.0"):
        from asterion.applications.prime.p3.runtime_binding import build_p3_runtime

        return build_p3_runtime(context)
    if key == ("prime.long-session-continuity", "1.0.0"):
        from asterion.applications.prime.p4.runtime_binding import build_p4_runtime

        return build_p4_runtime(context)
    if key == ("prime.bounded-autonomy", "1.0.0"):
        from asterion.applications.prime.p5.runtime_binding import build_p5_runtime

        return build_p5_runtime(context)
    if key == ("prime.continual-improvement", "1.0.0"):
        from asterion.applications.prime.p6.runtime_binding import build_p6_runtime

        return build_p6_runtime(context)
    if key == ("prime.arc-agi-3-solving", "1.0.0"):
        return build_p7_runtime(context)
    if key == ("prime.arc-agi-3-gameplay", "1.0.0"):
        return build_p7_gameplay_runtime(context)
    raise RuntimeFactoryError(_ERROR)


def __getattr__(name: str) -> object:
    """Preserve legacy P7 symbol imports without eager product imports."""

    if name in {
        "PrimeLaunch",
        "_P7SolveEventProjector",
        "_p7_continuation_prompt",
        "_p7_gameplay_terminal",
        "_p7_terminal",
        "_GAMEPLAY_OPTIONS",
        "_HOST_CAPABILITIES",
        "_GAMEPLAY_HOST_CAPABILITIES",
    }:
        from asterion.applications.prime.p7 import runtime_binding as p7_binding

        return getattr(p7_binding, name)
    raise AttributeError(name)


__all__ = (
    "asterion_prime_runtime_binding",
    "build_asterion_prime_runtime",
    "build_p7_runtime",
    "build_p7_gameplay_runtime",
)
