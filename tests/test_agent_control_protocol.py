from __future__ import annotations

import json
import unittest
from pathlib import Path

from asterion.control import protocol as control_protocol


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "agent_control" / "v1"
COMMAND_SCHEMA = ROOT / "schemas" / "agent-control" / "v1" / "command.schema.json"
EVENT_SCHEMA = ROOT / "schemas" / "agent-control" / "v1" / "event.schema.json"
def _fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text())
    assert isinstance(value, dict)
    return value


class TestAgentControlProtocol(unittest.TestCase):
    def test_protocol_identity_is_asterion_owned(self) -> None:
        self.assertEqual(
            control_protocol.AGENT_CONTROL_PROTOCOL,
            "asterion.agent-control/v1",
        )

    def test_valid_commands_are_discriminated_and_recursively_immutable(self) -> None:
        create_source = _fixture("valid-command-session-create.json")
        resolve_source = _fixture("valid-command-action-resolve.json")

        create = control_protocol.validate_control_command(create_source)
        resolution = control_protocol.validate_control_command(resolve_source)

        self.assertEqual(create["type"], "session.create")
        self.assertEqual(create["payload"]["goal_ref"], "goal-ref-1")
        self.assertEqual(resolution["payload"]["resolution"], "succeeded")
        with self.assertRaises(TypeError):
            create["payload"]["goal_ref"] = "changed"  # type: ignore[index]
        create_source["command_id"] = "changed"
        self.assertEqual(create["command_id"], "command-1")

    def test_valid_events_are_discriminated_and_recursively_immutable(self) -> None:
        proposed_source = _fixture("valid-event-action-proposed.json")
        terminal_source = _fixture("valid-event-terminal.json")

        proposed = control_protocol.validate_control_event(proposed_source)
        terminal = control_protocol.validate_control_event(terminal_source)

        self.assertEqual(proposed["type"], "action.proposed")
        self.assertEqual(proposed["payload"]["authority_revision"], 1)
        self.assertEqual(
            proposed["payload"]["target"]["application_id"],
            "alpha",
        )
        self.assertEqual(terminal["type"], "session.completed")
        self.assertIsInstance(proposed["payload"]["causal_parent_ids"], tuple)
        with self.assertRaises(TypeError):
            proposed["payload"]["target"]["application_id"] = "changed"  # type: ignore[index]

    def test_action_proposal_requires_the_expected_authority_revision(self) -> None:
        proposed = _fixture("valid-event-action-proposed.json")
        payload = proposed["payload"]
        assert isinstance(payload, dict)
        without_revision = {key: value for key, value in payload.items() if key != "authority_revision"}

        with self.assertRaises(control_protocol.ControlProtocolError):
            control_protocol.validate_control_event(
                {**proposed, "payload": without_revision}
            )

    def test_complete_stream_requires_one_identity_generation_and_terminal(self) -> None:
        events = (
            control_protocol.validate_control_event(
                {
                    **_fixture("valid-event-terminal.json"),
                    "event_id": "event-1",
                    "sequence": 1,
                    "type": "session.created",
                    "payload": {
                        "goal_id": "goal-1",
                        "authority_id": "authority-1",
                        "authority_revision": 1,
                    },
                }
            ),
            control_protocol.validate_control_event(
                {
                    **_fixture("valid-event-terminal.json"),
                    "event_id": "event-2",
                    "sequence": 2,
                    "type": "session.running",
                    "payload": {"reason_code": "started"},
                }
            ),
            control_protocol.validate_control_event(
                _fixture("valid-event-terminal.json")
            ),
        )

        snapshot = control_protocol.validate_control_event_stream(events)

        self.assertEqual(tuple(event["sequence"] for event in snapshot), (1, 2, 3))
        self.assertEqual(snapshot[-1]["type"], "session.completed")

    def test_rejects_gaps_mixed_sessions_and_multiple_terminals(self) -> None:
        terminal = _fixture("valid-event-terminal.json")
        started = {
            **terminal,
            "event_id": "event-1",
            "sequence": 1,
            "type": "session.created",
            "payload": {
                "goal_id": "goal-1",
                "authority_id": "authority-1",
                "authority_revision": 1,
            },
        }
        cases = (
            (started, {**terminal, "sequence": 4}),
            (started, {**terminal, "session_id": "session-2"}),
            (
                started,
                terminal,
                {
                    **terminal,
                    "event_id": "event-4",
                    "sequence": 4,
                    "type": "session.failed",
                    "payload": {"reason_code": "provider-failed"},
                },
            ),
        )
        for events in cases:
            with self.subTest(events=events), self.assertRaises(
                control_protocol.ControlProtocolError
            ):
                control_protocol.validate_control_event_stream(events)

    def test_rejects_invalid_wire_fixtures_and_private_payload_fields(self) -> None:
        cases = (
            ("invalid-command-prompt-body.json", control_protocol.validate_control_command),
            ("invalid-event-sequence.json", control_protocol.validate_control_event),
            (
                "invalid-event-provider-payload.json",
                control_protocol.validate_control_event,
            ),
        )
        for name, validator in cases:
            with self.subTest(name=name), self.assertRaises(
                control_protocol.ControlProtocolError
            ):
                validator(_fixture(name))

    def test_rejects_noncanonical_proposal_arrays_and_invalid_timestamp(self) -> None:
        proposed = _fixture("valid-event-action-proposed.json")
        payload = proposed["payload"]
        assert isinstance(payload, dict)
        cases = (
            {
                **proposed,
                "payload": {
                    **payload,
                    "expected_artifacts": ["report.zeta", "report.alpha"],
                },
            },
            {
                **proposed,
                "payload": {
                    **payload,
                    "causal_parent_ids": ["goal-1", "goal-1"],
                },
            },
            {**proposed, "emitted_at": "2026-08-09 23:00:00"},
        )
        for event in cases:
            with self.subTest(event=event), self.assertRaises(
                control_protocol.ControlProtocolError
            ):
                control_protocol.validate_control_event(event)

    def test_errors_never_render_wire_bodies(self) -> None:
        value = _fixture("invalid-command-prompt-body.json")

        with self.assertRaises(control_protocol.ControlProtocolError) as raised:
            control_protocol.validate_control_command(value)

        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    def test_wire_schemas_are_closed_discriminated_contracts(self) -> None:
        command_schema = json.loads(COMMAND_SCHEMA.read_text())
        event_schema = json.loads(EVENT_SCHEMA.read_text())

        self.assertFalse(command_schema["additionalProperties"])
        self.assertFalse(event_schema["additionalProperties"])
        self.assertEqual(command_schema["properties"]["payload"], {})
        self.assertEqual(event_schema["properties"]["payload"], {})
        self.assertEqual(len(command_schema["allOf"][0]["oneOf"]), 8)
        self.assertEqual(len(event_schema["allOf"][0]["oneOf"]), 13)
        rendered = json.dumps((command_schema, event_schema), sort_keys=True)
        for forbidden in ("prompt", "credentials", "provider_payload", "path"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(f'"{forbidden}"', rendered)


if __name__ == "__main__":
    unittest.main()
