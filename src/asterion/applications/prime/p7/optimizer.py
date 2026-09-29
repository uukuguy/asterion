"""Finite, game-neutral search over independently replayed action routes."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import difflib
import hashlib
import json
import math
import time
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PlannerAction:
    name: str
    data: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class ObservationWitness:
    kind: str
    action_index: int
    observation_sha256: str
    levels_completed: int
    state: str


@dataclass(frozen=True, slots=True)
class RouteResult:
    success: bool
    action_count: int
    terminal_state: str
    identity: tuple[str, int]
    observation_witness: tuple[ObservationWitness, ...] = ()


@dataclass(frozen=True, slots=True)
class RouteCompressionProof:
    kind: str
    source_start: int
    source_end: int
    before: tuple[PlannerAction, ...]
    after: tuple[PlannerAction, ...]
    removed_indices: tuple[int, ...]
    identity: tuple[str, int]
    baseline_action_count: int
    candidate_action_count: int
    source_digest: str
    candidate_digest: str
    prefix_digest: str
    suffix_digest: str
    terminal_state: str
    baseline_witness: tuple[ObservationWitness, ...] = ()
    candidate_witness: tuple[ObservationWitness, ...] = ()
    target_level: int = 0
    warmup_digest: str = ""


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
    proofs: tuple[RouteCompressionProof, ...] = ()


def _route_digest(actions: tuple[PlannerAction, ...]) -> str:
    encoded = [
        {"name": action.name, "data": dict(action.data)} for action in actions
    ]
    return "sha256:" + hashlib.sha256(
        json.dumps(encoded, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _compression_proof(
    baseline: tuple[PlannerAction, ...],
    candidate: tuple[PlannerAction, ...],
    baseline_result: RouteResult,
    replay: RouteResult,
    identity: tuple[str, int],
    *,
    target_level: int = 0,
    warmup_digest: str = "",
) -> RouteCompressionProof | None:
    matcher = difflib.SequenceMatcher(a=baseline, b=candidate, autojunk=False)
    opcodes = matcher.get_opcodes()
    changed = [opcode for opcode in opcodes if opcode[0] != "equal"]
    if not changed:
        return None
    removed = tuple(
        index
        for tag, start, end, _new_start, _new_end in changed
        if tag in {"delete", "replace"}
        for index in range(start, end)
    )
    if not removed:
        return None
    spans = [(start, end) for _tag, start, end, _ns, _ne in changed]
    kind = "delete_span" if all(tag == "delete" for tag, *_rest in changed) and len(spans) == 1 else "composite"
    first_start = min(start for start, _end in spans)
    last_end = max(end for _start, end in spans)
    prefix = baseline[:first_start]
    suffix = baseline[last_end:]
    return RouteCompressionProof(
        kind=kind,
        source_start=first_start,
        source_end=last_end,
        before=baseline[first_start:last_end],
        after=tuple(
            action
            for _tag, start, end, new_start, new_end in changed
            for action in candidate[new_start:new_end]
        ),
        removed_indices=removed,
        identity=identity,
        baseline_action_count=len(baseline),
        candidate_action_count=len(candidate),
        source_digest=_route_digest(baseline),
        candidate_digest=_route_digest(candidate),
        prefix_digest=_route_digest(prefix),
        suffix_digest=_route_digest(suffix),
        terminal_state=replay.terminal_state,
        baseline_witness=baseline_result.observation_witness,
        candidate_witness=replay.observation_witness,
        target_level=target_level,
        warmup_digest=warmup_digest,
    )


def optimize_route(
    route: tuple[PlannerAction, ...],
    oracle: ReplayOracle,
    *,
    identity: tuple[str, int],
    max_removed: int = 3,
    candidate_budget: int = 128,
    replacements: tuple[PlannerAction, ...] = (),
    time_budget_seconds: float | None = None,
    target_level: int = 0,
    warmup_digest: str = "",
    preserve_terminal_observation: bool = False,
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
        or type(preserve_terminal_observation) is not bool
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

    def structurally_valid(result: RouteResult, actions: tuple[PlannerAction, ...]) -> bool:
        return (
            type(result) is RouteResult
            and type(result.action_count) is int
            and result.action_count == len(actions)
            and result.identity == identity
            and type(result.terminal_state) is str
            and bool(result.terminal_state)
        )

    def valid(
        result: RouteResult,
        actions: tuple[PlannerAction, ...],
        baseline_result: RouteResult | None = None,
    ) -> bool:
        if not structurally_valid(result, actions):
            return False
        if not preserve_terminal_observation:
            return result.success is True
        if not result.observation_witness:
            return False
        if baseline_result is None or not baseline_result.observation_witness:
            return True
        expected = baseline_result.observation_witness[-1]
        actual = result.observation_witness[-1]
        return (
            actual.observation_sha256 == expected.observation_sha256
            and actual.levels_completed == expected.levels_completed
            and actual.state == expected.state
        )

    baseline = oracle.replay(route)
    if not valid(baseline, route):
        raise ValueError("verified baseline is unavailable")
    best = RouteCandidate(route, baseline, (), 1)
    best_proofs: tuple[RouteCompressionProof, ...] = ()
    replayed = 1
    seen = {route}

    timeout_elapsed: float | None = None
    budget_exhausted = False

    def timed_out() -> bool:
        nonlocal timeout_elapsed
        if time_budget_seconds is None:
            return False
        elapsed = max(0.0, time.monotonic() - started_at)
        if elapsed >= time_budget_seconds:
            timeout_elapsed = elapsed
            return True
        return False

    if replayed < candidate_budget and timed_out():
        budget_exhausted = True
        return RouteCandidate(
            best.actions,
            best.replay,
            best.removed_indices,
            replayed,
            timeout_elapsed if timeout_elapsed is not None else 0.0,
            True,
            best_proofs,
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
        # Adjacent reorder combined with one deletion.  This is deliberately
        # structural: the replay oracle, not action names, decides validity.
        for index in range(len(route) - 1):
            swapped = list(route)
            swapped[index], swapped[index + 1] = swapped[index + 1], swapped[index]
            for removed in combinations(
                (item for item in range(len(route)) if item not in {index, index + 1}),
                1,
            ):
                candidate = tuple(
                    action for position, action in enumerate(swapped) if position not in removed
                )
                yield candidate, removed

    for candidate, removed in candidates():
        if replayed >= candidate_budget:
            break
        if timed_out():
            budget_exhausted = True
            break
        if candidate in seen:
            continue
        seen.add(candidate)
        replay = oracle.replay(candidate)
        replayed += 1
        if valid(replay, candidate, baseline) and len(candidate) < len(best.actions):
            best = RouteCandidate(candidate, replay, removed, replayed)
            proof = _compression_proof(
                route, candidate, baseline, replay, identity,
                target_level=target_level, warmup_digest=warmup_digest,
            )
            best_proofs = () if proof is None else (proof,)
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
        budget_exhausted,
        best_proofs,
    )


def optimize_partial_route(
    route: tuple[PlannerAction, ...],
    oracle: ReplayOracle,
    *,
    identity: tuple[str, int],
    max_removed: int = 3,
    candidate_budget: int = 128,
    replacements: tuple[PlannerAction, ...] = (),
    time_budget_seconds: float | None = None,
    target_level: int = 0,
    warmup_digest: str = "",
) -> RouteCandidate:
    """Shorten an incomplete route only when its terminal observation is preserved."""

    return optimize_route(
        route,
        oracle,
        identity=identity,
        max_removed=max_removed,
        candidate_budget=candidate_budget,
        replacements=replacements,
        time_budget_seconds=time_budget_seconds,
        target_level=target_level,
        warmup_digest=warmup_digest,
        preserve_terminal_observation=True,
    )


__all__ = (
    "ObservationWitness", "PlannerAction", "ReplayOracle", "RouteCandidate",
    "RouteCompressionProof", "RouteResult", "optimize_partial_route", "optimize_route",
)
