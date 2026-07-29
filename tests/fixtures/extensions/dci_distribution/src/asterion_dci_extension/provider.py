"""Public-SDK-only provider for the external-form DCI fixture."""

from __future__ import annotations

import os
from importlib import metadata
from pathlib import Path

from asterion.capability_sdk import (
    BenchmarkTaskBinding,
    BenchmarkTaskInvocation,
    CapabilityExecutionResult,
    CapabilityImplementationBinding,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
    open_portable_payload,
)


if os.environ.get("ASTERION_TEST_FORBID_PROVIDER_IMPORT") == "1":
    raise RuntimeError("provider imported during metadata discovery")


PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")
SOURCE_ID = "dci.python-distribution"
SOURCE_KIND = "python-distribution"
PAYLOAD_RELATIVE_ROOT = "asterion_capability_packages/dci/1.0.0/payload"

_CAPABILITY_BINDINGS = (
    ("dci.analysis", "analysis.completed", "application/vnd.dci.analysis+json"),
    ("dci.benchmark", "benchmark.completed", "application/vnd.dci.benchmark+json"),
    ("dci.evaluation", "evaluation.completed", "application/vnd.dci.verdict+json"),
    ("dci.export", "export.completed", "application/vnd.dci.export+json"),
    ("dci.research", "research.completed", "application/vnd.dci.research+json"),
    ("protocol.observability", "audit.capability-observed", None),
)
_BENCHMARK_BINDING_IDS = (
    "bcplus.level3",
    "bcplus.main",
    "beir.arguana",
    "beir.scifact",
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
    "qa.2wikimultihopqa",
    "qa.bamboogle.github-sample50",
    "qa.bamboogle.paper-full125",
    "qa.hotpotqa",
    "qa.musique",
    "qa.nq",
    "qa.triviaqa",
)


class _SyntheticCapability:
    def __init__(self, event_type: str, media_type: str | None) -> None:
        self._event_type = event_type
        self._media_type = media_type

    async def execute(self, invocation) -> CapabilityExecutionResult:
        del invocation
        artifacts = (
            ()
            if self._media_type is None
            else (
                {
                    "artifact_id": "synthetic.external",
                    "media_type": self._media_type,
                    "payload": {"synthetic": True},
                },
            )
        )
        return CapabilityExecutionResult(
            events=({"type": self._event_type, "payload": {"synthetic": True}},),
            artifacts=artifacts,
        )


class _SyntheticBenchmarkTask:
    def __init__(self, binding_id: str) -> None:
        self._binding_id = binding_id

    def build_invocation(self, request) -> BenchmarkTaskInvocation:
        return BenchmarkTaskInvocation(
            task_id=request.task_id,
            binding_id=self._binding_id,
            public_arguments=("synthetic",),
            private_payload={"synthetic": True},
        )


def create_provider() -> InstalledCapabilityPackage:
    """Return the selected installed package after payload identity validation."""

    distribution = metadata.distribution("asterion-dci-extension")
    payload_root = Path(str(distribution.locate_file(PAYLOAD_RELATIVE_ROOT)))
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id=SOURCE_ID,
        source_kind=SOURCE_KIND,
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(payload_root / "benchmark-suites",),
        implementations=tuple(
            CapabilityImplementationBinding(
                CapabilityRef(capability_id, "1.0.0"),
                _SyntheticCapability(event_type, media_type),
            )
            for capability_id, event_type, media_type in _CAPABILITY_BINDINGS
        ),
        benchmark_bindings=tuple(
            BenchmarkTaskBinding(
                owner_package=PACKAGE_REF,
                binding_id=binding_id,
                implementation=_SyntheticBenchmarkTask(binding_id),
            )
            for binding_id in _BENCHMARK_BINDING_IDS
        ),
    )


__all__ = ("create_provider",)
