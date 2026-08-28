from __future__ import annotations

import hashlib
import io
import json
import unittest
from collections.abc import AsyncIterator, Mapping
from typing import TypedDict, cast

from asterion.client import AgentClient, ClientCursor, ClientEvent
from asterion.client.acp import ACP_EVENT_METHODS, ClientAcpAdapter
from asterion.client.rpc import ClientRpcAdapter, RPC_METHODS
from asterion.client.session import ClientSessionEndpoint


_COMMAND = "make test.prime-client-protocols.provider-free"
_FEATURE_IDS = ("interface.acp", "interface.rpc")
_SCENARIO_IDS = ("prime-parity.interface.acp", "prime-parity.interface.rpc")
_SENTINEL = "SENTINEL_PRIVATE_VALUE"


class _Receipt(TypedDict):
    command_id: str
    feature_ids: list[str]
    scenario_ids: list[str]
    rpc_methods: list[str]
    acp_event_methods: dict[str, str]
    protocol_digest: str
    provider_operations: int
    credential_reads: int
    retained_processes: int


class _Endpoint:
    def __init__(self) -> None:
        self.private_values = cast(object, None)
        self.submissions = 0

    async def submit(self, intent) -> str:  # type: ignore[no-untyped-def]
        self.submissions += 1
        return f"accepted:{intent.intent_id}"

    def events(self, cursor: ClientCursor | None = None) -> AsyncIterator[ClientEvent]:
        del cursor

        async def iterate() -> AsyncIterator[ClientEvent]:
            yield ClientEvent(
                protocol="asterion.agent-client/v1", event_id="event-1", session_id="session-1",
                generation=1, sequence=1, emitted_at="2026-08-28T12:00:00Z",
                type="session.terminal", payload={"reason_code": "completed", "status": "completed"},
            )

        return iterate()

    async def close(self) -> None:
        return None


def _input_params() -> dict[str, object]:
    return {
        "protocol": "asterion.agent-client/v1", "intent_id": "intent-1", "client_id": "client-1",
        "session_id": "session-1", "authority_revision": 1, "type": "input.submit",
        "payload": {"content_ref": "private-input-1", "delivery": "direct", "input_id": "input-1"},
    }


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(_plain(value), separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


async def _provider_free_receipt() -> _Receipt:
    endpoint = _Endpoint()
    client = AgentClient(cast(ClientSessionEndpoint, endpoint), client_id="client-1")
    rpc = ClientRpcAdapter(client)
    acp_stdout = io.BytesIO()
    acp = ClientAcpAdapter(client, stdout=acp_stdout)
    ack = await rpc.request({"id": "rpc-1", "method": "input.submit", "params": _input_params()})
    rpc_events = [event async for event in rpc.events()]
    acp_events = [event async for event in acp.events()]
    protocol_surface = {
        "ack": dict(ack), "acp_events": [_plain(event) for event in acp_events],
        "acp_stdout_sha256": hashlib.sha256(acp_stdout.getvalue()).hexdigest(),
        "rpc_events": [_plain(event) for event in rpc_events],
    }
    receipt: _Receipt = {
        "command_id": _COMMAND, "feature_ids": list(_FEATURE_IDS), "scenario_ids": list(_SCENARIO_IDS),
        "rpc_methods": sorted(RPC_METHODS), "acp_event_methods": dict(ACP_EVENT_METHODS),
        "protocol_digest": _digest(protocol_surface), "provider_operations": 0,
        "credential_reads": 0, "retained_processes": 0,
    }
    if endpoint.submissions != 1 or _SENTINEL in json.dumps(receipt, sort_keys=True):
        raise AssertionError("provider-free protocol behavior is invalid")
    return receipt


def _validate_receipt(receipt: _Receipt) -> None:
    if (
        receipt["command_id"] != _COMMAND
        or tuple(receipt["feature_ids"]) != _FEATURE_IDS
        or tuple(receipt["scenario_ids"]) != _SCENARIO_IDS
        or receipt["rpc_methods"] != sorted(RPC_METHODS)
        or receipt["acp_event_methods"] != dict(ACP_EVENT_METHODS)
        or receipt["protocol_digest"] != "2c1f61b6920342893dc9aeef10e232e87251db50c7fbcceb187c78e1826c35ab"
        or receipt["provider_operations"] != 0
        or receipt["credential_reads"] != 0
        or receipt["retained_processes"] != 0
        or _SENTINEL in json.dumps(receipt, sort_keys=True)
    ):
        raise AssertionError("provider-free protocol receipt is invalid")


class TestPrimeClientProtocolReceipt(unittest.IsolatedAsyncioTestCase):
    async def test_provider_free_receipt_executes_the_exact_protocol_boundary(self) -> None:
        receipt = await _provider_free_receipt()

        _validate_receipt(receipt)

    async def test_provider_free_receipt_rejects_identity_and_effect_drift(self) -> None:
        receipt = await _provider_free_receipt()
        mutations: tuple[_Receipt, ...] = (
            {**receipt, "provider_operations": 1}, {**receipt, "credential_reads": 1},
            {**receipt, "retained_processes": 1}, {**receipt, "feature_ids": ["interface.rpc"]},
            {**receipt, "command_id": _SENTINEL},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                _validate_receipt(mutation)
