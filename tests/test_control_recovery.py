from __future__ import annotations

import asyncio
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from asterion.control.authority import (
    ActionReceipt,
    AuthorityError,
    AuthorityLedger,
    BudgetUsage,
    action_proposal_digest,
)
from asterion.control.host import ControlCommand, ControlEvent, EventCursor
from asterion.control.execution import ActionExecutionReceipt
from asterion.control.journal import (
    FileCanonicalJournal,
    JournalConflictError,
    JournalCursor,
    JournalEntry,
    JournalRecord,
    MemoryCanonicalJournal,
)
from asterion.control.manager import ControlHost, ControlHostError
from asterion.control.recovery import recover_control_host_state
from asterion.control.system import resolve_agent_system
from asterion.runtime.host import CancellationSignal
from tests.test_control_authority import _envelope, _proposal
from tests.test_control_host import ScriptedClient, SpyExecutor
from tests.test_control_system import _control_factories, _manifest, _provider


def _event(
    event_type: str,
    sequence: int,
    payload: dict[str, object],
    *,
    generation: int = 1,
    session_id: str = "session-1",
) -> ControlEvent:
    return ControlEvent(
        event_id=f"event-{generation}-{sequence}",
        session_id=session_id,
        generation=generation,
        sequence=sequence,
        emitted_at=f"2026-08-10T00:00:{sequence:02d}Z",
        type=event_type,
        payload=payload,
    )


def _created(sequence: int = 1, *, session_id: str = "session-1") -> ControlEvent:
    return _event(
        "session.created",
        sequence,
        {
            "goal_id": "goal-1",
            "authority_id": "authority-1",
            "authority_revision": 1,
        },
        session_id=session_id,
    )


def _running(sequence: int = 2, *, generation: int = 1) -> ControlEvent:
    return _event(
        "session.running", sequence, {"reason_code": "started"}, generation=generation
    )


def _journal() -> MemoryCanonicalJournal:
    journal = MemoryCanonicalJournal("session-1")
    first = journal.append(
        0,
        JournalRecord.system_bound(system_id="research.system", system_version="1.0.0"),
    )
    journal.append(
        first.position,
        JournalRecord.authority_bound(authority_id="authority-1", authority_revision=1),
    )
    return journal


def _accept(journal: MemoryCanonicalJournal, *events: ControlEvent) -> None:
    for event in events:
        journal.accept_event(event, expected_position=journal.position)


def _proposal_event() -> ControlEvent:
    return ControlEvent.from_mapping(
        {**_proposal().to_mapping(), "event_id": "event-1-3", "sequence": 3}
    )


def _decision(
    journal: MemoryCanonicalJournal, proposal: ControlEvent, *, status: str = "admitted"
) -> None:
    journal.append(
        journal.position,
        JournalRecord.action_decided(
            action_id="action-1",
            authority_revision=1,
            status=status,
            reason="authorized" if status == "admitted" else "target-not-authorized",
            proposal_digest=action_proposal_digest(proposal),
        ),
    )


def _terminal_command(status: str, receipt_ref: str | None) -> ControlCommand:
    return ControlCommand(
        command_id="terminal:action-1",
        session_id="session-1",
        authority_revision=1,
        type="action.resolve",
        payload={
            "action_id": "action-1",
            "resolution": status,
            "reason_code": "executed"
            if status == "succeeded"
            else "transport-uncertain",
            "receipt_ref": receipt_ref,
        },
    )


def _admission_command() -> ControlCommand:
    return ControlCommand(
        command_id="admission:action-1",
        session_id="session-1",
        authority_revision=1,
        type="action.resolve",
        payload={
            "action_id": "action-1",
            "resolution": "admitted",
            "reason_code": "authorized",
            "receipt_ref": None,
        },
    )


def _create_command(
    *,
    session_id: str = "session-1",
    authority_revision: int = 1,
    system_id: str = "research.system",
    system_version: str = "1.0.0",
) -> ControlCommand:
    return ControlCommand(
        command_id="create-1",
        session_id=session_id,
        authority_revision=authority_revision,
        type="session.create",
        payload={
            "system_id": system_id,
            "system_version": system_version,
            "goal_id": "goal-1",
            "goal_ref": "goal-ref-1",
        },
    )


def _plan(directory: str, *, version: str = "1.0.0"):
    return resolve_agent_system(
        {**_manifest(), "version": version},
        application_providers=(_provider(Path(directory)),),
        control_factories=_control_factories([]),
        host_capabilities=("clock.monotonic", "storage.private"),
    )


def _action_prefix() -> tuple[MemoryCanonicalJournal, ControlEvent]:
    journal = _journal()
    proposal = _proposal_event()
    _accept(journal, _created(), _running(), proposal)
    _decision(journal, proposal)
    return journal, proposal


class TestControlRecovery(unittest.TestCase):
    def test_operation_recovery_allows_both_durable_rejected_shapes(self) -> None:
        from tests.test_operation_manager import (
            _append_records,
            _manager,
            _receipt,
            _rejected,
            _transaction,
        )

        transaction = _transaction()
        cases = {
            "prevalidation": [
                JournalRecord.operation_transaction_accepted(transaction),
                JournalRecord.operation_receipted(_receipt(transaction, "rejected")),
            ],
            "authority": [
                JournalRecord.operation_transaction_accepted(transaction),
                JournalRecord.operation_admitted(_rejected(transaction)),
                JournalRecord.operation_receipted(_receipt(transaction, "rejected")),
            ],
        }
        for name, records in cases.items():
            with self.subTest(name=name):
                _, _, _, _, journal = _manager()
                _append_records(journal, records)
                recovered = recover_control_host_state(
                    journal.replay(JournalCursor(0)),
                    _envelope(
                        host_service_grants=("operation.auth",),
                        allowed_operations=("operation.auth",),
                    ),
                    expected_session_id="session-1",
                    expected_generation=1,
                )
                self.assertEqual(recovered.authority.operation_settlements, {})
                self.assertEqual(recovered.authority.reserved_operation_ids, ())

    def test_operation_recovery_rejects_invalid_phase_order_and_digests(self) -> None:
        from tests.test_operation_manager import (
            _admitted,
            _append_records,
            _manager,
            _receipt,
            _transaction,
        )

        transaction = _transaction()
        decision = _admitted(transaction)
        accepted = JournalRecord.operation_transaction_accepted(transaction)
        admitted = JournalRecord.operation_admitted(decision)
        reserved = JournalRecord.operation_reserved(decision)
        dispatch = JournalRecord.operation_dispatch_started(transaction)
        handoff = JournalRecord.operation_handoff_fenced(transaction)
        uncertain = JournalRecord.operation_receipted(_receipt(transaction, "uncertain"))
        terminal = JournalRecord.operation_receipted(_receipt(transaction))
        cases = {
            "dispatch-without-reservation": [accepted, admitted, dispatch],
            "handoff-without-dispatch": [accepted, admitted, reserved, handoff],
            "wrong-digest": [
                accepted,
                admitted,
                reserved,
                JournalRecord(
                    "operation-dispatch-wrong-digest-recovery",
                    "operation.dispatch.started",
                    {
                        "operation_id": transaction.operation_id,
                        "transaction_digest": "a" * 64,
                    },
                ),
            ],
            "reconcile-without-uncertain": [
                accepted,
                admitted,
                reserved,
                dispatch,
                handoff,
                JournalRecord.operation_reconciliation_recorded(
                    operation_id=transaction.operation_id, attempt=1
                ),
            ],
            "attempt-gap": [
                accepted,
                admitted,
                reserved,
                dispatch,
                uncertain,
                JournalRecord.operation_reconciliation_recorded(
                    operation_id=transaction.operation_id, attempt=2
                ),
            ],
            "terminal-after-uncertain-without-reconcile": [
                accepted,
                admitted,
                reserved,
                dispatch,
                uncertain,
                terminal,
            ],
        }
        for name, records in cases.items():
            with self.subTest(name=name):
                _, _, _, _, journal = _manager()
                _append_records(journal, records)
                with self.assertRaises(JournalConflictError):
                    recover_control_host_state(
                        journal.replay(JournalCursor(0)),
                        _envelope(
                            host_service_grants=("operation.auth",),
                            allowed_operations=("operation.auth",),
                        ),
                        expected_session_id="session-1",
                        expected_generation=1,
                    )

    def test_operation_prefix_recovers_reserved_authority(self) -> None:
        from tests.test_operation_manager import _manager, _transaction

        manager, _, _, _, journal = _manager()
        asyncio.run(manager.execute(_transaction()))
        recovered = recover_control_host_state(
            journal.replay(JournalCursor(0)),
            _envelope(
                host_service_grants=("operation.auth",),
                allowed_operations=("operation.auth",),
            ),
            expected_session_id="session-1",
            expected_generation=1,
        )
        self.assertEqual(recovered.authority.reserved_operation_ids, ())

    def test_live_terminal_delivery_binds_public_safe_result_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proposal = _proposal_event()
            plan = _plan(directory)

            class BindingClient(ScriptedClient):
                def __init__(self) -> None:
                    super().__init__(
                        plan.control_binding.manifest,
                        (_created(), _running(), proposal),
                    )
                    self.bound: list[ActionExecutionReceipt] = []

                def bind_action_result(self, receipt: ActionExecutionReceipt) -> None:
                    self.bound.append(receipt)

            class SuccessfulExecutor:
                async def execute(
                    self, proposal: ControlEvent, signal: CancellationSignal
                ) -> ActionExecutionReceipt:
                    del proposal, signal
                    return ActionExecutionReceipt(
                        action_id="action-1",
                        receipt_ref="receipt-1",
                        usage=BudgetUsage(0, 80, 0, 80, 4_000),
                        artifact_ids=("artifact-1",),
                        media_types=("text/plain",),
                    )

            client = BindingClient()
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=MemoryCanonicalJournal("session-1"),
                client=client,
                action_executor=SuccessfulExecutor(),
                clock_ms=lambda: 1_000,
            )

            asyncio.run(host.pump())

            self.assertEqual(
                tuple(receipt.artifact_ids for receipt in client.bound),
                (("artifact-1",),),
            )
            self.assertEqual(client.bound[0].media_types, ("text/plain",))

    def test_recovered_terminal_delivery_rebinds_result_projection_from_file_journal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = FileCanonicalJournal.open(root / "journal", "session-1")
            first = journal.append(
                0,
                JournalRecord.system_bound(
                    system_id="research.system", system_version="1.0.0"
                ),
            )
            journal.append(
                first.position,
                JournalRecord.authority_bound(
                    authority_id="authority-1", authority_revision=1
                ),
            )
            proposal = _proposal_event()
            for event in (_created(), _running(), proposal):
                journal.accept_event(event, expected_position=journal.position)
            _decision(journal, proposal)  # type: ignore[arg-type]
            journal.accept_command(
                _admission_command(),
                expected_position=journal.position,
            )
            journal.append(
                journal.position,
                JournalRecord.action_running(
                    action_id="action-1",
                    proposal_digest=action_proposal_digest(proposal),
                ),
            )
            journal.append(
                journal.position,
                JournalRecord.action_receipted(
                    action_id="action-1",
                    receipt_ref="receipt-1",
                    usage=BudgetUsage(0, 80, 0, 80, 4_000),
                    artifact_ids=("artifact-1",),
                    media_types=("text/plain",),
                ),
            )
            journal.accept_command(
                _terminal_command("succeeded", "receipt-1"),
                expected_position=journal.position,
            )
            journal.close()
            plan = _plan(directory)

            class BindingClient(ScriptedClient):
                def __init__(self) -> None:
                    super().__init__(plan.control_binding.manifest)
                    self.bound: list[ActionExecutionReceipt] = []

                def bind_action_result(self, receipt: ActionExecutionReceipt) -> None:
                    self.bound.append(receipt)

            client = BindingClient()
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=FileCanonicalJournal.open(root / "journal", "session-1"),
                client=client,
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
            )

            asyncio.run(host.pump())

            self.assertEqual(client.bound[0].artifact_ids, ("artifact-1",))
            self.assertEqual(client.bound[0].media_types, ("text/plain",))

    def test_budget_report_recovery_is_exact_and_frozen(self) -> None:
        journal = _journal()
        _accept(
            journal,
            _created(),
            _running(),
            _event(
                "budget.reported",
                3,
                {
                    "controller_tokens": 20,
                    "application_tokens": 0,
                    "child_tokens": 0,
                    "aggregate_tokens": 20,
                    "cost_micros": 3,
                },
            ),
        )
        recovered = recover_control_host_state(
            journal.replay(JournalCursor(0)), _envelope()
        )
        self.assertEqual(
            recovered.authority.reported_usage, BudgetUsage(20, 0, 0, 20, 3)
        )
        self.assertEqual(recovered.authority_usage, BudgetUsage(20, 0, 0, 20, 3))
        with self.assertRaises(AuthorityError):
            recovered.authority.record_provider_usage(object())  # type: ignore[arg-type]

    def test_nonmonotonic_or_overflow_budget_report_recovery_fails_closed(self) -> None:
        for reports in (
            ((10, 10), (5, 5)),
            ((10, 10), (2_000, 2_000)),
        ):
            with self.subTest(reports=reports):
                journal = _journal()
                _accept(journal, _created(), _running())
                for sequence, (application, aggregate) in enumerate(reports, start=3):
                    _accept(
                        journal,
                        _event(
                            "budget.reported",
                            sequence,
                            {
                                "controller_tokens": 0,
                                "application_tokens": application,
                                "child_tokens": 0,
                                "aggregate_tokens": aggregate,
                                "cost_micros": 0,
                            },
                        ),
                    )
                with self.assertRaises(JournalConflictError):
                    recover_control_host_state(
                        journal.replay(JournalCursor(0)), _envelope()
                    )

    def test_reopen_reduces_receipt_usage_and_exact_cursor(self) -> None:
        journal, _ = _action_prefix()
        journal.accept_command(_admission_command(), expected_position=journal.position)
        journal.append(
            journal.position,
            JournalRecord.action_receipted(
                action_id="action-1",
                receipt_ref="receipt-1",
                usage=BudgetUsage(0, 80, 0, 80, 4_000),
            ),
        )
        journal.accept_command(
            _terminal_command("succeeded", "receipt-1"),
            expected_position=journal.position,
        )

        recovered = recover_control_host_state(
            journal.replay(JournalCursor(0)), _envelope()
        )

        self.assertEqual(recovered.state.actions["action-1"].status, "succeeded")
        self.assertEqual(recovered.authority_usage, BudgetUsage(0, 80, 0, 80, 4_000))
        self.assertEqual(recovered.reservations, ())
        self.assertEqual(recovered.cursor, EventCursor(generation=1, sequence=3))
        self.assertEqual(recovered.journal_position, journal.position)

    def test_admitted_without_receipt_preserves_the_exact_reservation(self) -> None:
        journal, _ = _action_prefix()

        recovered = recover_control_host_state(
            journal.replay(JournalCursor(0)), _envelope()
        )

        self.assertEqual(recovered.state.actions["action-1"].status, "admitted")
        self.assertEqual(recovered.reservations, ("action-1",))
        self.assertEqual(recovered.authority.usage, BudgetUsage.zero())

    def test_terminal_without_admission_or_durable_receipt_is_rejected(self) -> None:
        journal, _ = _action_prefix()
        journal.accept_command(
            _terminal_command("succeeded", "receipt-missing"),
            expected_position=journal.position,
        )

        with self.assertRaises(JournalConflictError):
            recover_control_host_state(journal.replay(JournalCursor(0)), _envelope())

    def test_terminal_without_admission_or_running_is_rejected(self) -> None:
        journal, _ = _action_prefix()
        journal.accept_command(
            _terminal_command("uncertain", None), expected_position=journal.position
        )

        with self.assertRaises(JournalConflictError):
            recover_control_host_state(journal.replay(JournalCursor(0)), _envelope())

    def test_canonical_cancelled_before_start_terminal_recovers(self) -> None:
        journal, _ = _action_prefix()
        journal.accept_command(_admission_command(), expected_position=journal.position)
        journal.accept_command(
            replace(
                _terminal_command("cancelled", None),
                payload={
                    "action_id": "action-1",
                    "resolution": "cancelled",
                    "reason_code": "cancelled-before-start",
                    "receipt_ref": None,
                },
            ),
            expected_position=journal.position,
        )

        recovered = recover_control_host_state(
            journal.replay(JournalCursor(0)), _envelope()
        )

        self.assertEqual(recovered.state.actions["action-1"].status, "cancelled")
        self.assertEqual(
            recovered.terminal_commands["action-1"].command_id,
            "terminal:action-1",
        )

    def test_recovery_rejects_noncanonical_action_resolution_prefixes(self) -> None:
        cases: list[tuple[str, MemoryCanonicalJournal]] = []

        noncanonical_admission, _ = _action_prefix()
        admission = _admission_command()
        noncanonical_admission.accept_command(
            replace(admission, command_id="resolve-admission"),
            expected_position=noncanonical_admission.position,
        )
        cases.append(("noncanonical-admission-id", noncanonical_admission))

        terminal_before_running, _ = _action_prefix()
        terminal_before_running.accept_command(
            admission, expected_position=terminal_before_running.position
        )
        terminal_before_running.accept_command(
            _terminal_command("uncertain", None),
            expected_position=terminal_before_running.position,
        )
        cases.append(("terminal-before-running", terminal_before_running))

        succeeded_without_receipt, proposal = _action_prefix()
        succeeded_without_receipt.accept_command(
            admission, expected_position=succeeded_without_receipt.position
        )
        succeeded_without_receipt.append(
            succeeded_without_receipt.position,
            JournalRecord.action_running(
                action_id="action-1",
                proposal_digest=action_proposal_digest(proposal),
            ),
        )
        succeeded_without_receipt.accept_command(
            _terminal_command("succeeded", "receipt-missing"),
            expected_position=succeeded_without_receipt.position,
        )
        cases.append(("succeeded-without-receipt", succeeded_without_receipt))

        noncanonical_terminal, proposal = _action_prefix()
        noncanonical_terminal.accept_command(
            admission, expected_position=noncanonical_terminal.position
        )
        noncanonical_terminal.append(
            noncanonical_terminal.position,
            JournalRecord.action_running(
                action_id="action-1",
                proposal_digest=action_proposal_digest(proposal),
            ),
        )
        terminal = _terminal_command("uncertain", None)
        noncanonical_terminal.accept_command(
            replace(terminal, command_id="resolve-terminal"),
            expected_position=noncanonical_terminal.position,
        )
        cases.append(("noncanonical-terminal-id", noncanonical_terminal))

        for label, journal in cases:
            with self.subTest(label=label), self.assertRaises(JournalConflictError):
                recover_control_host_state(
                    journal.replay(JournalCursor(0)), _envelope()
                )

    def test_checkpoint_prefix_advances_state_once_and_is_recoverable(self) -> None:
        journal = _journal()
        _accept(journal, _created(), _running())
        checkpoint = _event(
            "checkpoint.created",
            3,
            {
                "checkpoint_id": "checkpoint-1",
                "capsule_id": "capsule-1",
                "capsule_digest": "a" * 64,
                "control_plane_id": "prime",
                "control_plane_version": "1.0.0",
                "checkpoint_version": "1.0.0",
                "covered_sequence": 2,
                "storage_ref": "storage-1",
            },
        )
        journal.append(
            journal.position,
            JournalRecord.checkpoint_sealed(checkpoint_event=checkpoint),
        )

        recovered = recover_control_host_state(
            journal.replay(JournalCursor(0)), _envelope()
        )

        self.assertEqual(recovered.cursor, EventCursor(1, 3))
        self.assertEqual(recovered.state.next_sequence, 4)

    def test_recovery_is_repeatable_frozen_and_does_not_mutate_inputs(self) -> None:
        journal, _ = _action_prefix()
        entries = journal.replay(JournalCursor(0))
        envelope = _envelope()

        first = recover_control_host_state(entries, envelope)
        second = recover_control_host_state(entries, envelope)

        self.assertEqual(first.state, second.state)
        self.assertEqual(first.authority_usage, second.authority_usage)
        self.assertEqual(first.reservations, second.reservations)
        self.assertEqual(entries, journal.replay(JournalCursor(0)))
        self.assertEqual(envelope, _envelope())
        with self.assertRaises(FrozenInstanceError):
            first.cursor = EventCursor(1, 0)  # type: ignore[misc]

    def test_recovery_rejects_reordered_duplicate_and_conflicting_receipts_redacted(
        self,
    ) -> None:
        journal, _ = _action_prefix()
        entries = journal.replay(JournalCursor(0))
        malformed = (
            (entries[1], entries[0], *entries[2:]),
            (entries[0], entries[0], *entries[2:]),
        )
        for value in malformed:
            with self.subTest(value=value), self.assertRaises(JournalConflictError):
                recover_control_host_state(value, _envelope())

        journal.append(
            journal.position,
            JournalRecord.action_receipted(
                action_id="action-1",
                receipt_ref="receipt-1",
                usage=BudgetUsage(0, 80, 0, 80, 4_000),
            ),
        )
        conflict = replace(
            journal.replay(JournalCursor(journal.position - 1))[0].record,
            record_id="receipt:action-1:other",
            payload={
                "action_id": "action-1",
                "receipt_ref": "receipt-2",
                "usage": {
                    "controller_tokens": 0,
                    "application_tokens": 70,
                    "child_tokens": 0,
                    "aggregate_tokens": 70,
                    "cost_micros": 3_000,
                },
            },
        )
        journal.append(journal.position, conflict)
        with self.assertRaises(JournalConflictError) as raised:
            recover_control_host_state(journal.replay(JournalCursor(0)), _envelope())
        self.assertNotIn("receipt-2", str(raised.exception))

    def test_authority_revision_replays_only_to_the_exact_current_envelope(
        self,
    ) -> None:
        journal = _journal()
        _accept(
            journal,
            _created(),
            _running(),
            _event("session.budget-limited", 3, {"reason_code": "budget-exhausted"}),
        )
        journal.append(
            journal.position,
            JournalRecord(
                record_id="authority-revision:2",
                kind="authority.revised",
                payload={"authority_id": "authority-1", "authority_revision": 2},
            ),
        )
        _accept(journal, _running(1, generation=2))

        recovered = recover_control_host_state(
            journal.replay(JournalCursor(0)), replace(_envelope(), revision=2)
        )

        self.assertEqual(recovered.state.authority_revision, 2)
        self.assertEqual(recovered.cursor, EventCursor(2, 1))
        with self.assertRaises(JournalConflictError):
            recover_control_host_state(journal.replay(JournalCursor(0)), _envelope())

    def test_control_host_accepts_empty_or_exact_recovered_prefix_only(self) -> None:
        journal = _journal()
        _accept(journal, _created(), _running())
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
                journal=journal,
                client=ScriptedClient(plan.control_binding.manifest),
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
            )
            self.assertEqual(host.snapshot().journal_position, journal.position)
            self.assertEqual(host.snapshot().state.session_status, "running")

            cases = (
                {"session_id": "session-2"},
                {"generation": 2},
                {
                    "authority": AuthorityLedger(
                        replace(_envelope(), authority_id="authority-2")
                    )
                },
            )
            for changes in cases:
                arguments = {
                    "session_id": "session-1",
                    "generation": 1,
                    "plan": plan,
                    "authority": AuthorityLedger(_envelope()),
                    "journal": journal,
                    "client": ScriptedClient(plan.control_binding.manifest),
                    "action_executor": SpyExecutor(),
                    "clock_ms": lambda: 1_000,
                    **changes,
                }
                with self.subTest(changes=changes), self.assertRaises(ControlHostError):
                    ControlHost(**arguments)  # type: ignore[arg-type]

    def test_control_host_rejects_system_version_mismatch_without_rebinding(
        self,
    ) -> None:
        journal = _journal()
        _accept(journal, _created(), _running())
        entries_before = journal.replay(JournalCursor(0))
        with tempfile.TemporaryDirectory() as directory:
            changed_manifest = {**_manifest(), "version": "2.0.0"}
            plan = resolve_agent_system(
                changed_manifest,
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            with self.assertRaises(ControlHostError) as raised:
                ControlHost(
                    session_id="session-1",
                    generation=1,
                    plan=plan,
                    authority=AuthorityLedger(_envelope()),
                    journal=journal,
                    client=ScriptedClient(plan.control_binding.manifest),
                    action_executor=SpyExecutor(),
                    clock_ms=lambda: 1_000,
                )
        self.assertEqual(journal.replay(JournalCursor(0)), entries_before)
        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    def test_shortest_crash_prefixes_recover_without_duplicate_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = _plan(directory)
            journals: list[tuple[str, MemoryCanonicalJournal, int]] = []

            system_only = MemoryCanonicalJournal("session-1")
            system_only.append(
                0,
                JournalRecord.system_bound(
                    system_id="research.system", system_version="1.0.0"
                ),
            )
            journals.append(("system-only", system_only, 2))

            bound = _journal()
            journals.append(("bound", bound, 2))

            command_only = _journal()
            command_only.accept_command(
                _create_command(), expected_position=command_only.position
            )
            journals.append(("create-command", command_only, 3))

            for name, journal, position in journals:
                with self.subTest(name=name):
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
                    snapshot = host.snapshot()
                    self.assertEqual(snapshot.journal_position, position)
                    self.assertEqual(snapshot.state.session_id, "session-1")
                    self.assertIsNone(snapshot.state.session_status)
                    kinds = tuple(
                        entry.record.kind for entry in journal.replay(JournalCursor(0))
                    )
                    self.assertEqual(kinds[:2], ("system.bound", "authority.bound"))
                    self.assertEqual(kinds.count("authority.bound"), 1)

            wrong = MemoryCanonicalJournal("session-1")
            wrong.append(
                0,
                JournalRecord.system_bound(
                    system_id="other.system", system_version="1.0.0"
                ),
            )
            with self.assertRaises(ControlHostError):
                ControlHost(
                    session_id="session-1",
                    generation=1,
                    plan=plan,
                    authority=AuthorityLedger(_envelope()),
                    journal=wrong,
                    client=ScriptedClient(plan.control_binding.manifest),
                    action_executor=SpyExecutor(),
                    clock_ms=lambda: 1_000,
                )
            self.assertEqual(wrong.position, 1)

    def test_internal_expected_identity_recovers_empty_bound_prefix(self) -> None:
        system_only = MemoryCanonicalJournal("session-1")
        system_only.append(
            0,
            JournalRecord.system_bound(
                system_id="research.system", system_version="1.0.0"
            ),
        )
        bound = _journal()
        command_only = _journal()
        command_only.accept_command(
            _create_command(), expected_position=command_only.position
        )

        for journal in (system_only, bound, command_only):
            with self.subTest(position=journal.position):
                recovered = recover_control_host_state(
                    journal.replay(JournalCursor(0)),
                    _envelope(),
                    expected_session_id="session-1",
                    expected_generation=1,
                )

                self.assertEqual(recovered.state.session_id, "session-1")
                self.assertEqual(recovered.state.generation, 1)
                self.assertIsNone(recovered.state.session_status)
                self.assertEqual(recovered.cursor, EventCursor(1, 0))
                self.assertEqual(recovered.journal_position, journal.position)

    def test_recovery_rejects_identity_and_admission_resolution_conflicts(self) -> None:
        created_conflicts = (
            _event(
                "session.created",
                1,
                {
                    "goal_id": "goal-1",
                    "authority_id": "authority-2",
                    "authority_revision": 1,
                },
            ),
            _event(
                "session.created",
                1,
                {
                    "goal_id": "goal-1",
                    "authority_id": "authority-1",
                    "authority_revision": 2,
                },
            ),
        )
        for event in created_conflicts:
            with self.subTest(event=event):
                journal = _journal()
                _accept(journal, event)
                with self.assertRaises(JournalConflictError):
                    recover_control_host_state(
                        journal.replay(JournalCursor(0)), _envelope()
                    )

        command_conflicts = (
            _create_command(system_id="other.system"),
            _create_command(system_version="2.0.0"),
            _create_command(authority_revision=2),
        )
        for command in command_conflicts:
            with self.subTest(command=command):
                journal = _journal()
                journal.accept_command(command, expected_position=journal.position)
                with self.assertRaises(JournalConflictError):
                    recover_control_host_state(
                        journal.replay(JournalCursor(0)),
                        _envelope(),
                        expected_session_id="session-1",
                        expected_generation=1,
                    )

        journal = _journal()
        foreign = _create_command(session_id="session-2")
        record = JournalRecord(
            record_id="command:create-foreign",
            kind="command.accepted",
            payload={"command": foreign.to_mapping()},
        )
        entries = journal.replay(JournalCursor(0)) + (
            JournalEntry(position=3, digest=record.digest, record=record),
        )
        with self.assertRaises(JournalConflictError):
            recover_control_host_state(
                entries,
                _envelope(),
                expected_session_id="session-1",
                expected_generation=1,
            )

        for resolution, reason in (
            ("admitted", "target-not-authorized"),
            ("rejected", "authorized"),
        ):
            with self.subTest(resolution=resolution, reason=reason):
                journal, _ = _action_prefix()
                command = ControlCommand(
                    command_id=f"resolve-{resolution}",
                    session_id="session-1",
                    authority_revision=1,
                    type="action.resolve",
                    payload={
                        "action_id": "action-1",
                        "resolution": resolution,
                        "reason_code": reason,
                        "receipt_ref": None,
                    },
                )
                journal.accept_command(command, expected_position=journal.position)
                with self.assertRaises(JournalConflictError):
                    recover_control_host_state(
                        journal.replay(JournalCursor(0)), _envelope()
                    )

    def test_live_session_create_must_match_the_resolved_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = _plan(directory)
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

            with self.assertRaises(ControlHostError):
                asyncio.run(host.dispatch(_create_command(system_version="2.0.0")))
            self.assertEqual(journal.position, 2)

    def test_recovered_authority_is_frozen_but_host_receives_a_mutable_copy(
        self,
    ) -> None:
        journal, _ = _action_prefix()
        recovered = recover_control_host_state(
            journal.replay(JournalCursor(0)), _envelope()
        )
        reservation = recovered.authority.reservations["action-1"]
        receipt = ActionReceipt(
            action_id="action-1",
            receipt_ref="receipt-1",
            usage=BudgetUsage(0, 80, 0, 80, 4_000),
        )

        self.assertFalse(hasattr(AuthorityLedger(_envelope()), "restore_reservation"))
        with self.assertRaises(AuthorityError):
            AuthorityLedger(replace(_envelope(), revision=2)).reserve(reservation)
        with self.assertRaises(AuthorityError):
            recovered.authority.reserve(reservation)
        with self.assertRaises(AuthorityError):
            recovered.authority.settle("action-1", receipt)
        with self.assertRaises(AuthorityError):
            recovered.authority.replace_authority(replace(_envelope(), revision=2))

        live_journal = _journal()
        _accept(live_journal, _created(), _running())
        proposal = _proposal_event()
        with tempfile.TemporaryDirectory() as directory:

            class SuccessfulExecutor:
                async def execute(
                    self, proposal: ControlEvent, signal: CancellationSignal
                ) -> ActionExecutionReceipt:
                    del proposal, signal
                    return ActionExecutionReceipt(
                        action_id="action-1",
                        receipt_ref="receipt-1",
                        usage=BudgetUsage(0, 80, 0, 80, 4_000),
                    )

            plan = _plan(directory)
            client = ScriptedClient(plan.control_binding.manifest, (proposal,))
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=live_journal,
                client=client,
                action_executor=SuccessfulExecutor(),
                clock_ms=lambda: 1_000,
            )
            asyncio.run(host.pump())
        self.assertEqual(host.snapshot().state.actions["action-1"].status, "succeeded")


if __name__ == "__main__":
    unittest.main()
