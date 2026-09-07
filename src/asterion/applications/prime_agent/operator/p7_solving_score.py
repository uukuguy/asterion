"""Pinned official partial-game score projection for P7a."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import math
from .p7_solving_workload import (
    P7_SOLVING_ACTION_CAP,
    P7_SOLVING_ARC_AGI_WHEEL_SHA256,
    P7_SOLVING_BASELINE_ACTIONS,
    P7_SOLVING_GAME_ID,
)


class P7SolvingScoreError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 solving score is unavailable")


def _official_calculator() -> object:
    try:
        from arc_agi.scorecard import EnvironmentScoreCalculator

        return EnvironmentScoreCalculator()
    except BaseException:
        raise P7SolvingScoreError() from None


def official_p7_partial_score(
    action_count: object,
    *,
    arc_agi_wheel_sha256: object = P7_SOLVING_ARC_AGI_WHEEL_SHA256,
    baseline_actions: object = P7_SOLVING_BASELINE_ACTIONS,
) -> str:
    """Return the locked calculator's one-completed-level score."""

    if (
        type(action_count) is not int
        or not 1 <= action_count <= P7_SOLVING_ACTION_CAP
        or type(arc_agi_wheel_sha256) is not str
        or arc_agi_wheel_sha256 != P7_SOLVING_ARC_AGI_WHEEL_SHA256
        or type(baseline_actions) is not tuple
        or baseline_actions != P7_SOLVING_BASELINE_ACTIONS
        or any(type(item) is not int for item in baseline_actions)
    ):
        raise P7SolvingScoreError()
    try:
        calculator = _official_calculator()
        add_level = getattr(calculator, "add_level")
        for index, baseline in enumerate(P7_SOLVING_BASELINE_ACTIONS, 1):
            add_level(
                index,
                index == 1,
                action_count if index == 1 else 0,
                baseline,
                P7_SOLVING_GAME_ID,
            )
        score = getattr(calculator.to_score(), "score")
        if (
            type(score) not in (int, float)
            or not math.isfinite(score)
            or not 0 <= score <= 100
        ):
            raise ValueError
        value = Decimal(str(score)).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_EVEN
        )
        if not value.is_finite() or not Decimal("0") <= value <= Decimal("100"):
            raise ValueError
        return format(value, ".6f")
    except (AttributeError, InvalidOperation, TypeError, ValueError, ArithmeticError):
        raise P7SolvingScoreError() from None


__all__ = (
    "P7SolvingScoreError",
    "P7_SOLVING_ARC_AGI_WHEEL_SHA256",
    "P7_SOLVING_BASELINE_ACTIONS",
    "official_p7_partial_score",
)
