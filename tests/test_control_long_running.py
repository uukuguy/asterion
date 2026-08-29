from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory

from asterion.control.journal import (
    FileCanonicalJournal,
    JournalCursor,
    JournalRecord,
    MemoryCanonicalJournal,
)
from asterion.control.long_running import (
    HeartbeatSpec,
    LongRunningCoordinator,
    LongRunningError,
    LongRunningReceipt,
    LongRunningTransportError,
    OrphanAudit,
    ResidentLease,
    ScheduleSpec,
    TaskAuthority,
)


class _Clock:
    def __init__(self, now_ms: int = 0) -> None:
        self.now_ms = now_ms

    def advance(self, delta_ms: int) -> None:
        self.now_ms += delta_ms


class _Cancellation:
    def __init__(self) -> None:
        self.cancelled = False


class _Processes:
    def __init__(self) -> None:
        self.by_controller: dict[str, set[str]] = {}

    def add(self, controller_id: str, process_id: str) -> None:
        self.by_controller.setdefault(controller_id, set()).add(process_id)

    def evict_controller(self, controller_id: str) -> None:
        self.by_controller.pop(controller_id, None)

    def owned_process_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                process_id
                for process_ids in self.by_controller.values()
                for process_id in process_ids
            )
        )


class _FailingProcesses(_Processes):
    def evict_controller(self, controller_id: str) -> None:
        raise RuntimeError("private process failure")


def _journal() -> MemoryCanonicalJournal:
    journal = MemoryCanonicalJournal("long-running-session")
    journal.append(
        0,
        JournalRecord.system_bound(
            system_id="long-running-test",
            system_version="1.0.0",
        ),
    )
    journal.append(
        1,
        JournalRecord.authority_bound(
            authority_id="long-running-authority",
            authority_revision=1,
        ),
    )
    return journal


class TestControlLongRunning(unittest.TestCase):
    def test_user_and_agent_heartbeats_have_disjoint_exact_owners(self) -> None:
        user = HeartbeatSpec("heartbeat-user", "user", None, 60_000)
        first = HeartbeatSpec("heartbeat-agent-1", "agent", "child-1", 30_000)
        second = HeartbeatSpec("heartbeat-agent-2", "agent", "child-2", 30_000)

        self.assertEqual(user.owner_key, "user")
        self.assertEqual(first.owner_key, "agent:child-1")
        self.assertNotEqual(user.owner_key, first.owner_key)
        self.assertNotEqual(first.owner_key, second.owner_key)
        with self.assertRaises(LongRunningError):
            HeartbeatSpec("heartbeat-invalid", "user", "child-1", 30_000)

    def test_once_and_cron_fire_exactly_across_accelerated_24_hours(self) -> None:
        clock = _Clock()
        sent = []

        def send(intent):
            sent.append(intent)
            return LongRunningReceipt.succeeded(intent)

        coordinator = LongRunningCoordinator(
            journal=_journal(),
            clock_ms=lambda: clock.now_ms,
            effect_sender=send,
            cancellation_signal=_Cancellation(),
        )
        coordinator.register_schedule(ScheduleSpec.once("once-1", 3_600_000))
        coordinator.register_schedule(ScheduleSpec.cron("cron-1", "0 * * * *"))

        clock.advance(86_400_000)
        receipts = coordinator.advance()

        self.assertEqual(
            sum(item.source_id == "once-1" for item in receipts),
            1,
        )
        self.assertEqual(
            sum(item.source_id == "cron-1" for item in receipts),
            24,
        )
        self.assertEqual(len(sent), 25)
        self.assertEqual(len({item.effect_id for item in receipts}), 25)

    def test_intent_is_durable_before_effect_dispatch(self) -> None:
        clock = _Clock()
        journal = _journal()

        def send(intent):
            records = journal.replay(JournalCursor(0))
            self.assertEqual(records[-1].record.kind, "long-running.intent")
            self.assertEqual(
                records[-1].record.payload["effect_id"],
                intent.effect_id,
            )
            return LongRunningReceipt.succeeded(intent)

        coordinator = LongRunningCoordinator(
            journal=journal,
            clock_ms=lambda: clock.now_ms,
            effect_sender=send,
            cancellation_signal=_Cancellation(),
        )
        coordinator.register_heartbeat(
            HeartbeatSpec("heartbeat-user", "user", None, 60_000)
        )

        clock.advance(60_000)
        self.assertEqual(coordinator.advance()[0].status, "succeeded")

    def test_restart_never_retries_an_uncertain_effect(self) -> None:
        clock = _Clock()
        journal = _journal()
        calls = []

        def lose_result(intent):
            calls.append(intent.effect_id)
            raise LongRunningTransportError("private transport detail")

        first = LongRunningCoordinator(
            journal=journal,
            clock_ms=lambda: clock.now_ms,
            effect_sender=lose_result,
            cancellation_signal=_Cancellation(),
        )
        first.register_schedule(ScheduleSpec.once("once-1", 1_000))
        clock.advance(1_000)
        receipt = first.advance()[0]

        self.assertEqual(receipt.status, "uncertain")
        reopened = LongRunningCoordinator(
            journal=journal,
            clock_ms=lambda: clock.now_ms,
            effect_sender=lambda intent: self.fail(
                f"uncertain effect retried: {intent.effect_id}"
            ),
            cancellation_signal=_Cancellation(),
        )
        snapshot = reopened.recover()

        self.assertEqual(calls, [receipt.effect_id])
        self.assertEqual(snapshot.history[-1], receipt)
        self.assertEqual(reopened.advance(), ())

    def test_file_recovery_accepts_exact_registration_replay_after_due_time(
        self,
    ) -> None:
        clock = _Clock()
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "private-journal"
            journal = FileCanonicalJournal.open(root, "long-running-session")
            journal.append(
                0,
                JournalRecord.system_bound(
                    system_id="long-running-test",
                    system_version="1.0.0",
                ),
            )
            journal.append(
                1,
                JournalRecord.authority_bound(
                    authority_id="long-running-authority",
                    authority_revision=1,
                ),
            )
            first = LongRunningCoordinator(
                journal=journal,
                clock_ms=lambda: clock.now_ms,
                effect_sender=LongRunningReceipt.succeeded,
                cancellation_signal=_Cancellation(),
            )
            spec = ScheduleSpec.once("once-1", 1_000)
            first.register_schedule(spec)
            clock.advance(1_000)
            expected = first.advance()[0]
            journal.close()

            reopened_journal = FileCanonicalJournal.open(
                root,
                "long-running-session",
            )
            reopened = LongRunningCoordinator(
                journal=reopened_journal,
                clock_ms=lambda: clock.now_ms,
                effect_sender=lambda intent: self.fail(
                    f"completed effect retried: {intent.effect_id}"
                ),
                cancellation_signal=_Cancellation(),
            )

            reopened.register_schedule(spec)
            self.assertEqual(reopened.recover().history, (expected,))
            self.assertEqual(reopened.advance(), ())
            reopened_journal.close()

    def test_close_and_cancellation_stop_future_ticks_without_erasing_history(
        self,
    ) -> None:
        clock = _Clock()
        cancellation = _Cancellation()
        coordinator = LongRunningCoordinator(
            journal=_journal(),
            clock_ms=lambda: clock.now_ms,
            effect_sender=LongRunningReceipt.succeeded,
            cancellation_signal=cancellation,
        )
        coordinator.register_heartbeat(
            HeartbeatSpec("heartbeat-user", "user", None, 60_000)
        )
        clock.advance(60_000)
        coordinator.advance()
        before = coordinator.snapshot()

        cancellation.cancelled = True
        clock.advance(60_000)
        self.assertEqual(coordinator.advance(), ())
        coordinator.close()
        clock.advance(86_400_000)
        self.assertEqual(coordinator.advance(), ())
        after = coordinator.snapshot()

        self.assertEqual(after.history, before.history)
        with self.assertRaises(FrozenInstanceError):
            after.closed = False  # type: ignore[misc]

    def test_specs_reject_noncanonical_cron_and_duplicate_user_heartbeat(
        self,
    ) -> None:
        for expression in (
            "@hourly",
            "0 */2 * * *",
            "0 0-2 * * *",
            "0 0 * * UTC",
            "0 0 1 JAN *",
        ):
            with self.subTest(expression=expression), self.assertRaises(
                LongRunningError
            ):
                ScheduleSpec.cron("cron-invalid", expression)

        coordinator = LongRunningCoordinator(
            journal=_journal(),
            clock_ms=lambda: 0,
            effect_sender=LongRunningReceipt.succeeded,
            cancellation_signal=_Cancellation(),
        )
        coordinator.register_heartbeat(
            HeartbeatSpec("heartbeat-user", "user", None, 60_000)
        )
        with self.assertRaises(LongRunningError):
            coordinator.register_heartbeat(
                HeartbeatSpec("heartbeat-user-2", "user", None, 120_000)
            )

    def test_controller_residency_never_extends_task_authority(self) -> None:
        clock = _Clock()
        coordinator = LongRunningCoordinator(
            journal=_journal(),
            clock_ms=lambda: clock.now_ms,
            effect_sender=LongRunningReceipt.succeeded,
            cancellation_signal=_Cancellation(),
        )

        lease = coordinator.retain_controller("controller-1", until_ms=10_000)
        task = coordinator.start_task("task-1", authority_expires_at_ms=5_000)
        clock.advance(6_000)

        self.assertEqual(
            lease,
            ResidentLease("controller-1", acquired_at_ms=0, expires_at_ms=10_000),
        )
        self.assertEqual(
            task,
            TaskAuthority("task-1", started_at_ms=0, expires_at_ms=5_000),
        )
        self.assertEqual(coordinator.task_status("task-1"), "expired")
        self.assertEqual(coordinator.controller_status("controller-1"), "resident")

    def test_eviction_and_shutdown_leave_no_owned_processes(self) -> None:
        clock = _Clock()
        processes = _Processes()
        coordinator = LongRunningCoordinator(
            journal=_journal(),
            clock_ms=lambda: clock.now_ms,
            effect_sender=LongRunningReceipt.succeeded,
            cancellation_signal=_Cancellation(),
            process_observer=processes,
        )
        coordinator.retain_controller("controller-1", until_ms=10_000)
        coordinator.retain_controller("controller-2", until_ms=20_000)
        processes.add("controller-1", "process-1")
        processes.add("controller-2", "process-2")

        clock.advance(10_001)
        self.assertEqual(coordinator.evict_expired(), ("controller-1",))
        self.assertEqual(coordinator.audit_orphans().owned_process_count, 1)
        coordinator.close()

        self.assertEqual(
            coordinator.audit_orphans(),
            OrphanAudit(
                owned_process_count=0,
                process_ids_digest=(
                    "e3b0c44298fc1c149afbf4c8996fb924"
                    "27ae41e4649b934ca495991b7852b855"
                ),
            ),
        )

    def test_restart_and_repeated_attach_do_not_duplicate_controller_state(
        self,
    ) -> None:
        clock = _Clock()
        journal = _journal()
        first = LongRunningCoordinator(
            journal=journal,
            clock_ms=lambda: clock.now_ms,
            effect_sender=LongRunningReceipt.succeeded,
            cancellation_signal=_Cancellation(),
        )
        first.retain_controller("controller-1", until_ms=86_400_000)
        self.assertTrue(first.attach("controller-1"))
        self.assertFalse(first.attach("controller-1"))

        clock.advance(43_200_000)
        reopened = LongRunningCoordinator(
            journal=journal,
            clock_ms=lambda: clock.now_ms,
            effect_sender=LongRunningReceipt.succeeded,
            cancellation_signal=_Cancellation(),
        )
        self.assertFalse(reopened.attach("controller-1"))
        snapshot = reopened.snapshot()

        self.assertEqual(snapshot.attached_controller_ids, ("controller-1",))
        attached_records = [
            entry
            for entry in journal.replay(JournalCursor(0))
            if entry.record.kind == "long-running.controller-attached"
        ]
        self.assertEqual(len(attached_records), 1)

    def test_recovery_replays_exact_residency_identity_without_rebinding(self) -> None:
        clock = _Clock()
        journal = _journal()
        first = LongRunningCoordinator(
            journal=journal,
            clock_ms=lambda: clock.now_ms,
            effect_sender=LongRunningReceipt.succeeded,
            cancellation_signal=_Cancellation(),
        )
        lease = first.retain_controller("controller-1", until_ms=10_000)
        task = first.start_task("task-1", authority_expires_at_ms=5_000)
        clock.advance(1_000)
        reopened = LongRunningCoordinator(
            journal=journal,
            clock_ms=lambda: clock.now_ms,
            effect_sender=LongRunningReceipt.succeeded,
            cancellation_signal=_Cancellation(),
        )

        self.assertEqual(
            reopened.retain_controller("controller-1", until_ms=10_000),
            lease,
        )
        self.assertEqual(
            reopened.start_task("task-1", authority_expires_at_ms=5_000),
            task,
        )

    def test_recovery_reconciles_a_durable_eviction_with_the_same_identity(
        self,
    ) -> None:
        clock = _Clock()
        journal = _journal()
        failing = _FailingProcesses()
        failing.add("controller-1", "process-1")
        first = LongRunningCoordinator(
            journal=journal,
            clock_ms=lambda: clock.now_ms,
            effect_sender=LongRunningReceipt.succeeded,
            cancellation_signal=_Cancellation(),
            process_observer=failing,
        )
        first.retain_controller("controller-1", until_ms=1_000)
        clock.advance(1_000)
        with self.assertRaises(LongRunningError):
            first.evict_expired()

        recovered_processes = _Processes()
        recovered_processes.add("controller-1", "process-1")
        reopened = LongRunningCoordinator(
            journal=journal,
            clock_ms=lambda: clock.now_ms,
            effect_sender=LongRunningReceipt.succeeded,
            cancellation_signal=_Cancellation(),
            process_observer=recovered_processes,
        )
        reopened.recover()

        self.assertEqual(reopened.audit_orphans().owned_process_count, 0)


if __name__ == "__main__":
    unittest.main()
