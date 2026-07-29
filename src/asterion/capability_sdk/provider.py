"""Public capability provider protocols."""

from __future__ import annotations

from typing import Protocol

from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.runtime.host import CancellationSignal


class HostServices(Protocol):
    def get(self, key: str, default: object | None = None) -> object | None: ...


class CapabilityPackageProvider(Protocol):
    def load_package(self) -> InstalledCapabilityPackage: ...


__all__ = (
    "CapabilityPackageProvider",
    "CancellationSignal",
    "HostServices",
)
