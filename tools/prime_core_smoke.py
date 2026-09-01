"""Closed, body-free result contract for the bounded Prime Core smoke."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class PrimeCoreSmokeResult:
    terminal: str
    terminal_count: int
    root_model_selected: bool
    generated_program_admitted: bool
    application_succeeded: bool
    oracle_passed: bool
    child_target_count: int
    children_started: int
    children_completed: int
    children_deleted: int
    message_delivered: bool
    message_causality_complete: bool
    detached_while_active: bool
    reattached: bool
    replay_contiguous: bool
    work_continued_after_attach: bool
    recursion_policy_enforced: bool
    control_event_sequence_contiguous: bool
    observation_health: str
    observation_gap_count: int
    cleanup_complete: bool
    privacy_checks_passed: bool
    within_budget: bool


def verify_prime_core_smoke_result(
    result: PrimeCoreSmokeResult,
) -> Mapping[str, object]:
    """Project one exact, public-safe Core receipt and fail closed."""

    if not isinstance(result, PrimeCoreSmokeResult):
        raise TypeError("Prime Core smoke result is invalid")
    values = asdict(result)
    required = (
        result.terminal == "completed",
        result.terminal_count == 1,
        result.root_model_selected,
        result.generated_program_admitted,
        result.application_succeeded,
        result.oracle_passed,
        result.child_target_count == 2,
        result.children_started == result.child_target_count,
        result.children_completed == result.child_target_count,
        result.children_deleted == result.child_target_count,
        result.message_delivered,
        result.message_causality_complete,
        result.detached_while_active,
        result.reattached,
        result.replay_contiguous,
        result.work_continued_after_attach,
        result.recursion_policy_enforced,
        result.control_event_sequence_contiguous,
        result.observation_health == "healthy",
        result.observation_gap_count == 0,
        result.cleanup_complete,
        result.privacy_checks_passed,
        result.within_budget,
    )
    return MappingProxyType({
        "format": "asterion.prime-core-smoke-receipt/v1",
        **values,
        "status": "PASS" if all(required) else "External-limited",
    })
