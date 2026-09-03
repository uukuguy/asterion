from __future__ import annotations

import unittest

from asterion.applications.prime_agent.bounded_autonomy_acceptance import (
    BoundedAutonomyAcceptanceError,
    accept_bounded_autonomy,
)
from asterion.applications.prime_agent.bounded_autonomy_receipt import (
    BoundedAutonomyTrace,
)
from asterion.applications.prime_agent.operator.bounded_autonomy_workload import (
    P5_BOUNDED_AUTONOMY_MODEL_SHA256,
    P5_BOUNDED_AUTONOMY_ORACLE_SHA256,
    P5_BOUNDED_AUTONOMY_SCHEMA_SHA256,
    P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST,
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _trace() -> BoundedAutonomyTrace:
    return BoundedAutonomyTrace(
        P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST, _digest("b"), _digest("c"), _digest("d"), _digest("e"),
        P5_BOUNDED_AUTONOMY_ORACLE_SHA256, P5_BOUNDED_AUTONOMY_MODEL_SHA256, P5_BOUNDED_AUTONOMY_SCHEMA_SHA256, ("ipython",), 2, 2, 2, 1,
        True, True, True, True, True, True,
    )


class _Gate:
    def __init__(self, results: tuple[tuple[bool, str], ...]) -> None:
        self.results = list(results)
        self.workspaces: list[str] = []

    async def evaluate(self, workspace_sha256: str) -> tuple[bool, str]:
        self.workspaces.append(workspace_sha256)
        return self.results.pop(0)


class TestBoundedAutonomyAcceptance(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_one_failed_gate_then_one_repaired_passing_gate(self) -> None:
        trace = _trace()
        gate = _Gate(((False, _digest("2")), (True, trace.gate_result_sha256)))

        receipt = await accept_bounded_autonomy(
            gate=gate,
            first_workspace=trace.initial_workspace_sha256,
            second_workspace=trace.repaired_workspace_sha256,
            trace=trace,
            disposed=True,
            reaped=True,
        )

        self.assertEqual(receipt.scenario_id, "prime.bounded-autonomy/v1")
        self.assertEqual(receipt.level.value, "provider-free")
        self.assertEqual(
            gate.workspaces,
            [trace.initial_workspace_sha256, trace.repaired_workspace_sha256],
        )

    async def test_rejects_invalid_inputs_before_injected_services(self) -> None:
        with self.assertRaises(BoundedAutonomyAcceptanceError):
            await accept_bounded_autonomy(
                gate=object(), first_workspace=object(), second_workspace=object(),
                trace=object(), disposed=True, reaped=True,
            )
