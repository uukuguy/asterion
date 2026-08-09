from __future__ import annotations

import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from asterion.control.authority import (
    AuthorityLedger,
    BudgetUsage,
    action_proposal_digest,
)
from asterion.control.host import ControlCommand, ControlEvent, EventCursor
from asterion.control.journal import (
    JournalConflictError,
    JournalCursor,
    JournalRecord,
    MemoryCanonicalJournal,
)
from asterion.control.manager import ControlHost, ControlHostError
from asterion.control.recovery import recover_control_host_state
from asterion.control.system import resolve_agent_system
from tests.test_control_authority import _envelope, _proposal
from tests.test_control_host import ScriptedClient, SpyExecutor
from tests.test_control_system import _control_factories, _manifest, _provider


def _event(event_type: str, sequence: int, payload: dict[str, object], *, generation: int = 1, session_id: str = "session-1") -> ControlEvent:
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
    return _event("session.running", sequence, {"reason_code": "started"}, generation=generation)


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


def _decision(journal: MemoryCanonicalJournal, proposal: ControlEvent, *, status: str = "admitted") -> None:
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
        command_id=f"terminal:{status}",
        session_id="session-1",
        authority_revision=1,
        type="action.resolve",
        payload={
            "action_id": "action-1",
            "resolution": status,
            "reason_code": "executed" if status == "succeeded" else "transport-uncertain",
            "receipt_ref": receipt_ref,
        },
    )


def _action_prefix() -> tuple[MemoryCanonicalJournal, ControlEvent]:
    journal = _journal()
    proposal = _proposal_event()
    _accept(journal, _created(), _running(), proposal)
    _decision(journal, proposal)
    return journal, proposal


class TestControlRecovery(unittest.TestCase):
    def test_reopen_reduces_receipt_usage_and_exact_cursor(self) -> None:
        journal, _ = _action_prefix()
        journal.append(
            journal.position,
            JournalRecord.action_receipted(
                action_id="action-1",
                receipt_ref="receipt-1",
                usage=BudgetUsage(0, 80, 0, 80, 4_000),
            ),
        )
        journal.accept_command(_terminal_command("succeeded", "receipt-1"), expected_position=journal.position)

        recovered = recover_control_host_state(journal.replay(JournalCursor(0)), _envelope())

        self.assertEqual(recovered.state.actions["action-1"].status, "succeeded")
        self.assertEqual(recovered.authority_usage, BudgetUsage(0, 80, 0, 80, 4_000))
        self.assertEqual(recovered.reservations, ())
        self.assertEqual(recovered.cursor, EventCursor(generation=1, sequence=3))
        self.assertEqual(recovered.journal_position, journal.position)

    def test_admitted_without_receipt_preserves_the_exact_reservation(self) -> None:
        journal, _ = _action_prefix()

        recovered = recover_control_host_state(journal.replay(JournalCursor(0)), _envelope())

        self.assertEqual(recovered.state.actions["action-1"].status, "admitted")
        self.assertEqual(recovered.reservations, ("action-1",))
        self.assertEqual(recovered.authority.usage, BudgetUsage.zero())

    def test_terminal_without_durable_receipt_remains_uncertain(self) -> None:
        journal, _ = _action_prefix()
        journal.accept_command(_terminal_command("succeeded", "receipt-missing"), expected_position=journal.position)

        recovered = recover_control_host_state(journal.replay(JournalCursor(0)), _envelope())

        self.assertEqual(recovered.state.actions["action-1"].status, "uncertain")
        self.assertEqual(recovered.reservations, ("action-1",))
        self.assertEqual(recovered.authority.usage, BudgetUsage.zero())

    def test_explicit_uncertain_terminal_never_becomes_success(self) -> None:
        journal, _ = _action_prefix()
        journal.accept_command(_terminal_command("uncertain", None), expected_position=journal.position)

        recovered = recover_control_host_state(journal.replay(JournalCursor(0)), _envelope())

        self.assertEqual(recovered.state.actions["action-1"].status, "uncertain")
        self.assertEqual(recovered.reservations, ("action-1",))

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
        journal.append(journal.position, JournalRecord.checkpoint_sealed(checkpoint_event=checkpoint))

        recovered = recover_control_host_state(journal.replay(JournalCursor(0)), _envelope())

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

    def test_recovery_rejects_reordered_duplicate_and_conflicting_receipts_redacted(self) -> None:
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

    def test_authority_revision_replays_only_to_the_exact_current_envelope(self) -> None:
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
                {"authority": AuthorityLedger(replace(_envelope(), authority_id="authority-2"))},
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

    def test_control_host_rejects_system_version_mismatch_without_rebinding(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
