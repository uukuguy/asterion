"""Selected-only fixture provider for explicit local-source tests."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

if os.environ.get("ASTERION_TEST_FORBID_LOCAL_PROVIDER_IMPORT") == "1":
    raise RuntimeError("local provider imported during metadata discovery")

from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilityPackageRef


PACKAGE_REF = CapabilityPackageRef("example.package", "1.0.0")
SOURCE_ID = "example.local"


def create_provider() -> InstalledCapabilityPackage:
    """Build the selected fixture provider result."""

    if os.environ.get("ASTERION_TEST_LOCAL_FACTORY_FAILURE") == "1":
        raise RuntimeError("SENTINEL_LOCAL_FACTORY_FAILURE")
    root = Path(__file__).resolve().parents[1]
    payload_root = root / "payload"
    payload = open_portable_payload(payload_root)
    installed = InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id=SOURCE_ID,
        source_kind="local-directory",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(
            payload_root / "benchmark-suites/example-benchmark.json",
        ),
        implementations=(),
        benchmark_bindings=(),
    )
    mismatch = os.environ.get("ASTERION_TEST_LOCAL_IDENTITY_MISMATCH")
    if mismatch == "package":
        return replace(
            installed,
            package_ref=CapabilityPackageRef("other.package", "1.0.0"),
        )
    if mismatch == "payload":
        return replace(installed, payload_sha256="0" * 64)
    if mismatch == "source":
        return replace(installed, source_kind="builtin")
    if mismatch == "source-id":
        return replace(installed, source_id="other.local")
    return installed
