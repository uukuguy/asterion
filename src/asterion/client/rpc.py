"""Closed RPC admission and public-event adapter for one injected client."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import AsyncIterator, Mapping
from types import MappingProxyType

from asterion.client.jsonl import ClientJsonlError, JsonlClientCodec
from asterion.client.protocol import CLIENT_INTENT_TYPES, ClientCursor, ClientEvent, ClientIntent
from asterion.client.sdk import AgentClient


RPC_METHODS = frozenset(CLIENT_INTENT_TYPES)

_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REQUEST_FIELDS = frozenset({"id", "method", "params"})


class ClientRpcError(ValueError):
    """Raised when a closed RPC request cannot be admitted or streamed."""


class ClientRpcAdapter:
    """Adapt exact client intents into idempotent RPC acknowledgements."""

    def __init__(self, client: AgentClient) -> None:
        if not isinstance(client, AgentClient):
            raise ClientRpcError("client RPC adapter is invalid")
        self._client = client
        self._lock = asyncio.Lock()
        self._requests: dict[str, tuple[str, asyncio.Task[Mapping[str, object]]]] = {}

    async def request(self, value: Mapping[str, object]) -> Mapping[str, object]:
        """Submit one exact RPC request, sharing a matching admission task."""

        request, intent, digest = _validated_request(value)
        request_id = request["id"]
        assert isinstance(request_id, str)
        async with self._lock:
            prior = self._requests.get(request_id)
            if prior is None:
                admission = asyncio.create_task(self._admit(request_id, intent))
                self._requests[request_id] = (digest, admission)
            else:
                prior_digest, admission = prior
                if prior_digest != digest:
                    raise ClientRpcError("client RPC request identity conflicts")
        return await asyncio.shield(admission)

    async def _admit(self, request_id: str, intent: ClientIntent) -> Mapping[str, object]:
        try:
            await self._client.submit(intent)
        except Exception:
            raise ClientRpcError("client RPC request is rejected") from None
        return MappingProxyType({"id": request_id, "type": "ack", "intent_id": intent.intent_id})

    async def events(self, cursor: ClientCursor | None = None) -> AsyncIterator[Mapping[str, object]]:
        """Expose only validated, body-free client events as RPC event values."""

        try:
            if cursor is not None and not isinstance(cursor, ClientCursor):
                raise ValueError
            iterator = self._client.events(cursor)
            async for value in iterator:
                event = _validated_event(value)
                yield event.to_mapping()
        except ClientRpcError:
            raise
        except Exception:
            raise ClientRpcError("client RPC event stream is unavailable") from None


def _validated_request(value: object) -> tuple[Mapping[str, object], ClientIntent, str]:
    try:
        request = _snapshot_mapping(value)
        if set(request) != _REQUEST_FIELDS:
            raise ValueError
        request_id = request["id"]
        method = request["method"]
        params = request["params"]
        if (
            not isinstance(request_id, str)
            or _OPAQUE_ID.fullmatch(request_id) is None
            or not isinstance(method, str)
            or method not in RPC_METHODS
            or not isinstance(params, Mapping)
        ):
            raise ValueError
        intent = ClientIntent.from_mapping(params)
        if intent.type != method:
            raise ValueError
        canonical = JsonlClientCodec().encode(request)
    except Exception:
        raise ClientRpcError("client RPC request is invalid") from None
    return request, intent, hashlib.sha256(canonical).hexdigest()


def _snapshot_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError
    codec = JsonlClientCodec()
    encoded = codec.encode(value)
    snapshot = codec.feed(encoded, eof=True)
    if len(snapshot) != 1:
        raise ClientJsonlError("client RPC request is invalid")
    return snapshot[0]


def _validated_event(value: object) -> ClientEvent:
    if not isinstance(value, ClientEvent):
        raise ClientRpcError("client RPC event stream is unavailable")
    return value
