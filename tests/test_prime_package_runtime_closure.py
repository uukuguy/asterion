"""Prime's P1 package and runtime compose through the standard closure path."""

from __future__ import annotations

import unittest
import asyncio
from dataclasses import replace
import json
from pathlib import Path

from asterion.applications.prime_agent.provider import create_provider
from asterion.applications.provider import (
    ApplicationProviderError,
    InstalledApplication,
    InstalledApplicationProvider,
    resolve_installed_provider,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import CapabilityInvocation
from asterion.capabilities.prime_agent.provider import (
    PrimeIpythonCodingImplementation,
    create_prime_agent_package,
)
from asterion.runtime.defaults import default_runtime_factory_registry
from asterion.runtime.factory import RuntimeFactoryBinding, RuntimeFactoryRegistry
from asterion.runtime.host import RunEvent, RunRequest
from asterion.runtimes.prime_agent import PrimeAgentRuntimeClient, PrimeAgentRuntimeError
from asterion.runtimes.prime_agent_host import (
    PrimeSmallVerificationCancelled,
    PrimeSmallVerificationRequest,
    PrimeSmallVerificationResult,
)


class _VerificationService:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[PrimeSmallVerificationRequest] = []

    async def verify(
        self,
        request: PrimeSmallVerificationRequest,
        *,
        signal: object = None,
    ) -> object:
        del signal
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


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
            runtime = PrimeAgentRuntimeClient(
                _VerificationService(
                    PrimeSmallVerificationResult(
                        run_id="unused", trace_sha256="sha256:" + "a" * 64
                    )
                )
            )
            return tuple(
                [
                    event
                    async for event in runtime.run(
                        RunRequest(
                            run_id="prime-tool-rejection",
                            input_text="fixed-small-verification",
                            requested_capabilities=("prime.tool.shell",),
                        )
                    )
                ]
            )

        with self.assertRaisesRegex(PrimeAgentRuntimeError, "not declared"):
            asyncio.run(collect())

    def test_runtime_projects_one_fixed_small_verification(self) -> None:
        run_id = "prime-runtime-unavailable"
        service = _VerificationService(
            PrimeSmallVerificationResult(run_id=run_id, trace_sha256="sha256:" + "a" * 64)
        )

        async def collect() -> tuple[RunEvent, ...]:
            runtime = PrimeAgentRuntimeClient(service)
            return tuple(
                [
                    event
                    async for event in runtime.run(
                        RunRequest(
                            run_id=run_id,
                            input_text="fixed-small-verification",
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
                    type="artifact.created",
                    payload={
                        "artifact": {
                            "artifact_id": "prime.p1-b-development.trace",
                            "kind": "p1-b-development",
                            "media_type": "application/vnd.asterion.prime.p1-development-trace+json",
                            "sha256": "a" * 64,
                        },
                    },
                ),
                RunEvent(
                    run_id=run_id,
                    sequence=3,
                    type="run.completed",
                    payload={"status": "completed"},
                ),
            ),
        )
        self.assertEqual(service.requests, [PrimeSmallVerificationRequest(run_id)])

    def test_factory_rejects_missing_or_extra_prime_host_before_execution(self) -> None:
        binding = default_runtime_factory_registry().select("prime.agent")
        base = dict(
            provider_id="prime-agent",
            application_id="prime.ipython-coding",
            application_version="1.0.0",
            runtime_id="prime.agent",
            assembly_path=Path("/assembly.json"),
            options={},
        )
        service = _VerificationService(
            PrimeSmallVerificationResult(run_id="unused", trace_sha256="sha256:" + "a" * 64)
        )
        from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError

        cases = (
            ({}, {}),
            ({"prime.ipython-production": service, "extra": object()}, {}),
            ({"prime.ipython-production": service}, {"provider_id": "other"}),
            ({"prime.ipython-production": service}, {"application_id": "other"}),
            ({"prime.ipython-production": service}, {"application_version": "2.0.0"}),
        )
        for services, changes in cases:
            with self.subTest(services=tuple(services), changes=changes), self.assertRaises(RuntimeFactoryError):
                binding.factory(
                    RuntimeFactoryContext(
                        **{**base, **changes, "host_services": services}
                    )
                )

    def test_capability_projects_only_safe_trace_fields_and_rejects_noncompletion(self) -> None:
        run_id = "prime-capability-run"
        manifest = json.loads(
            (Path(__file__).parents[1] / "src/asterion/capabilities/prime_agent/payload/capabilities/ipython-coding.json").read_text()
        )

        async def execute(result: object):
            runtime = PrimeAgentRuntimeClient(_VerificationService(result))
            return await PrimeIpythonCodingImplementation().execute(
                CapabilityInvocation(
                    capability_ref=CapabilityRef("prime.ipython-coding", "1.0.0"),
                    manifest=manifest,
                    run_id=run_id,
                    input_text="fixed-small-verification",
                    upstream_artifacts=(),
                    runtime=runtime,
                    host_services={},
                )
            )

        result = asyncio.run(
            execute(PrimeSmallVerificationResult(run_id=run_id, trace_sha256="sha256:" + "b" * 64))
        )
        self.assertEqual(
            result.artifacts,
            ({"artifact_id": "prime.p1-b-development.trace", "media_type": "application/vnd.asterion.prime.p1-development-trace+json", "value": {"scope": "p1-b-development", "promotion": "unpromoted", "trace_sha256": "b" * 64}},),
        )
        for bad in ("invalid", PrimeSmallVerificationResult(run_id="other", trace_sha256="sha256:" + "b" * 64)):
            with self.subTest(bad=type(bad).__name__), self.assertRaisesRegex(Exception, "Prime"):
                asyncio.run(execute(bad))

    def test_cancelled_runtime_stream_cancels_the_capability(self) -> None:
        run_id = "prime-cancelled-run"
        manifest = json.loads(
            (Path(__file__).parents[1] / "src/asterion/capabilities/prime_agent/payload/capabilities/ipython-coding.json").read_text()
        )

        async def collect() -> tuple[RunEvent, ...]:
            return tuple(
                [
                    event
                    async for event in PrimeAgentRuntimeClient(
                        _VerificationService(PrimeSmallVerificationCancelled())
                    ).run(
                        RunRequest(
                            run_id=run_id,
                            input_text="fixed-small-verification",
                            requested_capabilities=("prime.tool.ipython",),
                        )
                    )
                ]
            )

        self.assertEqual(
            tuple(event.type for event in asyncio.run(collect())),
            ("run.started", "run.completed"),
        )

        async def execute() -> object:
            return await PrimeIpythonCodingImplementation().execute(
                CapabilityInvocation(
                    capability_ref=CapabilityRef("prime.ipython-coding", "1.0.0"),
                    manifest=manifest,
                    run_id=run_id,
                    input_text="fixed-small-verification",
                    upstream_artifacts=(),
                    runtime=PrimeAgentRuntimeClient(
                        _VerificationService(PrimeSmallVerificationCancelled())
                    ),
                    host_services={},
                )
            )

        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(execute())

    def test_host_failure_is_redacted_and_cancellation_is_rethrown(self) -> None:
        run_id = "prime-failure-run"

        async def collect(service: _VerificationService) -> tuple[RunEvent, ...]:
            return tuple(
                [
                    event
                    async for event in PrimeAgentRuntimeClient(service).run(
                        RunRequest(
                            run_id=run_id,
                            input_text="fixed-small-verification",
                            requested_capabilities=("prime.tool.ipython",),
                        )
                    )
                ]
            )

        sentinel = "SENTINEL-PRIME-HOST-SECRET"
        for failure, cancelled in (
            (RuntimeError(sentinel), False),
            (asyncio.CancelledError(), True),
        ):
            with self.subTest(failure=type(failure).__name__):
                if cancelled:
                    with self.assertRaises(asyncio.CancelledError):
                        asyncio.run(collect(_VerificationService(failure)))
                else:
                    events = asyncio.run(collect(_VerificationService(failure)))
                    self.assertEqual(events[-1].type, "run.failed")
                    self.assertNotIn(sentinel, repr(events))
