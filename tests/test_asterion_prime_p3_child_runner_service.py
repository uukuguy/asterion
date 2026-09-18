"""Tests for prime.child-runner host service (Phase 7, Task 3)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
import unittest

from asterion.applications.prime.services import (
    ChildAdmission,
    ChildAdmissionRefused,
    ChildRunnerHostService,
    create_child_runner_host_service,
)
from asterion.services.progress import NOOP_HOST_PROGRESS_REPORTER
from asterion.services.presentation import NOOP_HOST_PRESENTATION_SINK
from asterion.services.registry import HostServiceFactoryContext


def _context(
    options: dict[str, str] | None = None,
) -> HostServiceFactoryContext:
    return HostServiceFactoryContext(
        provider_id="prime-applications",
        application_id="prime.recursive-workflow",
        application_version="1.0.0",
        capability_id="prime.child-runner",
        options=options if options is not None else {},
        progress=NOOP_HOST_PROGRESS_REPORTER,
        presentation=NOOP_HOST_PRESENTATION_SINK,
    )


@dataclass(frozen=True)
class _StubChildReceipt:
    """Duck-typed receipt carrying the join inputs the host service reads."""

    root_result_sha256: str
    result_sha256: str
    depth_reached: int


def _child_identity():
    """Return a real :class:`PrimeBackendIdentity` instance for the child."""

    from asterion.agents.prime.state import PrimeBackendIdentity

    return PrimeBackendIdentity(
        session_id="prime.recursive-workflow.child",
        generation=2,
        provider_id="prime-applications",
        application_id="prime.recursive-workflow",
        application_version="1.0.0",
        runtime_id="asterion.prime",
        pi_command_sha256="0" * 64,
        extension_binding_fingerprint="0" * 64,
        worker_identity_sha256="0" * 64,
        continuation_id="continuation-test",
        private_root_identity="0" * 64,
        ceilings_sha256="0" * 64,
    )


async def _open_with_defaults():
    factory = create_child_runner_host_service().factory
    return factory(_context())


class TestChildRunnerHostService(unittest.TestCase):
    def test_service_exposes_public_identity_without_leaking_private_root(self) -> None:
        async def driver():
            factory = create_child_runner_host_service().factory
            async with factory(_context()) as service:
                self.assertIsInstance(service, ChildRunnerHostService)
                public = service.public_identity
                self.assertEqual(public.provider_id, "prime-applications")
                self.assertEqual(
                    public.application_id, "prime.recursive-workflow"
                )
                self.assertEqual(public.runtime_id, "asterion.prime")
                self.assertEqual(public.session_id, "prime.child-runner")
                self.assertEqual(public.generation, 1)
                # No private root field is exposed on the projection.
                self.assertNotIn("private_root", vars(public))
                self.assertNotIn("private_root_identity", vars(public))
                # The projection must never expose a private-root-style
                # digest through any of its other fields either.
                self.assertEqual(public.pi_command_sha256, "0" * 64)
                self.assertEqual(public.extension_binding_fingerprint, "0" * 64)
                self.assertEqual(public.worker_identity_sha256, "0" * 64)

        asyncio.run(driver())

    def test_service_admits_child_at_depth_two(self) -> None:
        async def driver():
            async with await _open_with_defaults() as service:
                outcome = await service.admit_child(
                    parent_run_id="root-run-1",
                    depth=2,
                    child_identity=_child_identity(),
                )
                self.assertIsInstance(outcome, ChildAdmission)
                self.assertEqual(outcome.admitted_at_depth, 2)
                self.assertEqual(outcome.child_run_id, "root-run-1.child-1")
                self.assertEqual(
                    outcome.child_identity.session_id,
                    "prime.recursive-workflow.child",
                )

        asyncio.run(driver())

    def test_service_refuses_depth_three_with_depth_exceeded(self) -> None:
        async def driver():
            async with await _open_with_defaults() as service:
                outcome = await service.admit_child(
                    parent_run_id="root-run-1",
                    depth=3,
                    child_identity=_child_identity(),
                )
                self.assertIsInstance(outcome, ChildAdmissionRefused)
                self.assertEqual(outcome.refusal_reason, "depth-exceeded")
                self.assertEqual(outcome.attempted_depth, 3)
                self.assertTrue(outcome.attempted_at)

        asyncio.run(driver())

    def test_service_refuses_concurrent_two_with_concurrency_exceeded(self) -> None:
        async def driver():
            # Lower the depth ceiling so concurrency kicks in before depth
            # by passing an explicit large-depth default and a one-slot
            # concurrent ceiling (the spec default).
            async with await _open_with_defaults() as service:
                first = await service.admit_child(
                    parent_run_id="root-run-1",
                    depth=2,
                    child_identity=_child_identity(),
                )
                self.assertIsInstance(first, ChildAdmission)
                # Service is configured with max_concurrent_children=1 by
                # default, so the second admission at the same depth must
                # be refused for concurrency, not for depth.
                second = await service.admit_child(
                    parent_run_id="root-run-1",
                    depth=2,
                    child_identity=_child_identity(),
                )
                self.assertIsInstance(second, ChildAdmissionRefused)
                self.assertEqual(second.refusal_reason, "concurrency-exceeded")
                self.assertEqual(second.attempted_depth, 2)

        asyncio.run(driver())

    def test_service_refuses_budget_exhausted_with_budget_exceeded(self) -> None:
        async def driver():
            async with await _open_with_defaults() as service:
                # Spend the entire budget on the first child so the next
                # admission must refuse with ``budget-exceeded``.
                admitted = await service.admit_child(
                    parent_run_id="root-run-1",
                    depth=2,
                    child_identity=_child_identity(),
                )
                self.assertIsInstance(admitted, ChildAdmission)
                service.record_child_cost(Decimal("0.10"), child_run_id=admitted.child_run_id)
                # The slot must be freed for the next attempt to surface
                # the budget reason rather than the concurrency reason.
                outcome = await service.admit_child(
                    parent_run_id="root-run-1",
                    depth=2,
                    child_identity=_child_identity(),
                )
                self.assertIsInstance(outcome, ChildAdmissionRefused)
                self.assertEqual(outcome.refusal_reason, "budget-exceeded")
                self.assertEqual(outcome.attempted_depth, 2)

        asyncio.run(driver())

    def test_join_child_result_is_digest_stable(self) -> None:
        async def driver():
            async with await _open_with_defaults() as service:
                receipt = _StubChildReceipt(
                    root_result_sha256="a" * 64,
                    result_sha256="b" * 64,
                    depth_reached=2,
                )
                first = await service.join_child_result(
                    parent_run_id="root-run-1",
                    child_receipt=receipt,
                )
                second = await service.join_child_result(
                    parent_run_id="root-run-1",
                    child_receipt=receipt,
                )
                self.assertEqual(first, second)
                self.assertEqual(len(first), 64)

                # Any change in any of the three inputs must change the
                # digest; verify one shift per field.
                with self.subTest("root_result_sha256 change"):
                    alt = await service.join_child_result(
                        parent_run_id="root-run-1",
                        child_receipt=_StubChildReceipt(
                            root_result_sha256="c" * 64,
                            result_sha256="b" * 64,
                            depth_reached=2,
                        ),
                    )
                    self.assertNotEqual(alt, first)
                with self.subTest("child_result_sha256 change"):
                    alt = await service.join_child_result(
                        parent_run_id="root-run-1",
                        child_receipt=_StubChildReceipt(
                            root_result_sha256="a" * 64,
                            result_sha256="d" * 64,
                            depth_reached=2,
                        ),
                    )
                    self.assertNotEqual(alt, first)
                with self.subTest("depth_reached change"):
                    alt = await service.join_child_result(
                        parent_run_id="root-run-1",
                        child_receipt=_StubChildReceipt(
                            root_result_sha256="a" * 64,
                            result_sha256="b" * 64,
                            depth_reached=3,
                        ),
                    )
                    self.assertNotEqual(alt, first)

        asyncio.run(driver())


if __name__ == "__main__":
    unittest.main()
