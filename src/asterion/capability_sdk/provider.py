"""Stable provider-side contracts for capability packages."""

from __future__ import annotations

from collections.abc import Mapping as _Mapping
from typing import Protocol as _Protocol
from typing import runtime_checkable as _runtime_checkable

from asterion.capability_packages.model import (
    InstalledCapabilityPackage as _InstalledCapabilityPackage,
)


@_runtime_checkable
class CapabilityPackageProvider(_Protocol):
    """A selected entry-point factory for one installed capability package."""

    def __call__(self) -> _InstalledCapabilityPackage: ...


class HostServices(_Mapping[str, object]):
    """Read-only package view of operator-injected host services."""
