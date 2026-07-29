"""Explicit local-directory provider factory for transitional DCI wiring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from asterion.capability_sdk import (
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
)
from asterion.capabilities.dci_research import DciLocalResearchImplementation
from asterion.capabilities.dci_research.complete import (
    INPUT_PROTOCOL,
    DciCompleteResearchImplementation,
    complete_dci_bindings,
)
from asterion.capabilities.dci_research._payload import (
    payload_sha256,
)


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
    bindings: tuple[tuple[CapabilityRef, object], ...] = (
        *complete_dci_bindings(),
        (
            CapabilityRef("dci.research", "1.0.0"),
            TransitionalDciResearchImplementation(),
        ),
    )
    deduped: dict[CapabilityRef, object] = dict(bindings)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload_sha256(payload_root),
        source_id=SOURCE_ID,
        source_kind=SOURCE_KIND,
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(payload_root / "benchmark-suites",),
        implementations=cast(Any, tuple(sorted(deduped.items()))),
        benchmark_bindings=(),
    )


__all__ = ("create_package",)
