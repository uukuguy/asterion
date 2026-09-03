from __future__ import annotations

import unittest

from asterion.applications.prime_agent.bounded_autonomy_gate import (
    BoundedAutonomyGateError,
    run_bounded_autonomy_gate,
)


class _Gate:
    def __init__(self) -> None:
        self.calls = 0

    async def evaluate(self, workspace_sha256: str) -> tuple[bool, str]:
        self.calls += 1
        return False, "sha256:" + "a" * 64


class _FailingGate:
    async def evaluate(self, workspace_sha256: str) -> tuple[bool, str]:
        raise RuntimeError("private gate failure")


class TestBoundedAutonomyGate(unittest.IsolatedAsyncioTestCase):
    async def test_redacts_unexpected_gate_failures(self) -> None:
        with self.assertRaisesRegex(BoundedAutonomyGateError, "gate is invalid"):
            await run_bounded_autonomy_gate(
                _FailingGate(), "sha256:" + "b" * 64, frozenset()
            )

    async def test_rejects_seen_workspace_before_gate_access(self) -> None:
        gate = _Gate()
        digest = "sha256:" + "b" * 64

        with self.assertRaises(BoundedAutonomyGateError):
            await run_bounded_autonomy_gate(gate, digest, frozenset({digest}))

        self.assertEqual(gate.calls, 0)

    async def test_normalizes_one_new_workspace_gate_result(self) -> None:
        result = await run_bounded_autonomy_gate(
            _Gate(), "sha256:" + "b" * 64, frozenset()
        )
        self.assertFalse(result.passed)
