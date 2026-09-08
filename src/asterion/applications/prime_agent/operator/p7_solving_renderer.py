"""Validated local-only rendering for a completed P7 solving episode."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Final

from asterion.services.presentation import HostPresentationSink

from .p7_solving_broker import normalize_p7_action


_SCORE: Final = re.compile(r"(?:0|[1-9][0-9]?|100)\.[0-9]{6}\Z")
_ACTION: Final = re.compile(r"ACTION[1-5]|ACTION7|ACTION6 x=(?:0|[1-5]?[0-9]|6[0-3]) y=(?:0|[1-5]?[0-9]|6[0-3])\Z")
_FIELDS: Final = frozenset(
    {
        "question",
        "initial_grid",
        "completion_grid",
        "applied_actions",
        "action_count",
        "model_callback_count",
        "tool_callback_count",
        "levels_completed",
        "terminal_reason",
        "partial_game_score",
    }
)
_MAX_LAYERS: Final = 4
_MAX_SIDE: Final = 64
_MAX_CELLS: Final = _MAX_LAYERS * _MAX_SIDE * _MAX_SIDE


class P7SolvingRendererError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 solving presentation is unavailable")


@dataclass(frozen=True, repr=False)
class P7SolvingPresentation:
    question: str
    initial_grid: tuple[tuple[tuple[int, ...], ...], ...]
    completion_grid: tuple[tuple[tuple[int, ...], ...], ...]
    applied_actions: tuple[str, ...]
    action_count: int
    model_callback_count: int
    tool_callback_count: int
    levels_completed: int
    terminal_reason: str
    partial_game_score: str

    def __repr__(self) -> str:
        return "P7SolvingPresentation(redacted)"


def create_p7_solving_presentation(
    value: object,
    *,
    model_callback_count: int,
    tool_callback_count: int,
) -> P7SolvingPresentation:
    """Copy the broker projection into one immutable renderer value."""

    fields = {
        "action_count",
        "applied_actions",
        "completion_grid",
        "initial_grid",
        "levels_completed",
        "score",
        "terminal_reason",
    }
    try:
        if type(value) is not dict or set(value) != fields:
            raise ValueError
        actions = value["applied_actions"]
        if type(actions) is not list:
            raise ValueError
        normalized_actions = tuple(_action_text(action) for action in actions)
        result = P7SolvingPresentation(
            question="First public level",
            initial_grid=_freeze_grid(value["initial_grid"]),
            completion_grid=_freeze_grid(value["completion_grid"]),
            applied_actions=normalized_actions,
            action_count=value["action_count"],  # type: ignore[arg-type]
            model_callback_count=model_callback_count,
            tool_callback_count=tool_callback_count,
            levels_completed=value["levels_completed"],  # type: ignore[arg-type]
            terminal_reason=value["terminal_reason"],  # type: ignore[arg-type]
            partial_game_score=value["score"],  # type: ignore[arg-type]
        )
        _validate(result)
        return result
    except BaseException:
        raise P7SolvingRendererError() from None


def render_p7_solving_presentation(
    value: object, sink: HostPresentationSink
) -> None:
    """Render only validated, bounded records through the injected sink."""

    try:
        _validate(value)
        write = getattr(sink, "write", None)
        if not callable(write):
            raise ValueError
        assert type(value) is P7SolvingPresentation
        records = [f"Question: {value.question}", "Initial grid:"]
        records.extend(_grid_records(value.initial_grid))
        records.append("Action answer:")
        records.extend(
            f"[{index:03d}] {action}"
            for index, action in enumerate(value.applied_actions, 1)
        )
        records.extend(
            (
                f"Model callbacks: {value.model_callback_count}",
                f"IPython calls: {value.tool_callback_count}",
                f"Solved level: {value.levels_completed}",
                "Solved grid:",
            )
        )
        records.extend(_grid_records(value.completion_grid))
        records.append(f"Partial score: {value.partial_game_score}")
        if any(not record or len(record) > 1024 or not record.isascii() for record in records):
            raise ValueError
        for record in records:
            write(record)
    except BaseException:
        raise P7SolvingRendererError() from None


def _freeze_grid(value: object) -> tuple[tuple[tuple[int, ...], ...], ...]:
    if type(value) is not list:
        raise ValueError
    return tuple(tuple(tuple(row) for row in layer) for layer in value)


def _valid_grid(value: object) -> bool:
    if type(value) is not tuple or not 1 <= len(value) <= _MAX_LAYERS:
        return False
    cells = 0
    shape: tuple[int, int] | None = None
    for layer in value:
        if type(layer) is not tuple or not 1 <= len(layer) <= _MAX_SIDE:
            return False
        widths = {len(row) for row in layer if type(row) is tuple}
        if len(widths) != 1:
            return False
        width = next(iter(widths), 0)
        if not 1 <= width <= _MAX_SIDE:
            return False
        layer_shape = (len(layer), width)
        if shape is None:
            shape = layer_shape
        elif layer_shape != shape:
            return False
        for row in layer:
            if (
                type(row) is not tuple
                or any(type(color) is not int or not 0 <= color <= 255 for color in row)
            ):
                return False
            cells += len(row)
    return cells <= _MAX_CELLS


def _valid_score(value: object) -> bool:
    try:
        return (
            type(value) is str
            and _SCORE.fullmatch(value) is not None
            and Decimal("0.000000") <= Decimal(value) <= Decimal("100.000000")
        )
    except InvalidOperation:
        return False


def _validate(value: object) -> None:
    if (
        type(value) is not P7SolvingPresentation
        or frozenset(vars(value)) != _FIELDS
        or value.question != "First public level"
        or not _valid_grid(value.initial_grid)
        or not _valid_grid(value.completion_grid)
        or type(value.applied_actions) is not tuple
        or any(type(action) is not str or _ACTION.fullmatch(action) is None for action in value.applied_actions)
        or type(value.action_count) is not int
        or not 1 <= value.action_count <= 500
        or len(value.applied_actions) != value.action_count
        or type(value.model_callback_count) is not int
        or not 1 <= value.model_callback_count <= 128
        or type(value.tool_callback_count) is not int
        or not 1 <= value.tool_callback_count <= 128
        or value.levels_completed != 1
        or value.terminal_reason != "level-completed"
        or not _valid_score(value.partial_game_score)
    ):
        raise P7SolvingRendererError()


def _action_text(value: object) -> str:
    if type(value) is not dict or normalize_p7_action(value) != value:
        raise ValueError
    name, data = value["name"], value["data"]
    if name == "ACTION6":
        return f"ACTION6 x={data['x']} y={data['y']}"
    return str(name)


def _grid_records(
    grid: tuple[tuple[tuple[int, ...], ...], ...],
) -> list[str]:
    records: list[str] = []
    for index, layer in enumerate(grid, 1):
        if len(grid) > 1:
            records.append(f"Layer {index}:")
        records.extend(" ".join(f"{color:3d}" for color in row) for row in layer)
    return records


__all__ = (
    "P7SolvingPresentation",
    "P7SolvingRendererError",
    "create_p7_solving_presentation",
    "render_p7_solving_presentation",
)
