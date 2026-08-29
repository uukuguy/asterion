"""Pure canonical state reduction for long-running sessions and actions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import cast

from asterion.control.authority import (
    AdmissionDecision,
    action_proposal_digest,
)
from asterion.control.host import ControlEvent
from asterion.control.protocol import OPAQUE_ID


class ControlStateError(ValueError):
    """Raised when a control transition violates canonical state."""


TERMINAL_SESSION_STATES = frozenset(
    {"completed", "failed", "cancelled", "budget_limited"}
)
TERMINAL_ACTION_STATES = frozenset(
    {"rejected", "succeeded", "failed", "cancelled", "uncertain"}
)
SESSION_TRANSITIONS = {
    "created": frozenset({"running", "failed", "cancelled"}),
    "running": frozenset(
        {
            "paused",
            "recovery_required",
            "completed",
            "failed",
            "cancelled",
            "budget_limited",
        }
    ),
    "paused": frozenset(
        {
            "running",
            "recovery_required",
            "completed",
            "failed",
            "cancelled",
            "budget_limited",
        }
    ),
    "recovery_required": frozenset(
        {"running", "paused", "completed", "failed", "cancelled", "budget_limited"}
    ),
    "budget_limited": frozenset(),
}
GOAL_TRANSITIONS = {
    "active": frozenset(
        {
            "paused",
            "needs_input",
            "budget_limited",
            "completed",
            "failed",
            "cancelled",
        }
    ),
    "paused": frozenset({"active", "cancelled", "failed"}),
    "needs_input": frozenset({"active", "cancelled", "failed"}),
    "budget_limited": frozenset({"active", "cancelled", "failed"}),
}
SESSION_EVENT_STATUSES = {
    "session.running": "running",
    "session.paused": "paused",
    "session.recovery-required": "recovery_required",
    "session.completed": "completed",
    "session.failed": "failed",
    "session.cancelled": "cancelled",
    "session.budget-limited": "budget_limited",
}


@dataclass(frozen=True)
class ActionState:
    action_id: str
    idempotency_key: str
    kind: str
    authority_revision: int
    proposal_event_id: str
    proposal_digest: str
    status: str = "proposed"
    reason: str | None = None
    receipt_ref: str | None = None


@dataclass(frozen=True)
class ControlState:
    session_id: str
    generation: int
    next_sequence: int
    session_status: str | None
    goal_id: str | None
    goal_status: str | None
    authority_id: str | None
    authority_revision: int | None
    actions: Mapping[str, ActionState]
    terminal_event_id: str | None = None

    def __post_init__(self) -> None:
        if (
            OPAQUE_ID.fullmatch(self.session_id) is None
            or isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation < 1
            or isinstance(self.next_sequence, bool)
            or not isinstance(self.next_sequence, int)
            or self.next_sequence < 1
            or not isinstance(self.actions, Mapping)
            or any(
                not isinstance(action_id, str)
                or not isinstance(action, ActionState)
                or action_id != action.action_id
                for action_id, action in self.actions.items()
            )
        ):
            raise ControlStateError("control state is invalid")
        object.__setattr__(self, "actions", MappingProxyType(dict(self.actions)))

    @classmethod
    def empty(cls, session_id: str, *, generation: int) -> ControlState:
        return cls(
            session_id=session_id,
            generation=generation,
            next_sequence=1,
            session_status=None,
            goal_id=None,
            goal_status=None,
            authority_id=None,
            authority_revision=None,
            actions={},
        )


def reduce_control_event(state: ControlState, event: ControlEvent) -> ControlState:
    """Apply one validated provider event without mutating prior state."""

    if not isinstance(state, ControlState) or not isinstance(event, ControlEvent):
        raise ControlStateError("control event reduction is invalid")
    if (
        event.session_id != state.session_id
        or event.generation != state.generation
        or event.sequence != state.next_sequence
    ):
        raise ControlStateError("control event identity or sequence mismatches")
    if state.terminal_event_id is not None:
        raise ControlStateError("control session already has a terminal event")

    if event.type == "session.created":
        result = _create_session(state, event)
    elif event.type in SESSION_EVENT_STATUSES:
        result = _transition_session(state, event, SESSION_EVENT_STATUSES[event.type])
    elif event.type == "goal.updated":
        result = _transition_goal(state, event)
    elif event.type == "action.proposed":
        result = _propose_action(state, event)
    elif event.type == "fault.raised":
        if state.session_status not in {"running", "paused", "recovery_required"}:
            raise ControlStateError("fault.raised requires an active session")
        result = state
    elif event.type == "checkpoint.created":
        # A checkpoint is allowed to preserve an explicit operator pause.  Its
        # preceding checkpoint action is already restricted to that same
        # paused-only exception in ``_propose_action``.
        if state.session_status not in {"running", "paused"}:
            raise ControlStateError("checkpoint.created requires an active session")
        result = state
    else:
        _require_running_session(state, event.type)
        result = state
    return replace(result, next_sequence=state.next_sequence + 1)


def apply_action_admission(
    state: ControlState, decision: AdmissionDecision
) -> ControlState:
    if not isinstance(state, ControlState) or not isinstance(
        decision, AdmissionDecision
    ):
        raise ControlStateError("action admission is invalid")
    action = state.actions.get(decision.action_id)
    if (
        action is None
        or action.status != "proposed"
        or action.proposal_digest != decision.proposal_digest
        or state.authority_id != decision.authority_id
        or state.authority_revision != decision.authority_revision
    ):
        raise ControlStateError("action admission conflicts with proposal")
    updated = replace(
        action,
        status=decision.status,
        reason=decision.reason,
    )
    return _replace_action(state, updated)


def mark_action_running(state: ControlState, action_id: str) -> ControlState:
    action = _action(state, action_id)
    if (
        action.status != "admitted"
        or (
            state.session_status != "running"
            and not (
                state.session_status == "paused"
                and action.kind == "checkpoint.create"
            )
        )
    ):
        raise ControlStateError("action cannot enter running state")
    return _replace_action(state, replace(action, status="running"))


def apply_action_resolution(
    state: ControlState,
    action_id: str,
    status: str,
    *,
    receipt_ref: str | None = None,
) -> ControlState:
    action = _action(state, action_id)
    if status not in {
        "succeeded",
        "failed",
        "cancelled",
        "uncertain",
    }:
        raise ControlStateError("action resolution transition is invalid")
    if action.status != "running" and not (
        action.status == "admitted" and status == "cancelled" and receipt_ref is None
    ):
        raise ControlStateError("action resolution transition is invalid")
    if status == "succeeded" and not _valid_optional_receipt(
        receipt_ref, required=True
    ):
        raise ControlStateError("succeeded action receipt is invalid")
    if status != "succeeded" and not _valid_optional_receipt(receipt_ref):
        raise ControlStateError("action receipt is invalid")
    return _replace_action(
        state,
        replace(action, status=status, receipt_ref=receipt_ref),
    )


def reconcile_uncertain_action(
    state: ControlState,
    action_id: str,
    status: str,
    *,
    receipt_ref: str,
) -> ControlState:
    action = _action(state, action_id)
    if (
        action.status != "uncertain"
        or status not in {"succeeded", "failed", "cancelled"}
        or not _valid_optional_receipt(receipt_ref, required=True)
    ):
        raise ControlStateError("uncertain action reconciliation is invalid")
    return _replace_action(
        state,
        replace(action, status=status, receipt_ref=receipt_ref),
    )


def apply_authority_revision(state: ControlState, revision: int) -> ControlState:
    if (
        not isinstance(state, ControlState)
        or state.session_status != "budget_limited"
        or state.authority_revision is None
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision <= state.authority_revision
    ):
        raise ControlStateError("authority revision cannot resume session")
    return replace(
        state,
        generation=state.generation + 1,
        next_sequence=1,
        session_status="paused",
        authority_revision=revision,
        terminal_event_id=None,
    )


def _create_session(state: ControlState, event: ControlEvent) -> ControlState:
    if state.session_status is not None or state.next_sequence != 1:
        raise ControlStateError("control session creation is duplicated")
    payload = event.payload
    return replace(
        state,
        session_status="created",
        goal_id=str(payload["goal_id"]),
        goal_status="active",
        authority_id=str(payload["authority_id"]),
        authority_revision=cast(int, payload["authority_revision"]),
    )


def _transition_session(
    state: ControlState, event: ControlEvent, target: str
) -> ControlState:
    current = state.session_status
    if current is None or target not in SESSION_TRANSITIONS.get(current, frozenset()):
        raise ControlStateError("control session transition is invalid")
    if target == "completed" and state.goal_status != "completed":
        raise ControlStateError("control session completion lacks completed goal")
    active_actions = tuple(
        action
        for action in state.actions.values()
        if action.status not in TERMINAL_ACTION_STATES
    )
    if target in {"completed", "failed", "budget_limited"} and active_actions:
        raise ControlStateError("control session terminal has active actions")
    actions = state.actions
    if target == "cancelled":
        actions = {
            action_id: (
                action
                if action.status in TERMINAL_ACTION_STATES
                else replace(action, status="cancelled")
            )
            for action_id, action in state.actions.items()
        }
    return replace(
        state,
        session_status=target,
        actions=actions,
        terminal_event_id=(
            event.event_id if target in TERMINAL_SESSION_STATES else None
        ),
    )


def _transition_goal(state: ControlState, event: ControlEvent) -> ControlState:
    payload = event.payload
    if payload["goal_id"] != state.goal_id or state.goal_status is None:
        raise ControlStateError("control goal identity is invalid")
    target = str(payload["status"])
    if state.session_status not in {"running", "paused"} and not (
        state.session_status == "recovery_required"
        and target in {"completed", "failed", "cancelled", "budget_limited"}
    ):
        raise ControlStateError(f"{event.type} requires a running session")
    if target == state.goal_status:
        raise ControlStateError("control goal transition is duplicated")
    if target not in GOAL_TRANSITIONS.get(state.goal_status, frozenset()):
        raise ControlStateError("control goal transition is invalid")
    return replace(state, goal_status=target)


def _propose_action(state: ControlState, event: ControlEvent) -> ControlState:
    payload = event.payload
    if not (
        state.session_status == "running"
        or (
            state.session_status == "paused"
            and payload.get("kind") == "checkpoint.create"
        )
    ):
        raise ControlStateError(f"{event.type} requires a running session")
    action_id = str(payload["action_id"])
    idempotency_key = str(payload["idempotency_key"])
    if (
        action_id in state.actions
        or any(
            action.idempotency_key == idempotency_key
            for action in state.actions.values()
        )
        or payload["authority_revision"] != state.authority_revision
    ):
        raise ControlStateError("control action proposal conflicts")
    action = ActionState(
        action_id=action_id,
        idempotency_key=idempotency_key,
        kind=str(payload["kind"]),
        authority_revision=cast(int, payload["authority_revision"]),
        proposal_event_id=event.event_id,
        proposal_digest=action_proposal_digest(event),
    )
    return _replace_action(state, action)


def _require_running_session(state: ControlState, event_type: str) -> None:
    if state.session_status != "running":
        raise ControlStateError(f"{event_type} requires a running session")


def _action(state: ControlState, action_id: str) -> ActionState:
    if not isinstance(state, ControlState):
        raise ControlStateError("control action state is invalid")
    action = state.actions.get(action_id)
    if action is None:
        raise ControlStateError("control action is unavailable")
    return action


def _replace_action(state: ControlState, action: ActionState) -> ControlState:
    actions = dict(state.actions)
    actions[action.action_id] = action
    return replace(state, actions=actions)


def mark_session_recovery_required(state: ControlState) -> ControlState:
    """Fence one non-terminal session after a durable uncertain operation."""

    if not isinstance(state, ControlState):
        raise ControlStateError("session recovery fence is invalid")
    if state.session_status in TERMINAL_SESSION_STATES:
        return state
    return replace(state, session_status="recovery_required")


def _valid_optional_receipt(value: str | None, *, required: bool = False) -> bool:
    if value is None:
        return not required
    return OPAQUE_ID.fullmatch(value) is not None
