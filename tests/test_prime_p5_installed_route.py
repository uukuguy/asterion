"""P5 closes through the installed Prime package and selected runtime profile."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import unittest

from asterion.applications.prime_agent.provider import create_provider
from asterion.applications.provider import resolve_installed_provider
from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.prime_agent.provider import create_prime_agent_package
from asterion.runner.composed import run_composed_application
from asterion.runtime.defaults import default_runtime_factory_registry
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError
from asterion.runtimes.prime_agent_host import (
    PrimeSmallVerificationRequest,
    PrimeSmallVerificationResult,
)
from asterion.services.registry import (
    HostServiceFactoryBinding,
    HostServiceFactoryRegistry,
)


class _VerificationService:
    def __init__(self, result: PrimeSmallVerificationResult) -> None:
        self.result = result
        self.requests: list[PrimeSmallVerificationRequest] = []

    async def verify(self, request: PrimeSmallVerificationRequest, *, signal=None):
        del signal
        self.requests.append(request)
        return self.result


class _HostEntryPoint:
    group = "asterion.host_services"
    name = "prime.bounded-autonomy-development"

    def __init__(self, factory) -> None:
        self._factory = factory

    def load(self):
        return self._factory


class TestPrimeP5InstalledRoute(unittest.TestCase):
    def test_p5_host_registry_uses_the_exact_selected_identity(self) -> None:
        observed = []

        def create_binding():
            @asynccontextmanager
            async def factory(context):
                observed.append(context)
                yield object()

            return HostServiceFactoryBinding(
                capability_id="prime.bounded-autonomy-development",
                option_names=(),
                factory=factory,
            )

        async def open_service() -> None:
            registry = HostServiceFactoryRegistry((_HostEntryPoint(create_binding),))
            async with registry.open(
                provider_id="prime-agent",
                application_id="prime.bounded-autonomy",
                application_version="1.0.0",
                capability_ids=("prime.bounded-autonomy-development",),
                options={},
            ) as services:
                self.assertEqual(set(services), {"prime.bounded-autonomy-development"})

        asyncio.run(open_service())
        self.assertEqual(len(observed), 1)
        context = observed[0]
        self.assertEqual(context.provider_id, "prime-agent")
        self.assertEqual(context.application_id, "prime.bounded-autonomy")
        self.assertEqual(context.application_version, "1.0.0")
        self.assertEqual(context.capability_id, "prime.bounded-autonomy-development")

    def test_p5_resolves_and_projects_its_safe_trace(self) -> None:
        package = create_prime_agent_package()
        resolved = resolve_installed_provider(
            create_provider(),
            runtime_factories=default_runtime_factory_registry(),
            installed_packages=(package,),
        )
        application = next(
            item
            for item in resolved.applications
            if item.application_id == "prime.bounded-autonomy"
        )
        assembly = application.assemblies[0]
        self.assertEqual(
            assembly.plan.capability_refs,
            (CapabilityRef("prime.bounded-autonomy", "1.0.0"),),
        )
        self.assertEqual(
            assembly.plan.host_capabilities,
            ("prime.bounded-autonomy-development",),
        )

        run_id = "prime-p5-composed-run"
        service = _VerificationService(
            PrimeSmallVerificationResult(
                run_id=run_id,
                trace_sha256="sha256:" + "5" * 64,
                scope="p5-development",
            )
        )
        runtime = default_runtime_factory_registry().select("prime.agent").factory(
            RuntimeFactoryContext(
                provider_id="prime-agent",
                application_id="prime.bounded-autonomy",
                application_version="1.0.0",
                runtime_id="prime.agent",
                assembly_path=assembly.path,
                options={},
                host_services={"prime.bounded-autonomy-development": service},
            )
        )
        result = asyncio.run(
            run_composed_application(
                assembly.plan,
                implementations=application.implementations,
                runtime=runtime,
                run_id=run_id,
                input_text="fixed-small-verification",
                host_services={"prime.bounded-autonomy-development": service},
            )
        )

        self.assertEqual(service.requests, [PrimeSmallVerificationRequest(run_id)])
        self.assertEqual(
            result.artifacts,
            (
                {
                    "artifact_id": "prime.p5-development.trace",
                    "media_type": "application/vnd.asterion.prime.p5-development-trace+json",
                    "value": {
                        "scope": "p5-development",
                        "promotion": "unpromoted",
                        "trace_sha256": "5" * 64,
                    },
                },
            ),
        )

    def test_p5_runtime_rejects_wrong_scope_and_host(self) -> None:
        binding = default_runtime_factory_registry().select("prime.agent")
        service = _VerificationService(
            PrimeSmallVerificationResult(
                run_id="prime-p5-scope-mismatch",
                trace_sha256="sha256:" + "4" * 64,
                scope="p4-development",
            )
        )
        runtime = binding.factory(
            RuntimeFactoryContext(
                provider_id="prime-agent",
                application_id="prime.bounded-autonomy",
                application_version="1.0.0",
                runtime_id="prime.agent",
                assembly_path=__file__,
                options={},
                host_services={"prime.bounded-autonomy-development": service},
            )
        )

        async def collect():
            from asterion.runtime.host import RunRequest

            return tuple(
                [
                    event
                    async for event in runtime.run(
                        RunRequest(
                            run_id="prime-p5-scope-mismatch",
                            input_text="fixed-small-verification",
                            requested_capabilities=("prime.tool.ipython",),
                        )
                    )
                ]
            )

        self.assertEqual(
            [event.type for event in asyncio.run(collect())],
            ["run.started", "run.failed"],
        )
        with self.assertRaises(RuntimeFactoryError):
            binding.factory(
                RuntimeFactoryContext(
                    provider_id="prime-agent",
                    application_id="prime.bounded-autonomy",
                    application_version="1.0.0",
                    runtime_id="prime.agent",
                    assembly_path=__file__,
                    options={},
                    host_services={"prime.long-session-continuity-development": service},
                )
            )


if __name__ == "__main__":
    unittest.main()
