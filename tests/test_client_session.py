from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from asterion.client.private import (
    ClientAccess,
    ClientPrivateValueError,
    ClientPrivateValueService,
    PrivateValueDescriptor,
)
from asterion.client.protocol import ClientIntent
from asterion.client.session import ClientSessionError, HostClientSessionEndpoint
from asterion.control.authority import AuthorityLedger
from asterion.control.journal import JournalCursor, MemoryCanonicalJournal
from asterion.control.manager import ControlHost
from tests.test_control_authority import _envelope
from tests.test_control_host import ScriptedClient, SpyExecutor
from tests.test_control_system import _control_factories, _manifest, _provider
from asterion.control.system import resolve_agent_system


class _PrivateBackend:
    def __init__(self) -> None:
        self._body = b"SENTINEL_PRIVATE_BODY"
        self._descriptor = PrivateValueDescriptor(
            reference="private-input-1",
            kind="input",
            media_type="text/plain",
            size=len(self._body),
            sha256=hashlib.sha256(self._body).hexdigest(),
        )

    def describe(self, reference: str) -> PrivateValueDescriptor:
        if reference != self._descriptor.reference:
            raise KeyError(reference)
        return self._descriptor

    def read(self, reference: str, *, max_bytes: int) -> bytes:
        if reference != self._descriptor.reference or max_bytes < len(self._body):
            raise KeyError(reference)
        return self._body


def _input_intent(intent_id: str, content_ref: str) -> ClientIntent:
    return ClientIntent(
        protocol="asterion.agent-client/v1",
        intent_id=intent_id,
        client_id="client-1",
        session_id="session-1",
        authority_revision=1,
        type="input.submit",
        payload={
            "content_ref": content_ref,
            "delivery": "direct",
            "input_id": "input-1",
        },
    )


def _client_kinds(journal: MemoryCanonicalJournal) -> tuple[str, ...]:
    return tuple(
        entry.record.kind
        for entry in journal.replay(JournalCursor(0))
        if entry.record.kind.startswith("client.")
    )


def _endpoint() -> tuple[HostClientSessionEndpoint, ScriptedClient, MemoryCanonicalJournal]:
    with tempfile.TemporaryDirectory() as directory:
        plan = resolve_agent_system(
            _manifest(),
            application_providers=(_provider(Path(directory)),),
            control_factories=_control_factories([]),
            host_capabilities=("clock.monotonic", "storage.private"),
        )
    journal = MemoryCanonicalJournal("session-1")
    provider = ScriptedClient(plan.control_binding.manifest)
    host = ControlHost(
        session_id="session-1",
        generation=1,
        plan=plan,
        authority=AuthorityLedger(_envelope()),
        journal=journal,
        client=provider,
        action_executor=SpyExecutor(),
        clock_ms=lambda: 1_000,
    )
    private_values = ClientPrivateValueService(
        access=ClientAccess(
            client_id="client-1",
            session_id="session-1",
            authority_revision=1,
            purposes=("interactive-render",),
        ),
        backend=_PrivateBackend(),
        clock_ms=lambda: 1,
    )
    endpoint = HostClientSessionEndpoint(
        client_id="client-1",
        host=host,
        journal=journal,
        private_values=private_values,
    )
    return endpoint, provider, journal


class TestClientSession(unittest.IsolatedAsyncioTestCase):
    async def test_persist_before_dispatch_and_identical_retry(self) -> None:
        endpoint, provider, journal = _endpoint()
        intent = _input_intent("intent-1", "private-input-1")

        await endpoint.submit(intent)
        await endpoint.submit(intent)

        self.assertEqual([item.command_id for item in provider.sent], ["client:intent-1"])
        self.assertEqual(_client_kinds(journal), ("client.intent.accepted",))

    async def test_conflicting_retry_and_wrong_private_purpose_reject(self) -> None:
        endpoint, provider, _journal = _endpoint()
        await endpoint.submit(_input_intent("intent-1", "private-input-1"))

        with self.assertRaises(ClientSessionError):
            await endpoint.submit(_input_intent("intent-1", "private-input-2"))
        with self.assertRaises(ClientPrivateValueError):
            endpoint.private_values.resolve_text(
                "private-input-1", purpose="private-export", max_bytes=32, deadline_ms=10
            )

        self.assertEqual([item.command_id for item in provider.sent], ["client:intent-1"])
