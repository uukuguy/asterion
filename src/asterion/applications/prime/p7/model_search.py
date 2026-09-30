"""Bounded planning over a verified declarative P7 mechanism.

The search layer is intentionally separate from the broker and the live model.
It consumes only a :class:`MechanismSpec` that the broker has retrodicted over
real history.  Unknown rules are skipped; the planner never turns an
unverified guess into a live action.  Results are shaped directly for
``p7_act_checked`` and therefore carry a full predicted frame digest for every
step.
"""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from itertools import count
from collections.abc import Mapping, Sequence
from .mechanism_model import MechanismSpec
from .score import digest

_ACTIONS = frozenset({f"ACTION{i}" for i in range(1, 8)} | {"RESET"})
_MAX_FRAME_CELLS = 4096
_MAX_ACTIONS = 128
_MAX_NODES = 4096
_MAX_DEPTH = 64


def _frame(value: object) -> tuple[tuple[int, ...], ...]:
    if not isinstance(value, (tuple, list)) or not value:
        raise ValueError("invalid search frame")
    rows: list[tuple[int, ...]] = []
    width: int | None = None
    for row in value:
        if not isinstance(row, (tuple, list)) or not row:
            raise ValueError("invalid search frame")
        converted = tuple(item for item in row if type(item) is int and 0 <= item <= 255)
        if len(converted) != len(row):
            raise ValueError("invalid search frame")
        if width is None:
            width = len(converted)
        elif width != len(converted):
            raise ValueError("invalid search frame")
        rows.append(converted)
    if width is None or len(rows) * width > _MAX_FRAME_CELLS:
        raise ValueError("search frame exceeds cap")
    return tuple(rows)


def _data(value: object) -> tuple[tuple[str, int], ...]:
    if value is None:
        return ()
    if not isinstance(value, Mapping):
        raise ValueError("invalid search action data")
    if any(type(key) is not str or type(item) is not int for key, item in value.items()):
        raise ValueError("invalid search action data")
    data = tuple(sorted(value.items()))
    if len(data) > 2 or tuple(key for key, _ in data) not in ((), ("x", "y")):
        raise ValueError("invalid search action data")
    if data and any(not 0 <= item <= 63 for _, item in data):
        raise ValueError("invalid search action data")
    return data


def _actions(values: Sequence[object]) -> tuple[tuple[str, tuple[tuple[str, int], ...]], ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise ValueError("invalid search actions")
    normalized: set[tuple[str, tuple[tuple[str, int], ...]]] = set()
    for value in values:
        if isinstance(value, str):
            name, data = value, ()
        elif isinstance(value, Mapping) and set(value) == {"name", "data"}:
            name, data = value["name"], _data(value["data"])
        else:
            raise ValueError("invalid search action")
        if type(name) is not str or name not in _ACTIONS:
            raise ValueError("invalid search action")
        if name != "ACTION6" and data:
            raise ValueError("invalid search action data")
        if name == "ACTION6" and (not data or tuple(key for key, _ in data) != ("x", "y")):
            raise ValueError("ACTION6 needs a focused position")
        normalized.add((name, data))
    if len(normalized) > _MAX_ACTIONS:
        raise ValueError("search action cap exceeded")
    return tuple(sorted(normalized, key=lambda item: (item[0], item[1])))


@dataclass(frozen=True, slots=True)
class PlannedAction:
    """One model-predicted action suitable for ``act_checked``."""

    action: dict[str, object]
    expect: dict[str, object]


@dataclass(frozen=True, slots=True)
class SearchResult:
    status: str
    plan: tuple[PlannedAction, ...] = ()
    expanded_nodes: int = 0
    generated_nodes: int = 0
    reason: str | None = None
    start: dict[str, object] | None = None

    def projection(self) -> dict[str, object]:
        return {
            "status": self.status,
            "plan": [
                {"action": dict(item.action), "expect": dict(item.expect)}
                for item in self.plan
            ],
            "expanded_nodes": self.expanded_nodes,
            "generated_nodes": self.generated_nodes,
            "reason": self.reason,
            "start": None if self.start is None else dict(self.start),
        }


@dataclass(frozen=True, slots=True)
class _Node:
    frame: tuple[tuple[int, ...], ...]
    level: int
    state: str
    path: tuple[PlannedAction, ...]


def _priority(node: _Node, target_level: int) -> tuple[int, int]:
    # A small admissible level-distance hint keeps the queue useful for long
    # plans while retaining breadth-first behaviour among equal candidates.
    remaining = max(0, target_level - node.level)
    return (len(node.path) + remaining * 4, len(node.path))


def search_model(
    spec: MechanismSpec,
    *,
    frame: object,
    level: int,
    state: str,
    actions: Sequence[object],
    target_level: int | None = None,
    entities: Mapping[str, object] | None = None,
    max_nodes: int = 512,
    max_depth: int = 24,
    strategy: str = "astar",
) -> SearchResult:
    """Search a verified mechanism without dispatching any live action.

    ``actions`` is a focused, evidence-backed action set.  In particular,
    ACTION6 positions must be supplied by perception/history; this function
    never enumerates the 64x64 click grid.
    """

    try:
        if type(spec) is not MechanismSpec:
            raise ValueError
        stable = _frame(frame)
        if type(level) is not int or level < 0 or level > spec.win_levels:
            raise ValueError
        if type(state) is not str or not state:
            raise ValueError
        candidates = _actions(actions)
        if not candidates:
            raise ValueError
        if target_level is None:
            target_level = min(spec.win_levels, level + 1)
        if type(target_level) is not int or not level < target_level <= spec.win_levels:
            raise ValueError
        if type(max_nodes) is not int or not 1 <= max_nodes <= _MAX_NODES:
            raise ValueError
        if type(max_depth) is not int or not 1 <= max_depth <= _MAX_DEPTH:
            raise ValueError
        if strategy not in {"astar", "bfs"}:
            raise ValueError
    except (TypeError, ValueError):
        return SearchResult("invalid-input", reason="input")

    start = {
        "frame_sha256": digest(stable),
        "levels_completed": level,
        "state": state,
    }
    root = _Node(stable, level, state, ())
    queue: list[tuple[tuple[int, int], int, _Node]] = []
    serial = count()
    heapq.heappush(queue, (_priority(root, target_level), next(serial), root))
    seen: dict[tuple[tuple[tuple[int, ...], ...], int, str], int] = {(stable, level, state): 0}
    expanded = 0
    generated = 0
    while queue:
        if expanded >= max_nodes:
            return SearchResult("budget-exhausted", expanded_nodes=expanded, generated_nodes=generated, reason="max-nodes", start=start)
        _, _, node = heapq.heappop(queue)
        expanded += 1
        if node.level >= target_level or node.state == "WIN":
            return SearchResult("found", node.path, expanded, generated, start=start)
        if node.state == "GAME_OVER" or len(node.path) >= max_depth:
            continue
        for name, data in candidates:
            prediction = spec.predict(
                frame=node.frame,
                action=name,
                data=dict(data),
                level=node.level,
                state=node.state,
                entities=entities or {},
            )
            if prediction.status != "predicted" or prediction.frame is None or prediction.level is None or prediction.state is None:
                continue
            child_frame = prediction.frame
            child = _Node(child_frame, prediction.level, prediction.state, ())
            key = (child_frame, prediction.level, prediction.state)
            depth = len(node.path) + 1
            if key in seen and seen[key] <= depth:
                continue
            seen[key] = depth
            expected = {
                "frame_sha256": digest(child_frame),
                "levels_completed": prediction.level,
                "state": prediction.state,
            }
            step = PlannedAction(
                {"name": name, "data": dict(data)},
                expected,
            )
            child = _Node(child_frame, prediction.level, prediction.state, (*node.path, step))
            generated += 1
            if child.level >= target_level or child.state == "WIN":
                return SearchResult("found", child.path, expanded, generated, start=start)
            if child.state == "GAME_OVER":
                continue
            priority = _priority(child, target_level) if strategy == "astar" else (depth, depth)
            heapq.heappush(queue, (priority, next(serial), child))
    return SearchResult("no-plan", expanded_nodes=expanded, generated_nodes=generated, reason="frontier-exhausted", start=start)


__all__ = ("PlannedAction", "SearchResult", "search_model")
