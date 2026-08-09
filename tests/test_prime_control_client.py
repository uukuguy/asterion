from __future__ import annotations

import asyncio
import unittest
from collections.abc import AsyncIterator, Mapping

from asterion.control.host import ControlCommand, EventCursor
from asterion.control.providers.prime.client import (
    PrimeControlError,
    PrimeControlPlaneClient,
)


class FakeResolver:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.requests: list[tuple[str, int]] = []

    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        self.requests.append((reference, max_bytes))
        return self.values[reference]


class FakeProcess:
    def __init__(self) -> None:
        self.requests: list[Mapping[str, object]] = []
        self.event_requests: list[Mapping[str, object]] = []
        self.closed = 0
        self.failure: Exception | None = None
        self.close_failures = 0
        self.response: Mapping[str, object] | None = None
        self.event_values: list[Mapping[str, object]] = []

    def fail_with(self, message: str) -> None:
        self.failure = RuntimeError(message)

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        self.requests.append(envelope)
        if self.failure is not None:
            raise self.failure
        if self.response is not None:
            if self.response.get("id") == "<request>":
                return {**self.response, "id": envelope["id"]}
            return self.response
        return {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": envelope["id"],
            "type": "command.accepted",
        }

    def events(self, envelope: Mapping[str, object]) -> AsyncIterator[Mapping[str, object]]:
        self.event_requests.append(envelope)
        return self._events()

    async def _events(self) -> AsyncIterator[Mapping[str, object]]:
        for value in self.event_values:
            yield value

    async def close(self) -> None:
        self.closed += 1
        if self.close_failures > 0:
            self.close_failures -= 1
            raise RuntimeError("SENTINEL_CLOSE_FAILURE")


def create_command() -> ControlCommand:
    return ControlCommand(
        command_id="command-1",
        session_id="session-1",
        authority_revision=1,
        type="session.create",
        payload={
            "system_id": "research.system",
            "system_version": "1.0.0",
            "goal_id": "goal-1",
            "goal_ref": "goal-ref-1",
        },
    )


def input_command() -> ControlCommand:
    return ControlCommand(
        command_id="command-2",
        session_id="session-1",
        authority_revision=1,
        type="input.submit",
        payload={
            "input_id": "input-1",
            "delivery": "direct",
            "content_ref": "content-ref-1",
        },
    )


def event(sequence: int) -> Mapping[str, object]:
    return {
        "protocol": "asterion.agent-control/v1",
        "event_id": f"event-{sequence}",
        "session_id": "session-1",
        "generation": 1,
        "sequence": sequence,
        "emitted_at": f"2026-08-10T03:00:0{sequence}Z",
        "type": "session.running",
        "payload": {"reason_code": "started"},
    }


class TestPrimeControlClient(unittest.IsolatedAsyncioTestCase):
    async def test_command_is_accepted_only_after_sidecar_ack(self) -> None:
        fake_process = FakeProcess()
        resolver = FakeResolver()
        resolver.values["goal-ref-1"] = "private goal"
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=resolver,
        )

        await client.send(create_command())

        self.assertEqual(fake_process.requests[0]["command"]["command_id"], "command-1")  # type: ignore[index]
        self.assertEqual(fake_process.requests[0]["private"], {"goal": "private goal"})
        self.assertEqual(resolver.requests[0][0], "goal-ref-1")

    async def test_private_goal_is_not_rendered_on_sidecar_failure(self) -> None:
        fake_process = FakeProcess()
        resolver = FakeResolver()
        resolver.values["goal-ref-1"] = "SENTINEL_SECRET"
        fake_process.fail_with("SENTINEL_SECRET provider body")
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=resolver,
        )

        with self.assertRaises(PrimeControlError) as raised:
            await client.send(create_command())

        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    async def test_sidecar_error_response_is_recognized_and_redacted(self) -> None:
        fake_process = FakeProcess()
        resolver = FakeResolver()
        resolver.values["goal-ref-1"] = "SENTINEL_SECRET"
        fake_process.response = {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": "<request>",
            "type": "error",
            "code": "prime-gateway-sidecar-failed",
        }
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=resolver,
        )

        with self.assertRaises(PrimeControlError) as raised:
            await client.send(create_command())

        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    async def test_input_content_is_resolved_in_private_sidecar_field(self) -> None:
        fake_process = FakeProcess()
        resolver = FakeResolver()
        resolver.values["content-ref-1"] = "private input"
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=resolver,
        )

        await client.send(input_command())

        self.assertEqual(fake_process.requests[0]["private"], {"content": "private input"})

    async def test_events_use_exact_cursor_and_validate_public_events(self) -> None:
        fake_process = FakeProcess()
        fake_process.event_values = [event(3)]
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )

        replay = [
            item async for item in client.events(EventCursor(generation=1, sequence=2))
        ]

        self.assertEqual([item.sequence for item in replay], [3])
        self.assertEqual(
            fake_process.event_requests[0]["cursor"],
            {"generation": 1, "sequence": 2},
        )

    async def test_invalid_sidecar_event_fails_closed(self) -> None:
        fake_process = FakeProcess()
        fake_process.event_values = [{"type": "provider.payload", "body": "SENTINEL_SECRET"}]
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )

        with self.assertRaises(PrimeControlError) as raised:
            _ = [item async for item in client.events()]

        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    async def test_close_delegates_to_sidecar_once(self) -> None:
        fake_process = FakeProcess()
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )

        await client.close()
        await client.close()

        self.assertEqual(fake_process.closed, 1)

    async def test_close_is_retryable_after_transport_failure(self) -> None:
        fake_process = FakeProcess()
        fake_process.close_failures = 1
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )

        with self.assertRaises(PrimeControlError) as raised:
            await client.close()
        self.assertNotIn("SENTINEL_CLOSE_FAILURE", str(raised.exception))

        await client.close()

        self.assertEqual(fake_process.closed, 2)

    async def test_concurrent_close_shares_one_transport_close(self) -> None:
        fake_process = FakeProcess()
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )

        await asyncio.gather(client.close(), client.close())

        self.assertEqual(fake_process.closed, 1)


if __name__ == "__main__":
    unittest.main()
