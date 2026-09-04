"""Prime's P1 package and runtime compose through the standard closure path."""

from __future__ import annotations

import unittest
import asyncio
from dataclasses import replace

from asterion.applications.prime_agent.provider import create_provider
from asterion.applications.provider import (
    ApplicationProviderError,
    InstalledApplication,
    InstalledApplicationProvider,
    resolve_installed_provider,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.prime_agent.provider import create_prime_agent_package
from asterion.runtime.defaults import default_runtime_factory_registry
from asterion.runtime.factory import RuntimeFactoryBinding, RuntimeFactoryRegistry
from asterion.runtime.host import RunEvent, RunRequest
from asterion.runtimes.prime_agent import PrimeAgentRuntimeClient, PrimeAgentRuntimeError


class TestPrimePackageRuntimeClosure(unittest.TestCase):
    def setUp(self) -> None:
        self.package = create_prime_agent_package()
        self.provider = create_provider()

    def test_standard_resolution_closes_exact_prime_package_runtime_and_tool(self) -> None:
        resolved = resolve_installed_provider(
            self.provider,
            runtime_factories=default_runtime_factory_registry(),
            installed_packages=(self.package,),
        )

        application = resolved.applications[0]
        assembly = application.assemblies[0]
        self.assertEqual(application.capability_packages, (self.package.package_ref,))
        self.assertEqual(assembly.runtime_id, "prime.agent")
        self.assertEqual(assembly.plan.capability_refs, (CapabilityRef("prime.ipython-coding", "1.0.0"),))
        self.assertEqual(assembly.plan.runtime_capabilities, ("prime.tool.ipython",))
        self.assertEqual(
            tuple(ref for ref, _ in application.implementations),
            (CapabilityRef("prime.ipython-coding", "1.0.0"),),
        )

        selected = next(
            item
            for item in resolved.applications
            if item.application_id == "prime.ipython-coding"
        )
        self.assertEqual(
            selected.assemblies[0].plan.host_capabilities,
            ("prime.ipython-production",),
        )

    def test_resolution_rejects_runtime_with_an_alternate_tool(self) -> None:
        binding = default_runtime_factory_registry().select("prime.agent")
        factories = RuntimeFactoryRegistry(
            (
                RuntimeFactoryBinding(
                    runtime_id="prime.agent",
                    capabilities=("prime.tool.shell",),
                    factory=binding.factory,
                ),
            )
        )

        with self.assertRaisesRegex(ApplicationProviderError, "closure is invalid"):
            resolve_installed_provider(
                self.provider,
                runtime_factories=factories,
                installed_packages=(self.package,),
            )

    def test_resolution_rejects_ambiguous_prime_implementation_binding(self) -> None:
        ambiguous = replace(
            self.package,
            implementations=(
                *self.package.implementations,
                self.package.implementations[0],
            ),
        )

        with self.assertRaisesRegex(ApplicationProviderError, "closure is invalid"):
            resolve_installed_provider(
                self.provider,
                runtime_factories=default_runtime_factory_registry(),
                installed_packages=(ambiguous,),
            )

    def test_provider_rejects_an_undeclared_runtime_before_resolution(self) -> None:
        application = self.provider.applications[0]
        altered = InstalledApplication(
            application_id=application.application_id,
            version=application.version,
            assembly_paths=application.assembly_paths,
            capability_packages=application.capability_packages,
            runtime_ids=("prime.unlisted",),
        )
        provider = InstalledApplicationProvider(
            protocol=self.provider.protocol,
            provider_id=self.provider.provider_id,
            resource_root=self.provider.resource_root,
            applications=(altered,),
        )

        with self.assertRaisesRegex(ApplicationProviderError, "assembly identity"):
            resolve_installed_provider(
                provider,
                runtime_factories=default_runtime_factory_registry(),
                installed_packages=(self.package,),
            )

    def test_runtime_rejects_a_non_ipython_tool_before_emitting_frames(self) -> None:
        async def collect() -> tuple[object, ...]:
            runtime = PrimeAgentRuntimeClient()
            return tuple(
                [
                    event
                    async for event in runtime.run(
                        RunRequest(
                            run_id="prime-tool-rejection",
                            input_text="unused",
                            requested_capabilities=("prime.tool.shell",),
                        )
                    )
                ]
            )

        with self.assertRaisesRegex(PrimeAgentRuntimeError, "not declared"):
            asyncio.run(collect())

    def test_runtime_collects_exact_unavailable_frames_for_ipython_tool(self) -> None:
        run_id = "prime-runtime-unavailable"

        async def collect() -> tuple[RunEvent, ...]:
            runtime = PrimeAgentRuntimeClient()
            return tuple(
                [
                    event
                    async for event in runtime.run(
                        RunRequest(
                            run_id=run_id,
                            input_text="unused",
                            requested_capabilities=("prime.tool.ipython",),
                        )
                    )
                ]
            )

        events = asyncio.run(collect())
        self.assertEqual(
            events,
            (
                RunEvent(
                    run_id=run_id,
                    sequence=1,
                    type="run.started",
                    payload={"capabilities": ["prime.tool.ipython"]},
                ),
                RunEvent(
                    run_id=run_id,
                    sequence=2,
                    type="run.failed",
                    payload={
                        "code": "runtime-unavailable",
                        "message": "Prime worker is unavailable",
                    },
                ),
            ),
        )
        self.assertEqual(tuple(event.sequence for event in events), (1, 2))
        self.assertEqual(tuple(event.run_id for event in events), (run_id, run_id))
        self.assertEqual(events[-1].payload["code"], "runtime-unavailable")
