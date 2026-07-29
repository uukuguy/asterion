"""Explicit local-directory provider factory for transitional DCI wiring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.dci_research import DciLocalResearchImplementation
from asterion.capabilities.dci_research.complete import (
    INPUT_PROTOCOL,
    DciCompleteResearchImplementation,
    complete_dci_bindings,
)
from asterion.capabilities.execution import (
    CapabilityImplementation,
    CapabilityImplementationBinding,
)
from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilityPackageRef


PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")
SOURCE_ID = "dci.transitional-local"
SOURCE_KIND = "local-directory"


class TransitionalDciResearchImplementation:
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
    root = Path(__file__).resolve().parent
    payload_root = root / "payload"
    payload = open_portable_payload(payload_root)
    bindings: tuple[tuple[CapabilityRef, CapabilityImplementation], ...] = (
        *cast(
            tuple[tuple[CapabilityRef, CapabilityImplementation], ...],
            complete_dci_bindings(),
        ),
        (
            CapabilityRef("dci.research", "1.0.0"),
            cast(CapabilityImplementation, TransitionalDciResearchImplementation()),
        ),
    )
    deduped: dict[CapabilityRef, CapabilityImplementation] = dict(bindings)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id=SOURCE_ID,
        source_kind=SOURCE_KIND,
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(payload_root / "benchmark-suites",),
        implementations=tuple(
            CapabilityImplementationBinding(ref, implementation)
            for ref, implementation in sorted(deduped.items())
        ),
        benchmark_bindings=(),
    )


__all__ = ("create_package",)
