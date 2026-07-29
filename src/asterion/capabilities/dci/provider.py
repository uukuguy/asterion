"""Selected-provider factory for the package-owned DCI implementation."""

from __future__ import annotations

import json
from pathlib import Path

from asterion.capability_sdk import (
    CapabilityExecutionResult,
    CapabilityImplementation,
    CapabilityImplementationBinding,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
    open_portable_payload,
)
from asterion.capabilities.dci.implementation.benchmark_bindings import (
    create_benchmark_bindings,
)
from asterion.capabilities.dci.implementation.complete import (
    INPUT_PROTOCOL,
    DciCompleteResearchImplementation,
    complete_dci_bindings,
)
from asterion.capabilities.dci.implementation.implementation import (
    DciLocalResearchImplementation,
)


PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")


class TransitionalDciResearchImplementation:
    """Select the local or complete DCI research contract by exact input."""

    def __init__(self) -> None:
        self._local = DciLocalResearchImplementation()
        self._complete = DciCompleteResearchImplementation()

    async def execute(self, invocation):
        try:
            value = json.loads(invocation.input_text)
        except ValueError:
            value = None
        if isinstance(value, dict) and value.get("protocol") == INPUT_PROTOCOL:
            return await self._complete.execute(invocation)
        return await self._local.execute(invocation)


class DciProtocolObservabilityImplementation:
    """Emit the package-declared body-free protocol observation."""

    async def execute(self, invocation) -> CapabilityExecutionResult:
        del invocation
        return CapabilityExecutionResult(
            events=(
                {
                    "type": "audit.capability-observed",
                    "payload": {"observed": True},
                },
            ),
            artifacts=(),
        )


def create_dci_package(
    *,
    payload_root: Path,
    source_id: str,
    source_kind: str,
) -> InstalledCapabilityPackage:
    """Create one source-neutral installed DCI package over an exact payload."""

    payload = open_portable_payload(payload_root)
    bindings: tuple[tuple[CapabilityRef, CapabilityImplementation], ...] = (
        *complete_dci_bindings(),
        (
            CapabilityRef("dci.research", "1.0.0"),
            TransitionalDciResearchImplementation(),
        ),
        (
            CapabilityRef("protocol.observability", "1.0.0"),
            DciProtocolObservabilityImplementation(),
        ),
    )
    implementations = tuple(
        CapabilityImplementationBinding(ref, implementation)
        for ref, implementation in sorted(dict(bindings).items())
    )
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id=source_id,
        source_kind=source_kind,
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(payload_root / "benchmark-suites",),
        implementations=implementations,
        benchmark_bindings=create_benchmark_bindings(),
    )


def create_provider() -> InstalledCapabilityPackage:
    """Load the DCI built-in only after its exact source has been selected."""

    return create_dci_package(
        payload_root=Path(__file__).resolve().parent / "payload",
        source_id="dci.builtin",
        source_kind="builtin",
    )


__all__ = ("create_dci_package", "create_provider")
