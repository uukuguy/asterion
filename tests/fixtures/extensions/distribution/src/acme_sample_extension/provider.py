"""Provider factory for the installed capability package fixture."""

from __future__ import annotations

import os
from importlib import metadata
from pathlib import Path

from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilityPackageRef


if os.environ.get("ASTERION_TEST_FORBID_PROVIDER_IMPORT") == "1":
    raise RuntimeError("provider imported during metadata discovery")


PACKAGE_REF = CapabilityPackageRef("acme.sample", "1.0.0")
SOURCE_ID = "acme.sample.python-distribution"
SOURCE_KIND = "python-distribution"
PAYLOAD_RELATIVE_ROOT = "asterion_capability_packages/acme.sample/1.0.0/payload"


def create_package() -> InstalledCapabilityPackage:
    distribution = metadata.distribution("asterion-acme-sample-extension")
    payload_root = Path(str(distribution.locate_file(PAYLOAD_RELATIVE_ROOT)))
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
