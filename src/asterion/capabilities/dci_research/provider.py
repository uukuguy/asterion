"""Transitional explicit-local installed provider for the DCI package."""

from __future__ import annotations

from dataclasses import replace

from asterion.capabilities.dci.implementation.bindings import complete_dci_bindings
from asterion.capabilities.dci.provider import create_provider as create_dci_provider
from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.capability_packages.protocol import CapabilityPackageRef


PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")
SOURCE_ID = "dci.local"


def create_provider() -> InstalledCapabilityPackage:
    """Return the installed DCI package for an explicitly injected local source."""

    return replace(
        create_dci_provider(),
        source_id=SOURCE_ID,
        source_kind="local-directory",
        implementations=complete_dci_bindings(),
        benchmark_bindings=(),
    )
