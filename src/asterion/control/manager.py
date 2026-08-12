"""Host orchestration for control commands, events and action admission."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, cast

from asterion.control.authority import (
    ActionReceipt,
    AuthorityError,
    AuthorityLedger,
    BudgetUsage,
    RemainingBudget,
    ProviderUsageReport,
)
from asterion.control.execution import (
    ActionExecutionFailure,
    ActionExecutionReceipt,
)
from asterion.control.evidence import ControlEvidenceProjector
from asterion.control.host import (
    ControlCommand,
    ControlEvent,
    ControlPlaneClient,
    EventCursor,
)
from asterion.control.journal import (
    CanonicalJournal,
    JournalConflictError,
    JournalCursor,
    JournalRecord,
)
from asterion.control.recovery import recover_control_host_state
from asterion.control.session_context import (
    SESSION_CONTEXT_CAPABILITY,
    SessionContextClient,
)
from asterion.control.session_context_manager import (
    SessionContextManager,
    SessionContextManagerError,
)
from asterion.control.state import (
    ControlState,
    ControlStateError,
    apply_action_admission,
    apply_action_resolution,
    mark_session_recovery_required,
    mark_action_running,
    reduce_control_event,
)
from asterion.runtime.host import CancellationSignal
from asterion.control.system import AgentSystemPlan
from asterion.pathlight.recorder import (
    NOOP_PATHLIGHT_RECORDER,
    PathlightRecorder,
)


class ControlHostError(RuntimeError):
    """Raised when canonical host processing cannot continue safely."""


class ControlHostTransportError(ControlHostError):
    """Raised when a persisted provider operation has uncertain transport state."""


class ActionExecutor(Protocol):
    async def execute(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt:
        """Return an exact receipt or raise ``ActionExecutionFailure``."""
        ...


class AdmittedActionPreparer(Protocol):
    """Persist provider-specific binding before an admitted action is delivered."""

    async def prepare(self, proposal: ControlEvent) -> None:
        ...


@dataclass(frozen=True)
class ProviderOwnedActionTerminal:
    """One terminal result observed from a provider-owned asynchronous action."""

    action_id: str
    status: str
    receipt: ActionExecutionReceipt | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.action_id, str)
            or self.status not in {"succeeded", "failed", "cancelled", "uncertain"}
            or (self.status == "succeeded") != isinstance(self.receipt, ActionExecutionReceipt)
            or (self.receipt is not None and self.receipt.action_id != self.action_id)
        ):
            raise ValueError("provider-owned action terminal is invalid")


class ProviderOwnedActionLifecycle(Protocol):
    """Observe actions whose selected provider, rather than host executor, runs them."""

    def owns(self, proposal: ControlEvent) -> bool:
        ...

    async def reconcile(self) -> tuple[ProviderOwnedActionTerminal, ...]:
        ...


class ActionResultBinder(Protocol):
    def bind_action_result(self, receipt: ActionExecutionReceipt) -> None:
        """Bind one public-safe execution projection before terminal delivery."""
        ...


class ActionInputPreparer(Protocol):
    async def prepare_private_input(self, reference: str) -> None:
        """Prepare one provider-owned private action input for sync executor use."""
        ...

    def release_private_input(self, reference: str) -> None:
        """Release one previously prepared private action input."""
        ...


class AuthoritySnapshotSink(Protocol):
    async def sync_authority_snapshot(self, budget: RemainingBudget) -> None:
        """Accept the latest host-authoritative remaining budget."""

        ...


class ChildLifecycleService(Protocol):
    """Lifecycle boundary injected by the host without child implementation imports."""

    @property
    def active_ids(self) -> tuple[str, ...]:
        """Return the active child identities."""
        ...

    async def cancel_all(self) -> None:
        """Request cancellation of all active child sessions."""
        ...

    async def close(self) -> None:
        """Close child provider resources."""
        ...


class _NeverCancelled:
    @property
    def cancelled(self) -> bool:
        return False


_TERMINAL_POLL_INTERVAL_SECONDS = 0.01
_TERMINAL_MAX_EMPTY_POLLS = 100


@dataclass(frozen=True)
class ControlHostSnapshot:
    state: ControlState
    journal_position: int
    authority_usage: BudgetUsage
    evidence_gaps: tuple[str, ...] = ()


class ControlHost:
    """Persist before dispatch/acknowledgement and reduce only validated events."""

    def __init__(
        self,
        *,
        session_id: str,
        generation: int,
        plan: AgentSystemPlan,
        authority: AuthorityLedger,
        journal: CanonicalJournal,
        client: ControlPlaneClient,
        action_executor: ActionExecutor,
        clock_ms: Callable[[], int],
        cancellation_signal: CancellationSignal | None = None,
        pathlight: PathlightRecorder = NOOP_PATHLIGHT_RECORDER,
        child_service: ChildLifecycleService | None = None,
        session_context_client: SessionContextClient | None = None,
        admitted_action_preparer: AdmittedActionPreparer | None = None,
        provider_owned_actions: ProviderOwnedActionLifecycle | None = None,
    ) -> None:
        if (
            not isinstance(plan, AgentSystemPlan)
            or not isinstance(authority, AuthorityLedger)
            or not callable(clock_ms)
            or not callable(getattr(action_executor, "execute", None))
            or (
                cancellation_signal is not None
                and not isinstance(
                    getattr(cancellation_signal, "cancelled", None), bool
                )
            )
            or client.manifest != plan.control_binding.manifest
            or authority.usage != BudgetUsage.zero()
            or authority.reserved_action_ids
            or authority.receipts
            or authority.reserved_session_context_ids
            or authority.session_context_settlements
            or not _valid_child_service(child_service)
            or (
                admitted_action_preparer is not None
                and not callable(getattr(admitted_action_preparer, "prepare", None))
            )
            or not _valid_provider_owned_actions(provider_owned_actions)
            or (
                session_context_client is not None
                and (
                    session_context_client is not client
                    or not isinstance(session_context_client, SessionContextClient)
                    or SESSION_CONTEXT_CAPABILITY
                    not in client.manifest.capabilities
                )
            )
        ):
            raise ControlHostError("control host construction is invalid")
        plan_grants = set(plan.portfolio_by_identity)
        authority_grants = {
            (
                grant.provider_id,
                grant.application_id,
                grant.version,
                grant.runtime_id,
            )
            for grant in authority.envelope.allowed_portfolio
        }
        if not authority_grants.issubset(plan_grants):
            raise ControlHostError("control authority exceeds the resolved system")
        self._plan = plan
        self._authority = authority
        self._journal = journal
        self._client = client
        self._action_executor = action_executor
        self._child_service = child_service
        self._admitted_action_preparer = admitted_action_preparer
        self._provider_owned_actions = provider_owned_actions
        self._children_closed = False
        self._cancellation_signal = cancellation_signal or _NeverCancelled()
        self._clock_ms = clock_ms
        self._evidence = ControlEvidenceProjector(pathlight)
        try:
            position = self._journal.position
            if position == 0:
                self._state = ControlState.empty(session_id, generation=generation)
                system = self._journal.append(
                    0,
                    JournalRecord.system_bound(
                        system_id=plan.system_id,
                        system_version=plan.version,
                    ),
                )
                authority_entry = self._journal.append(
                    system.position,
                    JournalRecord.authority_bound(
                        authority_id=authority.envelope.authority_id,
                        authority_revision=authority.envelope.revision,
                    ),
                )
                self._pending_proposals: dict[str, ControlEvent] = {}
                self._pending_admissions: dict[str, ControlCommand] = {}
                self._pending_terminals: dict[str, ControlCommand] = {}
                self._result_receipts: dict[str, ActionExecutionReceipt] = {}
                self._durable_terminal_ids: set[str] = set()
            else:
                entries = self._journal.replay(JournalCursor(0))
                if len(entries) != position:
                    raise JournalConflictError("control journal changed")
                system_payload = entries[0].record.payload
                if (
                    system_payload.get("system_id") != plan.system_id
                    or system_payload.get("system_version") != plan.version
                ):
                    raise JournalConflictError("control journal identity conflicts")
                if len(entries) == 1:
                    self._journal.append(
                        1,
                        JournalRecord.authority_bound(
                            authority_id=authority.envelope.authority_id,
                            authority_revision=authority.envelope.revision,
                        ),
                    )
                    position = self._journal.position
                    entries = self._journal.replay(JournalCursor(0))
                    if len(entries) != position:
                        raise JournalConflictError("control journal changed")
                authority_payload = entries[1].record.payload
                recovered = recover_control_host_state(
                    entries,
                    authority.envelope,
                    expected_session_id=session_id,
                    expected_generation=generation,
                )
                if (
                    authority_payload.get("authority_id")
                    != authority.envelope.authority_id
                    or recovered.state.session_id != session_id
                    or recovered.state.generation != generation
                    or (
                        recovered.state.authority_id is not None
                        and recovered.state.authority_id
                        != authority.envelope.authority_id
                    )
                    or (
                        recovered.state.authority_revision is not None
                        and recovered.state.authority_revision
                        != authority.envelope.revision
                    )
                    or recovered.journal_position != position
                ):
                    raise JournalConflictError("control journal identity conflicts")
                self._state = recovered.state
                self._authority = recovered.authority._mutable_copy()
                self._pending_proposals = dict(recovered.proposals)
                self._pending_admissions = dict(recovered.admission_commands)
                self._pending_terminals = dict(recovered.terminal_commands)
                self._result_receipts = dict(recovered.result_receipts)
                self._durable_terminal_ids = {
                    command.command_id
                    for command in recovered.terminal_commands.values()
                }
                authority_entry = entries[-1]
                if self._journal.position != position:
                    raise JournalConflictError("control journal changed")
        except (JournalConflictError, TypeError, ValueError):
            raise ControlHostError("control host recovery failed") from None
        self._journal_position = authority_entry.position
        try:
            self._session_context_manager = (
                None
                if session_context_client is None
                else SessionContextManager(
                    session_id=session_id,
                    generation=generation,
                    authority=self._authority,
                    journal=self._journal,
                    client=session_context_client,
                    clock_ms=self._clock_ms,
                    cancellation_signal=self._cancellation_signal,
                    session_status=lambda: self._state.session_status,
                    position_sink=self._advance_from_session_context,
                    recovery_sink=self._mark_session_context_recovery_required,
                )
            )
        except SessionContextManagerError:
            raise ControlHostError(
                "control host session context recovery failed"
            ) from None
        self._evidence.start_system(
            plan,
            session_id=session_id,
            generation=generation,
            authority=authority.envelope,
            journal_position=self._journal_position,
            timestamp_ns=self._clock_ms() * 1_000_000,
        )

    @property
    def session_context_manager(self) -> SessionContextManager | None:
        """Return the explicitly injected extension without discovering one."""

        return self._session_context_manager

    async def dispatch(self, command: ControlCommand) -> None:
        if (
            not isinstance(command, ControlCommand)
            or command.session_id != self._state.session_id
            or command.authority_revision != self._authority.envelope.revision
            or (
                command.type == "session.create"
                and (
                    command.payload["system_id"] != self._plan.system_id
                    or command.payload["system_version"] != self._plan.version
                )
            )
        ):
            raise ControlHostError("control command authority or identity mismatches")
        if command.type == "session.cancel":
            await self._close_children()
        try:
            entry = self._journal.accept_command(
                command, expected_position=self._journal_position
            )
            self._journal_position = max(self._journal_position, entry.position)
        except (JournalConflictError, TypeError, ValueError):
            raise ControlHostError("control command journal admission failed") from None
        try:
            await self._client.send(command)
        except Exception:
            raise ControlHostTransportError(
                "persisted control command delivery is uncertain"
            ) from None
        await self._sync_authority_snapshot()

    async def pump(self, *, until_terminal: bool = False) -> None:
        await self._sync_authority_snapshot()
        await self._reconcile_provider_owned_actions()
        await self._resume_pending_actions()
        empty_polls = 0
        try:
            while True:
                cursor = EventCursor(
                    generation=self._state.generation,
                    sequence=self._state.next_sequence - 1,
                )
                seen = False
                events = self._client.events(cursor)
                async for event in events:
                    seen = True
                    await self._accept_event(event)
                    if until_terminal and self._state.terminal_event_id is not None:
                        break
                await self._reconcile_provider_owned_actions()
                if not until_terminal or self._state.terminal_event_id is not None:
                    break
                if self._cancellation_signal.cancelled:
                    raise ControlHostError("control terminal polling cancelled")
                empty_polls = 0 if seen else empty_polls + 1
                if empty_polls > _TERMINAL_MAX_EMPTY_POLLS:
                    raise ControlHostTransportError(
                        "control terminal polling did not reach terminal state"
                    )
                await asyncio.sleep(_TERMINAL_POLL_INTERVAL_SECONDS)
        except ControlHostError:
            raise
        except Exception:
            raise ControlHostTransportError(
                "control provider event transport is uncertain"
            ) from None

    def snapshot(self) -> ControlHostSnapshot:
        return ControlHostSnapshot(
            state=self._state,
            journal_position=self._journal_position,
            authority_usage=self._authority.usage,
            evidence_gaps=self._evidence.gaps,
        )

    async def close(self) -> None:
        self._evidence.complete_open_spans(
            timestamp_ns=self._clock_ms() * 1_000_000
        )
        await self._close_children()
        journal_close = getattr(self._journal, "close", None)
        try:
            await self._client.close()
        except Exception:
            raise ControlHostTransportError(
                "control provider close is uncertain"
            ) from None
        finally:
            if callable(journal_close):
                journal_close()

    async def _accept_event(self, event: ControlEvent) -> None:
        if not isinstance(event, ControlEvent):
            raise ControlHostError("control provider event is invalid")
        if event.generation < self._state.generation or (
            event.generation == self._state.generation
            and event.sequence < self._state.next_sequence
        ):
            expected = JournalRecord(
                record_id=f"event:{event.event_id}",
                kind="event.accepted",
                payload={"event": event.to_mapping()},
            )
            try:
                existing = next(
                    (
                        entry
                        for entry in self._journal.replay(JournalCursor(0))
                        if entry.record.record_id == expected.record_id
                    ),
                    None,
                )
                if existing is None or existing.digest != expected.digest:
                    raise JournalConflictError("prior event replay conflicts")
                entry = self._journal.accept_event(
                    event, expected_position=self._journal_position
                )
                self._journal_position = max(self._journal_position, entry.position)
            except (JournalConflictError, TypeError, ValueError):
                raise ControlHostError("control provider event journal failed") from None
            return
        report: ProviderUsageReport | None = None
        if event.type == "budget.reported":
            try:
                report = ProviderUsageReport(
                    BudgetUsage(
                        controller_tokens=_usage_payload_integer(
                            event.payload.get("controller_tokens")
                        ),
                        application_tokens=_usage_payload_integer(
                            event.payload.get("application_tokens")
                        ),
                        child_tokens=_usage_payload_integer(
                            event.payload.get("child_tokens")
                        ),
                        aggregate_tokens=_usage_payload_integer(
                            event.payload.get("aggregate_tokens")
                        ),
                        cost_micros=_usage_payload_integer(
                            event.payload.get("cost_micros")
                        ),
                    )
                )
                self._authority.preview_provider_usage(report)
            except (AuthorityError, TypeError, ValueError):
                raise ControlHostError("control provider budget report failed") from None
        try:
            entry = self._journal.accept_event(
                event, expected_position=self._journal_position
            )
            self._journal_position = max(self._journal_position, entry.position)
        except (JournalConflictError, TypeError, ValueError):
            raise ControlHostError("control provider event journal failed") from None
        try:
            reduced = reduce_control_event(self._state, event)
        except ControlStateError:
            raise ControlHostError("control provider event transition failed") from None
        self._state = reduced
        if report is not None:
            try:
                self._authority.record_provider_usage(report)
            except AuthorityError:
                raise ControlHostError("control provider budget report failed") from None
            await self._sync_authority_snapshot()
        self._evidence.project_event(
            event,
            journal_position=entry.position,
            timestamp_ns=self._clock_ms() * 1_000_000,
        )
        if event.type == "action.proposed":
            await self._admit_action(event)

    async def _admit_action(self, proposal: ControlEvent) -> None:
        try:
            decision = self._authority.evaluate(
                proposal,
                now_ms=self._clock_ms(),
                active_children=self._active_child_count(),
            )
            if decision.status == "admitted":
                self._authority.reserve(decision)
            entry = self._journal.append(
                self._journal_position,
                JournalRecord.action_decided(
                    action_id=decision.action_id,
                    authority_revision=decision.authority_revision,
                    status=decision.status,
                    reason=decision.reason,
                    proposal_digest=decision.proposal_digest,
                ),
            )
            self._journal_position = max(self._journal_position, entry.position)
            self._state = apply_action_admission(self._state, decision)
            self._evidence.project_admission(
                decision,
                journal_position=entry.position,
                timestamp_ns=self._clock_ms() * 1_000_000,
            )
            if decision.status == "admitted" and self._admitted_action_preparer is not None:
                await self._admitted_action_preparer.prepare(proposal)
        except (JournalConflictError, ControlStateError, TypeError, ValueError):
            raise ControlHostError("control action admission failed") from None
        command = ControlCommand(
            command_id=f"admission:{decision.action_id}",
            session_id=self._state.session_id,
            authority_revision=decision.authority_revision,
            type="action.resolve",
            payload={
                "action_id": decision.action_id,
                "resolution": decision.status,
                "reason_code": decision.reason,
                "receipt_ref": None,
            },
        )
        self._pending_proposals[decision.action_id] = proposal
        self._persist_command(command)
        self._pending_admissions[decision.action_id] = command
        await self._sync_authority_snapshot()
        await self._deliver_pending_admission(decision.action_id)

    async def _resume_pending_actions(self) -> None:
        for action_id in tuple(sorted(self._pending_proposals)):
            action = self._state.actions.get(action_id)
            if action is None:
                raise ControlHostError("control action recovery failed")
            terminal = self._pending_terminals.get(action_id)
            if terminal is not None:
                self._ensure_pending_terminal_persisted(action_id)
                await self._deliver_pending_terminal(action_id)
                continue
            if action.status == "rejected":
                self._ensure_pending_admission(action_id)
                await self._deliver_pending_admission(action_id)
                continue
            if action.status == "admitted":
                self._ensure_pending_admission(action_id)
                await self._deliver_pending_admission(action_id)
                continue
            if action.status == "running":
                if self._provider_owns(self._pending_proposals[action_id]):
                    continue
                self._ensure_pending_admission(action_id)
                command = self._pending_admissions[action_id]
                await self._send_persisted_command(command)
                self._pending_admissions.pop(action_id, None)
                receipt = self._authority.receipts.get(action_id)
                if receipt is not None:
                    result_receipt = self._result_receipts.get(action_id)
                    await self._complete_action(
                        action_id,
                        status="succeeded",
                        reason_code="executed",
                        receipt_ref=receipt.receipt_ref,
                        usage=receipt.usage,
                        execution_receipt=result_receipt,
                    )
                else:
                    await self._complete_action(
                        action_id,
                        status="uncertain",
                        reason_code="progress-unknown",
                        receipt_ref=None,
                    )
                continue
            self._clear_pending_action(action_id)

    def _ensure_pending_admission(self, action_id: str) -> None:
        if action_id not in self._pending_admissions:
            command = self._admission_command(action_id)
            self._persist_command(command)
            self._pending_admissions[action_id] = command

    async def _deliver_pending_admission(self, action_id: str) -> None:
        command = self._pending_admissions[action_id]
        await self._send_persisted_command(command)
        self._pending_admissions.pop(action_id, None)
        action = self._state.actions[action_id]
        if action.status == "rejected":
            self._clear_pending_action(action_id)
            return
        if action.status != "admitted":
            raise ControlHostError("control admission delivery state is invalid")
        await self._execute_admitted_action(self._pending_proposals[action_id])

    async def _deliver_pending_terminal(self, action_id: str) -> None:
        command = self._pending_terminals[action_id]
        if command.command_id not in self._durable_terminal_ids:
            raise ControlHostError("control terminal command is not durable")
        await self._send_persisted_command(command)
        self._clear_pending_action(action_id)

    def _ensure_pending_terminal_persisted(self, action_id: str) -> None:
        command = self._pending_terminals[action_id]
        if command.command_id not in self._durable_terminal_ids:
            self._persist_command(command)
            self._durable_terminal_ids.add(command.command_id)

    def _clear_pending_action(self, action_id: str) -> None:
        self._pending_proposals.pop(action_id, None)
        self._pending_admissions.pop(action_id, None)
        terminal = self._pending_terminals.pop(action_id, None)
        if terminal is not None:
            self._durable_terminal_ids.discard(terminal.command_id)
        self._result_receipts.pop(action_id, None)

    async def _execute_admitted_action(self, proposal: ControlEvent) -> None:
        action_id = str(proposal.payload["action_id"])
        if self._cancellation_signal.cancelled:
            await self._complete_action(
                action_id,
                status="cancelled",
                reason_code="cancelled-before-start",
                receipt_ref=None,
            )
            return
        try:
            entry = self._journal.append(
                self._journal_position,
                JournalRecord.action_running(
                    action_id=action_id,
                    proposal_digest=self._state.actions[action_id].proposal_digest,
                ),
            )
            self._journal_position = max(self._journal_position, entry.position)
            self._state = mark_action_running(self._state, action_id)
        except (
            JournalConflictError,
            ControlStateError,
            KeyError,
            TypeError,
            ValueError,
        ):
            raise ControlHostError("control action running fence failed") from None

        if self._provider_owns(proposal):
            return

        prepared_reference = await self._prepare_action_input(proposal)
        try:
            result = await self._action_executor.execute(
                proposal, self._cancellation_signal
            )
        except ActionExecutionFailure as failure:
            if type(failure) is not ActionExecutionFailure:
                await self._resolve_unknown_progress(action_id)
                return
            await self._complete_action(
                action_id,
                status=failure.status,
                reason_code=failure.reason_code,
                receipt_ref=failure.receipt_ref,
            )
            return
        except Exception:
            await self._resolve_unknown_progress(action_id)
            return
        finally:
            if prepared_reference is not None:
                self._release_action_input(prepared_reference)

        if type(result) is not ActionExecutionReceipt:
            await self._resolve_unknown_progress(action_id)
            return
        receipt = result
        authority_receipt = ActionReceipt(
            action_id=receipt.action_id,
            receipt_ref=receipt.receipt_ref,
            usage=receipt.usage,
        )
        try:
            if receipt.action_id != action_id:
                raise AuthorityError("action receipt identity mismatches")
            self._authority.preview_settlement(action_id, authority_receipt)
        except (AuthorityError, TypeError, ValueError):
            await self._resolve_unknown_progress(action_id)
            return

        entry = self._journal.append(
            self._journal_position,
            JournalRecord.action_receipted(
                action_id=receipt.action_id,
                receipt_ref=receipt.receipt_ref,
                usage=receipt.usage,
                artifact_ids=receipt.artifact_ids,
                media_types=receipt.media_types,
            ),
        )
        self._journal_position = max(self._journal_position, entry.position)
        try:
            self._authority.settle(action_id, authority_receipt)
        except AuthorityError:
            raise ControlHostError("durable action receipt settlement failed") from None
        self._result_receipts[action_id] = receipt
        await self._sync_authority_snapshot()
        await self._complete_action(
            action_id,
            status="succeeded",
            reason_code="executed",
            receipt_ref=receipt.receipt_ref,
            execution_receipt=receipt,
        )

    async def _resolve_unknown_progress(self, action_id: str) -> None:
        await self._complete_action(
            action_id,
            status="uncertain",
            reason_code="progress-unknown",
            receipt_ref=None,
        )

    def _provider_owns(self, proposal: ControlEvent) -> bool:
        if self._provider_owned_actions is None:
            return False
        try:
            return self._provider_owned_actions.owns(proposal)
        except Exception:
            raise ControlHostError("provider-owned action ownership is invalid") from None

    async def _reconcile_provider_owned_actions(self) -> None:
        lifecycle = self._provider_owned_actions
        if lifecycle is None:
            return
        try:
            terminals = await lifecycle.reconcile()
            if not isinstance(terminals, tuple):
                raise TypeError
            for terminal in terminals:
                if not isinstance(terminal, ProviderOwnedActionTerminal):
                    raise TypeError
                action = self._state.actions.get(terminal.action_id)
                if action is None or action.status != "running":
                    raise TypeError
                if terminal.status == "succeeded":
                    assert terminal.receipt is not None
                    await self._settle_provider_owned_receipt(terminal.receipt)
                else:
                    await self._complete_action(
                        terminal.action_id,
                        status=terminal.status,
                        reason_code="provider-owned-terminal",
                        receipt_ref=None,
                    )
        except ControlHostError:
            raise
        except Exception:
            raise ControlHostError("provider-owned action lifecycle is invalid") from None

    async def _settle_provider_owned_receipt(
        self, receipt: ActionExecutionReceipt
    ) -> None:
        action_id = receipt.action_id
        authority_receipt = ActionReceipt(
            action_id=action_id,
            receipt_ref=receipt.receipt_ref,
            usage=receipt.usage,
        )
        self._authority.preview_settlement(action_id, authority_receipt)
        entry = self._journal.append(
            self._journal_position,
            JournalRecord.action_receipted(
                action_id=action_id,
                receipt_ref=receipt.receipt_ref,
                usage=receipt.usage,
                artifact_ids=receipt.artifact_ids,
                media_types=receipt.media_types,
            ),
        )
        self._journal_position = max(self._journal_position, entry.position)
        self._authority.settle(action_id, authority_receipt)
        self._result_receipts[action_id] = receipt
        await self._sync_authority_snapshot()
        await self._complete_action(
            action_id,
            status="succeeded",
            reason_code="provider-owned-terminal",
            receipt_ref=receipt.receipt_ref,
            execution_receipt=receipt,
        )

    async def _complete_action(
        self,
        action_id: str,
        *,
        status: str,
        reason_code: str,
        receipt_ref: str | None,
        execution_receipt: ActionExecutionReceipt | None = None,
        usage: BudgetUsage | None = None,
    ) -> None:
        try:
            self._state = apply_action_resolution(
                self._state,
                action_id,
                status,
                receipt_ref=receipt_ref,
            )
        except ControlStateError:
            raise ControlHostError(
                "control action terminal transition failed"
            ) from None
        self._evidence.project_execution(
            action_id=action_id,
            status=status,
            reason_code=reason_code,
            receipt_ref=receipt_ref,
            receipt=execution_receipt,
            usage=(
                execution_receipt.usage
                if execution_receipt is not None
                else usage or BudgetUsage.zero()
            ),
            journal_position=self._journal_position,
            timestamp_ns=self._clock_ms() * 1_000_000,
        )
        command = ControlCommand(
            command_id=f"terminal:{action_id}",
            session_id=self._state.session_id,
            authority_revision=self._state.actions[action_id].authority_revision,
            type="action.resolve",
            payload={
                "action_id": action_id,
                "resolution": status,
                "reason_code": reason_code,
                "receipt_ref": receipt_ref,
            },
        )
        self._pending_terminals[action_id] = command
        self._ensure_pending_terminal_persisted(action_id)
        await self._deliver_pending_terminal(action_id)

    def _admission_command(self, action_id: str) -> ControlCommand:
        action = self._state.actions[action_id]
        if action.reason is None or action.status == "proposed":
            raise ControlHostError("control admission recovery failed")
        resolution = "rejected" if action.status == "rejected" else "admitted"
        return ControlCommand(
            command_id=f"admission:{action_id}",
            session_id=self._state.session_id,
            authority_revision=action.authority_revision,
            type="action.resolve",
            payload={
                "action_id": action_id,
                "resolution": resolution,
                "reason_code": action.reason,
                "receipt_ref": None,
            },
        )

    def _persist_command(self, command: ControlCommand) -> None:
        try:
            entry = self._journal.accept_command(
                command, expected_position=self._journal_position
            )
            self._journal_position = max(self._journal_position, entry.position)
        except (JournalConflictError, TypeError, ValueError):
            raise ControlHostError("control command journal admission failed") from None

    async def _send_persisted_command(self, command: ControlCommand) -> None:
        try:
            self._bind_private_result_for_command(command)
            await self._client.send(command)
        except Exception:
            raise ControlHostTransportError(
                "persisted control command delivery is uncertain"
            ) from None

    def _bind_private_result_for_command(self, command: ControlCommand) -> None:
        binder = getattr(self._client, "bind_action_result", None)
        if not callable(binder) or command.type != "action.resolve":
            return
        if command.payload["resolution"] != "succeeded":
            return
        receipt_ref = command.payload["receipt_ref"]
        if receipt_ref is None:
            return
        action_id = str(command.payload["action_id"])
        receipt = self._result_receipts.get(action_id)
        if receipt is None or receipt.receipt_ref != receipt_ref:
            raise ControlHostError("control action result projection is unavailable")
        binder(receipt)

    async def _prepare_action_input(self, proposal: ControlEvent) -> str | None:
        preparer = getattr(self._client, "prepare_private_input", None)
        if not callable(preparer):
            return None
        reference = proposal.payload.get("input_ref")
        if not isinstance(reference, str):
            raise ControlHostError("control action private input is unavailable")
        try:
            await cast(Callable[[str], Awaitable[None]], preparer)(reference)
        except Exception:
            raise ControlHostError("control action private input is unavailable") from None
        return reference

    def _release_action_input(self, reference: str) -> None:
        releaser = getattr(self._client, "release_private_input", None)
        if not callable(releaser):
            return
        try:
            cast(Callable[[str], None], releaser)(reference)
        except Exception:
            raise ControlHostError("control action private input release failed") from None

    async def _sync_authority_snapshot(self) -> None:
        sink = getattr(self._client, "sync_authority_snapshot", None)
        if not callable(sink):
            return
        try:
            await cast(
                Callable[[RemainingBudget], Awaitable[None]],
                sink,
            )(self._authority.remaining_budget(now_ms=self._clock_ms()))
        except Exception:
            raise ControlHostTransportError(
                "control authority snapshot delivery is uncertain"
            ) from None

    async def _close_children(self) -> None:
        if self._child_service is None or self._children_closed:
            return
        try:
            await self._child_service.cancel_all()
            await self._child_service.close()
        except Exception:
            raise ControlHostError("control child cascade is unavailable") from None
        self._children_closed = True

    def _active_child_count(self) -> int:
        if self._child_service is None:
            return 0
        try:
            active_ids = self._child_service.active_ids
            if (
                not isinstance(active_ids, tuple)
                or any(not isinstance(child_id, str) for child_id in active_ids)
            ):
                raise TypeError
            return len(active_ids)
        except Exception:
            raise ControlHostError("control child lifecycle is unavailable") from None

    def _advance_from_session_context(self, position: int) -> None:
        if position < self._journal_position or position != self._journal.position:
            raise ControlHostError("control journal position conflicts")
        self._journal_position = position

    def _mark_session_context_recovery_required(self) -> None:
        try:
            self._state = mark_session_recovery_required(self._state)
        except ControlStateError:
            raise ControlHostError(
                "control session context recovery fence failed"
            ) from None


def _valid_child_service(value: object) -> bool:
    if value is None:
        return True
    try:
        active_ids = getattr(type(value), "active_ids", None)
        return all(
            callable(getattr(value, method, None))
            for method in ("cancel_all", "close")
        ) and (isinstance(active_ids, property) or isinstance(active_ids, tuple))
    except Exception:
        return False


def _valid_provider_owned_actions(value: object) -> bool:
    return value is None or (
        callable(getattr(value, "owns", None))
        and callable(getattr(value, "reconcile", None))
    )


def _usage_payload_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("control provider budget report failed")
    return value
