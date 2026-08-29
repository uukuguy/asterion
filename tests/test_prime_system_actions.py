from __future__ import annotations

import unittest

from asterion.control.authority import BudgetUsage
from asterion.control.execution import ActionExecutionFailure
from asterion.control.host import ControlCommand, ControlEvent
from asterion.control.providers.prime.system_actions import PrimeSystemActionService


class MutableSignal:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled


class RecordingClient:
    def __init__(self) -> None:
        self.commands: list[ControlCommand] = []

    async def send(self, command: ControlCommand) -> None:
        self.commands.append(command)


def _proposal(kind: str) -> ControlEvent:
    target = (
        {"kind": "checkpoint", "checkpoint_id": "checkpoint-1"}
        if kind == "checkpoint.create"
        else {"kind": "goal", "goal_id": "goal-1"}
    )
    return ControlEvent(
        event_id="event-1",
        session_id="session-1",
        generation=1,
        sequence=1,
        emitted_at="2026-08-10T03:00:00Z",
        type="action.proposed",
        payload={
            "action_id": "action-1",
            "authority_revision": 7,
            "idempotency_key": "idempotency-1",
            "kind": kind,
            "target": target,
            "input_ref": "private-input-1",
            "expected_artifacts": (),
            "budget": {
                "controller_tokens": 0,
                "application_tokens": 0,
                "child_tokens": 0,
                "aggregate_tokens": 0,
                "cost_micros": 0,
                "deadline_ms": 1000,
            },
            "causal_parent_ids": ("goal-1",),
        },
    )


class TestPrimeSystemActionService(unittest.IsolatedAsyncioTestCase):
    async def test_checkpoint_action_defers_materialization_to_gateway_terminal(self) -> None:
        client = RecordingClient()
        service = PrimeSystemActionService(client)

        receipt = await service.execute(
            _proposal("checkpoint.create"), MutableSignal()
        )

        self.assertEqual(receipt.action_id, "action-1")
        self.assertEqual(receipt.usage, BudgetUsage.zero())
        self.assertEqual(receipt.artifact_ids, ())
        self.assertEqual(receipt.media_types, ())
        self.assertEqual(client.commands, [])

    async def test_goal_actions_are_zero_usage_terminal_intents(self) -> None:
        for kind in ("goal.complete", "goal.fail"):
            with self.subTest(kind=kind):
                client = RecordingClient()
                receipt = await PrimeSystemActionService(client).execute(
                    _proposal(kind), MutableSignal()
                )
                self.assertEqual(receipt.action_id, "action-1")
                self.assertEqual(receipt.usage, BudgetUsage.zero())
                self.assertEqual(client.commands, [])
                self.assertEqual(receipt.receipt_ref, f"system-{kind}-action-1")

    async def test_cancellation_fails_closed_before_checkpoint_terminal(self) -> None:
        service = PrimeSystemActionService(RecordingClient())
        with self.assertRaises(ActionExecutionFailure) as cancelled:
            await service.execute(
                _proposal("checkpoint.create"), MutableSignal(cancelled=True)
            )
        self.assertEqual(cancelled.exception.status, "cancelled")
        self.assertIsNone(cancelled.exception.receipt_ref)



if __name__ == "__main__":
    unittest.main()
