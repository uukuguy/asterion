"""Canonical built-in provider for the DCI capability package."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from asterion.capabilities.dci.implementation.bindings import complete_dci_bindings
from asterion.capability_packages.protocol import validate_benchmark_suite_manifest
from asterion.capability_packages.sources.builtin import (
    builtin_capability_source_id,
)
from asterion.capability_sdk import (
    BenchmarkTaskBinding,
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
    CapabilityExecutionResult,
    CapabilityInvocation,
    CapabilityImplementationBinding,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
    open_portable_payload,
)


PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")
SOURCE_ID = builtin_capability_source_id(PACKAGE_REF)
SOURCE_KIND = "builtin"


class _ProtocolObservabilityImplementation:
    async def execute(
        self,
        invocation: CapabilityInvocation,
    ) -> CapabilityExecutionResult:
        if invocation.capability_ref != CapabilityRef(
            "protocol.observability",
            "1.0.0",
        ):
            raise ValueError("DCI observability invocation identity is invalid")
        return CapabilityExecutionResult(
            events=(
                {
                    "type": "audit.package-observed",
                    "payload": {"source": "synthetic"},
                },
            ),
            artifacts=(),
        )


class _DescriptorBenchmarkTask:
    """Provider-free benchmark placeholder with no private execution payload."""

    def __init__(self, binding_id: str) -> None:
        self._binding_id = binding_id

    def build_invocation(
        self,
        request: BenchmarkTaskRequest,
    ) -> BenchmarkTaskInvocation:
        return BenchmarkTaskInvocation(
            task_id=request.task_id,
            binding_id=self._binding_id,
            public_arguments=("synthetic",),
            private_payload=None,
        )


def create_provider() -> InstalledCapabilityPackage:
    """Return the selected built-in DCI package binding."""

    payload_root = _payload_root()
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id=SOURCE_ID,
        source_kind=SOURCE_KIND,
        catalog_roots=((payload_root / "capabilities").resolve(strict=True),),
        benchmark_suite_paths=_benchmark_suite_paths(payload_root),
        implementations=_implementation_bindings(),
        benchmark_bindings=_benchmark_bindings(payload_root),
    )


def _payload_root() -> Path:
    package_root = Path(str(resources.files("asterion"))).resolve()
    return package_root / "capabilities/dci/payload"


def _implementation_bindings() -> tuple[CapabilityImplementationBinding, ...]:
    return tuple(
        sorted(
            (
                *complete_dci_bindings(),
                CapabilityImplementationBinding(
                    CapabilityRef("protocol.observability", "1.0.0"),
                    _ProtocolObservabilityImplementation(),
                ),
            ),
            key=lambda binding: binding.capability_ref,
        )
    )


def _benchmark_suite_paths(payload_root: Path) -> tuple[Path, ...]:
    suite_root = payload_root / "benchmark-suites"
    return tuple(sorted(suite_root.glob("*.json")))


def _benchmark_bindings(payload_root: Path) -> tuple[BenchmarkTaskBinding, ...]:
    bindings: dict[str, BenchmarkTaskBinding] = {}
    for path in _benchmark_suite_paths(payload_root):
        suite = validate_benchmark_suite_manifest(
            json.loads(path.read_text(encoding="utf-8"))
        )
        for task in suite.tasks:
            bindings[task.binding_id] = BenchmarkTaskBinding(
                owner_package=PACKAGE_REF,
                binding_id=task.binding_id,
                implementation=_DescriptorBenchmarkTask(task.binding_id),
            )
    return tuple(bindings[key] for key in sorted(bindings))
