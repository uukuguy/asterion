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
_MODULE_IDS = (
    "tests.test_client_interactive", "tests.test_asterion_cli", "tests.test_prime_client_interactive",
)
_RECEIPT_KEYS = frozenset({
    "credential_reads", "feature_ids", "gate_id", "module_ids", "private_service_contract_digest",
    "provider_operations", "redaction_status", "retained_processes", "scenario_ids", "stream_contract_digest",
})
_FORBIDDEN_FIELDS = frozenset({"answer", "body", "command", "credential", "destination", "output", "path", "prompt", "raw_output", "source_path"})
_FORBIDDEN_TERMS = ("answer", "body", "credential", "destination", "output", "path", "private", "prompt", "raw", "source")
_SENTINEL = "SENTINEL_PRIVATE_VALUE"
_EXPECTED_PRIVATE_SERVICE_CONTRACT_DIGEST = "2698bba4cdb115363cc5cb0af1b45b52f4e17a20f890a9afec7478270913b403"
_EXPECTED_STREAM_CONTRACT_DIGEST = "b4727b9bbedfa05b9bba658462562f6c5e61bde8a8608d7b2277620c6d134c72"
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
    credential_reads: int
    feature_ids: list[str]
    gate_id: str
    module_ids: list[str]
    private_service_contract_digest: str
    provider_operations: int
    redaction_status: str
    retained_processes: int
    scenario_ids: list[str]
    stream_contract_digest: str


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
        if reference != "value-1" or purpose != "headless-final" or max_bytes != 5 or deadline_ms < 1:
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


def _digest(value: object) -> str:
    return hashlib.sha256(_serialize(value)).hexdigest()


def _serialize(value: object) -> bytes:
    return json.dumps(_plain(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple) or isinstance(value, list):
        return [_plain(item) for item in value]
    return value


async def _provider_free_receipt() -> _Receipt:
    effects = _Effects()
    message = _event("event-1", 1, "message.available", {
        "content_ref": "value-1", "media_type": "text/plain", "message_id": "message-1",
        "role": "assistant", "sha256": hashlib.sha256(b"FINAL").hexdigest(), "size": 5,
    })
    terminal = _event("event-2", 2, "session.terminal", {"reason_code": "completed", "status": "completed"})
    headless, headless_endpoint = _client(effects, (message, terminal))
    text = io.StringIO()
    await run_headless(headless, mode="text", stdout=text, deadline_ms=1)

    commands = _event("event-1", 1, "commands.changed", {"commands": ["inspect"], "revision": 1})
    interactive, interactive_endpoint = _client(effects, (commands, terminal))
    tui = io.StringIO()
    state = await run_interactive(interactive, stdout=tui)
    registry = ClientCommandRegistry.from_state(state)
    accepted = await registry.invoke(interactive, session_id="session-1", authority_revision=1, intent_id="intent-1", command_name="inspect", arguments_ref="arguments-1")

    ui_client, _ = _client(effects, ())
    response = await respond_to_extension_ui(ClientUiRequest("ui-1", "extension", "value-ui-1", 1), ui_client, clock_ms=lambda: 2)
    if (
        text.getvalue() != "FINAL\n" or effects.private_reads != [("value-1", "headless-final")]
        or not headless_endpoint.closed or not interactive_endpoint.closed or accepted != "accepted"
        or len(interactive_endpoint.submissions) != 1
        or response.payload != {"request_id": "ui-1", "cancelled": True, "response_ref": None}
    ):
        raise AssertionError("provider-free interactive behavior is invalid")
    return {
        "credential_reads": effects.credential_reads,
        "feature_ids": list(_FEATURE_IDS), "gate_id": _GATE_ID, "module_ids": list(_MODULE_IDS),
        "private_service_contract_digest": _digest({
            "purposes": ["headless-final", "interactive-render", "extension-ui-response"],
            "headless_read": effects.private_reads, "ui_timeout_cancelled": True,
        }),
        "provider_operations": effects.provider_operations, "redaction_status": "pass",
        "retained_processes": effects.retained_processes, "scenario_ids": list(_SCENARIO_IDS),
        "stream_contract_digest": _digest({
            "headless_events": [message.to_mapping(), terminal.to_mapping()],
            "interactive_render": tui.getvalue(),
            "command_revision": getattr(interactive_endpoint.submissions[0], "payload")["command_revision"],
        }),
    }


def _validate_receipt(receipt: object) -> None:
    try:
        if type(receipt) is not dict or set(receipt) != _RECEIPT_KEYS:
            raise AssertionError
        raw = cast(_Receipt, receipt)
        if (
            raw["gate_id"] != _GATE_ID or raw["feature_ids"] != list(_FEATURE_IDS)
            or raw["scenario_ids"] != list(_SCENARIO_IDS) or raw["module_ids"] != list(_MODULE_IDS)
            or raw["private_service_contract_digest"] != _EXPECTED_PRIVATE_SERVICE_CONTRACT_DIGEST
            or raw["stream_contract_digest"] != _EXPECTED_STREAM_CONTRACT_DIGEST
            or raw["redaction_status"] != "pass"
            or any(type(raw[field]) is not int or raw[field] != 0 for field in ("provider_operations", "credential_reads", "retained_processes"))
        ):
            raise AssertionError
        for field in ("private_service_contract_digest", "stream_contract_digest"):
            if re.fullmatch(r"[0-9a-f]{64}", raw[field]) is None:
                raise AssertionError
        _validate_public_evidence({key: value for key, value in raw.items() if key not in {"private_service_contract_digest", "stream_contract_digest"}})
    except AssertionError:
        raise
    except Exception:
        raise AssertionError("provider-free interactive receipt is invalid") from None


def _validate_public_evidence(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is not str or key.casefold() in _FORBIDDEN_FIELDS:
                raise AssertionError("provider-free interactive receipt is invalid")
            _validate_public_evidence(item)
        return
    if type(value) is list or type(value) is tuple:
        for item in value:
            _validate_public_evidence(item)
        return
    if type(value) is str:
        lowered = value.casefold()
        if value.startswith(("/", "~")) or "\\" in value or any(term in lowered for term in _FORBIDDEN_TERMS):
            raise AssertionError("provider-free interactive receipt is invalid")
        return
    if value is None or type(value) is bool or type(value) is int:
        return
    raise AssertionError("provider-free interactive receipt is invalid")


class TestPrimeClientInteractiveReceipt(unittest.IsolatedAsyncioTestCase):
    async def test_locked_real_prime_harness_proves_exact_interactive_package(self) -> None:
        receipt = _real_prime_receipt("interactive")
        self.assertEqual(
            set(receipt),
            {
                "artifact_lock_digest", "credential_reads", "feature_count", "feature_ids",
                "module_digest", "module_lock_digest", "package", "private_reads",
                "provider_operations", "retained_processes", "scenario_count",
                "scenario_evidence", "scenario_ids", "source_commit", "stdout_writes",
                "unauthorized_uploads",
            },
        )
        for field, filename in (
            ("artifact_lock_digest", "prime-artifact-lock.json"),
            ("module_lock_digest", "prime-client-module-lock.json"),
            ("module_digest", "prime-client-module.mjs"),
        ):
            with self.subTest(field=field):
                self.assertEqual(
                    receipt[field],
                    hashlib.sha256(
                        (_PROJECT / "packages/typescript/prime-gateway/resources" / filename).read_bytes()
                    ).hexdigest(),
                )
        self.assertEqual(receipt["source_commit"], "a18809e00ea30638584d87b3afea7285a9d7296c")
        self.assertEqual((receipt["package"], receipt["feature_count"], receipt["scenario_count"]), ("interactive", 4, 4))
        self.assertEqual((receipt["provider_operations"], receipt["credential_reads"], receipt["retained_processes"]), (0, 0, 0))
        self.assertNotIn(_SENTINEL, json.dumps(receipt, sort_keys=True))

    async def test_provider_free_receipt_executes_exact_interactive_boundary(self) -> None:
        receipt = await _provider_free_receipt()
        _validate_receipt(receipt)
        self.assertEqual(_serialize(receipt), _serialize(await _provider_free_receipt()))

    async def test_receipt_rejects_effect_identity_and_recursive_private_evidence(self) -> None:
        receipt = await _provider_free_receipt()
        mutations: tuple[object, ...] = (
            {**receipt, "provider_operations": 1}, {**receipt, "module_ids": []},
            {**receipt, "feature_ids": ["interface.cli-interactive"]}, {**receipt, "command": "make check"},
            {**receipt, "nested": {"raw_output": _SENTINEL}},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                _validate_receipt(mutation)
        for evidence in ({"source_path": "/secret"}, {"nested": {"raw_output": _SENTINEL}}, {"nested": "private_destination"}):
            with self.subTest(evidence=evidence), self.assertRaises(AssertionError):
                _validate_public_evidence(evidence)
