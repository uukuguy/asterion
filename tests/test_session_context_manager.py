from __future__ import annotations

import asyncio
import unittest
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import replace
from pathlib import Path
import tempfile

from asterion.control.authority import (
    AuthorityEnvelope,
    AuthorityLedger,
    BudgetLimit,
    BudgetUsage,
    PortfolioGrant,
    SessionContextDecision,
    session_context_command_digest,
)
from asterion.control.journal import (
    FileCanonicalJournal,
    JournalCursor,
    JournalRecord,
    MemoryCanonicalJournal,
)
from asterion.control.host import (
    ControlCommand,
    ControlEvent,
    ControlPlaneManifest,
    EventCursor,
)
from asterion.control.manager import ControlHost
from asterion.control.session_context import SessionContextCommand, SessionContextReceipt
from asterion.control.session_context_manager import (
    SessionContextManager,
    SessionContextManagerError,
    SessionContextTransportError,
)
from asterion.control.system import resolve_agent_system
from tests.test_control_authority import _envelope, _proposal
from tests.test_control_host import SpyExecutor, _create_command, _session_events
from tests.test_control_system import _control_factories, _manifest, _provider


SHA256 = "a" * 64


class MutableSignal:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled


class FakeSessionContextClient:
    def __init__(self) -> None:
        self.commands: list[SessionContextCommand] = []
        self.cancelled: list[str] = []
        self.response: SessionContextReceipt | None = None
        self.failure: Exception | None = None
        self.on_execute: Callable[[SessionContextCommand], None] | None = None

    async def execute_session_context(
        self, command: SessionContextCommand
    ) -> SessionContextReceipt:
        self.commands.append(command)
        if self.on_execute is not None:
            self.on_execute(command)
        if self.failure is not None:
            raise self.failure
        assert self.response is not None
        return self.response

    async def cancel_session_context(self, command_id: str) -> None:
        self.cancelled.append(command_id)


class HostSessionContextClient(FakeSessionContextClient):
    def __init__(
        self,
        manifest: ControlPlaneManifest,
        events: tuple[ControlEvent, ...] = (),
    ) -> None:
        super().__init__()
        self._manifest = manifest
        self._event_values = events
        self.sent: list[ControlCommand] = []
        self.closed = 0

    @property
    def manifest(self) -> ControlPlaneManifest:
        return self._manifest

    async def send(self, command: ControlCommand) -> None:
        self.sent.append(command)

    async def _events(self) -> AsyncIterator[ControlEvent]:
        for event in self._event_values:
            yield event
        self._event_values = ()

    def events(
        self, cursor: EventCursor | None = None
    ) -> AsyncIterator[ControlEvent]:
        del cursor
        return self._events()

    async def close(self) -> None:
        self.closed += 1


class BlockingSessionContextClient(FakeSessionContextClient):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def execute_session_context(
        self, command: SessionContextCommand
    ) -> SessionContextReceipt:
        self.commands.append(command)
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def authority(*operations: str) -> AuthorityLedger:
    return AuthorityLedger(
        AuthorityEnvelope(
            authority_id="authority-1",
            revision=1,
            allowed_portfolio=(
                PortfolioGrant(
                    provider_id="example.provider",
                    application_id="alpha",
                    version="1.0.0",
                    runtime_id="fake.runtime",
                ),
            ),
            allowed_operations=tuple(sorted(operations)),
            budget_limit=BudgetLimit(1_000, 1_000, 1_000, 3_000, 100_000),
            expires_at_ms=10_000,
            max_action_deadline_ms=5_000,
            max_recursion_depth=0,
            max_concurrent_children=0,
            execution_domain="trusted-local",
            host_service_grants=(),
        )
    )


def journal() -> MemoryCanonicalJournal:
    value = MemoryCanonicalJournal("session-1")
    system = value.append(
        0,
        JournalRecord.system_bound(
            system_id="research.system",
            system_version="1.0.0",
        ),
    )
    value.append(
        system.position,
        JournalRecord.authority_bound(
            authority_id="authority-1",
            authority_revision=1,
        ),
    )
    return value


def tree_command(
    *,
    command_id: str = "context-command-1",
    idempotency_key: str = "context-operation-1",
    authority_revision: int = 1,
) -> SessionContextCommand:
    return SessionContextCommand(
        command_id=command_id,
        session_id="session-1",
        generation=1,
        authority_revision=authority_revision,
        idempotency_key=idempotency_key,
        operation="session.tree.read",
        payload={"continuation_id": "continuation-1"},
    )


def compact_command(
    *, command_id: str = "context-command-compact"
) -> SessionContextCommand:
    return SessionContextCommand(
        command_id=command_id,
        session_id="session-1",
        generation=1,
        authority_revision=1,
        idempotency_key="context-operation-compact",
        operation="session.compact",
        payload={
            "continuation_id": "continuation-1",
            "instructions_ref": None,
            "budget": {
                "controller_tokens": 100,
                "application_tokens": 0,
                "child_tokens": 0,
                "aggregate_tokens": 100,
                "cost_micros": 1_000,
                "deadline_ms": 1_000,
            },
        },
    )


def receipt(
    command: SessionContextCommand,
    *,
    status: str = "succeeded",
    reason_code: str = "session-context-succeeded",
) -> SessionContextReceipt:
    result: object = None
    if status == "succeeded" and command.operation == "session.tree.read":
        result = {
            "continuation_id": "continuation-1",
            "nodes": [],
            "leaf_id": None,
        }
    if status == "succeeded" and command.operation == "session.compact":
        result = {
            "continuation_id": "continuation-1",
            "covered_leaf_id": "entry-1",
            "before_context_tokens": 90,
            "after_context_tokens": 20,
            "summary_sha256": SHA256,
            "usage": {
                "controller_tokens": 40,
                "application_tokens": 0,
                "child_tokens": 0,
                "aggregate_tokens": 40,
                "cost_micros": 400,
            },
        }
    return SessionContextReceipt(
        receipt_id=f"receipt:{command.command_id}",
        command_id=command.command_id,
        session_id=command.session_id,
        generation=command.generation,
        operation=command.operation,
        status=status,
        reason_code=reason_code,
        payload={"evidence_ref": None, "result": result},
    )


class TestSessionContextManager(unittest.IsolatedAsyncioTestCase):
    async def test_file_journal_reopens_exact_terminal_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "journal"
            store = FileCanonicalJournal.open(root, "session-1")
            system = store.append(
                0,
                JournalRecord.system_bound(
                    system_id="research.system",
                    system_version="1.0.0",
                ),
            )
            store.append(
                system.position,
                JournalRecord.authority_bound(
                    authority_id="authority-1",
                    authority_revision=1,
                ),
            )
            command = tree_command()
            client = FakeSessionContextClient()
            client.response = receipt(command)
            manager = SessionContextManager(
                session_id="session-1",
                generation=1,
                authority=authority("session.tree.read"),
                journal=store,
                client=client,
                clock_ms=lambda: 100,
                cancellation_signal=MutableSignal(),
                session_status=lambda: "running",
            )
            expected = await manager.execute(command)
            store.close()

            reopened = FileCanonicalJournal.open(root, "session-1")
            recovered_client = FakeSessionContextClient()
            recovered = SessionContextManager(
                session_id="session-1",
                generation=1,
                authority=authority("session.tree.read"),
                journal=reopened,
                client=recovered_client,
                clock_ms=lambda: 100,
                cancellation_signal=MutableSignal(),
                session_status=lambda: "running",
            )

            self.assertEqual(await recovered.execute(command), expected)
            self.assertEqual(recovered_client.commands, [])
            reopened.close()

    async def test_control_host_injects_one_shared_manager_journal_and_close(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capabilities = (
                "action-proposals",
                "checkpointing",
                "event-replay",
                "session-lifecycle",
                "session.context-v1",
            )
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories(
                    [], capabilities=capabilities
                ),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            client = HostSessionContextClient(
                plan.control_binding.manifest,
                _session_events(_proposal())[:2],
            )
            envelope = replace(
                _envelope(),
                allowed_operations=(
                    "application.invoke",
                    "child.spawn",
                    "session.tree.read",
                ),
            )
            store = MemoryCanonicalJournal("session-1")
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(envelope),
                journal=store,
                client=client,
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
                session_context_client=client,
            )
            command = tree_command()
            client.response = receipt(command)
            manager = host.session_context_manager
            self.assertIsNotNone(manager)
            assert manager is not None

            create = _create_command()
            await host.dispatch(create)
            await host.pump()
            await manager.execute(command)
            uncertain_command = tree_command(
                command_id="context-command-uncertain",
                idempotency_key="context-operation-uncertain",
            )
            client.response = receipt(
                uncertain_command,
                status="uncertain",
                reason_code="provider-progress-unknown",
            )
            await manager.execute(uncertain_command)
            self.assertEqual(
                host.snapshot().state.session_status,
                "recovery_required",
            )
            pause = ControlCommand(
                command_id="control-command-pause",
                session_id="session-1",
                authority_revision=1,
                type="session.pause",
                payload={"reason_code": "operator-requested"},
            )
            await host.dispatch(pause)
            await host.close()

            self.assertEqual(host.snapshot().journal_position, 12)
            self.assertEqual(client.commands, [command, uncertain_command])
            self.assertEqual(client.sent, [create, pause])
            self.assertEqual(client.closed, 1)

            recovered_client = HostSessionContextClient(
                plan.control_binding.manifest
            )
            recovered_host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(envelope),
                journal=store,
                client=recovered_client,
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
                session_context_client=recovered_client,
            )
            self.assertEqual(
                recovered_host.snapshot().state.session_status,
                "recovery_required",
            )
            await recovered_host.close()
            self.assertEqual(recovered_client.closed, 1)

    async def test_persists_command_and_decision_before_exact_dispatch(self) -> None:
        store = journal()
        ledger = authority("session.tree.read")
        client = FakeSessionContextClient()
        command = tree_command()
        client.response = receipt(command)

        def observe_dispatch(dispatched: SessionContextCommand) -> None:
            self.assertIs(dispatched, command)
            self.assertEqual(
                tuple(
                    entry.record.kind
                    for entry in store.replay(JournalCursor(0))[-2:]
                ),
                ("context.command.accepted", "context.operation.decided"),
            )

        client.on_execute = observe_dispatch
        manager = SessionContextManager(
            session_id="session-1",
            generation=1,
            authority=ledger,
            journal=store,
            client=client,
            clock_ms=lambda: 100,
            cancellation_signal=MutableSignal(),
            session_status=lambda: "running",
        )

        result = await manager.execute(command)

        self.assertEqual(result, client.response)
        self.assertEqual(
            tuple(entry.record.kind for entry in store.replay(JournalCursor(0))[-3:]),
            (
                "context.command.accepted",
                "context.operation.decided",
                "context.operation.receipted",
            ),
        )

    async def test_revision_and_operation_authority_fail_closed(self) -> None:
        store = journal()
        client = FakeSessionContextClient()
        manager = SessionContextManager(
            session_id="session-1",
            generation=1,
            authority=authority("session.describe"),
            journal=store,
            client=client,
            clock_ms=lambda: 100,
            cancellation_signal=MutableSignal(),
            session_status=lambda: "running",
        )

        with self.assertRaises(SessionContextManagerError):
            await manager.execute(tree_command(authority_revision=2))
        self.assertEqual(store.position, 2)

        rejected = await manager.execute(tree_command())
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.reason_code, "operation-not-authorized")
        self.assertEqual(client.commands, [])

    async def test_recovery_rejects_forged_admitted_operation(self) -> None:
        store = journal()
        command = tree_command()
        accepted = store.accept_session_context_command(
            command,
            expected_position=store.position,
        )
        store.append(
            accepted.position,
            JournalRecord.context_operation_decided(
                SessionContextDecision(
                    command_id=command.command_id,
                    idempotency_key=command.idempotency_key,
                    authority_id="authority-1",
                    authority_revision=1,
                    operation=command.operation,
                    command_digest=session_context_command_digest(command),
                    status="admitted",
                    reason="authorized",
                    reservation=None,
                )
            ),
        )

        with self.assertRaises(SessionContextManagerError):
            SessionContextManager(
                session_id="session-1",
                generation=1,
                authority=authority("session.describe"),
                journal=store,
                client=FakeSessionContextClient(),
                clock_ms=lambda: 100,
                cancellation_signal=MutableSignal(),
                session_status=lambda: "running",
            )

    async def test_exact_replay_and_idempotency_conflicts(self) -> None:
        store = journal()
        client = FakeSessionContextClient()
        command = tree_command()
        client.response = receipt(command)
        manager = SessionContextManager(
            session_id="session-1",
            generation=1,
            authority=authority("session.tree.read"),
            journal=store,
            client=client,
            clock_ms=lambda: 100,
            cancellation_signal=MutableSignal(),
            session_status=lambda: "running",
        )

        first = await manager.execute(command)
        replayed = await manager.execute(command)

        self.assertIs(replayed, first)
        self.assertEqual(len(client.commands), 1)
        with self.assertRaises(SessionContextManagerError):
            await manager.execute(
                tree_command(
                    command_id="context-command-2",
                    idempotency_key=command.idempotency_key,
                )
            )

    async def test_concurrent_exact_replay_dispatches_once(self) -> None:
        store = journal()
        client = FakeSessionContextClient()
        command = tree_command()
        client.response = receipt(command)
        manager = SessionContextManager(
            session_id="session-1",
            generation=1,
            authority=authority("session.tree.read"),
            journal=store,
            client=client,
            clock_ms=lambda: 100,
            cancellation_signal=MutableSignal(),
            session_status=lambda: "running",
        )

        first, second = await asyncio.gather(
            manager.execute(command),
            manager.execute(command),
        )

        self.assertIs(first, second)
        self.assertEqual(client.commands, [command])
        with self.assertRaises(SessionContextManagerError):
            await manager.execute(
                replace(
                    command,
                    payload={"continuation_id": "continuation-other"},
                )
            )

    async def test_terminal_session_rejects_mutation_but_allows_read(self) -> None:
        store = journal()
        client = FakeSessionContextClient()
        status = "completed"
        command = compact_command()
        manager = SessionContextManager(
            session_id="session-1",
            generation=1,
            authority=authority("session.compact", "session.tree.read"),
            journal=store,
            client=client,
            clock_ms=lambda: 100,
            cancellation_signal=MutableSignal(),
            session_status=lambda: status,
        )

        rejected = await manager.execute(command)
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.reason_code, "session-terminal")
        self.assertEqual(client.commands, [])

        read = tree_command(command_id="context-command-read")
        client.response = receipt(read)
        self.assertEqual((await manager.execute(read)).status, "succeeded")

    async def test_model_budget_is_reserved_then_settled_from_safe_usage(self) -> None:
        store = journal()
        ledger = authority("application.invoke", "session.compact")
        client = FakeSessionContextClient()
        command = compact_command()
        client.response = receipt(command)

        def observe_reservation(_: SessionContextCommand) -> None:
            self.assertEqual(
                ledger.reserved_session_context_ids,
                (command.command_id,),
            )
            self.assertEqual(
                ledger.remaining_budget(now_ms=100).controller_tokens,
                900,
            )
            competing = ledger.evaluate(
                _proposal(
                    budget={
                        "controller_tokens": 950,
                        "application_tokens": 0,
                        "child_tokens": 0,
                        "aggregate_tokens": 950,
                        "cost_micros": 0,
                        "deadline_ms": 1_000,
                    }
                ),
                now_ms=100,
            )
            self.assertEqual(competing.status, "rejected")
            self.assertEqual(competing.reason, "budget-exceeded")

        client.on_execute = observe_reservation
        manager = SessionContextManager(
            session_id="session-1",
            generation=1,
            authority=ledger,
            journal=store,
            client=client,
            clock_ms=lambda: 100,
            cancellation_signal=MutableSignal(),
            session_status=lambda: "running",
        )

        await manager.execute(command)

        self.assertEqual(ledger.reserved_session_context_ids, ())
        self.assertEqual(ledger.usage, BudgetUsage(40, 0, 0, 40, 400))

    async def test_cancelled_before_dispatch_is_durable_and_releases_budget(self) -> None:
        store = journal()
        ledger = authority("session.compact")
        client = FakeSessionContextClient()
        manager = SessionContextManager(
            session_id="session-1",
            generation=1,
            authority=ledger,
            journal=store,
            client=client,
            clock_ms=lambda: 100,
            cancellation_signal=MutableSignal(cancelled=True),
            session_status=lambda: "running",
        )

        result = await manager.execute(compact_command())

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.reason_code, "cancelled-before-dispatch")
        self.assertEqual(client.commands, [])
        self.assertEqual(ledger.reserved_session_context_ids, ())
        self.assertEqual(ledger.usage, BudgetUsage.zero())

    async def test_task_cancellation_seals_uncertainty_without_same_channel_cancel(
        self,
    ) -> None:
        store = journal()
        command = tree_command()
        client = BlockingSessionContextClient()
        manager = SessionContextManager(
            session_id="session-1",
            generation=1,
            authority=authority("session.tree.read"),
            journal=store,
            client=client,
            clock_ms=lambda: 100,
            cancellation_signal=MutableSignal(),
            session_status=lambda: "running",
        )
        task = asyncio.create_task(manager.execute(command))
        await client.started.wait()

        task.cancel()
        with self.assertRaises(SessionContextTransportError):
            await task

        self.assertEqual(client.cancelled, [])
        snapshot = manager.snapshot()
        self.assertEqual(snapshot.pending_command_ids, ())
        self.assertTrue(snapshot.recovery_required)
        receipt_record = store.replay(JournalCursor(0))[-1].record
        self.assertEqual(receipt_record.kind, "context.operation.receipted")
        self.assertEqual(receipt_record.payload["usage"], None)
        receipt_value = receipt_record.payload["receipt"]
        self.assertIsInstance(receipt_value, Mapping)
        assert isinstance(receipt_value, Mapping)
        sealed = SessionContextReceipt.from_mapping(receipt_value)
        self.assertEqual(sealed.status, "uncertain")
        self.assertEqual(sealed.reason_code, "delivery-outcome-unknown")

    async def test_transport_uncertainty_recovers_only_with_same_command(self) -> None:
        store = journal()
        command = tree_command()
        failing = FakeSessionContextClient()
        failing.failure = RuntimeError("SENTINEL_PRIVATE_FAILURE")
        manager = SessionContextManager(
            session_id="session-1",
            generation=1,
            authority=authority("session.tree.read"),
            journal=store,
            client=failing,
            clock_ms=lambda: 100,
            cancellation_signal=MutableSignal(),
            session_status=lambda: "running",
        )

        with self.assertRaises(SessionContextTransportError) as raised:
            await manager.execute(command)
        self.assertNotIn("SENTINEL_PRIVATE_FAILURE", str(raised.exception))

        recovered_client = FakeSessionContextClient()
        recovered_client.response = receipt(command)
        recovered = SessionContextManager(
            session_id="session-1",
            generation=1,
            authority=authority("session.tree.read"),
            journal=store,
            client=recovered_client,
            clock_ms=lambda: 100,
            cancellation_signal=MutableSignal(),
            session_status=lambda: "running",
        )

        result = await recovered.execute(command)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(recovered_client.commands, [command])
        self.assertEqual(
            tuple(entry.record.kind for entry in store.replay(JournalCursor(0))[-3:]),
            (
                "context.command.accepted",
                "context.operation.decided",
                "context.operation.receipted",
            ),
        )

    async def test_uncertain_receipt_fences_replay_without_redispatch(self) -> None:
        store = journal()
        command = tree_command()
        client = FakeSessionContextClient()
        client.response = receipt(
            command,
            status="uncertain",
            reason_code="provider-progress-unknown",
        )
        manager = SessionContextManager(
            session_id="session-1",
            generation=1,
            authority=authority("session.tree.read"),
            journal=store,
            client=client,
            clock_ms=lambda: 100,
            cancellation_signal=MutableSignal(),
            session_status=lambda: "running",
        )

        first = await manager.execute(command)
        replayed = await manager.execute(command)

        self.assertEqual(first.status, "uncertain")
        self.assertIs(replayed, first)
        self.assertTrue(manager.snapshot().recovery_required)
        self.assertEqual(len(client.commands), 1)


if __name__ == "__main__":
    unittest.main()
