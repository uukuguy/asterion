from __future__ import annotations

import hashlib
import io
import unittest
from collections.abc import AsyncIterator, Mapping
from typing import cast

from asterion.client import AgentClient, ClientCursor, ClientEvent, ClientInteractiveError
from asterion.client.interactive import (
    ClientCommandRegistry,
    ClientUiRequest,
    ClientViewState,
    reduce_client_view,
    respond_to_extension_ui,
    run_headless,
    run_interactive,
)
from asterion.client.session import ClientSessionEndpoint


def _event(event_type: str, sequence: int, payload: Mapping[str, object]) -> ClientEvent:
    return ClientEvent(
        protocol="asterion.agent-client/v1", event_id=f"event-{sequence}",
        session_id="session-1", generation=1, sequence=sequence,
        emitted_at="2026-08-28T12:00:00Z", type=event_type, payload=payload,
    )


def _commands(revision: int, sequence: int = 1) -> ClientEvent:
    return _event("commands.changed", sequence, {"commands": ["alpha", "beta"], "revision": revision})


class _PrivateValues:
    def __init__(self) -> None:
        self.reads: list[tuple[str, str, int, int]] = []

    def resolve_text(self, reference: str, *, purpose: str, max_bytes: int, deadline_ms: int) -> str:
        self.reads.append((reference, purpose, max_bytes, deadline_ms))
        if reference == "private-final-1":
            return "FINAL_SENTINEL"
        return "{\"answer\":\"SENTINEL\"}"


class _Endpoint:
    def __init__(self, events: tuple[ClientEvent, ...]) -> None:
        self.events_to_emit = events
        self.private_values = _PrivateValues()
        self.submitted: list[object] = []
        self.closed = False

    async def submit(self, intent: object) -> str:
        self.submitted.append(intent)
        return "accepted"

    def events(self, cursor: ClientCursor | None = None) -> AsyncIterator[ClientEvent]:
        del cursor

        async def iterate() -> AsyncIterator[ClientEvent]:
            for event in self.events_to_emit:
                yield event

        return iterate()

    async def close(self) -> None:
        self.closed = True


def _client(events: tuple[ClientEvent, ...]) -> tuple[AgentClient, _Endpoint]:
    endpoint = _Endpoint(events)
    return AgentClient(cast(ClientSessionEndpoint, endpoint), client_id="client-1"), endpoint


class TestClientInteractive(unittest.IsolatedAsyncioTestCase):
    async def test_command_revision_and_ui_timeout_are_deterministic(self) -> None:
        state = reduce_client_view(ClientViewState.empty("session-1", 1), _commands(2))
        self.assertEqual(state.command_revision, 2)
        self.assertEqual(tuple(command.name for command in state.commands), ("alpha", "beta"))
        with self.assertRaisesRegex(ClientInteractiveError, "command revision"):
            reduce_client_view(state, _commands(1, 2))

        client, endpoint = _client(())
        response = await respond_to_extension_ui(
            ClientUiRequest("ui-1", "extension", "private-ui-1", 1), client, clock_ms=lambda: 2
        )
        self.assertEqual(response.payload, {"request_id": "ui-1", "cancelled": True, "response_ref": None})
        self.assertEqual(endpoint.private_values.reads, [])

    async def test_headless_resolves_only_final_message(self) -> None:
        client, endpoint = _client((
            _event("message.available", 1, {"content_ref": "private-earlier-1", "media_type": "text/plain", "message_id": "message-1", "role": "assistant", "sha256": "a" * 64, "size": 7}),
            _event("message.available", 2, {"content_ref": "private-final-1", "media_type": "text/plain", "message_id": "message-2", "role": "assistant", "sha256": hashlib.sha256(b"FINAL_SENTINEL").hexdigest(), "size": 14}),
            _event("session.terminal", 3, {"reason_code": "completed", "status": "completed"}),
        ))
        output = io.StringIO()
        await run_headless(client, mode="text", stdout=output, deadline_ms=100)
        self.assertEqual(output.getvalue(), "FINAL_SENTINEL\n")
        self.assertEqual([(reference, purpose) for reference, purpose, _, _ in endpoint.private_values.reads], [("private-final-1", "headless-final")])
        self.assertTrue(endpoint.closed)

    async def test_reducer_handles_all_events_and_revalidates_hostile_event(self) -> None:
        events = (
            _event("artifact.available", 1, {"artifact_id": "artifact-1", "artifact_ref": "private-artifact-1", "media_type": "text/plain", "sha256": "a" * 64, "size": 1}),
            _event("commands.changed", 2, {"commands": ["alpha"], "revision": 1}),
            _event("export.created", 3, {"artifact_id": "artifact-1", "artifact_ref": "export-ref-1", "export_id": "export-1", "media_type": "text/plain", "sha256": "b" * 64, "size": 1, "visibility": "public"}),
            _event("extension-ui.requested", 4, {"deadline_ms": 100, "method": "extension", "payload_ref": "private-ui-1", "request_id": "ui-1"}),
            _event("fault.raised", 5, {"code": "failed", "evidence_ref": "evidence-1", "recoverable": False}),
            _event("message.available", 6, {"content_ref": "private-message-1", "media_type": "text/plain", "message_id": "message-1", "role": "assistant", "sha256": "c" * 64, "size": 1}),
            _event("session.state", 7, {"reason_code": "running", "status": "running"}),
            _event("share.created", 8, {"export_id": "export-1", "share_id": "share-1", "share_ref": "share-ref-1"}),
            _event("tool.started", 9, {"arguments_ref": "private-arguments-1", "call_id": "call-1", "name": "tool", "sha256": "d" * 64, "size": 1}),
            _event("tool.completed", 10, {"call_id": "call-1", "is_error": False, "media_type": "text/plain", "result_ref": "private-result-1", "sha256": "e" * 64, "size": 1}),
            _event("usage.reported", 11, {"aggregate_tokens": 1, "application_tokens": 1, "child_tokens": 0, "controller_tokens": 0, "cost_micros": 0}),
            _event("session.terminal", 12, {"reason_code": "completed", "status": "completed"}),
        )
        state = ClientViewState.empty("session-1", 1)
        for event in events:
            state = reduce_client_view(state, event)
        self.assertTrue(state.terminal)
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.active_tool_calls, {})
        self.assertEqual(len(state.messages), 1)
        with self.assertRaises(ClientInteractiveError):
            reduce_client_view(state, events[-1])

        class HostileEvent(ClientEvent):
            def to_mapping(self) -> Mapping[str, object]:
                mapping = dict(super().to_mapping())
                mapping["payload"] = {"raw_output": "SENTINEL_PRIVATE_VALUE"}
                return mapping

        hostile = HostileEvent(**events[0].__dict__)
        with self.assertRaisesRegex(ClientInteractiveError, "event is invalid") as raised:
            reduce_client_view(ClientViewState.empty("session-1", 1), hostile)
        self.assertNotIn("SENTINEL_PRIVATE_VALUE", str(raised.exception))

    async def test_interactive_is_deterministic_and_registry_uses_exact_revision(self) -> None:
        client, endpoint = _client((_commands(1), _event("session.terminal", 2, {"reason_code": "completed", "status": "completed"})))
        state = await run_interactive(client, stdout=io.StringIO())
        registry = ClientCommandRegistry.from_state(state)
        await registry.invoke(client, session_id="session-1", authority_revision=1, intent_id="invoke-1", command_name="alpha", arguments_ref="arguments-1")
        self.assertEqual(cast(object, endpoint.submitted).__class__, list)
        self.assertEqual(getattr(endpoint.submitted[0], "payload")["command_revision"], 1)
        with self.assertRaises(ClientInteractiveError):
            registry.intent(session_id="session-1", authority_revision=1, intent_id="invoke-2", command_name="missing", arguments_ref="arguments-1")
