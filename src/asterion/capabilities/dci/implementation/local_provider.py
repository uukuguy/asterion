"""Explicit local-directory provider factory for the package-owned DCI implementation."""

from __future__ import annotations

import json
from pathlib import Path

from asterion.capability_sdk import (
    CapabilityImplementationBinding,
    CapabilityImplementation,
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
SOURCE_ID = "dci.transitional-local"
SOURCE_KIND = "local-directory"


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


def create_package() -> InstalledCapabilityPackage:
    """Load the package-owned portable payload and exact DCI implementations."""

    package_root = Path(__file__).resolve().parents[1]
    payload_root = package_root / "payload"
    payload = open_portable_payload(payload_root)
    bindings: tuple[tuple[CapabilityRef, CapabilityImplementation], ...] = (
        *complete_dci_bindings(),
        (
            CapabilityRef("dci.research", "1.0.0"),
            TransitionalDciResearchImplementation(),
        ),
    )
    implementations = tuple(
        CapabilityImplementationBinding(ref, implementation)
        for ref, implementation in sorted(dict(bindings).items())
    )
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id=SOURCE_ID,
        source_kind=SOURCE_KIND,
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(payload_root / "benchmark-suites",),
        implementations=implementations,
        benchmark_bindings=create_benchmark_bindings(),
    )


__all__ = ("create_package",)
