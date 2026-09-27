"""Bounded, redacted cross-level mechanics evidence for P7."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

_MAX_RECORDS = 512
_MAX_CELLS = 16
_MAX_RULES = 32
_MAX_LEVELS = 64
_ACTIONS = frozenset(f"ACTION{index}" for index in range(1, 8))


@dataclass(frozen=True)
class _Record:
    sequence: int
    action: str
    data: Mapping[str, object]
    changed: int
    cells: tuple[tuple[int, int], ...]
    level: int


def _coord(value: object) -> tuple[int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        x, y = value[0], value[1]
        if type(x) is int and type(y) is int and 0 <= x <= 63 and 0 <= y <= 63:
            return x, y
    return None


def _record(row: Mapping[str, object], fallback_sequence: int) -> _Record | None:
    action = row.get("action")
    level = row.get("levels_completed")
    changed = row.get("changed_cell_count")
    if not isinstance(action, str) or action not in _ACTIONS:
        return None
    if type(level) is not int or level < 0 or level >= _MAX_LEVELS:
        return None
    if type(changed) is not int or changed < 0:
        return None
    data = row.get("data")
    if not isinstance(data, Mapping):
        data = {}
    cells: list[tuple[int, int]] = []
    raw_cells = row.get("changed_cells")
    if isinstance(raw_cells, (list, tuple)):
        for item in raw_cells:
            point = _coord(item)
            if point is not None and point not in cells:
                cells.append(point)
                if len(cells) >= _MAX_CELLS:
                    break
    sequence = row.get("sequence")
    if type(sequence) is not int or sequence < 0:
        sequence = fallback_sequence
    return _Record(sequence, action, data, changed, tuple(cells), level)


def build_mechanics_prior(
    records: Sequence[Mapping[str, object]], *, current_level: int
) -> dict[str, object]:
    """Summarize detached broker history without exposing frames or identities."""
    if type(current_level) is not int or current_level < 0:
        current_level = 0
    valid: list[_Record] = []
    for index, row in enumerate(records[:_MAX_RECORDS], start=1):
        if isinstance(row, Mapping):
            item = _record(row, index)
            if item is not None:
                valid.append(item)
    valid.sort(key=lambda item: (item.sequence, item.action))

    grouped: dict[int, list[_Record]] = defaultdict(list)
    for item in valid:
        grouped[item.level].append(item)
    levels: list[dict[str, object]] = []
    families: dict[str, list[_Record]] = defaultdict(list)
    for level in sorted(grouped)[:_MAX_LEVELS]:
        rows = grouped[level]
        counts = Counter(item.action for item in rows)
        sampled = sorted({point for item in rows for point in item.cells})[:_MAX_CELLS]
        view: dict[str, object] = {
            "level": level,
            "transition_count": len(rows),
            "action_counts": dict(sorted(counts.items())),
            "no_effect_count": sum(item.changed == 0 for item in rows),
            "changed_cell_total": sum(item.changed for item in rows),
            "changed_cells": [[x, y] for x, y in sampled],
        }
        coords = [
            (item.data.get("x"), item.data.get("y"))
            for item in rows
            if item.action == "ACTION6"
        ]
        points = [point for pair in coords if (point := _coord(pair)) is not None]
        if points:
            view["action6_coordinate_range"] = {
                "min_x": min(x for x, _ in points),
                "max_x": max(x for x, _ in points),
                "min_y": min(y for _, y in points),
                "max_y": max(y for _, y in points),
            }
        levels.append(view)
        for item in rows:
            families[item.action].append(item)

    advances: list[dict[str, object]] = []
    previous = 0
    for item in valid:
        if item.level > previous:
            advances.append(
                {"from_level": previous, "to_level": item.level, "sequence": item.sequence}
            )
            previous = item.level

    rules: list[dict[str, object]] = []
    for action in sorted(families)[:_MAX_RULES]:
        rows = families[action]
        seen_levels = sorted({item.level for item in rows})
        effects = {item.changed > 0 for item in rows}
        confidence = "mixed" if effects == {True, False} else (
            "repeated" if len(seen_levels) > 1 else "observed"
        )
        rules.append(
            {
                "action": action,
                "levels": seen_levels,
                "sequences": sorted(item.sequence for item in rows)[:_MAX_CELLS],
                "confidence": confidence,
                "effect_observed": True in effects,
                "no_effect_observed": False in effects,
            }
        )

    return {
        "available": bool(valid),
        "prefix_actions": len(valid),
        "highest_verified_level": max((item.level for item in valid), default=0),
        "current_level": current_level,
        "levels": levels,
        "level_advances": advances[:_MAX_LEVELS],
        "candidate_rules": rules,
    }
