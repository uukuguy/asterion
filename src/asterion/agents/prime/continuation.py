"""Domain-neutral admission for finite, naturally continued research."""

from dataclasses import dataclass
import math
import time

from asterion.runtime.host import CancellationSignal


AUTONOMOUS_RESEARCH_GUIDANCE = (
    "Choose the research form that helps the task: concise notes, hypotheses, "
    "local experiments, or executable models when useful. Prioritize actual "
    "feedback over assumptions and revise contradicted claims. Optionally retain "
    "durable facts, assumptions, open questions, and the next useful step in the "
    "application's supported workspace so natural continuation can resume from evidence."
)

RESOURCE_AWARE_RESEARCH_GUIDANCE = (
    "Both progress and investigation can provide useful information. As resources "
    "and evidence change, weigh the expected value of a next decision against its "
    "research, failure, reversal and opportunity costs. Choose your own balance "
    "using dated resource facts and actual feedback; unknown work costs remain unknown."
)


@dataclass(frozen=True, slots=True)
class PrimeContinuationBudget:
    """One trusted absolute deadline and zero-based natural-round allowance."""

    deadline_monotonic: float
    max_natural_rounds: int

    def __post_init__(self) -> None:
        if (type(self.deadline_monotonic) not in (int, float)
                or not math.isfinite(self.deadline_monotonic)
                or type(self.max_natural_rounds) is not int
                or self.max_natural_rounds < 1):
            raise ValueError("Prime continuation budget is invalid")


@dataclass(frozen=True, slots=True)
class PrimeContinuationController:
    """An admission hook, without dispatch, persistence or budget renewal."""

    budget: PrimeContinuationBudget

    def __post_init__(self) -> None:
        if type(self.budget) is not PrimeContinuationBudget:
            raise ValueError("Prime continuation budget is invalid")

    async def admit(self, round_index: int, signal: CancellationSignal) -> bool:
        if type(round_index) is not int or type(signal.cancelled) is not bool:
            raise ValueError("Prime continuation admission is invalid")
        return (not signal.cancelled
                and 0 <= round_index < self.budget.max_natural_rounds
                and time.monotonic() < self.budget.deadline_monotonic)

    def snapshot(self) -> dict[str, int | float]:
        """Return copied metadata; observing a budget cannot extend it."""
        return {
            "deadline_monotonic": self.budget.deadline_monotonic,
            "max_natural_rounds": self.budget.max_natural_rounds,
            "wall_time_remaining_seconds": max(0.0, self.budget.deadline_monotonic - time.monotonic()),
        }


__all__ = (
    "AUTONOMOUS_RESEARCH_GUIDANCE",
    "RESOURCE_AWARE_RESEARCH_GUIDANCE",
    "PrimeContinuationBudget",
    "PrimeContinuationController",
)
