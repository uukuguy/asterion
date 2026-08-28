from __future__ import annotations

import math
import unittest
from collections.abc import AsyncIterator
from typing import cast

from asterion.client import (
    AgentClient,
    AgentClientError,
    ClientCursor,
    ClientEvent,
    ClientIntent,
    ClientJsonlError,
    JsonlClientCodec,
)
from asterion.client.session import ClientSessionEndpoint


class _PrivateValues:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, int, int]] = []

    def resolve_text(
        self, reference: str, *, purpose: str, max_bytes: int, deadline_ms: int
    ) -> str:
        self.requests.append((reference, purpose, max_bytes, deadline_ms))
        return "private text"


class _RecordingEndpoint:
    def __init__(self) -> None:
        self.private_values = _PrivateValues()
        self.intents: list[ClientIntent] = []
        self.closed = False

    async def submit(self, intent: ClientIntent) -> str:
        self.intents.append(intent)
        return f"{intent.client_id}:{intent.payload['input_id']}"

    def events(self, cursor: ClientCursor | None = None) -> AsyncIterator[ClientEvent]:
        async def iterate() -> AsyncIterator[ClientEvent]:
            if False:
                yield _event()

        return iterate()

    async def close(self) -> None:
        self.closed = True


def _event() -> ClientEvent:
    return ClientEvent(
        protocol="asterion.agent-client/v1",
        event_id="event-1",
        session_id="session-1",
        generation=1,
        sequence=1,
        emitted_at="2026-08-10T15:00:00Z",
        type="session.state",
        payload={"reason_code": "created", "status": "idle"},
    )


class TestAgentClient(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_uses_injected_endpoint_only(self) -> None:
        endpoint = _RecordingEndpoint()
        client = AgentClient(cast(ClientSessionEndpoint, endpoint), client_id="client-1")

        accepted = await client.submit_input(
            session_id="session-1",
            authority_revision=1,
            input_id="input-1",
            content_ref="private-input-1",
            delivery="direct",
        )

        self.assertEqual(accepted, "client-1:input-1")
        self.assertEqual(len(endpoint.intents), 1)
        self.assertEqual(endpoint.intents[0].type, "input.submit")
        self.assertFalse(hasattr(client, "runtime"))
        self.assertFalse(hasattr(client, "provider"))

    async def test_sdk_rejects_foreign_intent_and_delegates_private_access(self) -> None:
        endpoint = _RecordingEndpoint()
        client = AgentClient(cast(ClientSessionEndpoint, endpoint), client_id="client-1")
        foreign = ClientIntent(
            protocol="asterion.agent-client/v1",
            intent_id="intent-1",
            client_id="client-2",
            session_id="session-1",
            authority_revision=1,
            type="input.submit",
            payload={
                "content_ref": "private-input-1",
                "delivery": "direct",
                "input_id": "input-1",
            },
        )

        with self.assertRaises(AgentClientError):
            await client.submit(foreign)
        self.assertEqual(
            client.resolve_text(
                "private-text-1", purpose="interactive-render", max_bytes=32, deadline_ms=100
            ),
            "private text",
        )
        self.assertEqual(
            endpoint.private_values.requests,
            [("private-text-1", "interactive-render", 32, 100)],
        )
        await client.close()
        self.assertTrue(endpoint.closed)


class TestJsonlClientCodec(unittest.TestCase):
    def test_jsonl_rejects_partial_oversized_and_nested_frames(self) -> None:
        codec = JsonlClientCodec(max_line_bytes=128, max_depth=8)
        for frame in (
            b"{",
            b'{"x":"' + b"a" * 129,
            b"[[[[[[[[[0]]]]]]]]]",
        ):
            with self.subTest(frame=frame[:8]), self.assertRaises(ClientJsonlError):
                codec.feed(frame, eof=True)

    def test_jsonl_is_lf_only_strict_and_canonical(self) -> None:
        codec = JsonlClientCodec(max_line_bytes=128, max_depth=4)

        self.assertEqual(codec.feed(b'{"b":2}\n{"a":1}\n'), ({"b": 2}, {"a": 1}))
        self.assertEqual(codec.encode({"b": 2, "a": 1}), b'{"a":1,"b":2}\n')
        for frame in (
            b'{"x":1}\r\n',
            b'{"x":1,"x":2}\n',
            b'{"x":NaN}\n',
            b'{"x":9007199254740992}\n',
            b"\xff\n",
            b"[]\n",
        ):
            with self.subTest(frame=frame):
                with self.assertRaises(ClientJsonlError):
                    JsonlClientCodec(max_line_bytes=128, max_depth=4).feed(frame)

        for value in ({"x": math.nan}, {"x": 9_007_199_254_740_992}, {"x": {"y": {"z": {"q": {"r": 1}}}}}):
            with self.subTest(value=value):
                with self.assertRaises(ClientJsonlError):
                    codec.encode(value)
