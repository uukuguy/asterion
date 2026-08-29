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

    def test_rejects_impossible_timestamps(self) -> None:
        event = _fixture("valid-event-message.json")
        for emitted_at in ("0000-01-01T00:00:00Z", "2026-02-30T15:00:00Z"):
            with self.subTest(emitted_at=emitted_at), self.assertRaises(ClientProtocolError):
                validate_client_event({**event, "emitted_at": emitted_at})

    def test_rejects_unsafe_integer_values(self) -> None:
        unsafe_integer = 9_007_199_254_740_992
        intent_cases = (
            {**_fixture("valid-intent-input.json"), "authority_revision": unsafe_integer},
            {
                **_fixture("valid-intent-input.json"),
                "type": "command.invoke",
                "payload": {
                    "arguments_ref": "arguments-1",
                    "command_name": "command",
                    "command_revision": unsafe_integer,
                },
            },
            {
                **_fixture("valid-intent-input.json"),
                "type": "export.request",
                "payload": {
                    "destination_ref": "destination-1",
                    "expires_at_ms": unsafe_integer,
                    "export_id": "export-1",
                    "max_bytes": unsafe_integer,
                    "media_type": "application/json",
                    "reference_ids": ["reference-1"],
                    "visibility": "private",
                },
            },
            {
                **_fixture("valid-intent-input.json"),
                "type": "session.attach",
                "payload": {"cursor": {"generation": unsafe_integer, "sequence": unsafe_integer}},
            },
            {
                **_fixture("valid-intent-input.json"),
                "type": "share.request",
                "payload": {"expires_at_ms": unsafe_integer, "export_id": "export-1", "share_id": "share-1"},
            },
        )
        event_cases = (
            {**_fixture("valid-event-message.json"), "generation": unsafe_integer},
            {**_fixture("valid-event-message.json"), "sequence": unsafe_integer},
            {
                **_fixture("valid-event-message.json"),
                "type": "artifact.available",
                "payload": {"artifact_id": "artifact-1", "artifact_ref": "artifact-ref-1", "media_type": "application/json", "sha256": "a" * 64, "size": unsafe_integer},
            },
            {
                **_fixture("valid-event-message.json"),
                "type": "commands.changed",
                "payload": {"commands": ["command"], "revision": unsafe_integer},
            },
            {
                **_fixture("valid-event-message.json"),
                "type": "extension-ui.requested",
                "payload": {"deadline_ms": unsafe_integer, "method": "request", "payload_ref": "payload-1", "request_id": "request-1"},
            },
            {
                **_fixture("valid-event-message.json"),
                "type": "usage.reported",
                "payload": {"aggregate_tokens": unsafe_integer, "application_tokens": unsafe_integer, "child_tokens": unsafe_integer, "controller_tokens": unsafe_integer, "cost_micros": unsafe_integer},
            },
        )

        for value in (*intent_cases, *event_cases):
            with self.subTest(value=value), self.assertRaises(ClientProtocolError):
                if "intent_id" in value:
                    validate_client_intent(value)
                else:
                    validate_client_event(value)

    def test_stream_rejects_reused_completed_tool_call_id(self) -> None:
        message = _fixture("valid-event-message.json")
        terminal = _fixture("valid-event-terminal.json")
        started = {
            **message,
            "event_id": "event-1",
            "sequence": 1,
            "type": "tool.started",
            "payload": {"arguments_ref": "arguments-1", "call_id": "call-1", "name": "tool", "sha256": "a" * 64, "size": 1},
        }
        completed = {
            **message,
            "event_id": "event-2",
            "sequence": 2,
            "type": "tool.completed",
            "payload": {"call_id": "call-1", "is_error": False, "media_type": "application/json", "result_ref": "result-1", "sha256": "b" * 64, "size": 1},
        }
        repeated_start = {**started, "event_id": "event-3", "sequence": 3}
        repeated_complete = {**completed, "event_id": "event-4", "sequence": 4}
        terminal = {**terminal, "event_id": "event-5", "sequence": 5}

        with self.assertRaises(ClientProtocolError):
            validate_client_event_stream((started, completed, repeated_start, repeated_complete, terminal))

    def test_direct_construction_redacts_non_mapping_payloads(self) -> None:
        intent = _fixture("valid-intent-input.json")
        event = _fixture("valid-event-message.json")
        for cls, value in ((ClientIntent, intent), (ClientEvent, event)):
            with self.subTest(cls=cls), self.assertRaises(ClientProtocolError) as raised:
                cls(**{**value, "payload": []})  # type: ignore[arg-type]
            self.assertEqual(str(raised.exception), "client payload is invalid")


if __name__ == "__main__":
    unittest.main()
