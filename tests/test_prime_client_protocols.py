from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import unittest
from collections.abc import AsyncIterator, Mapping
from typing import TypedDict, cast
from pathlib import Path

from asterion.client import AgentClient, ClientCursor, ClientEvent
from asterion.client.acp import ACP_EVENT_METHODS, ClientAcpAdapter
from asterion.client.rpc import ClientRpcAdapter, RPC_METHODS
from asterion.client.session import ClientSessionEndpoint


_GATE_ID = "test.prime-client-protocols.provider-free"
_FEATURE_IDS = ("interface.acp", "interface.rpc")
_SCENARIO_IDS = ("prime-parity.interface.acp", "prime-parity.interface.rpc")
_MODULE_IDS = ("tests.test_client_rpc_acp", "tests.test_prime_client_protocols")
_SENTINEL = "SENTINEL_PRIVATE_VALUE"
_RECEIPT_KEYS = frozenset(
    {
        "acp_event_methods", "credential_reads", "feature_ids", "gate_id", "module_ids",
        "protocol_digest", "provider_operations", "redaction_status", "retained_processes",
        "rpc_methods", "scenario_ids",
    }
)
_SAFE_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_FORBIDDEN_FIELD_NAMES = frozenset(
    {"answer", "body", "command", "credential", "destination", "output", "path",
     "private_destination", "prompt", "raw_output", "source_path"}
)
_FORBIDDEN_VALUE_TERMS = (
    "answer", "body", "credential", "destination", "output", "path", "private",
    "prompt", "raw", "source",
)
_PROJECT = Path(__file__).resolve().parents[1]


def _real_prime_receipt(package: str) -> dict[str, object]:
    completed = subprocess.run(
        ("node", str(_PROJECT / "tests/fixtures/prime_gateway/v1/real-prime-clients.mjs"),
         "--package", package, "--resource-root", str(_PROJECT / "packages/typescript/prime-gateway/resources"),
         "--prime-root", str(_PROJECT / "3th-party/prime-agent")),
        cwd=_PROJECT, check=True, capture_output=True, text=True,
    )
    return cast(dict[str, object], json.loads(completed.stdout))


class _Receipt(TypedDict):
    gate_id: str
    feature_ids: list[str]
    scenario_ids: list[str]
    module_ids: list[str]
    rpc_methods: list[str]
    acp_event_methods: dict[str, str]
    protocol_digest: str
    provider_operations: int
    credential_reads: int
    retained_processes: int
    redaction_status: str


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
        "gate_id": _GATE_ID, "feature_ids": list(_FEATURE_IDS), "scenario_ids": list(_SCENARIO_IDS),
        "module_ids": list(_MODULE_IDS),
        "rpc_methods": sorted(RPC_METHODS), "acp_event_methods": dict(ACP_EVENT_METHODS),
        "protocol_digest": _digest(protocol_surface), "provider_operations": 0,
        "credential_reads": 0, "retained_processes": 0, "redaction_status": "pass",
    }
    if (
        endpoint.submissions != 1
        or dict(ack) != {"id": "rpc-1", "type": "ack", "intent_id": "intent-1"}
        or [event["type"] for event in rpc_events] != ["session.terminal"]
        or [event["method"] for event in acp_events] != ["session_end"]
        or not acp_stdout.getvalue()
    ):
        raise AssertionError("provider-free protocol behavior is invalid")
    _validate_public_evidence(protocol_surface)
    _validate_receipt(receipt)
    return receipt


def _validate_receipt(receipt: object) -> None:
    try:
        _validate_public_evidence(receipt)
        if type(receipt) is not dict or set(receipt) != _RECEIPT_KEYS:
            raise AssertionError
        if not isinstance(receipt["gate_id"], str) or _SAFE_ID.fullmatch(receipt["gate_id"]) is None:
            raise AssertionError
        if receipt["gate_id"] != _GATE_ID:
            raise AssertionError
        _require_exact_string_list(receipt["feature_ids"], _FEATURE_IDS)
        _require_exact_string_list(receipt["scenario_ids"], _SCENARIO_IDS)
        _require_exact_string_list(receipt["module_ids"], _MODULE_IDS)
        _require_exact_string_list(receipt["rpc_methods"], tuple(sorted(RPC_METHODS)))
        _require_exact_string_mapping(receipt["acp_event_methods"], dict(ACP_EVENT_METHODS))
        if (
            type(receipt["protocol_digest"]) is not str
            or receipt["protocol_digest"]
            != "2c1f61b6920342893dc9aeef10e232e87251db50c7fbcceb187c78e1826c35ab"
            or re.fullmatch(r"[0-9a-f]{64}", receipt["protocol_digest"]) is None
            or receipt["redaction_status"] != "pass"
        ):
            raise AssertionError
        for field in ("provider_operations", "credential_reads", "retained_processes"):
            if type(receipt[field]) is not int or receipt[field] != 0:
                raise AssertionError
    except AssertionError:
        raise
    except Exception:
        raise AssertionError("provider-free protocol receipt is invalid")


def _require_exact_string_list(value: object, expected: tuple[str, ...]) -> None:
    if type(value) is not list or any(type(item) is not str for item in value) or value != list(expected):
        raise AssertionError("provider-free protocol receipt is invalid")


def _require_exact_string_mapping(value: object, expected: dict[str, str]) -> None:
    if (
        type(value) is not dict
        or any(type(key) is not str or type(item) is not str for key, item in value.items())
        or value != expected
    ):
        raise AssertionError("provider-free protocol receipt is invalid")


def _validate_public_evidence(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is not str or key.casefold() in _FORBIDDEN_FIELD_NAMES:
                raise AssertionError("provider-free protocol receipt is invalid")
            _validate_public_evidence(item)
        return
    if type(value) is list or type(value) is tuple:
        for item in value:
            _validate_public_evidence(item)
        return
    if type(value) is str:
        lowered = value.casefold()
        if value.startswith(("/", "~")) or "\\" in value or any(term in lowered for term in _FORBIDDEN_VALUE_TERMS):
            raise AssertionError("provider-free protocol receipt is invalid")
        return
    if value is None or type(value) is bool:
        return
    if type(value) is int and -9_007_199_254_740_991 <= value <= 9_007_199_254_740_991:
        return
    raise AssertionError("provider-free protocol receipt is invalid")


class TestPrimeClientProtocolReceipt(unittest.IsolatedAsyncioTestCase):
    async def test_locked_real_prime_harness_proves_exact_protocol_package(self) -> None:
        receipt = _real_prime_receipt("protocols")
        self.assertEqual((receipt["package"], receipt["feature_count"], receipt["scenario_count"]), ("protocols", 2, 2))
        self.assertEqual((receipt["provider_operations"], receipt["credential_reads"], receipt["retained_processes"]), (0, 0, 0))
        self.assertNotIn(_SENTINEL, json.dumps(receipt, sort_keys=True))

    async def test_provider_free_receipt_executes_the_exact_protocol_boundary(self) -> None:
        receipt = await _provider_free_receipt()

        _validate_receipt(receipt)

    async def test_provider_free_receipt_rejects_identity_and_effect_drift(self) -> None:
        receipt = await _provider_free_receipt()
        mutations: tuple[object, ...] = (
            {**receipt, "provider_operations": 1}, {**receipt, "credential_reads": 1},
            {**receipt, "retained_processes": 1}, {**receipt, "feature_ids": ["interface.rpc"]},
            {**receipt, "gate_id": _SENTINEL}, {**receipt, "command": "make check"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                _validate_receipt(mutation)

    async def test_provider_free_receipt_rejects_noncanonical_structures_and_nested_private_values(self) -> None:
        receipt = await _provider_free_receipt()
        mutations: tuple[object, ...] = (
            {**receipt, "module_ids": _MODULE_IDS},
            {**receipt, "provider_operations": False},
            {**receipt, "acp_event_methods": {**receipt["acp_event_methods"], "raw_output": _SENTINEL}},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                _validate_receipt(mutation)

        for value in (
            {"source_path": "/private/source"},
            {"nested": {"raw_output": _SENTINEL}},
            {"nested": "private_destination"},
        ):
            with self.subTest(value=value), self.assertRaises(AssertionError):
                _validate_public_evidence(value)
