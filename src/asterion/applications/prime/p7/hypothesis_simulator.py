"""Bounded counterfactual search over P7 transition candidates.

This module is deliberately a planning-only layer.  It accepts confirmed
``MechanismSpec`` objects and weaker candidates produced by experience
induction, simulates each candidate in an immutable ``SimState``, and keeps
the resulting branches separate when they disagree.  History records and
``TransitionRule`` objects are evidence ledgers; they do not contain enough
state transition information to be treated as a simulator.

No function in this module dispatches an action or grants execution
authority.  A returned path is a counterfactual prediction that a caller may
inspect, compare, or subsequently verify through a separate checked-action
boundary.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Mapping, Sequence

from .experience_induction import EffectHypothesis, SimState
from .mechanism_model import MechanismSpec, compile_effect_hypothesis, simulate_step
from .score import digest
from .transition_model import TransitionModel, TransitionRule

_ACTIONS = frozenset({f"ACTION{i}" for i in range(1, 8)} | {"RESET"})
_STATES = frozenset({"NOT_FINISHED", "WIN", "GAME_OVER"})
_MAX_NODES = 4096
_MAX_DEPTH = 64
_EVIDENCE_GRADES = frozenset({"confirmed", "hypothesis", "conflict", "history-only", "unknown"})


def _frame_signature(state: SimState) -> tuple[tuple[int, ...], ...]:
    return state.frame


def _action(value: object) -> tuple[str, tuple[tuple[str, int], ...]]:
    """Normalize an ARC action without importing the broker's action class."""

    if isinstance(value, str):
        name, raw_data = value, None
    elif isinstance(value, Mapping):
        if set(value) != {"name", "data"}:
            raise ValueError("invalid counterfactual action")
        name, raw_data = value["name"], value["data"]
    elif hasattr(value, "name") and hasattr(value, "data"):
        name, raw_data = getattr(value, "name"), getattr(value, "data")
    else:
        raise ValueError("invalid counterfactual action")
    if type(name) is not str or name not in _ACTIONS:
        raise ValueError("invalid counterfactual action")
    if raw_data is None:
        data: tuple[tuple[str, int], ...] = ()
    else:
        if not isinstance(raw_data, Mapping):
            raise ValueError("invalid counterfactual action data")
        if any(type(key) is not str or type(item) is not int for key, item in raw_data.items()):
            raise ValueError("invalid counterfactual action data")
        data = tuple(sorted(raw_data.items()))
    if name != "ACTION6" and data:
        raise ValueError("invalid counterfactual action data")
    if name == "ACTION6" and (not data or tuple(key for key, _ in data) != ("x", "y")):
        raise ValueError("ACTION6 requires x/y data")
    if any(not 0 <= item <= 63 for _, item in data):
        raise ValueError("counterfactual action coordinate out of bounds")
    return name, data


def _actions(values: Sequence[object] | None, current: SimState) -> tuple[tuple[str, tuple[tuple[str, int], ...]], ...]:
    raw = current.available_actions if values is None else values
    if isinstance(raw, (str, bytes, bytearray)):
        raise ValueError("invalid counterfactual actions")
    normalized = {_action(value) for value in raw}
    if not normalized or len(normalized) > _MAX_DEPTH:
        raise ValueError("invalid counterfactual actions")
    return tuple(sorted(normalized, key=lambda item: (item[0], item[1])))


@dataclass(frozen=True, slots=True)
class Subgoal:
    """A small observable target used to score counterfactual progress.

    A subgoal is complete when all supplied predicates hold.  ``cells`` uses
    ``(x, y, colour)`` triples and is intentionally restricted to observable
    frame facts.  A caller can compose several subgoals for object, trigger,
    or level milestones without making the simulator know game-specific
    semantics.
    """

    name: str
    target_level: int | None = None
    target_state: str | None = None
    cells: tuple[tuple[int, int, int], ...] = ()

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name:
            raise ValueError("subgoal name required")
        if self.target_level is not None and (type(self.target_level) is not int or self.target_level < 0):
            raise ValueError("invalid subgoal level")
        if self.target_state is not None and (
            type(self.target_state) is not str or self.target_state not in _STATES
        ):
            raise ValueError("invalid subgoal state")
        if type(self.cells) is not tuple or len(set(self.cells)) != len(self.cells):
            raise ValueError("invalid subgoal cells")
        if any(
            type(item) is not tuple or len(item) != 3
            or any(type(part) is not int for part in item)
            or not 0 <= item[0] <= 63 or not 0 <= item[1] <= 63
            or not 0 <= item[2] <= 255
            for item in self.cells
        ):
            raise ValueError("invalid subgoal cells")


@dataclass(frozen=True, slots=True)
class SubgoalProgress:
    name: str
    status: str
    matched: int
    total: int
    score: float
    reason: str

    def projection(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "matched": self.matched,
            "total": self.total,
            "score": self.score,
            "reason": self.reason,
        }


def _progress(subgoal: Subgoal, state: SimState) -> SubgoalProgress:
    checks: list[bool] = []
    reasons: list[str] = []
    if subgoal.target_level is not None:
        checks.append(state.level >= subgoal.target_level)
        reasons.append("level" if checks[-1] else "level-pending")
    if subgoal.target_state is not None:
        checks.append(state.state == subgoal.target_state)
        reasons.append("state" if checks[-1] else "state-pending")
    for x, y, colour in subgoal.cells:
        if y >= len(state.frame) or x >= len(state.frame[0]):
            checks.append(False)
            reasons.append("cell-out-of-bounds")
        else:
            checks.append(state.frame[y][x] == colour)
            reasons.append("cell" if checks[-1] else "cell-pending")
    if not checks:
        return SubgoalProgress(subgoal.name, "unknown", 0, 0, 0.0, "empty-subgoal")
    matched = sum(checks)
    total = len(checks)
    if matched == total:
        status = "complete"
    elif matched:
        status = "progress"
    else:
        status = "unchanged"
    return SubgoalProgress(
        subgoal.name, status, matched, total, matched / total,
        ",".join(reasons),
    )


@dataclass(frozen=True, slots=True)
class CounterfactualStep:
    action: dict[str, object]
    expect: dict[str, object]
    evidence_grade: str

    def __post_init__(self) -> None:
        if self.evidence_grade not in _EVIDENCE_GRADES:
            raise ValueError("invalid evidence grade")

    def projection(self) -> dict[str, object]:
        return {
            "action": dict(self.action),
            "expect": dict(self.expect),
            "evidence_grade": self.evidence_grade,
        }


@dataclass(frozen=True, slots=True)
class CounterfactualBranch:
    candidate_key: str
    evidence_grade: str
    path: tuple[CounterfactualStep, ...]
    state: SimState
    subgoals: tuple[SubgoalProgress, ...]
    status: str = "predicted"
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.evidence_grade not in _EVIDENCE_GRADES:
            raise ValueError("invalid evidence grade")
        if type(self.path) is not tuple or any(type(item) is not CounterfactualStep for item in self.path):
            raise ValueError("invalid counterfactual path")

    def projection(self) -> dict[str, object]:
        return {
            "candidate_key": self.candidate_key,
            "evidence_grade": self.evidence_grade,
            "path": [item.projection() for item in self.path],
            "state": {
                "frame_sha256": digest(self.state.frame),
                "levels_completed": self.state.level,
                "state": self.state.state,
            },
            "subgoals": [item.projection() for item in self.subgoals],
            "status": self.status,
            "conflicts": list(self.conflicts),
        }


@dataclass(frozen=True, slots=True)
class CounterfactualSearchResult:
    status: str
    branches: tuple[CounterfactualBranch, ...] = ()
    conflicts: tuple[str, ...] = ()
    progress: tuple[SubgoalProgress, ...] = ()
    expanded_nodes: int = 0
    generated_nodes: int = 0
    reason: str | None = None
    executed_actions: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        # This field is an explicit invariant for callers auditing the trust
        # boundary.  The simulator has no executor callback and always emits
        # an empty execution ledger.
        if self.executed_actions:
            raise ValueError("counterfactual simulation cannot execute actions")

    def projection(self) -> dict[str, object]:
        return {
            "status": self.status,
            "branches": [item.projection() for item in self.branches],
            "conflicts": list(self.conflicts),
            "progress": [item.projection() for item in self.progress],
            "expanded_nodes": self.expanded_nodes,
            "generated_nodes": self.generated_nodes,
            "reason": self.reason,
            "executed_actions": [],
        }


@dataclass(frozen=True, slots=True)
class _Candidate:
    key: str
    grade: str
    spec: MechanismSpec | None
    reason: str | None = None


def _normalize_candidate(value: object) -> _Candidate:
    if isinstance(value, MechanismSpec):
        return _Candidate(f"spec:{value.digest}", "confirmed", value)
    if isinstance(value, EffectHypothesis):
        key = f"hypothesis:{value.key}"
        if value.status == "contradicted" or value.conflict_sequences:
            return _Candidate(key, "conflict", None, "candidate-conflict")
        spec = compile_effect_hypothesis(value)
        if spec is None:
            return _Candidate(key, "hypothesis", None, "uncompilable-hypothesis")
        return _Candidate(key, "hypothesis", spec)
    if isinstance(value, (TransitionRule, TransitionModel)):
        return _Candidate(
            f"history:{type(value).__name__}", "history-only", None,
            "history-only-transition",
        )
    return _Candidate(f"unsupported:{type(value).__name__}", "unknown", None, "unsupported-candidate")


@dataclass(frozen=True, slots=True)
class _Node:
    candidate: _Candidate
    state: SimState
    path: tuple[CounterfactualStep, ...]


def _default_subgoals(current: SimState, candidates: tuple[_Candidate, ...]) -> tuple[Subgoal, ...]:
    target = current.level + 1
    for candidate in candidates:
        if candidate.spec is not None:
            target = min(target, candidate.spec.win_levels)
    return (Subgoal("advance-level", target_level=target),)


def search_counterfactual(
    current: SimState,
    candidates: Sequence[object],
    *,
    actions: Sequence[object] | None = None,
    subgoals: Sequence[Subgoal] = (),
    max_nodes: int = 256,
    max_depth: int = 16,
) -> CounterfactualSearchResult:
    """Search candidate transition branches without dispatching any action.

    A ``MechanismSpec`` is labelled ``confirmed`` and an inducible
    ``EffectHypothesis`` is labelled ``hypothesis``.  Candidates with only
    history hashes are reported as ``history-only`` and never receive a
    fabricated next state.  Divergent predictions for the same action are
    retained as separate branches and surfaced in ``conflicts``.
    """

    if not isinstance(current, SimState):
        return CounterfactualSearchResult("invalid-input", reason="state")
    try:
        if type(max_nodes) is not int or not 1 <= max_nodes <= _MAX_NODES:
            raise ValueError
        if type(max_depth) is not int or not 1 <= max_depth <= _MAX_DEPTH:
            raise ValueError
        normalized_actions = _actions(actions, current)
        normalized_subgoals = tuple(subgoals)
        if any(not isinstance(item, Subgoal) for item in normalized_subgoals):
            raise ValueError
    except (TypeError, ValueError):
        return CounterfactualSearchResult("invalid-input", reason="input")

    normalized = tuple(_normalize_candidate(item) for item in candidates)
    if not normalized:
        return CounterfactualSearchResult("no-plan", reason="no-candidates")
    goals = normalized_subgoals or _default_subgoals(current, normalized)
    conflicts: list[str] = []
    for candidate in normalized:
        if candidate.reason is not None:
            conflicts.append(candidate.reason)

    # Keep a root progress snapshot for callers that need to compare a
    # branch against its starting state, even when the node budget is tiny.
    root_progress = tuple(_progress(goal, current) for goal in goals)
    progress: list[SubgoalProgress] = list(root_progress)
    queue: deque[_Node] = deque(
        _Node(candidate, current, ())
        for candidate in normalized
        if candidate.spec is not None
    )
    # Reaching an identical candidate/state pair again cannot add a new
    # counterfactual outcome.  Omitting path length here also prevents an
    # idempotent rule (for example ``set_cell``) from consuming the entire
    # depth budget by repeating the same action.
    seen: set[tuple[str, tuple[tuple[int, ...], ...], int, str]] = set()
    emitted: set[tuple[str, tuple[tuple[int, ...], ...], int, str, str, tuple[tuple[str, int], ...]]] = set()
    branches: list[CounterfactualBranch] = []
    observed: dict[tuple[str, tuple[tuple[str, int], ...]], set[tuple[tuple[tuple[int, ...], ...], int, str]]] = {}
    expanded = 0
    generated = 0
    while queue:
        if expanded >= max_nodes:
            break
        node = queue.popleft()
        state_key = (node.candidate.key, _frame_signature(node.state), node.state.level, node.state.state)
        if state_key in seen:
            continue
        seen.add(state_key)
        expanded += 1
        if node.candidate.spec is None or node.state.state == "GAME_OVER" or len(node.path) >= max_depth:
            continue
        for name, data in normalized_actions:
            prediction = simulate_step(node.candidate.spec, node.state, {"name": name, "data": dict(data)})
            if prediction.status != "predicted" or prediction.next_state is None:
                reason = prediction.reason or prediction.status
                conflicts.append(f"{node.candidate.key}:{name}:{reason}")
                continue
            child = prediction.next_state
            action_key = (name, data)
            observed.setdefault(action_key, set()).add((child.frame, child.level, child.state))
            child_key = (
                node.candidate.key, child.frame, child.level, child.state,
                name, data,
            )
            if child_key in emitted:
                continue
            emitted.add(child_key)
            step = CounterfactualStep(
                action={"name": name, "data": dict(data)},
                expect={
                    "frame_sha256": digest(child.frame),
                    "levels_completed": child.level,
                    "state": child.state,
                },
                evidence_grade=node.candidate.grade,
            )
            path = (*node.path, step)
            subgoal_progress = tuple(_progress(goal, child) for goal in goals)
            progress.extend(subgoal_progress)
            complete = bool(subgoal_progress) and all(item.status == "complete" for item in subgoal_progress)
            branch = CounterfactualBranch(
                candidate_key=node.candidate.key,
                evidence_grade=node.candidate.grade,
                path=path,
                state=child,
                subgoals=subgoal_progress,
                status="goal-reached" if complete else "predicted",
            )
            branches.append(branch)
            generated += 1
            if not complete and child.state != "GAME_OVER" and len(path) < max_depth:
                queue.append(_Node(node.candidate, child, path))

    for (name, data), states in sorted(observed.items(), key=lambda item: item[0]):
        if len(states) > 1:
            suffix = "" if not data else f"/{dict(data)}"
            conflicts.append(f"candidate-divergence:{name}{suffix}")
    conflicts = list(dict.fromkeys(conflicts))
    found = any(branch.status == "goal-reached" for branch in branches)
    if found:
        status, reason = "found", None
    elif expanded >= max_nodes and queue:
        status, reason = "budget-exhausted", "max-nodes"
    elif branches:
        status, reason = "partial", "frontier-exhausted"
    else:
        status, reason = "no-plan", "no-predicted-transition"
    return CounterfactualSearchResult(
        status=status,
        branches=tuple(branches),
        conflicts=tuple(conflicts),
        progress=tuple(progress),
        expanded_nodes=expanded,
        generated_nodes=generated,
        reason=reason,
    )


__all__ = (
    "CounterfactualBranch",
    "CounterfactualSearchResult",
    "CounterfactualStep",
    "Subgoal",
    "SubgoalProgress",
    "search_counterfactual",
)
