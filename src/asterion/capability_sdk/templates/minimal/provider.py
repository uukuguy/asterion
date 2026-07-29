"""Asterion capability package provider template."""

from __future__ import annotations

from pathlib import Path

from asterion.capability_sdk import (
    BenchmarkTaskBinding,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
)
from asterion.capability_packages.payload import open_portable_payload


class ResearchImplementation:
    async def execute(self, invocation):
        raise NotImplementedError("replace the template implementation")


def create_package():
    payload_root = Path(__file__).resolve().parent / "payload"
    package_ref = CapabilityPackageRef("example.package", "1.0.0")
    payload = open_portable_payload(payload_root)
    implementation = ResearchImplementation()
    return InstalledCapabilityPackage(
        package_ref=package_ref,
        payload_sha256=payload.payload_sha256,
        source_id="example.package.local-directory",
        source_kind="local-directory",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(payload_root / "benchmark-suites",),
        implementations=(
            (CapabilityRef("example.research", "1.0.0"), implementation),
        ),
        benchmark_bindings=(
            BenchmarkTaskBinding(
                owner_package=package_ref,
                binding_id="example.task",
                implementation=implementation,
            ),
        ),
    )
