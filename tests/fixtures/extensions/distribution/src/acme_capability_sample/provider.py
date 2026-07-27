"""Selected-only fixture provider for distribution-source tests."""

from __future__ import annotations

import os
from dataclasses import replace
from importlib import metadata
from pathlib import Path

if os.environ.get("ASTERION_TEST_FORBID_PROVIDER_IMPORT") == "1":
    raise RuntimeError("provider imported during metadata discovery")

from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilityPackageRef


PACKAGE_REF = CapabilityPackageRef("acme.sample", "1.0.0")
PAYLOAD_ROOT = "asterion_capability_packages/acme.sample@1.0.0"
SOURCE_ID = "python-distribution:acme-capability-sample@1.0.0:acme.sample@1.0.0"


def create_package() -> InstalledCapabilityPackage:
    """Build the selected fixture provider result."""

    distribution = metadata.distribution("acme-capability-sample")
    root = Path(distribution.locate_file(PAYLOAD_ROOT)).resolve(strict=True)
    payload = open_portable_payload(root)
    installed = InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id=SOURCE_ID,
        source_kind="python-distribution",
        catalog_roots=(root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=(),
        benchmark_bindings=(),
    )
    mismatch = os.environ.get("ASTERION_TEST_PROVIDER_IDENTITY_MISMATCH")
    if mismatch == "package":
        return replace(
            installed,
            package_ref=CapabilityPackageRef("other.sample", "1.0.0"),
        )
    if mismatch == "payload":
        return replace(installed, payload_sha256="0" * 64)
    if mismatch == "source":
        return replace(installed, source_kind="builtin")
    if mismatch == "source-id":
        return replace(installed, source_id="python-distribution:other")
    return installed
