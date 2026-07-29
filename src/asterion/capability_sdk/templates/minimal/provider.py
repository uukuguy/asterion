"""Asterion capability package provider template."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from asterion.capability_sdk import (
    BenchmarkTaskBinding,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
)


PAYLOAD_SHA256 = "67df2a468e5923ee9f68f108b4955412c21813831552378125695cd38ffd53a2"


class ResearchImplementation:
    async def execute(self, invocation):
        raise NotImplementedError("replace the template implementation")


def create_package():
    payload_root = Path(__file__).resolve().parent / "payload"
    package_ref = CapabilityPackageRef("example.package", "1.0.0")
    implementation = ResearchImplementation()
    return InstalledCapabilityPackage(
        package_ref=package_ref,
        payload_sha256=PAYLOAD_SHA256,
        source_id="example.package.local-directory",
        source_kind="local-directory",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(payload_root / "benchmark-suites",),
        implementations=cast(
            Any,
            (
                (CapabilityRef("example.research", "1.0.0"), implementation),
            ),
        ),
        benchmark_bindings=(
            BenchmarkTaskBinding(
                owner_package=package_ref,
                binding_id="example.task",
                implementation=implementation,
            ),
        ),
    )
