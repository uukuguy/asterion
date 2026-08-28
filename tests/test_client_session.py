from __future__ import annotations

import asyncio
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
        self.read_calls = 0
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
        self.read_calls += 1
        if reference != self._descriptor.reference or max_bytes < len(self._body):
            raise KeyError(reference)
        return self._body


class _BlockingSendClient(ScriptedClient):
    def __init__(self, manifest) -> None:
        super().__init__(manifest)
        self.send_calls = 0
        self.send_started = asyncio.Event()
        self.release_send = asyncio.Event()

    async def send(self, command: ControlCommand) -> None:
        self.send_calls += 1
        self.send_started.set()
        await self.release_send.wait()
        self.sent.append(command)


class _BlockingFailingSendClient(_BlockingSendClient):
    async def send(self, command: ControlCommand) -> None:
        self.send_calls += 1
        self.send_started.set()
        await self.release_send.wait()
        raise RuntimeError("SENTINEL_PROVIDER_FAILURE")


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
    backend: _PrivateBackend | None = None,
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
        backend=backend or _PrivateBackend(),
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
    async def test_owner_cancellation_does_not_cancel_shared_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
        provider = _BlockingSendClient(plan.control_binding.manifest)
        endpoint, _, _ = _endpoint(provider=provider)
        intent = _input_intent("intent-1", "private-input-1")

        owner = asyncio.create_task(endpoint.submit(intent))
        await asyncio.wait_for(provider.send_started.wait(), timeout=1)
        owner.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await owner

        retry = asyncio.create_task(endpoint.submit(intent))
        await asyncio.sleep(0)
        self.assertEqual(provider.send_calls, 1)
        provider.release_send.set()
        self.assertEqual(await retry, "client:intent-1")
        self.assertEqual(await endpoint.submit(intent), "client:intent-1")
        self.assertEqual(provider.send_calls, 1)

    async def test_follower_cancellation_does_not_cancel_shared_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
        provider = _BlockingSendClient(plan.control_binding.manifest)
        endpoint, _, _ = _endpoint(provider=provider)
        intent = _input_intent("intent-1", "private-input-1")

        owner = asyncio.create_task(endpoint.submit(intent))
        await asyncio.wait_for(provider.send_started.wait(), timeout=1)
        follower = asyncio.create_task(endpoint.submit(intent))
        await asyncio.sleep(0)
        follower.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await follower

        self.assertEqual(provider.send_calls, 1)
        provider.release_send.set()
        self.assertEqual(await owner, "client:intent-1")
        self.assertEqual(provider.send_calls, 1)

    async def test_all_waiter_cancellation_keeps_dispatch_for_blocked_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
        provider = _BlockingSendClient(plan.control_binding.manifest)
        endpoint, _, _ = _endpoint(provider=provider)
        intent = _input_intent("intent-1", "private-input-1")

        owner = asyncio.create_task(endpoint.submit(intent))
        await asyncio.wait_for(provider.send_started.wait(), timeout=1)
        follower = asyncio.create_task(endpoint.submit(intent))
        await asyncio.sleep(0)
        owner.cancel()
        follower.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await owner
        with self.assertRaises(asyncio.CancelledError):
            await follower

        retry = asyncio.create_task(endpoint.submit(intent))
        await asyncio.sleep(0)
        self.assertEqual(provider.send_calls, 1)
        provider.release_send.set()
        self.assertEqual(await retry, "client:intent-1")
        self.assertEqual(provider.send_calls, 1)

    async def test_provider_failure_is_shared_and_does_not_leak_after_close(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
        provider = _BlockingFailingSendClient(plan.control_binding.manifest)
        endpoint, _, _ = _endpoint(provider=provider)
        intent = _input_intent("intent-1", "private-input-1")

        owner = asyncio.create_task(endpoint.submit(intent))
        await asyncio.wait_for(provider.send_started.wait(), timeout=1)
        follower = asyncio.create_task(endpoint.submit(intent))
        await asyncio.sleep(0)
        provider.release_send.set()
        for caller in (owner, follower):
            with self.assertRaisesRegex(ClientSessionError, "^client intent dispatch failed$"):
                await caller
        self.assertEqual(provider.send_calls, 1)
        await endpoint.close()

    async def test_close_cancels_unobserved_dispatch_without_a_second_send(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
        provider = _BlockingSendClient(plan.control_binding.manifest)
        endpoint, _, _ = _endpoint(provider=provider)
        owner = asyncio.create_task(
            endpoint.submit(_input_intent("intent-1", "private-input-1"))
        )
        await asyncio.wait_for(provider.send_started.wait(), timeout=1)

        await endpoint.close()
        with self.assertRaises(asyncio.CancelledError):
            await owner
        self.assertEqual(provider.send_calls, 1)

    async def test_concurrent_identical_submit_single_flights_provider_send(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
        provider = _BlockingSendClient(plan.control_binding.manifest)
        endpoint, _, _ = _endpoint(provider=provider)
        intent = _input_intent("intent-1", "private-input-1")

        first = asyncio.create_task(endpoint.submit(intent))
        await asyncio.wait_for(provider.send_started.wait(), timeout=1)
        second = asyncio.create_task(endpoint.submit(intent))
        await asyncio.sleep(0)

        self.assertEqual(provider.send_calls, 1)
        provider.release_send.set()
        self.assertEqual(
            await asyncio.gather(first, second),
            ["client:intent-1", "client:intent-1"],
        )
        self.assertEqual([item.command_id for item in provider.sent], ["client:intent-1"])

    async def test_concurrent_divergent_submit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
        provider = _BlockingSendClient(plan.control_binding.manifest)
        endpoint, _, _ = _endpoint(provider=provider)
        first = asyncio.create_task(
            endpoint.submit(_input_intent("intent-1", "private-input-1"))
        )
        await asyncio.wait_for(provider.send_started.wait(), timeout=1)

        with self.assertRaises(ClientSessionError):
            await endpoint.submit(_input_intent("intent-1", "private-input-2"))
        self.assertEqual(provider.send_calls, 1)
        provider.release_send.set()
        self.assertEqual(await first, "client:intent-1")

    async def test_recovery_projects_observation_only_prefix_once_without_body_read(self) -> None:
        endpoint, _, journal = _endpoint()
        observation = _observation(41, "observation-41")
        journal.accept_client_observation(
            observation.to_mapping(), expected_position=journal.position
        )
        backend = _PrivateBackend()

        recovered, _, recovered_journal = _endpoint(journal=journal, backend=backend)
        events = [event async for event in recovered.events()]
        repeated, _, _ = _endpoint(journal=recovered_journal, backend=backend)

        self.assertEqual(
            events,
            [
                ClientEvent(
                    protocol="asterion.agent-client/v1",
                    event_id="observation-41",
                    session_id="session-1",
                    generation=1,
                    sequence=1,
                    emitted_at="2026-08-10T15:00:00Z",
                    type="message.available",
                    payload=observation.payload,
                )
            ],
        )
        self.assertEqual(
            _client_kinds(recovered_journal),
            ("client.observation.accepted", "client.event.accepted"),
        )
        self.assertEqual(
            [event async for event in repeated.events()],
            events,
        )
        self.assertEqual(backend.read_calls, 0)

    async def test_recovery_rejects_interleaved_or_divergent_observation_prefix(self) -> None:
        for case in ("interleaved-intent", "divergent-event"):
            with self.subTest(case=case):
                endpoint, _, journal = _endpoint()
                observation = _observation(41, "observation-41")
                journal.accept_client_observation(
                    observation.to_mapping(), expected_position=journal.position
                )
                if case == "interleaved-intent":
                    journal.accept_client_intent(
                        _input_intent("intent-1", "private-input-1"),
                        expected_position=journal.position,
                    )
                else:
                    journal.accept_client_event(
                        ClientEvent(
                            protocol="asterion.agent-client/v1",
                            event_id="different-event",
                            session_id="session-1",
                            generation=1,
                            sequence=1,
                            emitted_at="2026-08-10T15:00:00Z",
                            type="message.available",
                            payload={
                                "content_ref": "private-different-event",
                                "media_type": "text/plain",
                                "message_id": "different-event",
                                "role": "assistant",
                                "sha256": "a" * 64,
                                "size": 1,
                            },
                        ),
                        expected_position=journal.position,
                    )

                with self.assertRaises(ClientSessionError):
                    _endpoint(journal=journal)

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

    async def test_private_resolution_rejects_invalid_or_throwing_clock_before_read(self) -> None:
        cases: tuple[tuple[str, object], ...] = (
            ("throws", RuntimeError("SENTINEL_CLOCK")),
            ("bool", True),
            ("non-integer", "1"),
            ("negative", -1),
            ("unsafe-large", 1 << 63),
        )
        for label, value in cases:
            with self.subTest(label=label):
                backend = _PrivateBackend()

                def clock() -> int:
                    if isinstance(value, Exception):
                        raise value
                    return value  # type: ignore[return-value]

                service = ClientPrivateValueService(
                    access=ClientAccess(
                        client_id="client-1",
                        session_id="session-1",
                        authority_revision=1,
                        purposes=("interactive-render",),
                    ),
                    backend=backend,
                    clock_ms=clock,
                    authority_revision_source=lambda: 1,
                )

                with self.assertRaisesRegex(
                    ClientPrivateValueError, "^private value access is denied$"
                ):
                    service.resolve_bytes(
                        "private-input-1",
                        purpose="interactive-render",
                        max_bytes=32,
                        deadline_ms=(1 << 63) - 1,
                    )
                self.assertEqual(backend.read_calls, 0)

    async def test_private_resolution_rechecks_clock_after_backend_read(self) -> None:
        values: list[object] = [1, True]
        backend = _PrivateBackend()
        service = ClientPrivateValueService(
            access=ClientAccess(
                client_id="client-1",
                session_id="session-1",
                authority_revision=1,
                purposes=("interactive-render",),
            ),
            backend=backend,
            clock_ms=lambda: values.pop(0),  # type: ignore[return-value]
            authority_revision_source=lambda: 1,
        )

        with self.assertRaisesRegex(
            ClientPrivateValueError, "^private value access is denied$"
        ):
            service.resolve_bytes(
                "private-input-1",
                purpose="interactive-render",
                max_bytes=32,
                deadline_ms=10,
            )
        self.assertEqual(backend.read_calls, 1)

    async def test_private_service_redacts_hostile_cancellation_signal_at_construction(self) -> None:
        class HostileCancellationSignal:
            @property
            def cancelled(self) -> bool:
                raise RuntimeError("SENTINEL_CANCELLED_ACCESS")

        with self.assertRaisesRegex(
            ClientPrivateValueError, "^client private service is invalid$"
        ):
            ClientPrivateValueService(
                access=ClientAccess(
                    client_id="client-1",
                    session_id="session-1",
                    authority_revision=1,
                    purposes=("interactive-render",),
                ),
                backend=_PrivateBackend(),
                clock_ms=lambda: 1,
                authority_revision_source=lambda: 1,
                cancellation_signal=HostileCancellationSignal(),
            )

    async def test_private_service_redacts_cancelled_error_at_construction(self) -> None:
        class CancelledCancellationSignal:
            @property
            def cancelled(self) -> bool:
                raise asyncio.CancelledError("SENTINEL_CANCELLED_ERROR")

        with self.assertRaisesRegex(
            ClientPrivateValueError, "^client private service is invalid$"
        ):
            ClientPrivateValueService(
                access=ClientAccess(
                    client_id="client-1",
                    session_id="session-1",
                    authority_revision=1,
                    purposes=("interactive-render",),
                ),
                backend=_PrivateBackend(),
                clock_ms=lambda: 1,
                authority_revision_source=lambda: 1,
                cancellation_signal=CancelledCancellationSignal(),
            )

    async def test_private_service_rejects_non_bool_cancellation_signal_at_construction(self) -> None:
        class NonBooleanCancellationSignal:
            @property
            def cancelled(self) -> bool:
                return "SENTINEL_NON_BOOLEAN"  # type: ignore[return-value]

        with self.assertRaisesRegex(
            ClientPrivateValueError, "^client private service is invalid$"
        ):
            ClientPrivateValueService(
                access=ClientAccess(
                    client_id="client-1",
                    session_id="session-1",
                    authority_revision=1,
                    purposes=("interactive-render",),
                ),
                backend=_PrivateBackend(),
                clock_ms=lambda: 1,
                authority_revision_source=lambda: 1,
                cancellation_signal=NonBooleanCancellationSignal(),
            )

    async def test_private_service_redacts_cancellation_signal_before_and_after_read(self) -> None:
        class ChangingCancellationSignal:
            def __init__(self, values: list[object]) -> None:
                self._values = values
                self.accesses = 0

            @property
            def cancelled(self) -> bool:
                self.accesses += 1
                value = self._values.pop(0)
                if isinstance(value, BaseException):
                    raise value
                return value  # type: ignore[return-value]

        for label, values, reads in (
            ("before-read", [False, RuntimeError("SENTINEL_BEFORE")], 0),
            ("after-read", [False, False, "SENTINEL_AFTER"], 1),
            ("before-read-cancelled", [False, asyncio.CancelledError("SENTINEL_BEFORE_CANCELLED")], 0),
            ("after-read-cancelled", [False, False, asyncio.CancelledError("SENTINEL_AFTER_CANCELLED")], 1),
        ):
            with self.subTest(label=label):
                backend = _PrivateBackend()
                signal = ChangingCancellationSignal(values)
                service = ClientPrivateValueService(
                    access=ClientAccess(
                        client_id="client-1",
                        session_id="session-1",
                        authority_revision=1,
                        purposes=("interactive-render",),
                    ),
                    backend=backend,
                    clock_ms=lambda: 1,
                    authority_revision_source=lambda: 1,
                    cancellation_signal=signal,
                )

                with self.assertRaisesRegex(
                    ClientPrivateValueError, "^private value access is denied$"
                ):
                    service.resolve_bytes(
                        "private-input-1",
                        purpose="interactive-render",
                        max_bytes=32,
                        deadline_ms=10,
                    )
                self.assertEqual(backend.read_calls, reads)
                self.assertEqual(
                    signal.accesses,
                    2 if label.startswith("before-read") else 3,
                )
