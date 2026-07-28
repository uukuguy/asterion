"""Selected-only DCI fixture provider for distribution-source tests."""

from __future__ import annotations

import json
import os
from importlib import metadata
from pathlib import Path

if os.environ.get("ASTERION_TEST_FORBID_PROVIDER_IMPORT") == "1":
    raise RuntimeError("provider imported during metadata discovery")

from asterion.capability_sdk import (
    BenchmarkTaskBinding,
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
    CapabilityImplementationBinding,
    CapabilityExecutionResult,
    CapabilityInvocation,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
    open_portable_payload,
)


PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")
PAYLOAD_ROOT = "asterion_capability_packages/dci@1.0.0"
SOURCE_ID = "python-distribution:asterion-dci-extension@1.0.0:dci@1.0.0"


if os.environ.get("ASTERION_DCI_EXTENSION_IMPORT_COUNT_FILE"):
    _count_path = Path(os.environ["ASTERION_DCI_EXTENSION_IMPORT_COUNT_FILE"])
    try:
        _count = int(_count_path.read_text(encoding="utf-8").strip() or "0")
    except FileNotFoundError:
        _count = 0
    _count_path.write_text(f"{_count + 1}\n", encoding="utf-8")


class _SyntheticCapability:
    def __init__(self, capability_ref: CapabilityRef, manifest_path: Path) -> None:
        self.capability_ref = capability_ref
        self.manifest_path = manifest_path

    async def execute(
        self,
        invocation: CapabilityInvocation,
    ) -> CapabilityExecutionResult:
        if invocation.capability_ref != self.capability_ref:
            raise ValueError("capability invocation identity is invalid")
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        events = tuple(
            {"type": event_type, "payload": {"source": "synthetic"}}
            for event_type in manifest["emits_events"]
        )
        artifacts = tuple(
            {
                "artifact_id": f"synthetic-{index}",
                "media_type": media_type,
                "value": {"source": "synthetic"},
            }
            for index, media_type in enumerate(
                manifest["produces_artifacts"],
                start=1,
            )
        )
        return CapabilityExecutionResult(events=events, artifacts=artifacts)


class _SyntheticBenchmarkTask:
    def __init__(self, binding_id: str) -> None:
        self.binding_id = binding_id

    def build_invocation(
        self,
        request: BenchmarkTaskRequest,
    ) -> BenchmarkTaskInvocation:
        return BenchmarkTaskInvocation(
            task_id=request.task_id,
            binding_id=self.binding_id,
            public_arguments=("synthetic",),
            private_payload=None,
        )


def create_provider() -> InstalledCapabilityPackage:
    """Build the selected external DCI package from public SDK values."""

    distribution = metadata.distribution("asterion-dci-extension")
    root = Path(distribution.locate_file(PAYLOAD_ROOT)).resolve(strict=True)

    payload = open_portable_payload(root)
    implementations = []
    for path in sorted((root / "capabilities").glob("*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["kind"] in {
            "capability",
            "evaluation",
            "memory",
            "observability",
            "research",
            "workflow",
        }:
            ref = CapabilityRef(str(manifest["capability_id"]), str(manifest["version"]))
            implementations.append(
                CapabilityImplementationBinding(
                    ref,
                    _SyntheticCapability(ref, path),
                )
            )
    benchmark_bindings = {}
    suite_paths = tuple(sorted((root / "benchmark-suites").glob("*.json")))
    for path in suite_paths:
        suite = json.loads(path.read_text(encoding="utf-8"))
        for task in suite["tasks"]:
            benchmark_bindings[str(task["binding_id"])] = (
                BenchmarkTaskBinding(
                    owner_package=PACKAGE_REF,
                    binding_id=str(task["binding_id"]),
                    implementation=_SyntheticBenchmarkTask(str(task["binding_id"])),
                )
            )
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id=SOURCE_ID,
        source_kind="python-distribution",
        catalog_roots=((root / "capabilities").resolve(strict=True),),
        benchmark_suite_paths=suite_paths,
        implementations=tuple(implementations),
        benchmark_bindings=tuple(
            benchmark_bindings[key] for key in sorted(benchmark_bindings)
        ),
    )
