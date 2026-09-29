"""Finite, game-neutral search over independently replayed action routes."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
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


def optimize_route(
    route: tuple[PlannerAction, ...],
    oracle: ReplayOracle,
    *,
    identity: tuple[str, int],
    max_removed: int = 3,
    candidate_budget: int = 128,
    replacements: tuple[PlannerAction, ...] = (),
) -> RouteCandidate:
    """Keep the shortest verified edit found within a finite replay budget.

    The baseline consumes one replay. Every candidate is replayed from scratch
    by the caller's oracle; no live broker or game instance is shared here.
    """

    if (
        type(route) is not tuple or not route
        or any(type(action) is not PlannerAction for action in route)
        or type(identity) is not tuple or len(identity) != 2
        or type(identity[0]) is not str or type(identity[1]) is not int
        or type(max_removed) is not int or max_removed < 0
        or type(candidate_budget) is not int or candidate_budget < 1
        or type(replacements) is not tuple
        or any(type(action) is not PlannerAction for action in replacements)
    ):
        raise ValueError("route optimization is unavailable")

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
        if candidate in seen:
            continue
        seen.add(candidate)
        replay = oracle.replay(candidate)
        replayed += 1
        if valid(replay, candidate) and len(candidate) < len(best.actions):
            best = RouteCandidate(candidate, replay, removed, replayed)
    return RouteCandidate(best.actions, best.replay, best.removed_indices, replayed)


__all__ = ("PlannerAction", "ReplayOracle", "RouteCandidate", "RouteResult", "optimize_route")
