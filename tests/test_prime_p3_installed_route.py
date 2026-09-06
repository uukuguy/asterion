"""P3 closes through the installed Prime package and selected runtime profile."""

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
from asterion.applications.prime_agent.runtime_binding import prime_runtime_binding
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
    name = "prime.recursive-workflow-development"

    def __init__(self, factory) -> None:
        self._factory = factory

    def load(self):
        return self._factory


class TestPrimeP3InstalledRoute(unittest.TestCase):
    def test_p3_host_registry_uses_the_exact_selected_identity(self) -> None:
        observed = []

        def create_binding():
            @asynccontextmanager
            async def factory(context):
                observed.append(context)
                yield _VerificationService(
                    PrimeSmallVerificationResult(
                        run_id="prime-p3-host-registry",
                        trace_sha256="sha256:" + "b" * 64,
                        scope="p3-development",
                    )
                )

            return HostServiceFactoryBinding(
                capability_id="prime.recursive-workflow-development",
                option_names=(),
                factory=factory,
            )

        async def open_service() -> None:
            registry = HostServiceFactoryRegistry((_HostEntryPoint(create_binding),))
            async with registry.open(
                provider_id="prime-agent",
                application_id="prime.recursive-workflow",
                application_version="1.0.0",
                capability_ids=("prime.recursive-workflow-development",),
                options={},
            ) as services:
                self.assertEqual(
                    set(services), {"prime.recursive-workflow-development"}
                )

        asyncio.run(open_service())
        self.assertEqual(len(observed), 1)
        context = observed[0]
        self.assertEqual(context.provider_id, "prime-agent")
        self.assertEqual(context.application_id, "prime.recursive-workflow")
        self.assertEqual(context.application_version, "1.0.0")
        self.assertEqual(context.capability_id, "prime.recursive-workflow-development")

    def test_p3_resolves_and_projects_its_safe_trace(self) -> None:
        package = create_prime_agent_package()
        resolved = resolve_installed_provider(
            create_provider(),
            runtime_factories=default_runtime_factory_registry(),
            installed_packages=(package,),
        )
        application = next(
            item
            for item in resolved.applications
            if item.application_id == "prime.recursive-workflow"
        )
        assembly = application.assemblies[0]
        self.assertEqual(
            assembly.plan.capability_refs,
            (CapabilityRef("prime.recursive-workflow", "1.0.0"),),
        )
        self.assertEqual(
            assembly.plan.host_capabilities,
            ("prime.recursive-workflow-development",),
        )

        run_id = "prime-p3-composed-run"
        service = _VerificationService(
            PrimeSmallVerificationResult(
                run_id=run_id,
                trace_sha256="sha256:" + "f" * 64,
                scope="p3-development",
            )
        )
        runtime = prime_runtime_binding().factory(
            RuntimeFactoryContext(
                provider_id="prime-agent",
                application_id="prime.recursive-workflow",
                application_version="1.0.0",
                runtime_id="prime.agent",
                assembly_path=assembly.path,
                options={},
                host_services={"prime.recursive-workflow-development": service},
            )
        )
        result = asyncio.run(
            run_composed_application(
                assembly.plan,
                implementations=application.implementations,
                runtime=runtime,
                run_id=run_id,
                input_text="fixed-small-verification",
                host_services={"prime.recursive-workflow-development": service},
            )
        )

        self.assertEqual(service.requests, [PrimeSmallVerificationRequest(run_id)])
        self.assertEqual(
            result.artifacts,
            (
                {
                    "artifact_id": "prime.p3-development.trace",
                    "media_type": "application/vnd.asterion.prime.p3-development-trace+json",
                    "value": {
                        "scope": "p3-development",
                        "promotion": "unpromoted",
                        "trace_sha256": "f" * 64,
                    },
                },
            ),
        )

    def test_p3_runtime_rejects_wrong_scope_and_host(self) -> None:
        binding = prime_runtime_binding()
        service = _VerificationService(
            PrimeSmallVerificationResult(
                run_id="prime-p3-scope-mismatch",
                trace_sha256="sha256:" + "a" * 64,
                scope="p2-development",
            )
        )
        runtime = binding.factory(
            RuntimeFactoryContext(
                provider_id="prime-agent",
                application_id="prime.recursive-workflow",
                application_version="1.0.0",
                runtime_id="prime.agent",
                assembly_path=__file__,
                options={},
                host_services={"prime.recursive-workflow-development": service},
            )
        )

        async def collect():
            from asterion.runtime.host import RunRequest

            return tuple(
                [
                    event
                    async for event in runtime.run(
                        RunRequest(
                            run_id="prime-p3-scope-mismatch",
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
                    application_id="prime.recursive-workflow",
                    application_version="1.0.0",
                    runtime_id="prime.agent",
                    assembly_path=__file__,
                    options={},
                    host_services={
                        "prime.programmatic-long-context-development": service
                    },
                )
            )


if __name__ == "__main__":
    unittest.main()
