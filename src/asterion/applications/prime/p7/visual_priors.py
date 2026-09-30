"""Conservative visual priors for the same-game world model.

The extractor describes regularities in a frame; it never labels a color as a
wall, floor, object, or goal.  Those labels remain hypotheses and require an
action transition before the broker can confirm them.
"""

from __future__ import annotations

from collections import Counter, deque
from typing import Iterable, Sequence


def _cells(frame: Sequence[Sequence[int]]) -> tuple[tuple[int, int, int], ...]:
    rows = tuple(tuple(row) for row in frame)
    if not rows or any(not row or any(type(value) is not int for value in row) for row in rows):
        return ()
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        return ()
    return tuple((x, y, rows[y][x]) for y in range(len(rows)) for x in range(width))


def _components(frame: Sequence[Sequence[int]], color: int, *, limit: int = 12) -> list[dict[str, int]]:
    rows = tuple(tuple(row) for row in frame)
    height = len(rows)
    width = len(rows[0]) if rows else 0
    remaining = {(x, y) for y in range(height) for x in range(width) if rows[y][x] == color}
    result: list[dict[str, int]] = []
    while remaining and len(result) < limit:
        start = min(remaining, key=lambda item: (item[1], item[0]))
        remaining.remove(start)
        queue = deque([start])
        size = 0
        min_x = max_x = start[0]
        min_y = max_y = start[1]
        while queue:
            x, y = queue.popleft()
            size += 1
            min_x, max_x = min(min_x, x), max(max_x, x)
            min_y, max_y = min(min_y, y), max(max_y, y)
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
        result.append({
            "size": size,
            "min_x": min_x,
            "max_x": max_x,
            "min_y": min_y,
            "max_y": max_y,
        })
    return result


def _roles(count: int, total: int, *, width: int, height: int, components: Iterable[dict[str, int]]) -> list[str]:
    roles: list[str] = []
    ratio = count / total if total else 0.0
    if ratio >= 0.15:
        roles.append("floor_or_background")
    if count <= max(4, total // 100):
        roles.append("rare_object_or_goal")
    spans = [(item["max_x"] - item["min_x"] + 1, item["max_y"] - item["min_y"] + 1) for item in components]
    if any(max(span) >= 8 and min(span) <= 3 for span in spans):
        roles.append("line_or_wall_candidate")
    if not roles:
        roles.append("unclassified_region")
    return roles


def derive_visual_candidates(frame: Sequence[Sequence[int]]) -> tuple[tuple[str, dict[str, object]], ...]:
    """Return bounded, deterministic candidate facts for one 2-D frame."""

    cells = _cells(frame)
    if not cells:
        return ()
    height = len(frame)
    width = len(frame[0])
    counts = Counter(value for _, _, value in cells)
    total = len(cells)
    candidates: list[tuple[str, dict[str, object]]] = []
    palette: dict[str, object] = {
        "source": "visual-regularity",
        "width": width,
        "height": height,
        "cell_count": total,
        "colors": [],
    }
    for color, count in sorted(counts.items()):
        components = _components(frame, color)
        roles = _roles(count, total, width=width, height=height, components=components)
        palette["colors"].append({
            "color": color,
            "count": count,
            "frequency": round(count / total, 6),
            "candidate_roles": roles,
            "component_count": len(components),
        })
        for index, component in enumerate(components[:3]):
            candidates.append((
                f"visual.component.{color}.{index}",
                {
                    "source": "visual-regularity",
                    "color": color,
                    "candidate_roles": roles,
                    **component,
                },
            ))
    candidates.insert(0, ("visual.palette", palette))
    # Keep projection size stable on dense frames.  Palette is always retained.
    return tuple(candidates[:32])


__all__ = ("derive_visual_candidates",)
