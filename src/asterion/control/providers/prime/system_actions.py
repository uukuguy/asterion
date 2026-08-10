"""Prime-backed execution of provider system action proposals."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Protocol

from asterion.control.authority import BudgetUsage
from asterion.control.execution import ActionExecutionFailure, ActionExecutionReceipt
from asterion.control.host import ControlCommand, ControlEvent
from asterion.runtime.host import CancellationSignal


class PrimeSystemCommandClient(Protocol):
    async def send(self, command: ControlCommand) -> None:
        """Accept one exact provider command."""


class PrimeSystemActionService:
    """Execute checkpoint and goal intents without application discovery."""

    def __init__(self, client: PrimeSystemCommandClient) -> None:
        if not callable(getattr(client, "send", None)):
            raise ValueError("Prime system action service is invalid")
        self._client = client

    async def execute(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt:
        action_id, authority_revision, kind, target = _proposal_fields(proposal)
        _raise_if_cancelled(action_id, signal)
        if kind == "checkpoint.create":
            checkpoint_id = _target_id(target, "checkpoint", "checkpoint_id")
            command = ControlCommand(
                command_id=f"system-checkpoint-{action_id}",
                session_id=proposal.session_id,
                authority_revision=authority_revision,
                type="checkpoint.request",
                payload={"checkpoint_id": checkpoint_id},
            )
            try:
                await self._client.send(command)
            except Exception:
                raise ActionExecutionFailure(
                    "uncertain", "checkpoint-progress-unknown", None
                ) from None
        elif kind in {"goal.complete", "goal.fail"}:
            _target_id(target, "goal", "goal_id")
        else:
            raise _invalid(proposal)
        return ActionExecutionReceipt(
            action_id=action_id,
            receipt_ref=f"system-{kind}-{action_id}",
            usage=BudgetUsage.zero(),
            artifact_ids=(),
            media_types=(),
        )


def _proposal_fields(
    proposal: object,
) -> tuple[str, int, str, Mapping[str, object]]:
    try:
        if not isinstance(proposal, ControlEvent) or proposal.type != "action.proposed":
            raise TypeError
        action_id = proposal.payload["action_id"]
        authority_revision = proposal.payload["authority_revision"]
        kind = proposal.payload["kind"]
        target = proposal.payload["target"]
        if (
            not isinstance(action_id, str)
            or isinstance(authority_revision, bool)
            or not isinstance(authority_revision, int)
            or not isinstance(kind, str)
            or not isinstance(target, Mapping)
        ):
            raise TypeError
        return action_id, authority_revision, kind, target
    except (KeyError, TypeError, ValueError):
        raise _invalid(proposal) from None


def _target_id(target: Mapping[str, object], kind: str, field: str) -> str:
    value = target.get(field)
    if set(target) != {"kind", field} or target.get("kind") != kind or not isinstance(
        value, str
    ):
        raise ActionExecutionFailure(
            "failed", "system-target-mismatch", _failure_ref("target")
        )
    return value


def _raise_if_cancelled(action_id: str, signal: CancellationSignal) -> None:
    try:
        cancelled = signal.cancelled
    except Exception:
        raise ActionExecutionFailure(
            "failed", "cancellation-state-unavailable", _failure_ref(action_id)
        ) from None
    if not isinstance(cancelled, bool):
        raise ActionExecutionFailure(
            "failed", "cancellation-state-unavailable", _failure_ref(action_id)
        )
    if cancelled:
        raise ActionExecutionFailure("cancelled", "cancelled", None)


def _invalid(proposal: object) -> ActionExecutionFailure:
    action_id = "unknown"
    if isinstance(proposal, ControlEvent):
        candidate = proposal.payload.get("action_id")
        if isinstance(candidate, str):
            action_id = candidate
    return ActionExecutionFailure(
        "failed", "invalid-system-proposal", _failure_ref(action_id)
    )


def _failure_ref(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"system-failure-{digest[:32]}"
