"""Closed ACP event codec over one injected public client stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Buffer, Mapping
from types import MappingProxyType
from typing import Protocol

from asterion.client.jsonl import ClientJsonlError, JsonlClientCodec
from asterion.client.protocol import ClientCursor, ClientEvent
from asterion.client.sdk import AgentClient


ACP_EVENT_METHODS = MappingProxyType(
    {
        "artifact.available": "artifact_update",
        "fault.raised": "session_error",
        "message.available": "agent_message_chunk",
        "session.state": "session_update",
        "session.terminal": "session_end",
        "tool.completed": "tool_call_update",
        "tool.started": "tool_call",
        "usage.reported": "usage_update",
    }
)


class _BinaryStdout(Protocol):
    def write(self, data: Buffer, /) -> int:
        """Write one complete protocol frame."""
        ...


class ClientAcpError(ValueError):
    """Raised when a closed ACP operation cannot produce a protocol frame."""


class ClientAcpAdapter:
    """Translate only the approved public client events into ACP frames."""

    def __init__(self, client: AgentClient, *, stdout: _BinaryStdout, max_frame_bytes: int = 64 * 1024) -> None:
        if not isinstance(client, AgentClient) or not callable(getattr(stdout, "write", None)):
            raise ClientAcpError("client ACP adapter is invalid")
        try:
            JsonlClientCodec(max_line_bytes=max_frame_bytes)
        except ClientJsonlError:
            raise ClientAcpError("client ACP limits are invalid") from None
        self._client = client
        self._stdout = stdout
        self._max_frame_bytes = max_frame_bytes
        self._write_lock = asyncio.Lock()
        self._closed = False

    async def request(self, value: object) -> None:
        """ACP has no inbound operation in this closed public projection."""

        del value
        raise ClientAcpError("client ACP request is unsupported")

    async def events(self, cursor: ClientCursor | None = None) -> AsyncIterator[Mapping[str, object]]:
        """Write one bounded frame per supported public client event."""

        if self._closed:
            raise ClientAcpError("client ACP output is unavailable")
        try:
            if cursor is not None and not isinstance(cursor, ClientCursor):
                raise ValueError
            iterator = self._client.events(cursor)
            async for value in iterator:
                frame = _frame_for_event(value)
                await self._write_frame(frame)
                yield frame
        except ClientAcpError:
            raise
        except Exception:
            raise ClientAcpError("client ACP event stream is unavailable") from None

    async def _write_frame(self, frame: Mapping[str, object]) -> None:
        try:
            encoded = JsonlClientCodec(max_line_bytes=self._max_frame_bytes).encode(frame)
        except Exception:
            self._closed = True
            raise ClientAcpError("client ACP output is unavailable") from None
        async with self._write_lock:
            if self._closed:
                raise ClientAcpError("client ACP output is unavailable")
            try:
                written = self._stdout.write(encoded)
            except Exception:
                self._closed = True
                raise ClientAcpError("client ACP output is unavailable") from None
            if isinstance(written, bool) or not isinstance(written, int) or written != len(encoded):
                self._closed = True
                raise ClientAcpError("client ACP output is unavailable")


def _frame_for_event(value: object) -> Mapping[str, object]:
    if not isinstance(value, ClientEvent):
        raise ClientAcpError("client ACP event stream is unavailable")
    event = value
    method = ACP_EVENT_METHODS.get(event.type)
    if method is None:
        raise ClientAcpError("client ACP event is unsupported")
    return MappingProxyType({"method": method, "params": event.to_mapping()})
