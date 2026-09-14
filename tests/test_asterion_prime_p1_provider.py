"""Native P1 package, application metadata, and selection tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
import json
from pathlib import Path
import tomllib
import unittest

from asterion.applications.discovery import select_application_provider_id
from asterion.applications.first_party_packages import (
    builtin_capability_registrations,
    create_prime_ipython_coding_native_package,
)
from asterion.applications.prime import create_provider
from asterion.applications.provider import compose_installed_provider
from asterion.capability_packages import CapabilityPackageRef
from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource
from asterion.capabilities.execution import (
    CapabilityExecutionError,
    CapabilityInvocation,
)
from asterion.capabilities.prime_ipython_coding_native.provider import CAPABILITY_REF
from asterion.runtime.factory import RuntimeFactoryRegistry
from asterion.runtime.host import RunEvent, RunRequest, RuntimeManifest


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY = ROOT / "src/asterion/applications/prime/assemblies/prime-ipython-coding.json"
PACKAGE = (
    ROOT
    / "src/asterion/capabilities/prime_ipython_coding_native/payload/capability-package.json"
)
CAPABILITY = (
    ROOT
    / "src/asterion/capabilities/prime_ipython_coding_native/payload/capabilities/prime-ipython-coding.json"
)
P1_HOST_CAPABILITIES = (
    "prime.ipython",
    "prime.launch",
    "prime.p1-oracle",
    "prime.private-trace",
    "prime.session-backend",
)


class _Runtime:
    def __init__(self) -> None:
        self.requests: list[RunRequest] = []

    @property
    def manifest(self) -> RuntimeManifest:
        return RuntimeManifest("asterion.prime", ("prime.tool.ipython",))

    async def run(
        self, request: RunRequest, *, signal: object = None
    ) -> AsyncIterator[RunEvent]:
        del signal
        self.requests.append(request)
        yield RunEvent(
            request.run_id,
            1,
            "run.started",
            {"capabilities": ["prime.tool.ipython"]},
        )
        yield RunEvent(
            request.run_id,
            2,
            "artifact.created",
            {
                "artifact": {
                    "artifact_id": "prime.p1-native.receipt",
                    "kind": "p1-native",
                    "media_type": "application/vnd.asterion.prime.p1-native-receipt+json",
                    "sha256": "a" * 64,
                }
            },
        )
        yield RunEvent(request.run_id, 3, "run.completed", {"status": "completed"})


class _CancelledAfterUsageRuntime(_Runtime):
    async def run(
        self, request: RunRequest, *, signal: object = None
    ) -> AsyncIterator[RunEvent]:
        del signal
        self.requests.append(request)
        yield RunEvent(
            request.run_id,
            1,
            "run.started",
            {"capabilities": ["prime.tool.ipython"]},
        )
        yield RunEvent(
            request.run_id,
            2,
            "usage.reported",
            {"input_tokens": 11, "output_tokens": 7},
        )
        yield RunEvent(request.run_id, 3, "run.completed", {"status": "cancelled"})


class TestAsterionPrimeP1Provider(unittest.TestCase):
    def test_capability_accepts_only_literal_preset_and_projects_digest(self) -> None:
        package = create_prime_ipython_coding_native_package()
        implementation = package.implementations[0].implementation
        manifest = json.loads(CAPABILITY.read_text(encoding="utf-8"))
        runtime = _Runtime()

        result = asyncio.run(
            implementation.execute(
                CapabilityInvocation(
                    capability_ref=CAPABILITY_REF,
                    manifest=manifest,
                    run_id="p1-capability-test",
                    input_text="fixed-small-verification",
                    upstream_artifacts=(),
                    runtime=runtime,
                    host_services={},
                )
            )
        )
        self.assertEqual(len(result.artifacts), 1)
        value = result.artifacts[0]["value"]
        self.assertIsInstance(value, Mapping)
        assert isinstance(value, Mapping)
        self.assertEqual(value["receipt_sha256"], "a" * 64)
        self.assertEqual(runtime.requests[0].deadline_ms, 600_000)

        with self.assertRaises(CapabilityExecutionError):
            asyncio.run(
                implementation.execute(
                    CapabilityInvocation(
                        capability_ref=CAPABILITY_REF,
                        manifest=manifest,
                        run_id="p1-capability-invalid",
                        input_text="not-the-preset",
                        upstream_artifacts=(),
                        runtime=runtime,
                        host_services={},
                    )
                )
            )
        self.assertEqual(len(runtime.requests), 1)

    def test_capability_preserves_cancellation_after_committed_usage(self) -> None:
        package = create_prime_ipython_coding_native_package()
        implementation = package.implementations[0].implementation
        manifest = json.loads(CAPABILITY.read_text(encoding="utf-8"))
        runtime = _CancelledAfterUsageRuntime()

        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(
                implementation.execute(
                    CapabilityInvocation(
                        capability_ref=CAPABILITY_REF,
                        manifest=manifest,
                        run_id="p1-capability-cancelled",
                        input_text="fixed-small-verification",
                        upstream_artifacts=(),
                        runtime=runtime,
                        host_services={},
                    )
                )
            )

    def test_provider_publishes_exact_sorted_p1_and_p7_applications(self) -> None:
        provider = create_provider()

        self.assertEqual(provider.provider_id, "prime-applications")
        self.assertEqual(
            tuple(
                (application.application_id, application.version)
                for application in provider.applications
            ),
            (
                ("prime.arc-agi-3-solving", "1.0.0"),
                ("prime.ipython-coding", "1.0.0"),
            ),
        )
        application = provider.applications[1]
        self.assertEqual(
            application.capability_packages,
            (CapabilityPackageRef("prime-ipython-coding-native", "1.0.0"),),
        )
        self.assertEqual(application.runtime_ids, ("asterion.prime",))
        self.assertEqual(
            tuple(binding.runtime_id for binding in provider.runtime_factory_bindings),
            ("asterion.prime",),
        )

    def test_p1_package_is_explicitly_registered_and_composes(self) -> None:
        source = BuiltinCapabilitySource(builtin_capability_registrations())
        candidates = tuple(source.discover_metadata())
        matching = tuple(
            candidate
            for candidate in candidates
            if candidate.package_ref
            == CapabilityPackageRef("prime-ipython-coding-native", "1.0.0")
        )
        self.assertEqual(len(matching), 1)
        self.assertEqual(
            source.load_provider(matching[0]).package_ref, matching[0].package_ref
        )

        composed = compose_installed_provider(
            create_provider(),
            runtime_factories=RuntimeFactoryRegistry(()),
            installed_packages=(
                create_prime_ipython_coding_native_package(),
                # The provider owns P7 as well, so its exact closure stays available.
                next(
                    registration.provider_factory()
                    for registration in builtin_capability_registrations()
                    if registration.package_ref.package_id == "prime-arc-agi-3-solver"
                ),
            ),
        )
        application = next(
            item
            for item in composed.applications
            if item.application_id == "prime.ipython-coding"
        )
        self.assertEqual(
            application.assemblies[0].plan.host_capabilities, P1_HOST_CAPABILITIES
        )
        self.assertEqual(
            tuple(
                ref.capability_id
                for ref in application.assemblies[0].plan.capability_refs
            ),
            ("prime.ipython-coding",),
        )

    def test_closed_metadata_is_exact_sorted_and_contains_no_authority(self) -> None:
        assembly = json.loads(ASSEMBLY.read_text(encoding="utf-8"))
        package = json.loads(PACKAGE.read_text(encoding="utf-8"))
        capability = json.loads(CAPABILITY.read_text(encoding="utf-8"))

        self.assertEqual(
            assembly,
            {
                "protocol": "asterion.application-assembly/v1",
                "application_id": "prime.ipython-coding",
                "version": "1.0.0",
                "runtime_id": "asterion.prime",
                "capability_packages": [
                    {"package_id": "prime-ipython-coding-native", "version": "1.0.0"}
                ],
                "capabilities": [
                    {"capability_id": "prime.ipython-coding", "version": "1.0.0"}
                ],
                "host_capabilities": list(P1_HOST_CAPABILITIES),
                "host_policies": [],
                "host_events": [],
                "host_artifacts": [],
            },
        )
        self.assertEqual(
            package,
            {
                "benchmark_suites": [],
                "capabilities": [
                    {"capability_id": "prime.ipython-coding", "version": "1.0.0"}
                ],
                "conformance": [],
                "package_id": "prime-ipython-coding-native",
                "protocol": "asterion.capability-package/v1",
                "resources": [],
                "version": "1.0.0",
            },
        )
        self.assertEqual(capability["capability_id"], "prime.ipython-coding")
        self.assertEqual(capability["requires_capabilities"], ["prime.tool.ipython"])
        self.assertEqual(
            capability["produces_artifacts"],
            ["application/vnd.asterion.prime.p1-native-receipt+json"],
        )
        for value in (assembly, package, capability):
            serialized = json.dumps(value).lower()
            for forbidden in (
                "command",
                "credential",
                "environment",
                "executable",
                "model",
                "path",
                "prompt",
                "state",
            ):
                self.assertNotIn(forbidden, serialized)

    def test_public_index_migrates_only_p1_and_keeps_legacy_surfaces(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        entry_points = pyproject["project"]["entry-points"]

        self.assertEqual(
            select_application_provider_id("prime.arc-agi-3-solving@1.0.0"),
            "prime-applications",
        )


if __name__ == "__main__":
    unittest.main()
