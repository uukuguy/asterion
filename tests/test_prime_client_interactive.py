from __future__ import annotations

import hashlib
import io
import unittest
from collections.abc import AsyncIterator
from typing import cast

from asterion.client import AgentClient, ClientCursor, ClientEvent
from asterion.client.interactive import (
    ClientCommandRegistry,
    ClientUiRequest,
    respond_to_extension_ui,
    run_headless,
    run_interactive,
)
from asterion.client.session import ClientSessionEndpoint


_GATE_ID = "test.prime-client-interactive.provider-free"
_FEATURE_IDS = (
    "interface.cli-interactive", "interface.headless-print",
    "interface.tui-commands", "interface.tui-extension-ui",
)
_SCENARIO_IDS = (
    "prime-client-interactive.cli", "prime-client-interactive.headless",
    "prime-client-interactive.commands", "prime-client-interactive.extension-ui",
)
_SENTINEL = "SENTINEL_PRIVATE_VALUE"


class _Effects:
    provider_operations = 0
    credential_reads = 0
    retained_processes = 0

    def __init__(self) -> None:
        self.private_reads: list[tuple[str, str]] = []


class _PrivateValues:
    def __init__(self, effects: _Effects) -> None:
        self.effects = effects

    def resolve_text(self, reference: str, *, purpose: str, max_bytes: int, deadline_ms: int) -> str:
        if reference != "private-final-1" or purpose != "headless-final" or max_bytes != 5 or deadline_ms < 1:
            raise AssertionError("private-value contract is invalid")
        self.effects.private_reads.append((reference, purpose))
        return "FINAL"


def _event(event_id: str, sequence: int, event_type: str, payload: dict[str, object]) -> ClientEvent:
    return ClientEvent(
        protocol="asterion.agent-client/v1", event_id=event_id, session_id="session-1",
        generation=1, sequence=sequence, emitted_at="2026-08-28T12:00:00Z",
        type=event_type, payload=payload,
    )


class _Endpoint:
    def __init__(self, effects: _Effects, events: tuple[ClientEvent, ...]) -> None:
        self.private_values = _PrivateValues(effects)
        self.events_to_emit = events
        self.submissions: list[object] = []
        self.closed = False

    async def submit(self, intent: object) -> str:
        self.submissions.append(intent)
        return "accepted"

    def events(self, cursor: ClientCursor | None = None) -> AsyncIterator[ClientEvent]:
        del cursor

        async def iterate() -> AsyncIterator[ClientEvent]:
            for event in self.events_to_emit:
                yield event

        return iterate()

    async def close(self) -> None:
        self.closed = True


def _client(effects: _Effects, events: tuple[ClientEvent, ...]) -> tuple[AgentClient, _Endpoint]:
    endpoint = _Endpoint(effects, events)
    return AgentClient(cast(ClientSessionEndpoint, endpoint), client_id="client-1"), endpoint


class TestPrimeClientInteractiveReceipt(unittest.IsolatedAsyncioTestCase):
    async def test_provider_free_receipt_exercises_exact_four_features(self) -> None:
        effects = _Effects()
        terminal = _event("event-2", 2, "session.terminal", {"reason_code": "completed", "status": "completed"})
        message = _event("event-1", 1, "message.available", {
            "content_ref": "private-final-1", "media_type": "text/plain", "message_id": "message-1",
            "role": "assistant", "sha256": hashlib.sha256(b"FINAL").hexdigest(), "size": 5,
        })
        headless, headless_endpoint = _client(effects, (message, terminal))
        text = io.StringIO()
        await run_headless(headless, mode="text", stdout=text, deadline_ms=1)
        self.assertEqual(text.getvalue(), "FINAL\n")
        self.assertEqual(effects.private_reads, [("private-final-1", "headless-final")])
        self.assertTrue(headless_endpoint.closed)

        interactive, interactive_endpoint = _client(effects, (
            _event("event-1", 1, "commands.changed", {"commands": ["inspect"], "revision": 1}), terminal,
        ))
        state = await run_interactive(interactive, stdout=io.StringIO())
        registry = ClientCommandRegistry.from_state(state)
        await registry.invoke(interactive, session_id="session-1", authority_revision=1, intent_id="intent-1", command_name="inspect", arguments_ref="arguments-1")
        self.assertEqual(getattr(interactive_endpoint.submissions[0], "payload")["command_revision"], 1)

        ui_client, _ = _client(effects, ())
        response = await respond_to_extension_ui(
            ClientUiRequest("ui-1", "extension", "private-ui-1", 1), ui_client, clock_ms=lambda: 2,
        )
        self.assertEqual(response.payload, {"request_id": "ui-1", "cancelled": True, "response_ref": None})

        receipt = {
            "gate_id": _GATE_ID, "feature_ids": list(_FEATURE_IDS),
            "scenario_ids": list(_SCENARIO_IDS),
            "stream_contract_digest": hashlib.sha256(repr((message.to_mapping(), terminal.to_mapping())).encode()).hexdigest(),
            "private_service_contract_digest": hashlib.sha256(b"headless-final|interactive-render|extension-ui-response").hexdigest(),
            "provider_operations": effects.provider_operations, "credential_reads": effects.credential_reads,
            "retained_processes": effects.retained_processes, "redaction_status": "PASS",
        }
        self.assertEqual(receipt["feature_ids"], list(_FEATURE_IDS))
        self.assertEqual(receipt["scenario_ids"], list(_SCENARIO_IDS))
        self.assertEqual(receipt["provider_operations"], 0)
        self.assertEqual(receipt["credential_reads"], 0)
        self.assertEqual(receipt["retained_processes"], 0)
        self.assertNotIn(_SENTINEL, repr(receipt))
