from __future__ import annotations

import unittest

from asterion.control.host import ControlCommand, EventCursor
from asterion.control.testing import (
    REQUIRED_PHASE0_SCENARIOS,
    ControlProviderConformanceError,
    FakeControlPlaneClient,
    run_control_provider_conformance,
)


def _create_command(*, command_id: str = "command-1", goal_ref: str = "goal-ref-1") -> ControlCommand:
    return ControlCommand(
        command_id=command_id,
        session_id="session-1",
        authority_revision=1,
        type="session.create",
        payload={
            "system_id": "research.system",
            "system_version": "1.0.0",
            "goal_id": "goal-1",
            "goal_ref": goal_ref,
        },
    )


async def _events(
    client: FakeControlPlaneClient,
    cursor: EventCursor | None = None,
) -> tuple[object, ...]:
    return tuple([event async for event in client.events(cursor)])


class TestControlConformance(unittest.IsolatedAsyncioTestCase):
    async def test_fake_provider_passes_every_required_phase0_scenario(self) -> None:
        report = await run_control_provider_conformance(FakeControlPlaneClient)

        self.assertEqual(report.failed, ())
        self.assertEqual(report.passed, tuple(sorted(REQUIRED_PHASE0_SCENARIOS)))

    async def test_command_replay_is_idempotent_and_divergence_fails_closed(self) -> None:
        client = FakeControlPlaneClient()
        command = _create_command()

        await client.send(command)
        await client.send(command)

        self.assertEqual(len(client.command_log), 1)
        self.assertEqual(len(await _events(client)), 2)
        with self.assertRaises(ControlProviderConformanceError):
            await client.send(_create_command(goal_ref="goal-ref-2"))

    async def test_attach_cursor_replays_exact_suffix_without_mutation(self) -> None:
        client = FakeControlPlaneClient()
        await client.send(_create_command())
        client.emit_goal_status("completed")
        client.emit_session_status("completed", reason_code="goal-accepted")

        suffix = await _events(client, EventCursor(generation=1, sequence=2))

        self.assertEqual(tuple(event.sequence for event in suffix), (3, 4))
        self.assertEqual(suffix[-1].type, "session.completed")
        with self.assertRaises(AttributeError):
            suffix[-1].sequence = 9  # type: ignore[misc]

    async def test_fault_injection_disconnects_then_replays_persisted_event(self) -> None:
        client = FakeControlPlaneClient(disconnect_after_sequence=2)
        await client.send(_create_command())
        client.emit_fault("provider-disconnected", recoverable=True)

        with self.assertRaises(ControlProviderConformanceError):
            await _events(client)
        client.disconnect_after_sequence = None
        replay = await _events(client, EventCursor(generation=1, sequence=2))

        self.assertEqual(tuple(event.sequence for event in replay), (3, 4))
        self.assertEqual(replay[-1].type, "session.recovery-required")

    async def test_delivery_modes_are_persisted_without_public_content(self) -> None:
        client = FakeControlPlaneClient()
        await client.send(_create_command())
        for index, delivery in enumerate(("direct", "steer", "follow_up"), start=2):
            await client.send(
                ControlCommand(
                    command_id=f"command-{index}",
                    session_id="session-1",
                    authority_revision=1,
                    type="input.submit",
                    payload={
                        "input_id": f"input-{index}",
                        "delivery": delivery,
                        "content_ref": f"content-ref-{index}",
                    },
                )
            )

        rendered = repr(client.command_log)
        self.assertEqual(
            tuple(command.payload["delivery"] for command in client.command_log[1:]),
            ("direct", "steer", "follow_up"),
        )
        self.assertNotIn("prompt", rendered)
        self.assertNotIn("SENTINEL_SECRET", rendered)


if __name__ == "__main__":
    unittest.main()
