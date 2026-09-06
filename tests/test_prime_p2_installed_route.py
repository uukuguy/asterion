"""P2 closes through the installed Prime package and selected runtime profile."""

from __future__ import annotations

import asyncio
import unittest

from asterion.applications.prime_agent.provider import create_provider
from asterion.applications.provider import resolve_installed_provider
from asterion.capabilities.catalog import CapabilityRef
from asterion.runtime.defaults import default_runtime_factory_registry
from asterion.applications.prime_agent.runtime_binding import prime_runtime_binding
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError
from asterion.runner.composed import run_composed_application
from asterion.runtimes.prime_agent_host import (
    PrimeSmallVerificationRequest,
    PrimeSmallVerificationResult,
)
from asterion.capabilities.prime_agent.provider import create_prime_agent_package


class _VerificationService:
    def __init__(self, result: PrimeSmallVerificationResult) -> None:
        self.result = result
        self.requests: list[PrimeSmallVerificationRequest] = []

    async def verify(self, request: PrimeSmallVerificationRequest, *, signal=None):
        del signal
        self.requests.append(request)
        return self.result


class TestPrimeP2InstalledRoute(unittest.TestCase):
    def test_p2_resolves_and_projects_its_safe_trace(self) -> None:
        package = create_prime_agent_package()
        resolved = resolve_installed_provider(
            create_provider(),
            runtime_factories=default_runtime_factory_registry(),
            installed_packages=(package,),
        )
        application = next(
            item
            for item in resolved.applications
            if item.application_id == "prime.programmatic-long-context"
        )
        assembly = application.assemblies[0]
        self.assertEqual(
            assembly.plan.capability_refs,
            (CapabilityRef("prime.programmatic-long-context", "1.0.0"),),
        )
        self.assertEqual(
            assembly.plan.host_capabilities,
            ("prime.programmatic-long-context-development",),
        )

        run_id = "prime-p2-composed-run"
        service = _VerificationService(
            PrimeSmallVerificationResult(
                run_id=run_id,
                trace_sha256="sha256:" + "d" * 64,
                scope="p2-development",
            )
        )
        runtime = prime_runtime_binding().factory(
            RuntimeFactoryContext(
                provider_id="prime-agent",
                application_id="prime.programmatic-long-context",
                application_version="1.0.0",
                runtime_id="prime.agent",
                assembly_path=assembly.path,
                options={},
                host_services={"prime.programmatic-long-context-development": service},
            )
        )
        result = asyncio.run(
            run_composed_application(
                assembly.plan,
                implementations=application.implementations,
                runtime=runtime,
                run_id=run_id,
                input_text="fixed-small-verification",
                host_services={"prime.programmatic-long-context-development": service},
            )
        )

        self.assertEqual(service.requests, [PrimeSmallVerificationRequest(run_id)])
        self.assertEqual(
            result.artifacts,
            (
                {
                    "artifact_id": "prime.p2-development.trace",
                    "media_type": "application/vnd.asterion.prime.p2-development-trace+json",
                    "value": {
                        "scope": "p2-development",
                        "promotion": "unpromoted",
                        "trace_sha256": "d" * 64,
                    },
                },
            ),
        )

    def test_p2_runtime_rejects_a_p1_result_scope(self) -> None:
        service = _VerificationService(
            PrimeSmallVerificationResult(
                run_id="prime-p2-scope-mismatch",
                trace_sha256="sha256:" + "e" * 64,
            )
        )
        binding = prime_runtime_binding()
        runtime = binding.factory(
            RuntimeFactoryContext(
                provider_id="prime-agent",
                application_id="prime.programmatic-long-context",
                application_version="1.0.0",
                runtime_id="prime.agent",
                assembly_path=__file__,
                options={},
                host_services={"prime.programmatic-long-context-development": service},
            )
        )

        async def collect():
            from asterion.runtime.host import RunRequest

            return tuple(
                [
                    event
                    async for event in runtime.run(
                        RunRequest(
                            run_id="prime-p2-scope-mismatch",
                            input_text="fixed-small-verification",
                            requested_capabilities=("prime.tool.ipython",),
                        )
                    )
                ]
            )

        events = asyncio.run(collect())
        self.assertEqual(
            [event.type for event in events], ["run.started", "run.failed"]
        )

        with self.assertRaises(RuntimeFactoryError):
            binding.factory(
                RuntimeFactoryContext(
                    provider_id="prime-agent",
                    application_id="prime.programmatic-long-context",
                    application_version="1.0.0",
                    runtime_id="prime.agent",
                    assembly_path=__file__,
                    options={},
                    host_services={"prime.ipython-production": service},
                )
            )


if __name__ == "__main__":
    unittest.main()
