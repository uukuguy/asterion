"""Minimal provider used by the capability author template."""

from __future__ import annotations

from pathlib import Path

from asterion.capabilities.execution import CapabilityImplementationBinding
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_sdk import (
    BenchmarkTaskBinding,
    CapabilityExecutionResult,
    CapabilityInvocation,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
)


PACKAGE_REF = CapabilityPackageRef("example.package", "1.0.0")
SOURCE_ID = "example.local"


class ExampleResearch:
    """Minimal implementation placeholder for author conformance."""

    async def execute(
        self,
        invocation: CapabilityInvocation,
    ) -> CapabilityExecutionResult:
        del invocation
        return CapabilityExecutionResult(
            events=(
                {
                    "type": "research.completed",
                    "payload": {"status": "completed"},
                },
            ),
            artifacts=(
                {
                    "artifact_id": "example-research",
                    "media_type": "application/vnd.example.research+json",
                    "value": {"status": "completed"},
                },
            ),
        )


class ExampleBenchmark:
    """Opaque benchmark task placeholder."""


def create_provider() -> InstalledCapabilityPackage:
    """Return the exact package installed from this local source."""

    root = Path(__file__).resolve().parents[1]
    payload_root = root / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id=SOURCE_ID,
        source_kind="local-directory",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(
            payload_root / "benchmark-suites/example-benchmark.json",
        ),
        implementations=(
            CapabilityImplementationBinding(
                CapabilityRef("example.research", "1.0.0"),
                ExampleResearch(),
            ),
        ),
        benchmark_bindings=(
            BenchmarkTaskBinding(
                owner_package=PACKAGE_REF,
                binding_id="example.binding",
                implementation=ExampleBenchmark(),
            ),
        ),
    )
