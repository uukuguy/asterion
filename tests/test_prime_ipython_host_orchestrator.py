"""Provider-free tests for the closed P1 trusted host orchestration path."""

from __future__ import annotations

import unittest
from typing import Any, cast

import asterion.applications.prime_agent.operator.ipython_host_orchestrator as subject
class _StructuralFake:
    async def snapshot(self, lease: object) -> object:
        del lease
        return object()

    async def brokered_cell(self, lease: object) -> object:
        del lease
        return object()

    async def revoke_broker(self, lease: object) -> None:
        del lease

    async def force_remove(self, lease: object) -> None:
        del lease

    async def assert_absent(self, lease: object) -> None:
        del lease


class TestIpythonHostOrchestrator(unittest.TestCase):
    def test_structural_adapter_cannot_mint_a_public_pass(self) -> None:
        self.assertFalse(hasattr(subject, "run_ipython_host_orchestration"))
        with self.assertRaises(subject.IpythonHostOrchestrationError):
            subject.IpythonHostLiveRun()  # type: ignore[call-arg]

    def test_private_operation_token_rejects_manual_or_structural_values(self) -> None:
        fake = _StructuralFake()
        with self.assertRaises(subject.IpythonHostOrchestrationError):
            subject._IpythonHostOperations(  # noqa: SLF001 - adversarial boundary test
                _seal=object(), snapshot=cast(Any, fake.snapshot), brokered_cell=cast(Any, fake.brokered_cell),
                revoke_broker=fake.revoke_broker, force_remove=fake.force_remove,
                assert_absent=fake.assert_absent,
            )

    def test_public_surface_exports_no_generic_adapter_or_runner(self) -> None:
        self.assertEqual(subject.__all__, ("IpythonHostOrchestrationError", "IpythonHostLiveRun"))
        self.assertFalse(hasattr(subject, "_IpythonHostAdapter"))
