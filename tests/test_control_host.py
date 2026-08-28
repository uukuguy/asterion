from __future__ import annotations

import tempfile
import unittest
from collections.abc import AsyncIterator
from pathlib import Path

from asterion.control.authority import AuthorityLedger, BudgetUsage
from asterion.control.execution import ActionExecutionReceipt
from asterion.control.host import (
    ControlCommand,
    ControlEvent,
    ControlPlaneManifest,
    EventCursor,
)
from asterion.control.journal import MemoryCanonicalJournal
from asterion.control.manager import (
    ControlHost,
    ControlHostError,
    ControlHostTransportError,
    ProviderOwnedActionTerminal,
)
from asterion.control.system import resolve_agent_system
from asterion.runtime.host import CancellationSignal
from tests.test_control_authority import _envelope, _proposal
from tests.test_control_system import (
    _control_factories,
    _manifest,
    _provider,
)


class ScriptedClient:
    def __init__(
        self,
        manifest: ControlPlaneManifest,
        events: tuple[ControlEvent, ...] = (),
        *,
        audit: list[str] | None = None,
        fail_send: bool = False,
    ) -> None:
        self._manifest = manifest
        self._events = events
        self.audit = audit if audit is not None else []
        self.fail_send = fail_send
        self.sent: list[ControlCommand] = []

    @property
    def manifest(self) -> ControlPlaneManifest:
        return self._manifest

    async def send(self, command: ControlCommand) -> None:
        self.audit.append("provider.send")
        if self.fail_send:
            raise RuntimeError("SENTINEL_SECRET transport body")
        self.sent.append(command)

    async def _iterate(self) -> AsyncIterator[ControlEvent]:
        for event in self._events:
            yield event

    def events(self, cursor: EventCursor | None = None) -> AsyncIterator[ControlEvent]:
        del cursor
        return self._iterate()

    async def close(self) -> None:
        self.audit.append("provider.close")


class AuditedJournal(MemoryCanonicalJournal):
    def __init__(self, session_id: str, audit: list[str]) -> None:
        super().__init__(session_id)
        self.audit = audit

    def accept_command(
        self, command: ControlCommand, *, expected_position: int | None = None
    ):
        self.audit.append("journal.command")
        return super().accept_command(command, expected_position=expected_position)

    def accept_event(
        self, event: ControlEvent, *, expected_position: int | None = None
    ):
        self.audit.append("journal.event")
        return super().accept_event(event, expected_position=expected_position)


class SpyExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt:
        del signal
        self.calls.append(str(proposal.payload["action_id"]))
        raise AssertionError("Phase 0 host must not execute applications")


class AdmissionPreparer:
    def __init__(self, audit: list[str]) -> None:
        self.audit = audit

    async def prepare(self, proposal: ControlEvent) -> None:
        self.audit.append(f"prepare:{proposal.payload['action_id']}")


class ProviderOwnedLifecycle:
    def __init__(self) -> None:
        self.action_id: str | None = None
        self.delivered = False

    def owns(self, proposal: ControlEvent) -> bool:
        self.action_id = str(proposal.payload["action_id"])
        return proposal.payload["kind"] == "child.spawn"

    @property
    def active_child_count(self) -> int:
        return 0

    async def reconcile(self) -> tuple[ProviderOwnedActionTerminal, ...]:
        if self.action_id is None or self.delivered:
            return ()
        self.delivered = True
        return (
            ProviderOwnedActionTerminal(
                self.action_id,
                "succeeded",
                ActionExecutionReceipt(
                    action_id=self.action_id,
                    receipt_ref=f"receipt:{self.action_id}",
                    usage=BudgetUsage.zero(),
                ),
            ),
        )


def _session_events(proposal: ControlEvent) -> tuple[ControlEvent, ...]:
    created = ControlEvent.from_mapping(
        {
            "protocol": "asterion.agent-control/v1",
            "event_id": "event-1",
            "session_id": "session-1",
            "generation": 1,
            "sequence": 1,
            "emitted_at": "2026-08-09T15:00:00Z",
            "type": "session.created",
            "payload": {
                "goal_id": "goal-1",
                "authority_id": "authority-1",
                "authority_revision": 1,
            },
        }
    )
    running = ControlEvent.from_mapping(
        {
            "protocol": "asterion.agent-control/v1",
            "event_id": "event-running",
            "session_id": "session-1",
            "generation": 1,
            "sequence": 2,
            "emitted_at": "2026-08-09T15:00:01Z",
            "type": "session.running",
            "payload": {"reason_code": "started"},
        }
    )
    return created, running, proposal


def _create_command() -> ControlCommand:
    return ControlCommand(
        command_id="command-1",
        session_id="session-1",
        authority_revision=1,
        type="session.create",
        payload={
            "system_id": "research.system",
            "system_version": "1.0.0",
            "goal_id": "goal-1",
            "goal_ref": "goal-ref-1",
        },
    )


class TestControlHost(unittest.IsolatedAsyncioTestCase):
    async def test_recovered_operation_host_exposes_host_operation_methods(
        self,
    ) -> None:
        from tests.test_operation_manager import _manager, _transaction

        manager, _, _, service, journal = _manager()
        service.fail_execute = True
        transaction = _transaction()
        await manager.execute(transaction)
        recovered = ControlHost.recover_operation_host(
            journal,
            _envelope(
                allowed_operations=("operation.auth",),
                host_service_grants=("operation.auth",),
            ),
            services={"operation.auth": service},
        )
        self.assertTrue(callable(getattr(recovered, "execute_operation", None)))
        self.assertEqual(
            (await recovered.reconcile_operation(transaction)).status, "uncertain"
        )

    async def test_dispatch_rejects_unverified_client_journal_tail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            journal = MemoryCanonicalJournal("session-1")
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=journal,
                client=ScriptedClient(plan.control_binding.manifest),
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
            )
            journal.accept_client_intent(
                {
                    "protocol": "asterion.agent-client/v1",
                    "intent_id": "intent-1",
                    "client_id": "client-1",
                    "session_id": "session-1",
                    "authority_revision": 1,
                    "type": "input.submit",
                    "payload": {
                        "content_ref": "private-input-1",
                        "delivery": "direct",
                        "input_id": "input-1",
                    },
                },
                expected_position=journal.position,
            )

            with self.assertRaises(ControlHostError):
                await host.dispatch(_create_command())

    async def test_client_command_uses_only_existing_control_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=MemoryCanonicalJournal("session-1"),
                client=ScriptedClient(plan.control_binding.manifest),
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
            )

            command = host.client_command(
                command_id="client:intent-1",
                command_type="input.submit",
                payload={
                    "content_ref": "private-input-1",
                    "delivery": "direct",
                    "input_id": "input-1",
                },
            )

        self.assertEqual(command.type, "input.submit")
        self.assertEqual(command.command_id, "client:intent-1")

    async def test_provider_owned_child_skips_generic_executor_and_settles_later(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            executor = SpyExecutor()
            lifecycle = ProviderOwnedLifecycle()
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=MemoryCanonicalJournal("session-1"),
                client=ScriptedClient(plan.control_binding.manifest),
                action_executor=executor,
                clock_ms=lambda: 1_000,
                provider_owned_actions=lifecycle,
            )
            child_payload = _proposal().to_mapping()["payload"]
            assert isinstance(child_payload, dict)
            proposal = ControlEvent.from_mapping(
                {
                    **_proposal().to_mapping(),
                    "sequence": 3,
                    "payload": {
                        **child_payload,
                        "kind": "child.spawn",
                        "target": {"kind": "child", "child_id": "child-1"},
                    },
                }
            )
            created, running, _ = _session_events(proposal)
            await host._accept_event(created)
            await host._accept_event(running)
            await host._accept_event(proposal)
            self.assertEqual(executor.calls, [])
            self.assertEqual(
                host.snapshot().state.actions["action-1"].status, "running"
            )

            await host.pump()

            self.assertEqual(
                host.snapshot().state.actions["action-1"].status, "succeeded"
            )

    async def test_admitted_action_preparer_runs_before_admission_delivery(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit: list[str] = []
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            client = ScriptedClient(plan.control_binding.manifest, audit=audit)
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=MemoryCanonicalJournal("session-1"),
                client=client,
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
                admitted_action_preparer=AdmissionPreparer(audit),
            )
            proposal = ControlEvent.from_mapping(
                {
                    **_proposal(
                        kind="child.spawn",
                        target={"kind": "child", "child_id": "child-1"},
                    ).to_mapping(),
                    "sequence": 3,
                }
            )
            created, running, _ = _session_events(proposal)
            await host._accept_event(created)
            await host._accept_event(running)
            await host._accept_event(proposal)

        self.assertLess(
            audit.index(f"prepare:{proposal.payload['action_id']}"),
            audit.index("provider.send"),
        )

    async def test_recovery_rebuilds_admitted_provider_binding_before_ownership(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit: list[str] = []

            class RecoveryLifecycle:
                def owns(self, proposal: ControlEvent) -> bool:
                    audit.append(f"owns:{proposal.payload['action_id']}")
                    return proposal.payload["kind"] == "child.spawn"

                @property
                def active_child_count(self) -> int:
                    return 0

                async def reconcile(self) -> tuple[ProviderOwnedActionTerminal, ...]:
                    return ()

            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            journal = MemoryCanonicalJournal("session-1")
            first = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=journal,
                client=ScriptedClient(plan.control_binding.manifest),
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
                admitted_action_preparer=AdmissionPreparer(audit),
                provider_owned_actions=RecoveryLifecycle(),
            )
            proposal = ControlEvent.from_mapping(
                {
                    **_proposal(
                        kind="child.spawn",
                        target={"kind": "child", "child_id": "child-1"},
                    ).to_mapping(),
                    "sequence": 3,
                }
            )
            created, running, _ = _session_events(proposal)
            await first._accept_event(created)
            await first._accept_event(running)
            await first._accept_event(proposal)

            audit.clear()
            recovered = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=journal,
                client=ScriptedClient(plan.control_binding.manifest),
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
                admitted_action_preparer=AdmissionPreparer(audit),
                provider_owned_actions=RecoveryLifecycle(),
            )
            await recovered.pump()

        self.assertEqual(
            audit,
            [
                f"prepare:{proposal.payload['action_id']}",
                f"owns:{proposal.payload['action_id']}",
            ],
        )

    async def test_exact_stale_budget_report_replay_preserves_current_usage(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            journal = MemoryCanonicalJournal("session-1")
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=journal,
                client=ScriptedClient(plan.control_binding.manifest),
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
            )
            created, running, _ = _session_events(_proposal())
            lower = ControlEvent.from_mapping(
                {
                    "protocol": "asterion.agent-control/v1",
                    "event_id": "budget-lower",
                    "session_id": "session-1",
                    "generation": 1,
                    "sequence": 3,
                    "emitted_at": "2026-08-10T00:00:02Z",
                    "type": "budget.reported",
                    "payload": {
                        "controller_tokens": 10,
                        "application_tokens": 0,
                        "child_tokens": 0,
                        "aggregate_tokens": 10,
                        "cost_micros": 0,
                    },
                }
            )
            higher = ControlEvent.from_mapping(
                {
                    **lower.to_mapping(),
                    "event_id": "budget-higher",
                    "sequence": 4,
                    "payload": {
                        "controller_tokens": 20,
                        "application_tokens": 0,
                        "child_tokens": 0,
                        "aggregate_tokens": 20,
                        "cost_micros": 0,
                    },
                }
            )
            for event in (created, running, lower, higher):
                await host._accept_event(event)
            position = journal.position

            await host._accept_event(lower)

            self.assertEqual(journal.position, position)
            self.assertEqual(host.snapshot().authority_usage.controller_tokens, 20)
            self.assertEqual(host.snapshot().state.next_sequence, 5)

    async def test_overflow_budget_report_is_rejected_before_journal_append(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            journal = MemoryCanonicalJournal("session-1")
            authority = AuthorityLedger(_envelope())
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=authority,
                journal=journal,
                client=ScriptedClient(plan.control_binding.manifest),
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
            )
            before = host.snapshot()
            event = ControlEvent.from_mapping(
                {
                    "protocol": "asterion.agent-control/v1",
                    "event_id": "budget-1",
                    "session_id": "session-1",
                    "generation": 1,
                    "sequence": 1,
                    "emitted_at": "2026-08-10T00:00:00Z",
                    "type": "budget.reported",
                    "payload": {
                        "controller_tokens": 0,
                        "application_tokens": 1001,
                        "child_tokens": 0,
                        "aggregate_tokens": 1001,
                        "cost_micros": 0,
                    },
                }
            )
            with self.assertRaises(ControlHostError):
                await host._accept_event(event)
            self.assertEqual(journal.position, before.journal_position)
            self.assertEqual(
                host.snapshot().state.next_sequence, before.state.next_sequence
            )
            self.assertEqual(host.snapshot().authority_usage, before.authority_usage)

    async def test_command_is_journaled_before_provider_send(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls: list[str] = []
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            client = ScriptedClient(plan.control_binding.manifest, audit=calls)
            journal = AuditedJournal("session-1", calls)
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=journal,
                client=client,
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
            )
            calls.clear()

            await host.dispatch(_create_command())

            self.assertEqual(calls, ["journal.command", "provider.send"])

    async def test_send_failure_preserves_accepted_command_and_redacts_error(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            client = ScriptedClient(plan.control_binding.manifest, fail_send=True)
            journal = MemoryCanonicalJournal("session-1")
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=journal,
                client=client,
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
            )

            with self.assertRaises(ControlHostTransportError) as raised:
                await host.dispatch(_create_command())

            self.assertEqual(journal.position, 3)
            self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    async def test_unauthorized_proposal_is_rejected_without_executor_contact(
        self,
    ) -> None:
        target = {
            "kind": "application",
            "provider_id": "example.provider",
            "application_id": "zeta",
            "version": "2.0.0",
            "runtime_id": "fake.runtime",
        }
        proposal = _proposal(target=target)
        proposal = ControlEvent.from_mapping(
            {**proposal.to_mapping(), "sequence": 3, "event_id": "event-3"}
        )
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            client = ScriptedClient(
                plan.control_binding.manifest,
                _session_events(proposal),
            )
            executor = SpyExecutor()
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=MemoryCanonicalJournal("session-1"),
                client=client,
                action_executor=executor,
                clock_ms=lambda: 1_000,
            )

            await host.pump()

            self.assertEqual(
                host.snapshot().state.actions["action-1"].status, "rejected"
            )
            self.assertEqual(executor.calls, [])
            resolution = client.sent[-1]
            self.assertEqual(resolution.type, "action.resolve")
            self.assertEqual(resolution.payload["resolution"], "rejected")

    async def test_authorized_proposal_executes_only_after_admission(self) -> None:
        from asterion.control.authority import BudgetUsage

        class SuccessfulExecutor(SpyExecutor):
            async def execute(
                self, proposal: ControlEvent, signal: CancellationSignal
            ) -> ActionExecutionReceipt:
                del signal
                self.calls.append(str(proposal.payload["action_id"]))
                return ActionExecutionReceipt(
                    action_id="action-1",
                    receipt_ref="receipt-1",
                    usage=BudgetUsage(0, 80, 0, 80, 4_000),
                )

        proposal = ControlEvent.from_mapping(
            {**_proposal().to_mapping(), "sequence": 3, "event_id": "event-3"}
        )
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            client = ScriptedClient(
                plan.control_binding.manifest, _session_events(proposal)
            )
            executor = SuccessfulExecutor()
            authority = AuthorityLedger(_envelope())
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=authority,
                journal=MemoryCanonicalJournal("session-1"),
                client=client,
                action_executor=executor,
                clock_ms=lambda: 1_000,
            )

            await host.pump()

            self.assertEqual(
                host.snapshot().state.actions["action-1"].status, "succeeded"
            )
            self.assertEqual(authority.reserved_action_ids, ())
            self.assertEqual(executor.calls, ["action-1"])

    async def test_gap_is_persisted_then_fails_without_synthesizing_state(self) -> None:
        gap = ControlEvent.from_mapping(
            {**_proposal().to_mapping(), "sequence": 4, "event_id": "event-4"}
        )
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            journal = MemoryCanonicalJournal("session-1")
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=journal,
                client=ScriptedClient(
                    plan.control_binding.manifest, _session_events(gap)
                ),
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
            )

            with self.assertRaises(ControlHostError):
                await host.pump()

            self.assertEqual(journal.position, 5)
            self.assertEqual(host.snapshot().state.next_sequence, 3)


if __name__ == "__main__":
    unittest.main()
