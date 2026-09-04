"""Exact installed package binding for Prime's P1 coding capability."""

from __future__ import annotations

from pathlib import Path

from asterion.capability_sdk import (
    CapabilityExecutionError,
    CapabilityExecutionResult,
    CapabilityImplementationBinding,
    CapabilityInvocation,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
    open_portable_payload,
)
from asterion.runtime.host import RunRequest


PACKAGE_REF = CapabilityPackageRef("prime-agent", "1.0.0")
CAPABILITY_REF = CapabilityRef("prime.ipython-coding", "1.0.0")


class PrimeIpythonCodingImplementation:
    """Frame-only P1 bridge; the application supplies the real worker later."""

    async def execute(self, invocation: CapabilityInvocation) -> CapabilityExecutionResult:
        if invocation.runtime.manifest.runtime_id != "prime.agent" or (
            invocation.runtime.manifest.capabilities != ("prime.tool.ipython",)
        ):
            raise CapabilityExecutionError("Prime runtime is unavailable")
        events = [
            event
            async for event in invocation.runtime.run(
                RunRequest(
                    run_id=invocation.run_id,
                    input_text=invocation.input_text,
                    requested_capabilities=("prime.tool.ipython",),
                ),
                signal=invocation.signal,
            )
        ]
        if events[-1].type != "run.completed":
            raise CapabilityExecutionError("Prime runtime did not complete")
        return CapabilityExecutionResult(events=(), artifacts=())


def create_prime_agent_package() -> InstalledCapabilityPackage:
    """Load the exact local Prime package payload and its one implementation."""

    payload_root = Path(__file__).resolve().parent / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id="prime-agent.builtin",
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=(
            CapabilityImplementationBinding(CAPABILITY_REF, PrimeIpythonCodingImplementation()),
        ),
        benchmark_bindings=(),
    )


__all__ = ("create_prime_agent_package",)
