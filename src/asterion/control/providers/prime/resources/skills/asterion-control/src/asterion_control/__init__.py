"""Model-facing, host-authorized Asterion control operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from asterion_control._protocol import (
    AsterionControlError as AsterionControlError,
    AsterionControlUncertainError as AsterionControlUncertainError,
    effect_payload,
    exchange,
    require_opaque_id,
    require_text,
    validate_identifiers,
    validate_target,
)


__all__ = [
    "portfolio",
    "remaining_budget",
    "invoke_application",
    "spawn_child",
    "message_child",
    "cancel_child",
    "request_checkpoint",
    "complete_goal",
    "fail_goal",
    "action_status",
]


async def portfolio() -> object:
    return await exchange("portfolio.get", {}, effectful=False)


async def remaining_budget() -> object:
    return await exchange("budget.get", {}, effectful=False)


async def invoke_application(
    *,
    target: Mapping[str, str],
    input_text: str,
    idempotency_key: str,
    budget: Mapping[str, int],
    expected_artifacts: Sequence[str] = (),
) -> object:
    payload = effect_payload(
        idempotency_key=idempotency_key,
        budget=budget,
        fields={
            "target": validate_target(target),
            "input_text": require_text(input_text, "input_text"),
            "expected_artifacts": validate_identifiers(
                expected_artifacts, "expected_artifacts"
            ),
        },
    )
    return await exchange("application.invoke", payload, effectful=True)


async def spawn_child(
    *,
    child_id: str,
    goal_text: str,
    idempotency_key: str,
    budget: Mapping[str, int],
) -> object:
    payload = effect_payload(
        idempotency_key=idempotency_key,
        budget=budget,
        fields={
            "child_id": require_opaque_id(child_id, "child_id"),
            "goal_text": require_text(goal_text, "goal_text"),
        },
    )
    return await exchange("child.spawn", payload, effectful=True)


async def message_child(
    *,
    child_id: str,
    message: str,
    idempotency_key: str,
    budget: Mapping[str, int],
) -> object:
    payload = effect_payload(
        idempotency_key=idempotency_key,
        budget=budget,
        fields={
            "child_id": require_opaque_id(child_id, "child_id"),
            "message": require_text(message, "message"),
        },
    )
    return await exchange("child.message", payload, effectful=True)


async def cancel_child(
    *,
    child_id: str,
    idempotency_key: str,
    budget: Mapping[str, int],
) -> object:
    payload = effect_payload(
        idempotency_key=idempotency_key,
        budget=budget,
        fields={"child_id": require_opaque_id(child_id, "child_id")},
    )
    return await exchange("child.cancel", payload, effectful=True)


async def request_checkpoint(
    *,
    checkpoint_id: str,
    idempotency_key: str,
    budget: Mapping[str, int],
) -> object:
    payload = effect_payload(
        idempotency_key=idempotency_key,
        budget=budget,
        fields={
            "checkpoint_id": require_opaque_id(checkpoint_id, "checkpoint_id")
        },
    )
    return await exchange("checkpoint.request", payload, effectful=True)


async def complete_goal(
    *,
    goal_id: str,
    summary: str,
    idempotency_key: str,
    budget: Mapping[str, int],
) -> object:
    payload = effect_payload(
        idempotency_key=idempotency_key,
        budget=budget,
        fields={
            "goal_id": require_opaque_id(goal_id, "goal_id"),
            "summary": require_text(summary, "summary"),
        },
    )
    return await exchange("goal.complete", payload, effectful=True)


async def fail_goal(
    *,
    goal_id: str,
    reason: str,
    idempotency_key: str,
    budget: Mapping[str, int],
) -> object:
    payload = effect_payload(
        idempotency_key=idempotency_key,
        budget=budget,
        fields={
            "goal_id": require_opaque_id(goal_id, "goal_id"),
            "reason": require_text(reason, "reason"),
        },
    )
    return await exchange("goal.fail", payload, effectful=True)


async def action_status(*, action_id: str) -> object:
    return await exchange(
        "action.status",
        {"action_id": require_opaque_id(action_id, "action_id")},
        effectful=False,
    )
