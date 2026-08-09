"""Host orchestration for control commands, events and action admission."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from asterion.control.authority import AuthorityLedger
from asterion.control.host import (
    ControlCommand,
    ControlEvent,
    ControlPlaneClient,
    EventCursor,
)
from asterion.control.journal import (
    CanonicalJournal,
    JournalConflictError,
    JournalRecord,
)
from asterion.control.state import (
    ControlState,
    ControlStateError,
    apply_action_admission,
    reduce_control_event,
)
from asterion.control.system import AgentSystemPlan


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
    ) -> None:
        if (
            not isinstance(plan, AgentSystemPlan)
            or not isinstance(authority, AuthorityLedger)
            or not callable(clock_ms)
            or not callable(getattr(action_executor, "execute", None))
            or client.manifest != plan.control_binding.manifest
            or journal.position != 0
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
        self._state = ControlState.empty(session_id, generation=generation)
        system = self._journal.append(
            0,
            JournalRecord.system_bound(
                system_id=plan.system_id,
                system_version=plan.version,
            ),
        )
        self._journal.append(
            system.position,
            JournalRecord.authority_bound(
                authority_id=authority.envelope.authority_id,
                authority_revision=authority.envelope.revision,
            ),
        )

    async def dispatch(self, command: ControlCommand) -> None:
        if (
            not isinstance(command, ControlCommand)
            or command.session_id != self._state.session_id
            or command.authority_revision != self._authority.envelope.revision
        ):
            raise ControlHostError("control command authority or identity mismatches")
        try:
            self._journal.accept_command(
                command, expected_position=self._journal.position
            )
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
            journal_position=self._journal.position,
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
            self._journal.accept_event(
                event, expected_position=self._journal.position
            )
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
            self._journal.append(
                self._journal.position,
                JournalRecord.action_decided(
                    action_id=decision.action_id,
                    authority_revision=decision.authority_revision,
                    status=decision.status,
                    reason=decision.reason,
                    proposal_digest=decision.proposal_digest,
                ),
            )
            self._state = apply_action_admission(self._state, decision)
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
