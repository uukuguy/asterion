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
from asterion.client.protocol import (
    ClientCursor,
    ClientEvent,
    ClientIntent,
    validate_client_event_stream,
)
from asterion.client.session import (
    ClientObservation,
    ClientSessionError,
    HostClientSessionEndpoint,
)
from asterion.control.authority import AuthorityLedger
from asterion.control.host import ControlCommand
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


class _ObservationSource:
    def __init__(self, observations: tuple[ClientObservation, ...]) -> None:
        self.observations = observations
        self.cursors: list[ClientCursor | None] = []

    def client_observations(self, cursor: ClientCursor | None = None):
        self.cursors.append(cursor)

        async def iterate():
            for observation in self.observations:
                if cursor is None or observation.source_sequence > cursor.sequence:
                    yield observation

        return iterate()


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


def _observation(
    source_sequence: int,
    observation_id: str,
    *,
    kind: str = "message.available",
    payload: dict[str, object] | None = None,
) -> ClientObservation:
    return ClientObservation(
        observation_id=observation_id,
        session_id="session-1",
        generation=1,
        source_sequence=source_sequence,
        emitted_at="2026-08-10T15:00:00Z",
        kind=kind,
        payload=payload
        if payload is not None
        else {
            "content_ref": f"private-{observation_id}",
            "media_type": "text/plain",
            "message_id": observation_id,
            "role": "assistant",
            "sha256": "a" * 64,
            "size": 1,
        },
    )


def _endpoint(
    *,
    journal: MemoryCanonicalJournal | None = None,
    provider: ScriptedClient | None = None,
    observation_source: _ObservationSource | None = None,
) -> tuple[HostClientSessionEndpoint, ScriptedClient, MemoryCanonicalJournal]:
    with tempfile.TemporaryDirectory() as directory:
        plan = resolve_agent_system(
            _manifest(),
            application_providers=(_provider(Path(directory)),),
            control_factories=_control_factories([]),
            host_capabilities=("clock.monotonic", "storage.private"),
        )
    journal = journal or MemoryCanonicalJournal("session-1")
    provider = provider or ScriptedClient(plan.control_binding.manifest)
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
        authority_revision_source=lambda: host.authority_revision,
    )
    endpoint = HostClientSessionEndpoint(
        client_id="client-1",
        host=host,
        journal=journal,
        private_values=private_values,
        observation_source=observation_source,
    )
    return endpoint, provider, journal


class TestClientSession(unittest.IsolatedAsyncioTestCase):
    async def test_recovery_retries_durably_accepted_undispatched_intent_once(self) -> None:
        endpoint, provider, journal = _endpoint()
        intent = _input_intent("intent-1", "private-input-1")
        journal.accept_client_intent(intent, expected_position=journal.position)

        recovered, _, _ = _endpoint(journal=journal, provider=provider)

        self.assertEqual(await recovered.submit(intent), "client:intent-1")
        self.assertEqual(await recovered.submit(intent), "client:intent-1")
        self.assertEqual([item.command_id for item in provider.sent], ["client:intent-1"])
        with self.assertRaises(ClientSessionError):
            await recovered.submit(_input_intent("intent-1", "private-input-2"))

    async def test_recovery_does_not_redeliver_command_accepted_prefix(self) -> None:
        _, _, journal = _endpoint()
        intent = _input_intent("intent-1", "private-input-1")
        journal.accept_client_intent(intent, expected_position=journal.position)
        journal.accept_command(
            ControlCommand(
                command_id="client:intent-1",
                session_id="session-1",
                authority_revision=1,
                type="input.submit",
                payload={
                    "content_ref": "private-input-1",
                    "delivery": "direct",
                    "input_id": "input-1",
                },
            ),
            expected_position=journal.position,
        )

        recovered, provider, _ = _endpoint(journal=journal)

        self.assertEqual(await recovered.submit(intent), "client:intent-1")
        self.assertEqual(provider.sent, [])

    async def test_recovery_rejects_client_prefix_interleaving_or_identity_mismatch(self) -> None:
        cases = ("interleaved-event", "mismatched-command")
        for case in cases:
            with self.subTest(case=case):
                _, _, journal = _endpoint()
                intent = _input_intent("intent-1", "private-input-1")
                journal.accept_client_intent(intent, expected_position=journal.position)
                if case == "interleaved-event":
                    journal.accept_client_event(
                        ClientEvent(
                            protocol="asterion.agent-client/v1",
                            event_id="event-1",
                            session_id="session-1",
                            generation=1,
                            sequence=1,
                            emitted_at="2026-08-10T15:00:00Z",
                            type="message.available",
                            payload={
                                "content_ref": "private-message-1",
                                "media_type": "text/plain",
                                "message_id": "message-1",
                                "role": "assistant",
                                "sha256": "a" * 64,
                                "size": 1,
                            },
                        ),
                        expected_position=journal.position,
                    )
                else:
                    journal.accept_command(
                        ControlCommand(
                            command_id="client:intent-1",
                            session_id="session-1",
                            authority_revision=1,
                            type="input.submit",
                            payload={
                                "content_ref": "private-input-2",
                                "delivery": "direct",
                                "input_id": "input-1",
                            },
                        ),
                        expected_position=journal.position,
                    )

                with self.assertRaises(ClientSessionError):
                    _endpoint(journal=journal)

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

    async def test_observation_cursor_uses_last_source_sequence(self) -> None:
        source = _ObservationSource(
            (
                _observation(41, "observation-41"),
                _observation(97, "observation-97"),
            )
        )
        endpoint, _, journal = _endpoint(observation_source=source)

        await endpoint.pump()
        await endpoint.pump()

        self.assertEqual(source.cursors, [None, ClientCursor(1, 97)])
        self.assertEqual(
            [event.sequence async for event in endpoint.events()],
            [1, 2],
        )
        self.assertEqual(
            _client_kinds(journal),
            (
                "client.observation.accepted",
                "client.event.accepted",
                "client.observation.accepted",
                "client.event.accepted",
            ),
        )

    async def test_observation_prefix_rejects_invalid_tool_and_terminal_events(self) -> None:
        tool_started = {
            "call_id": "call-1",
            "arguments_ref": "private-arguments-1",
            "name": "tool",
            "sha256": "a" * 64,
            "size": 1,
        }
        tool_completed = {
            "call_id": "call-1",
            "is_error": False,
            "media_type": "application/json",
            "result_ref": "private-result-1",
            "sha256": "a" * 64,
            "size": 1,
        }
        terminal = {"reason_code": "completed", "status": "completed"}
        cases = (
            (
                "completion without start",
                (_observation(1, "completed", kind="tool.completed", payload=tool_completed),),
            ),
            (
                "terminal with active call",
                (
                    _observation(1, "started", kind="tool.started", payload=tool_started),
                    _observation(2, "terminal", kind="session.terminal", payload=terminal),
                ),
            ),
            (
                "post terminal",
                (
                    _observation(1, "terminal", kind="session.terminal", payload=terminal),
                    _observation(2, "message", kind="message.available"),
                ),
            ),
            (
                "call id reuse",
                (
                    _observation(1, "started-1", kind="tool.started", payload=tool_started),
                    _observation(2, "completed", kind="tool.completed", payload=tool_completed),
                    _observation(3, "started-2", kind="tool.started", payload=tool_started),
                ),
            ),
        )
        for label, observations in cases:
            with self.subTest(label=label):
                endpoint, _, _ = _endpoint(
                    observation_source=_ObservationSource(observations)
                )
                with self.assertRaises(ClientSessionError):
                    await endpoint.pump()

    async def test_terminal_observation_stream_is_protocol_valid(self) -> None:
        endpoint, _, _ = _endpoint(
            observation_source=_ObservationSource(
                (
                    _observation(7, "message-1"),
                    _observation(
                        12,
                        "terminal-1",
                        kind="session.terminal",
                        payload={"reason_code": "completed", "status": "completed"},
                    ),
                )
            )
        )

        await endpoint.pump()
        events = [event async for event in endpoint.events()]

        self.assertEqual(validate_client_event_stream(events), tuple(events))

    async def test_private_resolution_checks_live_authority_before_and_after_read(self) -> None:
        revision = [1]

        class RevokingBackend(_PrivateBackend):
            def read(self, reference: str, *, max_bytes: int) -> bytes:
                body = super().read(reference, max_bytes=max_bytes)
                revision[0] = 2
                return body

        service = ClientPrivateValueService(
            access=ClientAccess(
                client_id="client-1",
                session_id="session-1",
                authority_revision=1,
                purposes=("interactive-render",),
            ),
            backend=RevokingBackend(),
            clock_ms=lambda: 1,
            authority_revision_source=lambda: revision[0],
        )

        with self.assertRaises(ClientPrivateValueError):
            service.resolve_bytes(
                "private-input-1",
                purpose="interactive-render",
                max_bytes=32,
                deadline_ms=10,
            )
