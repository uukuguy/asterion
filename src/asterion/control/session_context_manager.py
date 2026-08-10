"""Host-owned authority, durability and recovery for session-context commands."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from asterion.control.authority import (
    AuthorityError,
    AuthorityLedger,
    BudgetUsage,
    SessionContextDecision,
    SessionContextSettlement,
    session_context_command_digest,
)
from asterion.control.journal import (
    CanonicalJournal,
    JournalConflictError,
    JournalCursor,
    JournalRecord,
)
from asterion.control.recovery import recover_control_host_state
from asterion.control.session_context import (
    SESSION_CONTEXT_MODEL_OPERATIONS,
    SESSION_CONTEXT_READ_OPERATIONS,
    SessionContextClient,
    SessionContextCommand,
    SessionContextReceipt,
)
from asterion.control.state import TERMINAL_SESSION_STATES
from asterion.runtime.host import CancellationSignal


class SessionContextManagerError(RuntimeError):
    """Raised when a context command cannot be admitted or recovered safely."""


class SessionContextTransportError(SessionContextManagerError):
    """Raised when a persisted provider operation has uncertain transport state."""


@dataclass(frozen=True)
class SessionContextManagerSnapshot:
    journal_position: int
    pending_command_ids: tuple[str, ...]
    recovery_required: bool
    authority_usage: BudgetUsage


class SessionContextManager:
    """Execute closed context commands through one explicitly injected client."""

    def __init__(
        self,
        *,
        session_id: str,
        generation: int,
        authority: AuthorityLedger,
        journal: CanonicalJournal,
        client: SessionContextClient,
        clock_ms: Callable[[], int],
        cancellation_signal: CancellationSignal,
        session_status: Callable[[], str | None],
        position_sink: Callable[[int], None] | None = None,
        recovery_sink: Callable[[], None] | None = None,
    ) -> None:
        if (
            not isinstance(authority, AuthorityLedger)
            or not isinstance(client, SessionContextClient)
            or not callable(clock_ms)
            or not callable(session_status)
            or not isinstance(
                getattr(cancellation_signal, "cancelled", None), bool
            )
            or (position_sink is not None and not callable(position_sink))
            or (recovery_sink is not None and not callable(recovery_sink))
        ):
            raise SessionContextManagerError(
                "session context manager construction is invalid"
            )
        try:
            position = journal.position
            if position < 2:
                raise JournalConflictError("control journal prefix is incomplete")
            entries = journal.replay(JournalCursor(0))
            if len(entries) != position:
                raise JournalConflictError("control journal changed")
            recovered = recover_control_host_state(
                entries,
                authority.envelope,
                expected_session_id=session_id,
                expected_generation=generation,
            )
            if authority == recovered.authority:
                owned_authority = authority
            elif _authority_is_pristine(authority):
                owned_authority = recovered.authority._mutable_copy()
            else:
                raise AuthorityError("session context authority state conflicts")
        except (AuthorityError, JournalConflictError, TypeError, ValueError):
            raise SessionContextManagerError(
                "session context manager recovery failed"
            ) from None
        self._session_id = session_id
        self._generation = generation
        self._authority = owned_authority
        self._journal = journal
        self._client = client
        self._clock_ms = clock_ms
        self._cancellation_signal = cancellation_signal
        self._session_status = session_status
        self._position_sink = position_sink
        self._recovery_sink = recovery_sink
        self._execute_lock = asyncio.Lock()
        self._journal_position = position
        self._commands = dict(recovered.session_context_commands)
        self._decisions = dict(recovered.session_context_decisions)
        self._receipts = dict(recovered.session_context_receipts)
        self._idempotency = {
            command.idempotency_key: session_context_command_digest(command)
            for command in self._commands.values()
        }
        self._recovery_required = any(
            receipt.status == "uncertain" for receipt in self._receipts.values()
        )
        if self._recovery_required and self._recovery_sink is not None:
            self._recovery_sink()

    async def execute(
        self,
        command: SessionContextCommand,
    ) -> SessionContextReceipt:
        """Persist, authorize, dispatch and seal one exact command."""

        async with self._execute_lock:
            return await self._execute_locked(command)

    async def _execute_locked(
        self,
        command: SessionContextCommand,
    ) -> SessionContextReceipt:

        if (
            not isinstance(command, SessionContextCommand)
            or command.session_id != self._session_id
            or command.generation != self._generation
            or command.authority_revision != self._authority.envelope.revision
        ):
            raise SessionContextManagerError(
                "session context command authority or identity mismatches"
            )
        self._refresh_position()
        digest = session_context_command_digest(command)
        existing = self._commands.get(command.command_id)
        if existing is not None and session_context_command_digest(existing) != digest:
            raise SessionContextManagerError("session context command replay conflicts")
        prior_digest = self._idempotency.get(command.idempotency_key)
        if prior_digest is not None and prior_digest != digest:
            raise SessionContextManagerError(
                "session context idempotency replay conflicts"
            )
        terminal = self._receipts.get(command.command_id)
        if terminal is not None:
            return terminal

        if existing is None:
            self._accept_command(command)
        decision = self._decisions.get(command.command_id)
        if decision is None:
            decision = self._decide(command)
        if decision.status == "rejected":
            return self._seal_host_receipt(
                command,
                status="rejected",
                reason_code=decision.reason,
            )
        if self._cancellation_signal.cancelled:
            return self._seal_host_receipt(
                command,
                status="cancelled",
                reason_code="cancelled-before-dispatch",
            )

        try:
            receipt = await self._client.execute_session_context(command)
        except asyncio.CancelledError:
            self._seal_provider_receipt(
                command,
                decision,
                SessionContextReceipt(
                    receipt_id=f"host-uncertain:{command.command_id}",
                    command_id=command.command_id,
                    session_id=command.session_id,
                    generation=command.generation,
                    operation=command.operation,
                    status="uncertain",
                    reason_code="delivery-outcome-unknown",
                    payload={"evidence_ref": None, "result": None},
                ),
            )
            raise SessionContextTransportError(
                "persisted session context delivery is uncertain"
            ) from None
        except Exception:
            raise SessionContextTransportError(
                "persisted session context delivery is uncertain"
            ) from None
        if (
            not isinstance(receipt, SessionContextReceipt)
            or receipt.command_id != command.command_id
            or receipt.session_id != command.session_id
            or receipt.generation != command.generation
            or receipt.operation != command.operation
        ):
            raise SessionContextTransportError(
                "persisted session context delivery is uncertain"
            )
        return self._seal_provider_receipt(command, decision, receipt)

    def snapshot(self) -> SessionContextManagerSnapshot:
        pending = tuple(
            sorted(set(self._commands) - set(self._receipts))
        )
        return SessionContextManagerSnapshot(
            journal_position=self._journal_position,
            pending_command_ids=pending,
            recovery_required=self._recovery_required,
            authority_usage=self._authority.usage,
        )

    def _accept_command(self, command: SessionContextCommand) -> None:
        try:
            entry = self._journal.accept_session_context_command(
                command,
                expected_position=self._journal_position,
            )
        except (JournalConflictError, TypeError, ValueError):
            raise SessionContextManagerError(
                "session context command journal admission failed"
            ) from None
        self._advance(entry.position)
        self._commands[command.command_id] = command
        self._idempotency[command.idempotency_key] = (
            session_context_command_digest(command)
        )

    def _decide(self, command: SessionContextCommand) -> SessionContextDecision:
        try:
            status = self._session_status()
            if status is not None and not isinstance(status, str):
                raise TypeError
            if (
                status in TERMINAL_SESSION_STATES
                and command.operation not in SESSION_CONTEXT_READ_OPERATIONS
            ):
                decision = self._authority.reject_session_context(
                    command,
                    reason="session-terminal",
                )
            else:
                decision = self._authority.evaluate_session_context(
                    command,
                    now_ms=self._clock_ms(),
                )
            if decision.status == "admitted":
                self._authority.reserve_session_context(decision)
            entry = self._journal.append(
                self._journal_position,
                JournalRecord.context_operation_decided(decision),
            )
        except (AuthorityError, JournalConflictError, TypeError, ValueError):
            raise SessionContextManagerError(
                "session context authority decision failed"
            ) from None
        self._advance(entry.position)
        self._decisions[command.command_id] = decision
        return decision

    def _seal_host_receipt(
        self,
        command: SessionContextCommand,
        *,
        status: str,
        reason_code: str,
    ) -> SessionContextReceipt:
        receipt = SessionContextReceipt(
            receipt_id=f"host:{command.command_id}",
            command_id=command.command_id,
            session_id=command.session_id,
            generation=command.generation,
            operation=command.operation,
            status=status,
            reason_code=reason_code,
            payload={"evidence_ref": None, "result": None},
        )
        decision = self._decisions[command.command_id]
        return self._seal_definitive_receipt(
            decision,
            receipt,
            BudgetUsage.zero(),
        )

    def _seal_provider_receipt(
        self,
        command: SessionContextCommand,
        decision: SessionContextDecision,
        receipt: SessionContextReceipt,
    ) -> SessionContextReceipt:
        if receipt.status == "uncertain":
            try:
                entry = self._journal.append(
                    self._journal_position,
                    JournalRecord.context_operation_receipted(
                        receipt,
                        usage=None,
                    ),
                )
            except (JournalConflictError, TypeError, ValueError):
                raise SessionContextManagerError(
                    "session context receipt journal failed"
                ) from None
            self._advance(entry.position)
            self._receipts[command.command_id] = receipt
            self._recovery_required = True
            if self._recovery_sink is not None:
                self._recovery_sink()
            return receipt
        usage = self._receipt_usage(command, decision, receipt)
        return self._seal_definitive_receipt(decision, receipt, usage)

    def _seal_definitive_receipt(
        self,
        decision: SessionContextDecision,
        receipt: SessionContextReceipt,
        usage: BudgetUsage,
    ) -> SessionContextReceipt:
        settlement = None
        try:
            if decision.status == "admitted":
                settlement = SessionContextSettlement(
                    command_id=receipt.command_id,
                    receipt_id=receipt.receipt_id,
                    usage=usage,
                )
                self._authority.preview_session_context_settlement(
                    receipt.command_id,
                    settlement,
                )
            entry = self._journal.append(
                self._journal_position,
                JournalRecord.context_operation_receipted(
                    receipt,
                    usage=usage,
                ),
            )
            if settlement is not None:
                self._authority.settle_session_context(
                    receipt.command_id,
                    settlement,
                )
        except (AuthorityError, JournalConflictError, TypeError, ValueError):
            raise SessionContextManagerError(
                "session context receipt settlement failed"
            ) from None
        self._advance(entry.position)
        self._receipts[receipt.command_id] = receipt
        return receipt

    def _receipt_usage(
        self,
        command: SessionContextCommand,
        decision: SessionContextDecision,
        receipt: SessionContextReceipt,
    ) -> BudgetUsage:
        if decision.reservation is None:
            return BudgetUsage.zero()
        if receipt.status != "succeeded":
            return decision.reservation.as_usage()
        if command.operation not in SESSION_CONTEXT_MODEL_OPERATIONS:
            return BudgetUsage.zero()
        result = receipt.payload.get("result")
        if not isinstance(result, Mapping):
            raise SessionContextManagerError("session context receipt usage is invalid")
        usage = result.get("usage")
        if not isinstance(usage, Mapping):
            raise SessionContextManagerError("session context receipt usage is invalid")
        try:
            return BudgetUsage(
                controller_tokens=_integer(usage.get("controller_tokens")),
                application_tokens=_integer(usage.get("application_tokens")),
                child_tokens=_integer(usage.get("child_tokens")),
                aggregate_tokens=_integer(usage.get("aggregate_tokens")),
                cost_micros=_integer(usage.get("cost_micros")),
            )
        except (TypeError, ValueError):
            raise SessionContextManagerError(
                "session context receipt usage is invalid"
            ) from None

    def _refresh_position(self) -> None:
        try:
            position = self._journal.position
            if position < self._journal_position:
                raise JournalConflictError("control journal position regressed")
            if position > self._journal_position:
                suffix = self._journal.replay(
                    JournalCursor(self._journal_position)
                )
                if any(
                    entry.record.kind.startswith("context.") for entry in suffix
                ):
                    raise JournalConflictError(
                        "session context journal changed externally"
                    )
                self._advance(position)
        except (JournalConflictError, TypeError, ValueError):
            raise SessionContextManagerError(
                "session context journal changed"
            ) from None

    def _advance(self, position: int) -> None:
        self._journal_position = max(self._journal_position, position)
        if self._position_sink is not None:
            self._position_sink(self._journal_position)


def _authority_is_pristine(authority: AuthorityLedger) -> bool:
    return (
        authority.usage == BudgetUsage.zero()
        and not authority.reserved_action_ids
        and not authority.receipts
        and not authority.reserved_session_context_ids
        and not authority.session_context_settlements
    )


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("usage integer is invalid")
    return value
