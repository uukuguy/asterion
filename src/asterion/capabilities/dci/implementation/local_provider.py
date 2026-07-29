"""Explicit local-directory adapter for the package-owned DCI provider."""

from __future__ import annotations

from pathlib import Path

from asterion.capability_sdk import InstalledCapabilityPackage
from asterion.capabilities.dci.provider import (
    create_dci_package,
)


def create_package() -> InstalledCapabilityPackage:
    """Load the package-owned portable payload and exact DCI implementations."""

    return create_dci_package(
        payload_root=Path(__file__).resolve().parents[1] / "payload",
        source_id="dci.transitional-local",
        source_kind="local-directory",
    )


__all__ = ("create_package",)
