from __future__ import annotations

import json
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from types import MappingProxyType

from asterion.assembly.protocol import resolve_assembly
from asterion.packages.catalog import PackageRef, discover_packages
from asterion.packages.execution import (
    PackageExecutionError,
    PackageExecutionResult,
    PackageInvocation,
    validate_implementation_bindings,
    validate_package_result,
)
from asterion.runtime.host import RunEvent, RunRequest, RuntimeManifest


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"
MANIFEST_ROOT = SOURCE / "capabilities/dci_research/manifests"
ASSEMBLY = (
    SOURCE
    / "applications/dci_agent_lite/assemblies/dci-local-research.json"
)


class FixtureRuntime:
    manifest = RuntimeManifest(
        runtime_id="pi.reference",
        capabilities=("filesystem.read", "shell"),
    )

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del request, signal
        if False:
            yield RunEvent("", 0, "", {})


class RecordingImplementation:
    async def execute(
        self, invocation: PackageInvocation
    ) -> PackageExecutionResult:
        del invocation
        return PackageExecutionResult(events=(), artifacts=())


def resolve_plan():
    return resolve_assembly(
        json.loads(ASSEMBLY.read_text()),
        catalog=discover_packages((MANIFEST_ROOT,)),
        runtime_manifest=FixtureRuntime.manifest.to_mapping(),
    )


class PackageImplementationBindingTests(unittest.TestCase):
    def test_exact_bindings_require_every_executable_package(self) -> None:
        implementation = RecordingImplementation()

        with self.assertRaises(PackageExecutionError):
            validate_implementation_bindings(
                resolve_plan(),
                ((PackageRef("dci.research", "1.0.0"), implementation),),
            )

    def test_duplicate_exact_bindings_fail_before_mapping_conversion(self) -> None:
        implementation = RecordingImplementation()
        binding = (PackageRef("dci.research", "1.0.0"), implementation)

        with self.assertRaises(PackageExecutionError):
            validate_implementation_bindings(resolve_plan(), (binding, binding))

    def test_complete_exact_bindings_are_immutable_and_policy_is_declarative(self) -> None:
        implementation = RecordingImplementation()
        bindings = tuple(
            (PackageRef(package_id, "1.0.0"), implementation)
            for package_id in ("dci.evaluation", "dci.research", "protocol.observability")
        )

        resolved = validate_implementation_bindings(resolve_plan(), bindings)

        self.assertIsInstance(resolved, MappingProxyType)
        self.assertNotIn(PackageRef("policy.local-corpus", "1.0.0"), resolved)
        with self.assertRaises(TypeError):
            resolved[PackageRef("other", "1.0.0")] = implementation

    def test_unknown_exact_binding_is_rejected(self) -> None:
        implementation = RecordingImplementation()
        bindings = tuple(
            (PackageRef(package_id, "1.0.0"), implementation)
            for package_id in (
                "dci.evaluation",
                "dci.research",
                "protocol.observability",
                "unknown.package",
            )
        )

        with self.assertRaises(PackageExecutionError):
            validate_implementation_bindings(resolve_plan(), bindings)


class PackageExecutionValueTests(unittest.TestCase):
    def test_invocation_and_result_are_deeply_immutable(self) -> None:
        manifest = resolve_plan().package_manifests[1]
        invocation = PackageInvocation(
            package_ref=PackageRef("dci.research", "1.0.0"),
            manifest=manifest,
            run_id="package-run-1",
            input_text="Read the corpus",
            upstream_artifacts=({"media_type": "text/plain", "value": {"x": 1}},),
            runtime=FixtureRuntime(),
            host_services={"service.example": object()},
        )
        result = PackageExecutionResult(
            events=({"type": "research.completed", "payload": {"ok": True}},),
            artifacts=({
                "artifact_id": "research-result",
                "media_type": "application/vnd.dci.research+json",
                "value": {"answer_artifact_uri": "final.txt"},
            },),
        )

        self.assertIsInstance(invocation.host_services, MappingProxyType)
        with self.assertRaises(TypeError):
            invocation.upstream_artifacts[0]["media_type"] = "changed"
        with self.assertRaises(TypeError):
            result.events[0]["type"] = "changed"
        with self.assertRaises(TypeError):
            result.artifacts[0]["value"]["answer_artifact_uri"] = "changed"


class PackageResultValidationTests(unittest.TestCase):
    def manifest(self):
        return next(
            manifest
            for manifest in resolve_plan().package_manifests
            if manifest["package_id"] == "dci.research"
        )

    def test_declared_events_and_artifacts_are_accepted(self) -> None:
        validate_package_result(
            self.manifest(),
            PackageExecutionResult(
                events=({"type": "research.completed", "payload": {}},),
                artifacts=({
                    "artifact_id": "research-result",
                    "media_type": "application/vnd.dci.research+json",
                    "value": {},
                },),
            ),
        )

    def test_undeclared_or_malformed_outputs_are_rejected_without_content(self) -> None:
        sentinel = "SECRET-PACKAGE-OUTPUT"
        invalid = (
            PackageExecutionResult(events=({"type": sentinel, "payload": {}},), artifacts=()),
            PackageExecutionResult(
                events=(),
                artifacts=({
                    "artifact_id": "result",
                    "media_type": sentinel,
                    "value": {},
                },),
            ),
            PackageExecutionResult(
                events=(),
                artifacts=(
                    {"artifact_id": "same", "media_type": "application/vnd.dci.research+json", "value": {}},
                    {"artifact_id": "same", "media_type": "application/vnd.dci.research+json", "value": {}},
                ),
            ),
        )
        for result in invalid:
            with self.subTest(result=result):
                with self.assertRaises(PackageExecutionError) as raised:
                    validate_package_result(self.manifest(), result)
                self.assertNotIn(sentinel, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
