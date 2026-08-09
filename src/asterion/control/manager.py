"""Host orchestration for control commands, events and action admission."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from asterion.control.authority import AuthorityLedger, BudgetUsage
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
from asterion.control.state import (
    ControlState,
    ControlStateError,
    apply_action_admission,
    reduce_control_event,
)
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
    async def execute(self, proposal: ControlEvent) -> object:
        """Execute one already-admitted action in a later integration phase."""


@dataclass(frozen=True)
class ControlHostSnapshot:
    state: ControlState
    journal_position: int
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
        pathlight: PathlightRecorder = NOOP_PATHLIGHT_RECORDER,
    ) -> None:
        if (
            not isinstance(plan, AgentSystemPlan)
            or not isinstance(authority, AuthorityLedger)
            or not callable(clock_ms)
            or not callable(getattr(action_executor, "execute", None))
            or client.manifest != plan.control_binding.manifest
            or authority.usage != BudgetUsage.zero()
            or authority.reserved_action_ids
            or authority.receipts
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
            else:
                entries = self._journal.replay(JournalCursor(0))
                if len(entries) != position:
                    raise JournalConflictError("control journal changed")
                recovered = recover_control_host_state(entries, authority.envelope)
                system_payload = entries[0].record.payload
                authority_payload = entries[1].record.payload
                if (
                    system_payload.get("system_id") != plan.system_id
                    or system_payload.get("system_version") != plan.version
                    or authority_payload.get("authority_id")
                    != authority.envelope.authority_id
                    or recovered.state.session_id != session_id
                    or recovered.state.generation != generation
                    or recovered.state.authority_id
                    != authority.envelope.authority_id
                    or recovered.state.authority_revision
                    != authority.envelope.revision
                    or recovered.journal_position != position
                ):
                    raise JournalConflictError("control journal identity conflicts")
                self._state = recovered.state
                self._authority = recovered.authority
                authority_entry = entries[-1]
                if self._journal.position != position:
                    raise JournalConflictError("control journal changed")
        except (JournalConflictError, TypeError, ValueError):
            raise ControlHostError("control host recovery failed") from None
        self._journal_position = authority_entry.position
        self._evidence.start_system(
            plan,
            session_id=session_id,
            generation=generation,
            authority=authority.envelope,
            journal_position=self._journal_position,
            timestamp_ns=self._clock_ms() * 1_000_000,
        )

    async def dispatch(self, command: ControlCommand) -> None:
        if (
            not isinstance(command, ControlCommand)
            or command.session_id != self._state.session_id
            or command.authority_revision != self._authority.envelope.revision
        ):
            raise ControlHostError("control command authority or identity mismatches")
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

    async def pump(self, *, until_terminal: bool = False) -> None:
        cursor = EventCursor(
            generation=self._state.generation,
            sequence=self._state.next_sequence - 1,
        )
        try:
            events = self._client.events(cursor)
            async for event in events:
                await self._accept_event(event)
                if until_terminal and self._state.terminal_event_id is not None:
                    break
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
            evidence_gaps=self._evidence.gaps,
        )

    async def close(self) -> None:
        try:
            await self._client.close()
        except Exception:
            raise ControlHostTransportError(
                "control provider close is uncertain"
            ) from None

    async def _accept_event(self, event: ControlEvent) -> None:
        if not isinstance(event, ControlEvent):
            raise ControlHostError("control provider event is invalid")
        try:
            entry = self._journal.accept_event(
                event, expected_position=self._journal_position
            )
            self._journal_position = max(self._journal_position, entry.position)
        except (JournalConflictError, TypeError, ValueError):
            raise ControlHostError("control provider event journal failed") from None
        if (
            event.generation < self._state.generation
            or (
                event.generation == self._state.generation
                and event.sequence < self._state.next_sequence
            )
        ):
            return
        try:
            reduced = reduce_control_event(self._state, event)
        except ControlStateError:
            raise ControlHostError("control provider event transition failed") from None
        self._state = reduced
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
        await self.dispatch(command)
