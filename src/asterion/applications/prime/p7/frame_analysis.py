"""Bounded, game-agnostic summaries for the public P7 settled frame."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence


def _settled(frame: Sequence[object]) -> Sequence[Sequence[int]]:
    if (
        isinstance(frame, (list, tuple))
        and frame
        and isinstance(frame[0], (list, tuple))
        and frame[0]
        and isinstance(frame[0][0], (list, tuple))
    ):
        frame = frame[-1]  # type: ignore[assignment]
    if not isinstance(frame, (list, tuple)):
        return ()
    rows: list[Sequence[int]] = []
    for row in frame:
        if not isinstance(row, (list, tuple)):
            return ()
        values = tuple(value for value in row if type(value) is int)
        if len(values) != len(row):
            return ()
        rows.append(values)
    width = len(rows[0]) if rows else 0
    if any(len(row) != width for row in rows):
        return ()
    return tuple(rows)


def summarize_frame(frame: Sequence[object], *, background: int = 4) -> dict[str, object]:
    """Return bounded dimensions, color counts, and non-background components."""

    grid = _settled(frame)
    rows, columns = len(grid), len(grid[0]) if grid else 0
    counts = Counter(value for row in grid for value in row)
    seen: set[tuple[int, int]] = set()
    components: list[dict[str, object]] = []
    for y, row in enumerate(grid):
        for x, value in enumerate(row):
            if value == background or (x, y) in seen:
                continue
            stack = [(x, y)]
            seen.add((x, y))
            cells: list[tuple[int, int]] = []
            while stack:
                cx, cy = stack.pop()
                cells.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if (
                        0 <= ny < rows
                        and 0 <= nx < columns
                        and (nx, ny) not in seen
                        and grid[ny][nx] == value
                    ):
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            xs = [cell[0] for cell in cells]
            ys = [cell[1] for cell in cells]
            components.append(
                {"value": value, "bbox": [min(xs), min(ys), max(xs), max(ys)], "size": len(cells)}
            )
    components.sort(key=lambda item: (item["bbox"][1], item["bbox"][0], item["value"], item["size"]))
    return {
        "shape": [rows, columns],
        "counts": dict(sorted(counts.items())),
        "components": components[:40],
    }
