"""Private, bounded history and prediction contracts for one P7 run."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING

from .score import digest

if TYPE_CHECKING:
    from .broker import ArcAction

Grid = tuple[tuple[int, ...], ...]
CellChange = tuple[int, int, int, int]
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_ERROR = "P7 prediction is unavailable"


class ArcPredictionError(ValueError):
    """Safe failure for private history and prediction operations."""

    def __init__(self) -> None:
        super().__init__(_SAFE_ERROR)


def _grid(value: object) -> Grid:
    if not isinstance(value, (list, tuple)) or not value:
        raise ArcPredictionError
    rows: list[tuple[int, ...]] = []
    width: int | None = None
    for row in value:
        if not isinstance(row, (list, tuple)) or not row:
            raise ArcPredictionError
        if any(type(color) is not int or not 0 <= color <= 255 for color in row):
            raise ArcPredictionError
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise ArcPredictionError
        rows.append(tuple(row))
    return tuple(rows)


def _hash(value: object) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ArcPredictionError
    return value


def stable_changed_cells(
    before: object, after: object, limit: int = 80,
) -> tuple[int, tuple[CellChange, ...], int]:
    """Count every stable-frame change and retain a row-major prefix."""

    if type(limit) is not int or limit < 0:
        raise ArcPredictionError
    left, right = _grid(before), _grid(after)
    if len(left) != len(right) or len(left[0]) != len(right[0]):
        raise ArcPredictionError
    total = 0
    sample: list[CellChange] = []
    for y, (before_row, after_row) in enumerate(zip(left, right)):
        for x, (old, new) in enumerate(zip(before_row, after_row)):
            if old != new:
                total += 1
                if len(sample) < limit:
                    sample.append((x, y, old, new))
    return total, tuple(sample), total - len(sample)


def validate_history_query(
    *, start: int, limit: int, latest_sequence: int,
) -> tuple[int, int]:
    """Validate a finite history page without looking beyond the latest record."""

    if (
        type(start) is not int or type(limit) is not int
        or type(latest_sequence) is not int or latest_sequence < 0
        or not 0 <= start <= latest_sequence or not 1 <= limit <= 32
    ):
        raise ArcPredictionError
    return start, limit


def _action_fields(value: object) -> tuple[str, tuple[tuple[str, int], ...]]:
    if type(value) is not dict or set(value) != {"name", "data"}:
        raise ArcPredictionError
    name, data = value["name"], value["data"]
    if type(name) is not str or name not in {"RESET", *(f"ACTION{i}" for i in range(1, 8))}:
        raise ArcPredictionError
    if type(data) is not dict:
        raise ArcPredictionError
    if name == "ACTION6":
        if set(data) != {"x", "y"} or any(
            type(data[key]) is not int or not 0 <= data[key] <= 63 for key in ("x", "y")
        ):
            raise ArcPredictionError
        return name, (("x", data["x"]), ("y", data["y"]))
    if data:
        raise ArcPredictionError
    return name, ()


def validate_prediction(
    value: object, *, current_levels: int,
) -> tuple[str, tuple[tuple[str, int], ...], dict[str, object]]:
    """Validate one canonical action and at least one falsifiable expectation."""

    if type(current_levels) is not int or current_levels < 0:
        raise ArcPredictionError
    if type(value) is not dict or set(value) != {"action", "expect"}:
        raise ArcPredictionError
    name, data = _action_fields(value["action"])
    expect = value["expect"]
    if type(expect) is not dict or not expect or not set(expect) <= {
        "cell", "frame_sha256", "levels_completed", "state"
    }:
        raise ArcPredictionError
    checked: dict[str, object] = {}
    distinguishing = False
    if "cell" in expect:
        cell = expect["cell"]
        if type(cell) is not dict or set(cell) != {"x", "y", "value"}:
            raise ArcPredictionError
        if any(type(cell[key]) is not int or not 0 <= cell[key] <= 63 for key in ("x", "y")):
            raise ArcPredictionError
        if type(cell["value"]) is not int or not 0 <= cell["value"] <= 255:
            raise ArcPredictionError
        checked["cell"] = dict(cell)
        distinguishing = True
    if "frame_sha256" in expect:
        checked["frame_sha256"] = _hash(expect["frame_sha256"])
        distinguishing = True
    if "levels_completed" in expect:
        level = expect["levels_completed"]
        if type(level) is not int or level <= current_levels:
            raise ArcPredictionError
        checked["levels_completed"] = level
        distinguishing = True
    if "state" in expect:
        if expect["state"] not in ("WIN", "GAME_OVER"):
            raise ArcPredictionError
        checked["state"] = expect["state"]
        distinguishing = True
    if not distinguishing:
        raise ArcPredictionError
    return name, data, checked


@dataclass(frozen=True, slots=True, repr=False)
class ArcHistoryRecord:
    game_id: str
    seed: int
    run_id: str
    sequence: int
    action: str | None
    data: tuple[tuple[str, int], ...]
    before_state_sha256: str | None
    after_state_sha256: str
    before_frame_sha256: str | None
    after_frame_sha256: str
    frame: Grid
    changed_cell_count: int
    changed_cells: tuple[CellChange, ...]
    changed_cells_omitted: int
    levels_completed: int
    state: str

    def __post_init__(self) -> None:
        stable = _grid(self.frame)
        if (
            type(self.game_id) is not str or not self.game_id
            or type(self.seed) is not int
            or type(self.run_id) is not str or not self.run_id or not self.run_id.isascii()
            or type(self.sequence) is not int or self.sequence < 0
            or type(self.levels_completed) is not int or self.levels_completed < 0
            or type(self.state) is not str or not self.state
            or type(self.changed_cell_count) is not int or self.changed_cell_count < 0
            or type(self.changed_cells_omitted) is not int or self.changed_cells_omitted < 0
            or type(self.data) is not tuple
            or type(self.changed_cells) is not tuple
            or len(self.changed_cells) > 80
            or self.changed_cell_count > len(stable) * len(stable[0])
            or self.changed_cell_count != len(self.changed_cells) + self.changed_cells_omitted
        ):
            raise ArcPredictionError
        _hash(self.after_state_sha256)
        _hash(self.after_frame_sha256)
        if self.after_frame_sha256 != digest(stable):
            raise ArcPredictionError
        if any(
            type(item) is not tuple or len(item) != 2
            or type(item[0]) is not str or type(item[1]) is not int
            for item in self.data
        ):
            raise ArcPredictionError
        if any(
            type(item) is not tuple or len(item) != 4
            or any(type(value) is not int for value in item)
            or not 0 <= item[0] < len(stable[0])
            or not 0 <= item[1] < len(stable)
            or not 0 <= item[2] <= 255 or not 0 <= item[3] <= 255
            or item[2] == item[3]
            or item[3] != stable[item[1]][item[0]]
            for item in self.changed_cells
        ):
            raise ArcPredictionError
        coordinates = tuple((item[1], item[0]) for item in self.changed_cells)
        if coordinates != tuple(sorted(set(coordinates))):
            raise ArcPredictionError
        if self.sequence == 0:
            if (
                self.action is not None or self.data
                or self.before_state_sha256 is not None
                or self.before_frame_sha256 is not None
                or self.changed_cell_count != 0
            ):
                raise ArcPredictionError
        else:
            _hash(self.before_state_sha256)
            _hash(self.before_frame_sha256)
            name, canonical_data = _action_fields(
                {"name": self.action, "data": dict(self.data)}
            )
            if name != self.action or canonical_data != self.data:
                raise ArcPredictionError
        object.__setattr__(self, "frame", stable)

    def __repr__(self) -> str:
        return "ArcHistoryRecord(redacted)"

    @property
    def stable_frame_sha256(self) -> str:
        return self.after_frame_sha256

    @classmethod
    def initial(
        cls, *, game_id: str, seed: int, run_id: str, frame: object,
        levels_completed: int, state: str, after_state_sha256: str,
    ) -> ArcHistoryRecord:
        stable = _grid(frame)
        if (
            type(game_id) is not str or not game_id or type(seed) is not int
            or type(run_id) is not str or not run_id
            or type(levels_completed) is not int or levels_completed < 0
            or type(state) is not str or not state
        ):
            raise ArcPredictionError
        return cls(
            game_id, seed, run_id, 0, None, (), None, _hash(after_state_sha256),
            None, digest(stable), stable, 0, (), 0, levels_completed, state,
        )

    @classmethod
    def following(
        cls, previous: ArcHistoryRecord, *, action: ArcAction,
        before_state_sha256: str, after_state_sha256: str, frame: object,
        levels_completed: int, state: str,
    ) -> ArcHistoryRecord:
        if (
            type(previous) is not cls or _hash(before_state_sha256) != previous.after_state_sha256
            or type(levels_completed) is not int or levels_completed < 0
            or type(state) is not str or not state
        ):
            raise ArcPredictionError
        stable = _grid(frame)
        data = getattr(action, "data", None)
        name = getattr(action, "name", None)
        if (
            type(data) is not tuple
            or any(
                type(item) is not tuple or len(item) != 2
                or type(item[0]) is not str or type(item[1]) is not int
                for item in data
            )
        ):
            raise ArcPredictionError
        canonical_name, canonical_data = _action_fields({"name": name, "data": dict(data)})
        if data != canonical_data:
            raise ArcPredictionError
        total, sample, omitted = stable_changed_cells(previous.frame, stable)
        return cls(
            previous.game_id, previous.seed, previous.run_id, previous.sequence + 1,
            canonical_name, canonical_data, previous.after_state_sha256,
            _hash(after_state_sha256), previous.after_frame_sha256, digest(stable),
            stable, total, sample, omitted, levels_completed, state,
        )

    def public_view(self) -> dict[str, object]:
        """Return a detached worker projection without run identity or raw frame."""

        return {
            "sequence": self.sequence,
            "action": self.action,
            "data": dict(self.data),
            "before_state_sha256": self.before_state_sha256,
            "after_state_sha256": self.after_state_sha256,
            "before_frame_sha256": self.before_frame_sha256,
            "after_frame_sha256": self.after_frame_sha256,
            "changed_cell_count": self.changed_cell_count,
            "changed_cells": list(self.changed_cells),
            "changed_cells_omitted": self.changed_cells_omitted,
            "levels_completed": self.levels_completed,
            "state": self.state,
        }
