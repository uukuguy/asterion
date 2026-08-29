from __future__ import annotations

import asyncio
import io
import unittest
from collections.abc import AsyncIterator, Mapping
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Buffer

from asterion.client import AgentClient, ClientCursor, ClientEvent
from asterion.client.acp import ACP_EVENT_METHODS, ClientAcpAdapter, ClientAcpError
from asterion.client.jsonl import JsonlClientCodec
from asterion.client.rpc import ClientRpcAdapter, ClientRpcError, RPC_METHODS
from asterion.client.session import ClientSessionEndpoint


def _input_params(*, intent_id: str = "intent-1") -> dict[str, object]:
    return {
        "protocol": "asterion.agent-client/v1",
        "intent_id": intent_id,
        "client_id": "client-1",
        "session_id": "session-1",
        "authority_revision": 1,
        "type": "input.submit",
        "payload": {
            "content_ref": "private-input-1",
            "delivery": "direct",
            "input_id": "input-1",
        },
    }


def _event(event_type: str, sequence: int = 1) -> ClientEvent:
    payloads: dict[str, Mapping[str, object]] = {
        "artifact.available": {
            "artifact_id": "artifact-1", "artifact_ref": "artifact-ref-1",
            "media_type": "text/plain", "sha256": "a" * 64, "size": 1,
        },
        "fault.raised": {"code": "failed", "evidence_ref": "evidence-1", "recoverable": False},
        "message.available": {
            "content_ref": "private-message-1", "media_type": "text/plain",
            "message_id": "message-1", "role": "assistant", "sha256": "b" * 64, "size": 1,
        },
        "session.state": {"reason_code": "created", "status": "idle"},
        "session.terminal": {"reason_code": "completed", "status": "completed"},
        "commands.changed": {"commands": [], "revision": 1},
        "tool.completed": {
            "call_id": "call-1", "is_error": False, "media_type": "text/plain",
            "result_ref": "private-result-1", "sha256": "c" * 64, "size": 1,
        },
        "tool.started": {
            "arguments_ref": "private-arguments-1", "call_id": "call-1",
            "name": "tool", "sha256": "d" * 64, "size": 1,
        },
        "usage.reported": {
            "aggregate_tokens": 1, "application_tokens": 1, "child_tokens": 0,
            "controller_tokens": 0, "cost_micros": 0,
        },
    }
    return ClientEvent(
        protocol="asterion.agent-client/v1",
        event_id=f"event-{sequence}",
        session_id="session-1",
        generation=1,
        sequence=sequence,
        emitted_at="2026-08-28T12:00:00Z",
        type=event_type,
        payload=payloads[event_type],
    )


class _Endpoint:
    def __init__(self, events: tuple[ClientEvent, ...] = (_event("session.terminal"),)) -> None:
        self.private_values = cast(object, None)
        self.events_to_emit = events
        self.submissions = 0
        self.release_submission: asyncio.Event | None = None

    async def submit(self, intent) -> str:  # type: ignore[no-untyped-def]
        self.submissions += 1
        if self.release_submission is not None:
            await self.release_submission.wait()
        return f"accepted:{intent.intent_id}"

    def events(self, cursor: ClientCursor | None = None) -> AsyncIterator[ClientEvent]:
        del cursor

        async def iterate() -> AsyncIterator[ClientEvent]:
            for item in self.events_to_emit:
                yield item

        return iterate()

    async def close(self) -> None:
        return None


def _agent_client(endpoint: _Endpoint | None = None) -> tuple[AgentClient, _Endpoint]:
    selected = endpoint or _Endpoint()
    return AgentClient(cast(ClientSessionEndpoint, selected), client_id="client-1"), selected


class TestClientRpcAdapter(unittest.IsolatedAsyncioTestCase):
    async def test_rpc_acknowledges_admission_and_streams_terminal(self) -> None:
        client, _ = _agent_client()
        adapter = ClientRpcAdapter(client)

        ack = await adapter.request(
            {"id": "rpc-1", "method": "input.submit", "params": _input_params()}
        )

        self.assertEqual(ack, {"id": "rpc-1", "type": "ack", "intent_id": "intent-1"})
        self.assertEqual([item["type"] async for item in adapter.events()], ["session.terminal"])

    async def test_rpc_snapshots_requests_and_deduplicates_concurrent_admission(self) -> None:
        endpoint = _Endpoint()
        endpoint.release_submission = asyncio.Event()
        client, _ = _agent_client(endpoint)
        adapter = ClientRpcAdapter(client)
        request = {"id": "rpc-1", "method": "input.submit", "params": _input_params()}

        first = asyncio.create_task(adapter.request(request))
        await asyncio.sleep(0)
        request["params"] = _input_params(intent_id="intent-2")
        second = asyncio.create_task(
            adapter.request({"id": "rpc-1", "method": "input.submit", "params": _input_params()})
        )
        await asyncio.sleep(0)
        self.assertEqual(endpoint.submissions, 1)
        endpoint.release_submission.set()

        self.assertIs(await first, await second)
        self.assertEqual(endpoint.submissions, 1)
        with self.assertRaisesRegex(ClientRpcError, "^client RPC request identity conflicts$"):
            await adapter.request(
                {"id": "rpc-1", "method": "input.submit", "params": _input_params(intent_id="intent-3")}
            )

    async def test_rpc_rejects_noncanonical_or_private_requests_without_dispatch(self) -> None:
        client, endpoint = _agent_client()
        adapter = ClientRpcAdapter(client)
        hostile = _input_params()
        hostile["payload"] = {"content_ref": "private-input-1", "delivery": "direct", "input_id": "input-1", "prompt": "SENTINEL_PRIVATE_VALUE"}

        for request in (
            {"id": "rpc-1", "method": "private.dump", "params": {}},
            {"id": "rpc-1", "method": "input.submit", "params": hostile},
            {"id": "rpc-1", "method": "input.submit", "params": _input_params(), "extra": 1},
            {"id": True, "method": "input.submit", "params": _input_params()},
        ):
            with self.subTest(request=request), self.assertRaisesRegex(ClientRpcError, "^client RPC request is invalid$") as raised:
                await adapter.request(request)
            self.assertNotIn("SENTINEL_PRIVATE_VALUE", str(raised.exception))
        self.assertEqual(endpoint.submissions, 0)

    async def test_rpc_revalidates_hostile_event_mappers_before_yielding(self) -> None:
        client, _ = _agent_client(_Endpoint((_evil_event(),)))
        adapter = ClientRpcAdapter(client)
        yielded: list[Mapping[str, object]] = []

        with self.assertRaisesRegex(ClientRpcError, "^client RPC event stream is unavailable$") as raised:
            async for event in adapter.events():
                yielded.append(event)

        self.assertEqual(yielded, [])
        self.assertNotIn("SENTINEL_PRIVATE_VALUE", str(raised.exception))

    async def test_rpc_redacts_hostile_mapper_failures_and_propagates_cancellation(self) -> None:
        client, _ = _agent_client(_Endpoint((_exploding_event(),)))
        adapter = ClientRpcAdapter(client)
        with self.assertRaisesRegex(ClientRpcError, "^client RPC event stream is unavailable$") as raised:
            _ = [event async for event in adapter.events()]
        self.assertNotIn("SENTINEL_PRIVATE_VALUE", str(raised.exception))

        client, _ = _agent_client(_CancelledEndpoint())
        with self.assertRaises(asyncio.CancelledError):
            _ = [event async for event in ClientRpcAdapter(client).events()]
        for signal in (KeyboardInterrupt, SystemExit):
            with self.subTest(signal=signal):
                client, _ = _agent_client(_ProcessExceptionEndpoint(signal))
                with self.assertRaises(signal):
                    _ = [event async for event in ClientRpcAdapter(client).events()]


class TestClientAcpAdapter(unittest.IsolatedAsyncioTestCase):
    async def test_acp_rejects_unknown_request_without_stdout_data(self) -> None:
        client, _ = _agent_client()
        output = io.BytesIO()
        adapter = ClientAcpAdapter(client, stdout=output)

        with self.assertRaisesRegex(ClientAcpError, "^client ACP request is unsupported$"):
            await adapter.request({"id": "acp-1", "method": "private.dump", "params": {}})

        self.assertEqual(output.getvalue(), b"")

    async def test_acp_writes_only_exact_bounded_protocol_frames(self) -> None:
        events = tuple(_event(event_type, index + 1) for index, event_type in enumerate(ACP_EVENT_METHODS))
        client, _ = _agent_client(_Endpoint(events))
        output = _AtomicBytesIO()
        adapter = ClientAcpAdapter(client, stdout=output, max_frame_bytes=2_048)

        frames = [frame async for frame in adapter.events()]

        self.assertEqual([frame["method"] for frame in frames], list(ACP_EVENT_METHODS.values()))
        decoded = JsonlClientCodec(max_line_bytes=2_048).feed(output.getvalue(), eof=True)
        self.assertEqual(decoded, tuple(frames))
        self.assertEqual(output.write_calls, len(frames))
        self.assertNotIn(b"SENTINEL_PRIVATE_VALUE", output.getvalue())

    async def test_acp_rejects_unmapped_events_and_redacts_output_failures(self) -> None:
        client, _ = _agent_client(_Endpoint((_event("session.terminal"),)))
        adapter = ClientAcpAdapter(client, stdout=_FailingBytesIO())
        with self.assertRaisesRegex(ClientAcpError, "^client ACP output is unavailable$") as raised:
            _ = [frame async for frame in adapter.events()]
        self.assertNotIn("SENTINEL_PRIVATE_VALUE", str(raised.exception))
        with self.assertRaisesRegex(ClientAcpError, "^client ACP output is unavailable$"):
            _ = [frame async for frame in adapter.events()]

        client, _ = _agent_client(_Endpoint((_event("session.terminal"), _event("commands.changed", 2))))
        adapter = ClientAcpAdapter(client, stdout=io.BytesIO())
        with self.assertRaisesRegex(ClientAcpError, "^client ACP event is unsupported$"):
            _ = [frame async for frame in adapter.events()]

    async def test_acp_revalidates_hostile_events_before_stdout_write(self) -> None:
        output = _AtomicBytesIO()
        client, _ = _agent_client(_Endpoint((_evil_event(),)))
        adapter = ClientAcpAdapter(client, stdout=output)

        with self.assertRaisesRegex(ClientAcpError, "^client ACP event stream is unavailable$") as raised:
            _ = [frame async for frame in adapter.events()]

        self.assertEqual(output.getvalue(), b"")
        self.assertEqual(output.write_calls, 0)
        self.assertNotIn("SENTINEL_PRIVATE_VALUE", str(raised.exception))

    async def test_acp_redacts_hostile_mapper_failures_and_propagates_cancellation(self) -> None:
        output = _AtomicBytesIO()
        client, _ = _agent_client(_Endpoint((_exploding_event(),)))
        with self.assertRaisesRegex(ClientAcpError, "^client ACP event stream is unavailable$") as raised:
            _ = [frame async for frame in ClientAcpAdapter(client, stdout=output).events()]
        self.assertEqual(output.getvalue(), b"")
        self.assertNotIn("SENTINEL_PRIVATE_VALUE", str(raised.exception))

        client, _ = _agent_client(_CancelledEndpoint())
        with self.assertRaises(asyncio.CancelledError):
            _ = [frame async for frame in ClientAcpAdapter(client, stdout=output).events()]
        for signal in (KeyboardInterrupt, SystemExit):
            with self.subTest(signal=signal):
                client, _ = _agent_client(_ProcessExceptionEndpoint(signal))
                with self.assertRaises(signal):
                    _ = [frame async for frame in ClientAcpAdapter(client, stdout=output).events()]


class _AtomicBytesIO(io.BytesIO):
    def __init__(self) -> None:
        super().__init__()
        self.write_calls = 0

    def write(self, data: Buffer, /) -> int:
        self.write_calls += 1
        return super().write(data)


class _FailingBytesIO(io.BytesIO):
    def write(self, data: Buffer, /) -> int:
        del data
        raise RuntimeError("SENTINEL_PRIVATE_VALUE")


class _EvilEvent(ClientEvent):
    def to_mapping(self) -> Mapping[str, object]:
        mapping = dict(super().to_mapping())
        payload = dict(cast(Mapping[str, object], mapping["payload"]))
        payload["raw_output"] = "SENTINEL_PRIVATE_VALUE"
        mapping["payload"] = payload
        return mapping


class _ExplodingEvent(ClientEvent):
    def to_mapping(self) -> Mapping[str, object]:
        raise RuntimeError("SENTINEL_PRIVATE_VALUE")


class _CancelledEndpoint(_Endpoint):
    def __init__(self) -> None:
        super().__init__(())

    def events(self, cursor: ClientCursor | None = None) -> AsyncIterator[ClientEvent]:
        del cursor

        async def iterate() -> AsyncIterator[ClientEvent]:
            raise asyncio.CancelledError()
            yield _event("session.terminal")

        return iterate()


class _ProcessExceptionEndpoint(_Endpoint):
    def __init__(self, signal: type[BaseException]) -> None:
        super().__init__(())
        self._signal = signal

    def events(self, cursor: ClientCursor | None = None) -> AsyncIterator[ClientEvent]:
        del cursor

        async def iterate() -> AsyncIterator[ClientEvent]:
            raise self._signal()
            yield _event("session.terminal")

        return iterate()


def _evil_event() -> ClientEvent:
    event = _event("session.terminal")
    return _EvilEvent(
        protocol=event.protocol, event_id=event.event_id, session_id=event.session_id,
        generation=event.generation, sequence=event.sequence, emitted_at=event.emitted_at,
        type=event.type, payload=event.payload,
    )


def _exploding_event() -> ClientEvent:
    event = _event("session.terminal")
    return _ExplodingEvent(
        protocol=event.protocol, event_id=event.event_id, session_id=event.session_id,
        generation=event.generation, sequence=event.sequence, emitted_at=event.emitted_at,
        type=event.type, payload=event.payload,
    )


class TestProtocolConstants(unittest.TestCase):
    def test_closed_method_tables_match_client_protocol(self) -> None:
        self.assertEqual(RPC_METHODS, frozenset({"command.invoke", "export.request", "extension-ui.respond", "input.submit", "session.attach", "session.cancel", "session.create", "session.detach", "session.pause", "session.resume", "share.request"}))
        self.assertEqual(
            dict(ACP_EVENT_METHODS),
            {
                "artifact.available": "artifact_update", "fault.raised": "session_error",
                "message.available": "agent_message_chunk", "session.state": "session_update",
                "session.terminal": "session_end", "tool.completed": "tool_call_update",
                "tool.started": "tool_call", "usage.reported": "usage_update",
            },
        )
