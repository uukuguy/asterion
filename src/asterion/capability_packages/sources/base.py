"""Base protocol for source-neutral capability-package adapters."""

from __future__ import annotations

from typing import Protocol

from asterion.capability_packages.model import (
    CapabilityPackageCandidate,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)


class CapabilityPackageSource(Protocol):
    def discover_metadata(self) -> tuple[CapabilityPackageCandidate, ...]: ...

    def open_payload(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> PortableCapabilityPayload: ...

    def validate_source_identity(
        self,
        candidate: CapabilityPackageCandidate,
        payload: PortableCapabilityPayload,
    ) -> None: ...

    def load_provider(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> InstalledCapabilityPackage: ...


__all__ = ("CapabilityPackageSource",)
