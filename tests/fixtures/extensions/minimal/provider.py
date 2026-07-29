"""Provider factory for the explicit local-directory source fixture."""

from __future__ import annotations

import os
from pathlib import Path

from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilityPackageRef


if os.environ.get("ASTERION_TEST_FORBID_PROVIDER_IMPORT") == "1":
    raise RuntimeError("provider imported during local metadata discovery")


PACKAGE_REF = CapabilityPackageRef("example.package", "1.0.0")
SOURCE_ID = "example.package.local-directory"
SOURCE_KIND = "local-directory"


def create_package() -> InstalledCapabilityPackage:
    payload_root = Path(__file__).resolve().parent / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id=SOURCE_ID,
        source_kind=SOURCE_KIND,
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(payload_root / "benchmark-suites",),
        implementations=(),
        benchmark_bindings=(),
    )
