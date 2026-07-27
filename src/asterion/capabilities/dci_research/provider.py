"""Transitional explicit-local installed provider for the DCI package."""

from __future__ import annotations

from pathlib import Path

from asterion.capabilities.dci_research.bindings import complete_dci_bindings
from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilityPackageRef


PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")
SOURCE_ID = "dci.local"


def create_provider() -> InstalledCapabilityPackage:
    """Return the installed DCI package for an explicitly injected local source."""

    root = Path(__file__).resolve().parent
    payload_root = root / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id=SOURCE_ID,
        source_kind="local-directory",
        catalog_roots=((payload_root / "capabilities").resolve(strict=True),),
        benchmark_suite_paths=(),
        implementations=complete_dci_bindings(),
        benchmark_bindings=(),
    )
