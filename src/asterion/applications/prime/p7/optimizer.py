"""Finite, game-neutral search over independently replayed action routes."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import math
import time
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PlannerAction:
    name: str
    data: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class RouteResult:
    success: bool
    action_count: int
    terminal_state: str
    identity: tuple[str, int]


class ReplayOracle(Protocol):
    def replay(self, actions: tuple[PlannerAction, ...]) -> RouteResult: ...


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    actions: tuple[PlannerAction, ...]
    replay: RouteResult
    removed_indices: tuple[int, ...]
    candidates_replayed: int
    elapsed_seconds: float = 0.0
    timed_out: bool = False


def optimize_route(
    route: tuple[PlannerAction, ...],
    oracle: ReplayOracle,
    *,
    identity: tuple[str, int],
    max_removed: int = 3,
    candidate_budget: int = 128,
    replacements: tuple[PlannerAction, ...] = (),
    time_budget_seconds: float | None = None,
) -> RouteCandidate:
    """Keep the shortest verified edit found within a finite replay budget.

    The baseline consumes one replay. Every candidate is replayed from scratch
    by the caller's oracle; no live broker or game instance is shared here.
    """

    if (
        type(route) is not tuple
        or any(type(action) is not PlannerAction for action in route)
        or type(identity) is not tuple or len(identity) != 2
        or type(identity[0]) is not str or type(identity[1]) is not int
        or type(max_removed) is not int or max_removed < 0
        or type(candidate_budget) is not int or candidate_budget < 1
        or type(replacements) is not tuple
        or any(type(action) is not PlannerAction for action in replacements)
        or (
            time_budget_seconds is not None
            and (
                type(time_budget_seconds) not in (int, float)
                or isinstance(time_budget_seconds, bool)
                or not math.isfinite(time_budget_seconds)
                or time_budget_seconds < 0
            )
        )
    ):
        raise ValueError("route optimization is unavailable")

    started_at = time.monotonic()

    def valid(result: RouteResult, actions: tuple[PlannerAction, ...]) -> bool:
        return (
            type(result) is RouteResult
            and result.success is True
            and type(result.action_count) is int
            and result.action_count == len(actions)
            and result.identity == identity
            and type(result.terminal_state) is str
            and bool(result.terminal_state)
        )

    baseline = oracle.replay(route)
    if not valid(baseline, route):
        raise ValueError("verified baseline is unavailable")
    best = RouteCandidate(route, baseline, (), 1)
    replayed = 1
    seen = {route}

    timeout_elapsed: float | None = None

    def timed_out() -> bool:
        nonlocal timeout_elapsed
        if time_budget_seconds is None:
            return False
        elapsed = max(0.0, time.monotonic() - started_at)
        if elapsed >= time_budget_seconds:
            timeout_elapsed = elapsed
            return True
        return False

    if timed_out():
        return RouteCandidate(
            best.actions,
            best.replay,
            best.removed_indices,
            replayed,
            timeout_elapsed if timeout_elapsed is not None else 0.0,
            True,
        )

    def candidates():
        for count in range(1, min(max_removed, len(route)) + 1):
            for removed in combinations(range(len(route)), count):
                excluded = set(removed)
                yield tuple(action for index, action in enumerate(route) if index not in excluded), removed
        # Replacement edits may be combined with deletion edits.  This lets a
        # harmless action be removed while a neighboring action is corrected,
        # still within the same finite candidate budget.
        for count in range(0, min(max_removed, len(route) - 1) + 1):
            for removed in combinations(range(len(route)), count):
                excluded = set(removed)
                remaining = tuple(
                    (index, action)
                    for index, action in enumerate(route)
                    if index not in excluded
                )
                for position, (index, original) in enumerate(remaining):
                    for action in replacements:
                        if action != original:
                            candidate = tuple(
                                action if offset == position else item
                                for offset, (_source, item) in enumerate(remaining)
                            )
                            yield candidate, removed

    for candidate, removed in candidates():
        if replayed >= candidate_budget:
            break
        if timed_out():
            break
        if candidate in seen:
            continue
        seen.add(candidate)
        replay = oracle.replay(candidate)
        replayed += 1
        if valid(replay, candidate) and len(candidate) < len(best.actions):
            best = RouteCandidate(candidate, replay, removed, replayed)
    elapsed_seconds = (
        timeout_elapsed
        if timeout_elapsed is not None
        else max(0.0, time.monotonic() - started_at)
    )
    return RouteCandidate(
        best.actions,
        best.replay,
        best.removed_indices,
        replayed,
        elapsed_seconds,
        time_budget_seconds is not None and elapsed_seconds >= time_budget_seconds,
    )


__all__ = ("PlannerAction", "ReplayOracle", "RouteCandidate", "RouteResult", "optimize_route")
