from __future__ import annotations

import tempfile
import unittest
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast

from asterion.control.authority import AuthorityLedger, BudgetUsage
from asterion.control.execution import (
    ActionExecutionFailure,
    ActionExecutionReceipt,
)
from asterion.control.host import (
    ControlCommand,
    ControlEvent,
    ControlPlaneManifest,
    EventCursor,
)
from asterion.control.journal import (
    FileCanonicalJournal,
    JournalCursor,
    JournalRecord,
    MemoryCanonicalJournal,
)
from asterion.control.manager import (
    ActionExecutor,
    ControlHost,
    ControlHostError,
    ControlHostTransportError,
)
from asterion.control.system import resolve_agent_system
from tests.test_control_authority import _envelope, _proposal
from tests.test_control_host import _session_events
from tests.test_control_system import _control_factories, _manifest, _provider


USAGE = BudgetUsage(0, 80, 0, 80, 4_000)


def _receipt(**changes: object) -> ActionExecutionReceipt:
    values: dict[str, object] = {
        "action_id": "action-1",
        "receipt_ref": "receipt-1",
        "usage": USAGE,
        "artifact_ids": ("artifact-1",),
        "media_types": ("application/json",),
    }
    values.update(changes)
    return ActionExecutionReceipt(**values)  # type: ignore[arg-type]


class MutableSignal:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled


class RecordingExecutor:
    def __init__(
        self,
        outcome: object = None,
        *,
        audit: list[str] | None = None,
        cancel_during: bool = False,
    ) -> None:
        self.outcome = _receipt() if outcome is None else outcome
        self.audit = audit if audit is not None else []
        self.cancel_during = cancel_during
        self.calls: list[tuple[ControlEvent, object]] = []

    async def execute(self, proposal: ControlEvent, signal: object) -> object:
        self.audit.append("executor.start")
        self.calls.append((proposal, signal))
        if self.cancel_during:
            assert isinstance(signal, MutableSignal)
            signal.cancelled = True
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class ReturnedFailureExecutor(RecordingExecutor):
    async def execute(self, proposal: ControlEvent, signal: object) -> object:
        self.calls.append((proposal, signal))
        return ActionExecutionFailure("failed", "runtime-failed", "failure-receipt-1")


class ExecutionClient:
    def __init__(
        self,
        manifest: ControlPlaneManifest,
        events: tuple[ControlEvent, ...] = (),
        *,
        audit: list[str] | None = None,
        fail_terminal_once: bool = False,
        fail_admission_once: bool = False,
        cancel_on_admission: MutableSignal | None = None,
    ) -> None:
        self._manifest = manifest
        self._events = events
        self.audit = audit if audit is not None else []
        self.fail_terminal_once = fail_terminal_once
        self.fail_admission_once = fail_admission_once
        self.cancel_on_admission = cancel_on_admission
        self.sent: list[ControlCommand] = []

    @property
    def manifest(self) -> ControlPlaneManifest:
        return self._manifest

    async def send(self, command: ControlCommand) -> None:
        resolution = command.payload.get("resolution")
        self.audit.append(f"provider.{resolution or command.type}")
        if resolution == "admitted" and self.cancel_on_admission is not None:
            self.cancel_on_admission.cancelled = True
        if resolution == "admitted" and self.fail_admission_once:
            self.fail_admission_once = False
            raise RuntimeError("SENTINEL_SECRET admission transport body")
        if (
            resolution in {"succeeded", "failed", "cancelled", "uncertain"}
            and self.fail_terminal_once
        ):
            self.fail_terminal_once = False
            raise RuntimeError("SENTINEL_SECRET provider body")
        self.sent.append(command)

    async def _iterate(self) -> AsyncIterator[ControlEvent]:
        for event in self._events:
            yield event

    def events(self, cursor: EventCursor | None = None) -> AsyncIterator[ControlEvent]:
        del cursor
        return self._iterate()

    async def close(self) -> None:
        return None


class AuditJournal(MemoryCanonicalJournal):
    def __init__(self, session_id: str, audit: list[str]) -> None:
        super().__init__(session_id)
        self.audit = audit

    def append(self, expected_position: int, record: JournalRecord):
        labels = {
            "action.decided": "journal.decision",
            "action.running": "journal.running",
            "action.receipted": "journal.receipt",
        }
        if record.kind in labels:
            self.audit.append(labels[record.kind])
        return super().append(expected_position, record)


class AuditedLedger(AuthorityLedger):
    def __init__(self, audit: list[str]) -> None:
        super().__init__(_envelope())
        self.audit = audit

    def settle(self, action_id: str, receipt: object) -> None:
        self.audit.append("authority.settle")
        super().settle(action_id, receipt)  # type: ignore[arg-type]


class CrashAfterReceiptJournal:
    def __init__(self, journal: FileCanonicalJournal) -> None:
        self.journal = journal

    @property
    def position(self) -> int:
        return self.journal.position

    def replay(self, cursor: JournalCursor):
        return self.journal.replay(cursor)

    def accept_command(self, command: ControlCommand, *, expected_position=None):
        return self.journal.accept_command(command, expected_position=expected_position)

    def accept_event(self, event: ControlEvent, *, expected_position=None):
        return self.journal.accept_event(event, expected_position=expected_position)

    def append(self, expected_position: int, record: JournalRecord):
        entry = self.journal.append(expected_position, record)
        if record.kind == "action.receipted":
            raise RuntimeError("simulated-crash-after-durable-receipt")
        return entry


class CrashAfterRunningJournal(CrashAfterReceiptJournal):
    def append(self, expected_position: int, record: JournalRecord):
        entry = self.journal.append(expected_position, record)
        if record.kind == "action.running":
            raise RuntimeError("simulated-crash-after-durable-running")
        return entry


def _proposal_events() -> tuple[ControlEvent, ...]:
    proposal = ControlEvent.from_mapping(
        {**_proposal().to_mapping(), "sequence": 3, "event_id": "event-3"}
    )
    return _session_events(proposal)


def _build_host(
    root: Path,
    *,
    client: ExecutionClient,
    executor: RecordingExecutor,
    journal: object,
    authority: AuthorityLedger | None = None,
    signal: MutableSignal | None = None,
) -> ControlHost:
    plan = resolve_agent_system(
        _manifest(),
        application_providers=(_provider(root),),
        control_factories=_control_factories([]),
        host_capabilities=("clock.monotonic", "storage.private"),
    )
    return ControlHost(
        session_id="session-1",
        generation=1,
        plan=plan,
        authority=authority or AuthorityLedger(_envelope()),
        journal=journal,  # type: ignore[arg-type]
        client=client,
        action_executor=cast(ActionExecutor, executor),
        cancellation_signal=signal,
        clock_ms=lambda: 1_000,
    )


def _plan(root: Path):
    return resolve_agent_system(
        _manifest(),
        application_providers=(_provider(root),),
        control_factories=_control_factories([]),
        host_capabilities=("clock.monotonic", "storage.private"),
    )


class TestActionExecutionContracts(unittest.TestCase):
    def test_receipt_is_frozen_closed_canonical_and_body_safe(self) -> None:
        receipt = _receipt()
        self.assertEqual(receipt.artifact_ids, ("artifact-1",))
        self.assertNotIn("SENTINEL_SECRET", repr(receipt))
        with self.assertRaises((AttributeError, TypeError)):
            receipt.receipt_ref = "changed"  # type: ignore[misc]

        invalid = (
            {"action_id": "../SENTINEL_SECRET"},
            {"receipt_ref": "/private/SENTINEL_SECRET"},
            {"usage": object()},
            {"artifact_ids": ["artifact-1"]},
            {"artifact_ids": ("artifact-2", "artifact-1")},
            {"artifact_ids": ("artifact-1", "artifact-1")},
            {"media_types": ["application/json"]},
            {"media_types": ("not a media type",)},
            {"media_types": ("text/plain", "application/json")},
        )
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError) as raised:
                _receipt(**changes)
            self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    def test_failure_is_a_strict_redacted_controlled_exception(self) -> None:
        failure = ActionExecutionFailure(
            status="failed",
            reason_code="runtime-failed",
            receipt_ref="failure-receipt-1",
        )
        self.assertIsInstance(failure, Exception)
        self.assertNotIn("failure-receipt-1", repr(failure))
        for values in (
            ("succeeded", "runtime-failed", "receipt-1"),
            ("failed", "SENTINEL_SECRET body", "receipt-1"),
            ("failed", "runtime-failed", None),
            ("uncertain", "progress-unknown", "receipt-1"),
        ):
            with self.subTest(values=values), self.assertRaises(ValueError) as raised:
                ActionExecutionFailure(*values)
            self.assertNotIn("SENTINEL_SECRET", str(raised.exception))


class TestControlExecution(unittest.IsolatedAsyncioTestCase):
    async def test_admission_precedes_executor_and_receipt_settlement_precedes_terminal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit: list[str] = []
            root = Path(directory)
            plan = _plan(root)
            client = ExecutionClient(
                plan.control_binding.manifest, _proposal_events(), audit=audit
            )
            executor = RecordingExecutor(audit=audit)
            ledger = AuditedLedger(audit)
            host = _build_host(
                root,
                client=client,
                executor=executor,
                journal=AuditJournal("session-1", audit),
                authority=ledger,
            )
            audit.clear()

            await host.pump()

            self.assertEqual(
                audit,
                [
                    "journal.decision",
                    "provider.admitted",
                    "journal.running",
                    "executor.start",
                    "journal.receipt",
                    "authority.settle",
                    "provider.succeeded",
                ],
            )
            self.assertEqual(
                host.snapshot().state.actions["action-1"].status, "succeeded"
            )
            self.assertEqual(ledger.usage, USAGE)
            self.assertEqual(len(executor.calls), 1)

    async def test_cancelled_before_start_never_contacts_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan(root)
            signal = MutableSignal()
            client = ExecutionClient(
                plan.control_binding.manifest,
                _proposal_events(),
                cancel_on_admission=signal,
            )
            executor = RecordingExecutor()
            host = _build_host(
                root,
                client=client,
                executor=executor,
                journal=MemoryCanonicalJournal("session-1"),
                signal=signal,
            )

            await host.pump()

            self.assertEqual(executor.calls, [])
            self.assertEqual(
                host.snapshot().state.actions["action-1"].status, "cancelled"
            )
            self.assertEqual(client.sent[-1].payload["resolution"], "cancelled")

    async def test_controlled_and_unknown_failures_are_distinguished(self) -> None:
        cases = (
            (
                ActionExecutionFailure("failed", "runtime-failed", "failure-receipt-1"),
                "failed",
                "failure-receipt-1",
            ),
            (RuntimeError("SENTINEL_SECRET provider body"), "uncertain", None),
            (object(), "uncertain", None),
        )
        for outcome, status, receipt_ref in cases:
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                plan = _plan(root)
                client = ExecutionClient(
                    plan.control_binding.manifest, _proposal_events()
                )
                executor = RecordingExecutor(outcome)
                host = _build_host(
                    root,
                    client=client,
                    executor=executor,
                    journal=MemoryCanonicalJournal("session-1"),
                )

                await host.pump()

                command = client.sent[-1]
                self.assertEqual(command.payload["resolution"], status)
                self.assertEqual(command.payload["receipt_ref"], receipt_ref)
                self.assertNotIn("SENTINEL_SECRET", repr(host.snapshot()))

    async def test_returning_a_failure_instead_of_raising_it_fails_uncertain(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan(root)
            client = ExecutionClient(plan.control_binding.manifest, _proposal_events())
            executor = ReturnedFailureExecutor()
            host = _build_host(
                root,
                client=client,
                executor=executor,
                journal=MemoryCanonicalJournal("session-1"),
            )

            await host.pump()

            self.assertEqual(client.sent[-1].payload["resolution"], "uncertain")
            self.assertEqual(
                host.snapshot().state.actions["action-1"].status, "uncertain"
            )

    async def test_cancel_during_execution_requires_executor_proof(self) -> None:
        cases = (
            (
                ActionExecutionFailure(
                    "cancelled", "execution-cancelled", "cancel-receipt-1"
                ),
                "cancelled",
            ),
            (RuntimeError("SENTINEL_SECRET cancellation race"), "uncertain"),
        )
        for outcome, expected in cases:
            with (
                self.subTest(expected=expected),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                plan = _plan(root)
                signal = MutableSignal()
                client = ExecutionClient(
                    plan.control_binding.manifest, _proposal_events()
                )
                executor = RecordingExecutor(outcome, cancel_during=True)
                host = _build_host(
                    root,
                    client=client,
                    executor=executor,
                    journal=MemoryCanonicalJournal("session-1"),
                    signal=signal,
                )

                await host.pump()

                self.assertEqual(
                    host.snapshot().state.actions["action-1"].status, expected
                )

    async def test_invalid_receipts_never_enter_the_canonical_prefix(self) -> None:
        invalid = (
            _receipt(action_id="action-other"),
            _receipt(
                usage=replace(USAGE, application_tokens=101, aggregate_tokens=101)
            ),
        )
        for receipt in invalid:
            with (
                self.subTest(receipt=receipt),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                plan = _plan(root)
                journal = MemoryCanonicalJournal("session-1")
                client = ExecutionClient(
                    plan.control_binding.manifest, _proposal_events()
                )
                host = _build_host(
                    root,
                    client=client,
                    executor=RecordingExecutor(receipt),
                    journal=journal,
                )

                await host.pump()

                kinds = tuple(
                    entry.record.kind for entry in journal.replay(JournalCursor(0))
                )
                self.assertNotIn("action.receipted", kinds)
                self.assertEqual(client.sent[-1].payload["resolution"], "uncertain")
                self.assertEqual(
                    host.snapshot().state.actions["action-1"].status, "uncertain"
                )

    async def test_terminal_send_failure_recovers_without_reexecution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan(root)
            journal = MemoryCanonicalJournal("session-1")
            client = ExecutionClient(
                plan.control_binding.manifest,
                _proposal_events(),
                fail_terminal_once=True,
            )
            executor = RecordingExecutor()
            host = _build_host(root, client=client, executor=executor, journal=journal)

            with self.assertRaises(ControlHostTransportError) as raised:
                await host.pump()
            self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
            first_terminal = journal.replay(JournalCursor(0))[-1].record
            self.assertEqual(first_terminal.kind, "command.accepted")
            self.assertEqual(
                host.snapshot().state.actions["action-1"].status, "succeeded"
            )

            resumed_client = ExecutionClient(plan.control_binding.manifest)
            resumed_executor = RecordingExecutor(RuntimeError("must not execute"))
            resumed = _build_host(
                root,
                client=resumed_client,
                executor=resumed_executor,
                journal=journal,
            )
            await resumed.pump()

            self.assertEqual(resumed_executor.calls, [])
            command_value = first_terminal.payload["command"]
            assert isinstance(command_value, Mapping)
            self.assertEqual(
                resumed_client.sent,
                [ControlCommand.from_mapping(command_value)],
            )
            self.assertEqual(journal.position, resumed.snapshot().journal_position)

    async def test_persisted_admission_recovers_and_executes_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan(root)
            journal = MemoryCanonicalJournal("session-1")
            first_client = ExecutionClient(
                plan.control_binding.manifest,
                _proposal_events(),
                fail_admission_once=True,
            )
            first_executor = RecordingExecutor(RuntimeError("must not execute"))
            first = _build_host(
                root,
                client=first_client,
                executor=first_executor,
                journal=journal,
            )

            with self.assertRaises(ControlHostTransportError):
                await first.pump()
            self.assertEqual(first_executor.calls, [])

            resumed_client = ExecutionClient(plan.control_binding.manifest)
            resumed_executor = RecordingExecutor()
            resumed = _build_host(
                root,
                client=resumed_client,
                executor=resumed_executor,
                journal=journal,
            )
            await resumed.pump()

            self.assertEqual(len(resumed_executor.calls), 1)
            self.assertEqual(
                tuple(command.payload["resolution"] for command in resumed_client.sent),
                ("admitted", "succeeded"),
            )

    async def test_durable_running_fence_without_receipt_recovers_uncertain(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            plan = _plan(root)
            durable = FileCanonicalJournal.open(journal_root, "session-1")
            first = _build_host(
                root,
                client=ExecutionClient(
                    plan.control_binding.manifest, _proposal_events()
                ),
                executor=RecordingExecutor(RuntimeError("must not be reached")),
                journal=CrashAfterRunningJournal(durable),
            )

            with self.assertRaises(RuntimeError):
                await first.pump()

            resumed_client = ExecutionClient(plan.control_binding.manifest)
            resumed_executor = RecordingExecutor(RuntimeError("must not execute"))
            resumed = _build_host(
                root,
                client=resumed_client,
                executor=resumed_executor,
                journal=FileCanonicalJournal.open(journal_root, "session-1"),
            )
            await resumed.pump()

            self.assertEqual(resumed_executor.calls, [])
            self.assertEqual(
                resumed.snapshot().state.actions["action-1"].status, "uncertain"
            )
            self.assertEqual(resumed_client.sent[-1].payload["resolution"], "uncertain")

    async def test_equal_terminal_replay_is_idempotent_but_divergent_semantics_fail(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan(root)
            journal = MemoryCanonicalJournal("session-1")
            client = ExecutionClient(plan.control_binding.manifest, _proposal_events())
            host = _build_host(
                root,
                client=client,
                executor=RecordingExecutor(),
                journal=journal,
            )
            await host.pump()
            terminal = client.sent[-1]
            before = journal.position

            journal.accept_command(terminal, expected_position=journal.position)
            self.assertEqual(journal.position, before)
            divergent = ControlCommand(
                command_id="terminal:action-1:divergent",
                session_id="session-1",
                authority_revision=1,
                type="action.resolve",
                payload={
                    "action_id": "action-1",
                    "resolution": "uncertain",
                    "reason_code": "progress-unknown",
                    "receipt_ref": None,
                },
            )
            journal.accept_command(divergent, expected_position=journal.position)

            with self.assertRaises(ControlHostError):
                _build_host(
                    root,
                    client=ExecutionClient(plan.control_binding.manifest),
                    executor=RecordingExecutor(),
                    journal=journal,
                )

    async def test_file_reopen_after_durable_receipt_settles_and_never_reexecutes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            plan = _plan(root)
            durable = FileCanonicalJournal.open(journal_root, "session-1")
            client = ExecutionClient(plan.control_binding.manifest, _proposal_events())
            executor = RecordingExecutor()
            crashing = _build_host(
                root,
                client=client,
                executor=executor,
                journal=CrashAfterReceiptJournal(durable),
            )

            with self.assertRaises(RuntimeError):
                await crashing.pump()

            reopened = FileCanonicalJournal.open(journal_root, "session-1")
            resumed_client = ExecutionClient(plan.control_binding.manifest)
            resumed_executor = RecordingExecutor(RuntimeError("must not execute"))
            resumed = _build_host(
                root,
                client=resumed_client,
                executor=resumed_executor,
                journal=reopened,
            )
            await resumed.pump()

            self.assertEqual(resumed_executor.calls, [])
            self.assertEqual(
                resumed.snapshot().state.actions["action-1"].status, "succeeded"
            )
            self.assertEqual(
                resumed_client.sent[-1].payload["receipt_ref"], "receipt-1"
            )


if __name__ == "__main__":
    unittest.main()
