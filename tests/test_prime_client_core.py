from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import TypedDict, cast
from pathlib import Path

from asterion.client import (
    AgentClient,
    ClientAccess,
    ClientCursor,
    ClientEvent,
    ClientIntent,
    ClientPrivateValueService,
    JsonlClientCodec,
    PrivateValueDescriptor,
)
from asterion.client.session import ClientSessionEndpoint


_COMMAND = "make test.prime-client-core.provider-free"
_FEATURE_IDS = ("interface.json-stream", "interface.sdk")
_SCENARIO_IDS = ("prime-client-core.jsonl", "prime-client-core.sdk")
_PRIVATE_BODY = b"SENTINEL_PRIVATE_VALUE"
_EXPECTED_PRIVATE_SERVICE_CONTRACT_DIGEST = "253fd97dfe3a84ec859474538bc0998afa8182ae420d5bc5b1e46460a91ea85b"
_EXPECTED_STREAM_CONTRACT_DIGEST = "7859db9960e895e4ffd60d90c06f54471897409c753ee7dbb7eed23a1369a1f4"
_PROJECT = Path(__file__).resolve().parents[1]


def _real_prime_receipt(package: str) -> dict[str, object]:
    completed = subprocess.run(
        ("node", str(_PROJECT / "tests/fixtures/prime_gateway/v1/real-prime-clients.mjs"),
         "--package", package, "--resource-root", str(_PROJECT / "packages/typescript/prime-gateway/resources"),
         "--prime-root", str(_PROJECT / "3th-party/prime-agent")),
        cwd=_PROJECT, check=True, capture_output=True, text=True,
    )
    return cast(dict[str, object], json.loads(completed.stdout))


class _CoreReceipt(TypedDict):
    command_id: str
    credential_reads: int
    feature_ids: list[str]
    private_service_contract_digest: str
    provider_operations: int
    retained_processes: int
    scenario_ids: list[str]
    stream_contract_digest: str


@dataclass
class _Effects:
    credential_reads: int = 0
    provider_operations: int = 0
    private_reads: int = 0
    retained_processes: int = 0


class _PrivateBackend:
    def __init__(self, effects: _Effects) -> None:
        self._effects = effects
        self._descriptor = PrivateValueDescriptor(
            reference="private-message-1",
            kind="message",
            media_type="text/plain",
            size=len(_PRIVATE_BODY),
            sha256=hashlib.sha256(_PRIVATE_BODY).hexdigest(),
        )
        self.describe_calls = 0

    @property
    def descriptor(self) -> PrivateValueDescriptor:
        return self._descriptor

    def describe(self, reference: str) -> PrivateValueDescriptor:
        self.describe_calls += 1
        if reference != self._descriptor.reference:
            raise ValueError("private reference is unavailable")
        return self._descriptor

    def read(self, reference: str, *, max_bytes: int) -> bytes:
        if reference != self._descriptor.reference or max_bytes < len(_PRIVATE_BODY):
            raise ValueError("private reference is unavailable")
        self._effects.private_reads += 1
        return _PRIVATE_BODY


class _EvidenceEndpoint:
    def __init__(self, effects: _Effects, backend: _PrivateBackend) -> None:
        self._effects = effects
        self._private_values = ClientPrivateValueService(
            access=ClientAccess(
                client_id="client-1",
                session_id="session-1",
                authority_revision=1,
                purposes=("interactive-render",),
            ),
            backend=backend,
            clock_ms=lambda: 1,
            authority_revision_source=lambda: 1,
        )
        self.closed = False
        self.events_calls = 0
        self.submissions: list[ClientIntent] = []

    @property
    def private_values(self) -> ClientPrivateValueService:
        return self._private_values

    async def submit(self, intent: ClientIntent) -> str:
        self.submissions.append(intent)
        return f"accepted:{intent.intent_id}"

    def events(self, cursor: ClientCursor | None = None) -> AsyncIterator[ClientEvent]:
        self.events_calls += 1

        async def iterate() -> AsyncIterator[ClientEvent]:
            yield ClientEvent(
                protocol="asterion.agent-client/v1",
                event_id="event-1",
                session_id="session-1",
                generation=1,
                sequence=1,
                emitted_at="2026-08-10T15:00:00Z",
                type="session.terminal",
                payload={"reason_code": "completed", "status": "completed"},
            )

        return iterate()

    async def pump(self, *, until_terminal: bool = False) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _public_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {key: _public_value(item) for key, item in value.items()}


def _public_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _public_mapping(value)
    if isinstance(value, tuple):
        return [_public_value(item) for item in value]
    return value


async def _provider_free_receipt() -> _CoreReceipt:
    effects = _Effects()
    backend = _PrivateBackend(effects)
    endpoint = _EvidenceEndpoint(effects, backend)
    client = AgentClient(cast(ClientSessionEndpoint, endpoint), client_id="client-1")
    codec = JsonlClientCodec(max_line_bytes=2_048, max_depth=8)

    accepted = await client.submit_input(
        session_id="session-1",
        authority_revision=1,
        input_id="input-1",
        content_ref="private-message-1",
        delivery="direct",
    )
    events = [event async for event in client.events()]
    resolved = client.resolve_text(
        "private-message-1", purpose="interactive-render", max_bytes=64, deadline_ms=2
    )
    encoded = codec.encode({"accepted": accepted, "events": [event.to_mapping() for event in events]})
    decoded = codec.feed(encoded, eof=True)
    await client.close()

    if (
        resolved.encode("utf-8") != _PRIVATE_BODY
        or len(endpoint.submissions) != 1
        or endpoint.events_calls != 1
        or not endpoint.closed
        or effects.private_reads != 1
    ):
        raise AssertionError("provider-free client behavior is invalid")
    return {
        "command_id": _COMMAND,
        "credential_reads": effects.credential_reads,
        "feature_ids": list(_FEATURE_IDS),
        "private_service_contract_digest": _digest(
            {
                "access": {
                    "authority_revision": endpoint.private_values.access.authority_revision,
                    "client_id": endpoint.private_values.access.client_id,
                    "purposes": list(endpoint.private_values.access.purposes),
                    "session_id": endpoint.private_values.access.session_id,
                },
                "descriptor": {
                    "media_type": backend.descriptor.media_type,
                    "sha256": backend.descriptor.sha256,
                    "size": backend.descriptor.size,
                },
                "describe_calls": backend.describe_calls,
                "private_reads": effects.private_reads,
            }
        ),
        "provider_operations": effects.provider_operations,
        "retained_processes": effects.retained_processes,
        "scenario_ids": list(_SCENARIO_IDS),
        "stream_contract_digest": _digest(
            {
                "decoded": [_public_mapping(item) for item in decoded],
                "encoded_sha256": hashlib.sha256(encoded).hexdigest(),
                "event_ids": [event.event_id for event in events],
                "event_types": [event.type for event in events],
            }
        ),
    }


def _validate_receipt(receipt: _CoreReceipt) -> None:
    if (
        receipt["command_id"] != _COMMAND
        or tuple(receipt["feature_ids"]) != _FEATURE_IDS
        or tuple(receipt["scenario_ids"]) != _SCENARIO_IDS
        or receipt["private_service_contract_digest"] != _EXPECTED_PRIVATE_SERVICE_CONTRACT_DIGEST
        or receipt["stream_contract_digest"] != _EXPECTED_STREAM_CONTRACT_DIGEST
        or receipt["provider_operations"] != 0
        or receipt["credential_reads"] != 0
        or receipt["retained_processes"] != 0
        or "SENTINEL_PRIVATE_VALUE" in json.dumps(receipt, sort_keys=True)
    ):
        raise AssertionError("provider-free client receipt is invalid")


class TestPrimeClientCoreReceipt(unittest.IsolatedAsyncioTestCase):
    async def test_locked_real_prime_harness_proves_exact_core_package(self) -> None:
        receipt = _real_prime_receipt("core")
        self.assertEqual(receipt["package"], "core")
        self.assertEqual(receipt["feature_count"], 2)
        self.assertEqual(receipt["scenario_count"], 2)
        self.assertEqual(receipt["provider_operations"], 0)
        self.assertEqual(receipt["credential_reads"], 0)
        self.assertEqual(receipt["retained_processes"], 0)
        self.assertNotIn("SENTINEL_PRIVATE_VALUE", json.dumps(receipt, sort_keys=True))

    async def test_provider_free_receipt_executes_the_exact_core_boundary(self) -> None:
        receipt = await _provider_free_receipt()

        _validate_receipt(receipt)

    async def test_provider_free_receipt_rejects_counter_and_identity_drift(self) -> None:
        receipt = await _provider_free_receipt()
        mutations: tuple[_CoreReceipt, ...] = (
            {**receipt, "provider_operations": 1},
            {**receipt, "credential_reads": 1},
            {**receipt, "retained_processes": 1},
            {**receipt, "feature_ids": ["interface.sdk"]},
            {**receipt, "command_id": "SENTINEL_PRIVATE_VALUE"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.assertRaises(AssertionError):
                    _validate_receipt(cast(_CoreReceipt, mutation))
