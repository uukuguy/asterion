"""Installed independent route for the finite P7 solver action."""

from __future__ import annotations

import asyncio
import unittest

from asterion.applications.prime_agent.provider import create_provider
from asterion.applications.prime_agent.runtime_binding import prime_runtime_binding
from asterion.applications.provider import resolve_installed_provider
from asterion.applications.first_party_packages import create_prime_arc_agi_3_solver_package
from asterion.capabilities.prime_agent.provider import create_prime_agent_package
from asterion.capabilities.prime_arc_agi_3_solver.host import PrimeArcAgi3SolveReceipt
from asterion.runner.composed import run_composed_application
from asterion.runner.application import ApplicationRunError
from asterion.runtime.defaults import default_runtime_factory_registry
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError
from asterion.runtimes.prime_agent_host import (
    PrimePresetExecutionRequest,
    PrimePresetExecutionResult,
)
from asterion.assembly.protocol import AssemblyError, resolve_assembly
from asterion.capabilities.catalog import CapabilityCatalog, CatalogEntry, CapabilityRef
from pathlib import Path


class _SolverHost:
    def __init__(
        self,
        receipt: PrimeArcAgi3SolveReceipt,
        *,
        execution_digest: str | None = None,
        retrieved_receipt: PrimeArcAgi3SolveReceipt | None = None,
    ) -> None:
        self.receipt = receipt
        self.execution_digest = execution_digest or receipt.receipt_sha256
        self.retrieved_receipt = retrieved_receipt or receipt
        self.requests: list[PrimePresetExecutionRequest] = []

    async def execute(self, request: PrimePresetExecutionRequest, *, signal=None):
        del signal
        self.requests.append(request)
        return PrimePresetExecutionResult(
            run_id=request.run_id,
            receipt_sha256=self.execution_digest,
            scope="p7-solving",
            promotion="unpromoted",
        )

    def get_receipt(self, *, run_id: str, receipt_sha256: str) -> PrimeArcAgi3SolveReceipt:
        del run_id, receipt_sha256
        return self.retrieved_receipt


class TestPrimeP7SolvingInstalledRoute(unittest.TestCase):
    def test_host_capability_overlap_is_limited_to_exact_self_provider(self) -> None:
        def plan(capability_id: str, provided: str, host: str, runtime: list[str]):
            manifest = {
                "protocol": "asterion.capability/v1", "capability_id": capability_id,
                "version": "1.0.0", "kind": "capability",
                "provides_capabilities": [provided], "requires_capabilities": [],
                "requires_policies": [], "emits_events": [], "consumes_events": [],
                "produces_artifacts": [], "consumes_artifacts": [],
            }
            catalog = CapabilityCatalog((CatalogEntry(
                CapabilityRef(capability_id, "1.0.0"), Path(__file__), manifest,
            ),))
            return resolve_assembly({
                "protocol": "asterion.application-assembly/v1", "application_id": "solve.test",
                "version": "1.0.0", "runtime_id": "prime.agent",
                "capability_packages": [{"package_id": "solve-package", "version": "1.0.0"}],
                "capabilities": [{"capability_id": capability_id, "version": "1.0.0"}],
                "host_capabilities": [host], "host_policies": [], "host_events": [], "host_artifacts": [],
            }, catalog=catalog, runtime_manifest={
                "protocol": "asterion.agent-runtime/v1", "runtime_id": "prime.agent", "capabilities": runtime,
            })

        self.assertEqual(
            plan("solve.self", "solve.self", "solve.self", []).host_capabilities,
            ("solve.self",),
        )
        for args in (
            ("solve.self", "solve.alias", "solve.alias", []),
            ("solve.self", "runtime.shared", "unrelated.host", ["runtime.shared"]),
        ):
            with self.subTest(args=args), self.assertRaises(AssemblyError):
                plan(*args)
    def _application(self):
        resolved = resolve_installed_provider(
            create_provider(),
            runtime_factories=default_runtime_factory_registry(),
            installed_packages=(
                create_prime_agent_package(), create_prime_arc_agi_3_solver_package(),
            ),
        )
        return next(
            item for item in resolved.applications
            if item.application_id == "prime.arc-agi-3-solving"
        )

    def test_resolves_and_projects_only_the_allowlisted_receipt(self) -> None:
        application = self._application()
        assembly = application.assemblies[0]
        receipt = PrimeArcAgi3SolveReceipt.create(
            run_id="prime-p7-solve-route", completed_level_count=1,
            primitive_action_count=22, partial_game_score="3.571429",
        )
        host = _SolverHost(receipt)
        runtime = prime_runtime_binding().factory(RuntimeFactoryContext(
            provider_id="prime-agent", application_id="prime.arc-agi-3-solving",
            application_version="1.0.0", runtime_id="prime.agent", assembly_path=assembly.path,
            options={}, host_services={"prime.arc-agi-3-solving": host},
        ))
        result = asyncio.run(run_composed_application(
            assembly.plan, implementations=application.implementations, runtime=runtime,
            run_id=receipt.run_id, input_text="solve-first-public-level",
            host_services={"prime.arc-agi-3-solving": host},
        ))
        self.assertEqual(host.requests, [PrimePresetExecutionRequest(receipt.run_id, "solve-first-public-level")])
        self.assertEqual(result.artifacts, ({
            "artifact_id": "prime.p7-solving.receipt",
            "media_type": "application/vnd.asterion.prime.p7-solving-receipt+json",
            "value": {"scope": "p7-solving", "promotion": "unpromoted",
                      "receipt_sha256": receipt.receipt_sha256.removeprefix("sha256:"),
                      "completed_level_count": 1, "primitive_action_count": 22,
                      "partial_game_score": "3.571429"},
        },))

    def test_rejects_a_preset_service_without_the_receipt_accessor(self) -> None:
        class ExecuteOnly:
            async def execute(self, request, *, signal=None):
                del signal
                return PrimePresetExecutionResult(
                    run_id=request.run_id, receipt_sha256="sha256:" + "a" * 64,
                    scope="p7-solving", promotion="unpromoted",
                )

        application = self._application()
        assembly = application.assemblies[0]
        host = ExecuteOnly()
        runtime = prime_runtime_binding().factory(RuntimeFactoryContext(
            provider_id="prime-agent", application_id="prime.arc-agi-3-solving",
            application_version="1.0.0", runtime_id="prime.agent", assembly_path=assembly.path,
            options={}, host_services={"prime.arc-agi-3-solving": host},
        ))
        with self.assertRaises(ApplicationRunError):
            asyncio.run(run_composed_application(
                assembly.plan, implementations=application.implementations, runtime=runtime,
                run_id="prime-p7-missing-accessor", input_text="solve-first-public-level",
                host_services={"prime.arc-agi-3-solving": host},
            ))

    def test_rejects_receipt_run_and_digest_mismatches(self) -> None:
        application = self._application()
        assembly = application.assemblies[0]
        receipt = PrimeArcAgi3SolveReceipt.create(
            run_id="prime-p7-solve-route", completed_level_count=1,
            primitive_action_count=22, partial_game_score="3.571429",
        )
        other = PrimeArcAgi3SolveReceipt.create(
            run_id="other-run", completed_level_count=1,
            primitive_action_count=22, partial_game_score="3.571429",
        )
        for host in (
            _SolverHost(receipt, retrieved_receipt=other),
            _SolverHost(receipt, execution_digest="sha256:" + "a" * 64),
        ):
            with self.subTest(host=host):
                runtime = prime_runtime_binding().factory(RuntimeFactoryContext(
                    provider_id="prime-agent", application_id="prime.arc-agi-3-solving",
                    application_version="1.0.0", runtime_id="prime.agent", assembly_path=assembly.path,
                    options={}, host_services={"prime.arc-agi-3-solving": host},
                ))
                with self.assertRaises(ApplicationRunError):
                    asyncio.run(run_composed_application(
                        assembly.plan, implementations=application.implementations, runtime=runtime,
                        run_id=receipt.run_id, input_text="solve-first-public-level",
                        host_services={"prime.arc-agi-3-solving": host},
                    ))

    def test_runtime_requires_the_exact_preset_service(self) -> None:
        with self.assertRaises(RuntimeFactoryError):
            prime_runtime_binding().factory(RuntimeFactoryContext(
                provider_id="prime-agent", application_id="prime.arc-agi-3-solving",
                application_version="1.0.0", runtime_id="prime.agent", assembly_path=Path(__file__),
                options={}, host_services={"prime.arc-agi-3-solving": object()},
            ))


if __name__ == "__main__":
    unittest.main()
