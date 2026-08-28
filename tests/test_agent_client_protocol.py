from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from asterion.client.protocol import (
    AGENT_CLIENT_PROTOCOL,
    ClientEvent,
    ClientIntent,
    ClientProtocolError,
    validate_client_event,
    validate_client_event_stream,
    validate_client_intent,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "agent_client" / "v1"


def _fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text())
    assert isinstance(value, dict)
    return value


class TestAgentClientProtocol(unittest.TestCase):
    def test_valid_values_are_immutable_and_body_free(self) -> None:
        intent = ClientIntent.from_mapping(_fixture("valid-intent-input.json"))
        event = ClientEvent.from_mapping(_fixture("valid-event-message.json"))

        self.assertEqual(AGENT_CLIENT_PROTOCOL, "asterion.agent-client/v1")
        self.assertEqual(intent.protocol, "asterion.agent-client/v1")
        self.assertEqual(event.payload["content_ref"], "private-message-1")
        self.assertNotIn("SENTINEL_BODY", repr(event))
        with self.assertRaises(TypeError):
            event.payload["content_ref"] = "changed"  # type: ignore[index]

    def test_invalid_values_fail_closed_without_echoing_bodies(self) -> None:
        for name, validate in (
            ("invalid-intent-secret.json", validate_client_intent),
            ("invalid-event-body.json", validate_client_event),
            ("invalid-event-unknown.json", validate_client_event),
        ):
            with self.subTest(name=name), self.assertRaises(ClientProtocolError) as raised:
                validate(_fixture(name))
            self.assertNotIn("SENTINEL_BODY", str(raised.exception))

    def test_stream_rejects_gap_mixed_generation_and_post_terminal(self) -> None:
        first = ClientEvent.from_mapping(_fixture("valid-event-message.json"))
        terminal = ClientEvent.from_mapping(_fixture("valid-event-terminal.json"))
        validate_client_event_stream((first, terminal))

        for stream in (
            (first, replace(terminal, sequence=3)),
            (first, replace(terminal, generation=2)),
            (first, replace(terminal, event_id=first.event_id)),
            (first, terminal, replace(terminal, event_id="event-3", sequence=3)),
        ):
            with self.subTest(stream=stream), self.assertRaises(ClientProtocolError):
                validate_client_event_stream(stream)

    def test_stream_rejects_unmatched_tool_calls(self) -> None:
        first = ClientEvent.from_mapping(_fixture("valid-event-message.json"))
        terminal = ClientEvent.from_mapping(_fixture("valid-event-terminal.json"))
        completed = replace(
            first,
            event_id="event-2",
            sequence=2,
            type="tool.completed",
            payload={
                "call_id": "call-1",
                "is_error": False,
                "media_type": "application/json",
                "result_ref": "private-result-1",
                "sha256": "b" * 64,
                "size": 2,
            },
        )
        with self.assertRaises(ClientProtocolError):
            validate_client_event_stream((first, completed, replace(terminal, sequence=3)))


if __name__ == "__main__":
    unittest.main()
