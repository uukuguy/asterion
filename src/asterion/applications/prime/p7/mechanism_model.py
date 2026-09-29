"""Bounded declarative mechanism hypotheses for one P7 game.

This module is deliberately independent from the broker and engine.  A
mechanism can only inspect a supplied observation and apply a small allowlist
of pure frame/state effects; it cannot execute model text or access process,
filesystem, or network services.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .score import digest
from .verified_history import ArcHistoryRecord, ArcPredictionError, stable_changed_cells

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ACTIONS = frozenset({"RESET", *(f"ACTION{i}" for i in range(1, 8))})
_GUARDS = frozenset(
    {
        "state_is",
        "level_is",
        "cell_equals",
        "cell_in_bounds",
        "action_data_equals",
        "entity_attr_equals",
    }
)
_EFFECTS = frozenset(
    {
        "set_cell",
        "toggle_cell",
        "translate_cells",
        "set_state",
        "increment_level",
    }
)
_MAX_RULES = 128
_MAX_GUARDS = 16
_MAX_EFFECTS = 16
_MAX_VALUE_BYTES = 8192
_MAX_FRAME_CELLS = 4096


def _id(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"invalid {name}")
    return value


def _json_value(value: Any, *, path: str = "value", depth: int = 0) -> Any:
    """Normalize only detached JSON values; tuples become JSON arrays."""

    if depth > 12:
        raise ValueError(f"{path} is too deep")
    if value is None or type(value) in (str, bool, int):
        if type(value) is str and len(value) > 1024:
            raise ValueError(f"{path} is too large")
        return value
    if type(value) is float:
        # Mechanism rules have no need for floating point values.  Rejecting
        # them avoids platform-specific equality and NaN corner cases.
        raise ValueError(f"{path} is not JSON-safe")
    if type(value) in (list, tuple):
        if len(value) > 256:
            raise ValueError(f"{path} is too large")
        return [_json_value(item, path=f"{path}[]", depth=depth + 1) for item in value]
    if isinstance(value, Mapping):
        if len(value) > 256 or any(type(key) is not str for key in value):
            raise ValueError(f"{path} is not JSON-safe")
        return {
            key: _json_value(value[key], path=f"{path}.{key}", depth=depth + 1)
            for key in sorted(value)
        }
    raise ValueError(f"{path} is not JSON-safe")


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return tuple((key, _freeze(item)) for key, item in value.items())
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if type(value) is tuple:
        # A mapping is represented by sorted key/value pairs; ordinary arrays
        # are represented as tuples of non-pair values.
        if all(type(item) is tuple and len(item) == 2 and type(item[0]) is str for item in value):
            return {key: _thaw(item) for key, item in value}
        return [_thaw(item) for item in value]
    return value


def _bounded_json(value: Any) -> Any:
    detached = _json_value(value)
    if len(json.dumps(detached, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()) > _MAX_VALUE_BYTES:
        raise ValueError("mechanism value exceeds cap")
    return detached


def _operation(value: object, allowed: frozenset[str], name: str) -> tuple[str, dict[str, Any]]:
    if isinstance(value, Mapping):
        keys = set(value)
        if keys == {"kind", "args"}:
            kind, args = value["kind"], value["args"]
        elif keys == {"op", "args"}:
            kind, args = value["op"], value["args"]
        elif keys == {"op", "value"}:
            kind, args = value["op"], value["value"]
        else:
            raise ValueError(f"invalid {name}")
    elif type(value) in (tuple, list) and len(value) == 2:
        kind, args = value
    else:
        raise ValueError(f"invalid {name}")
    if type(kind) is not str or kind not in allowed:
        raise ValueError(f"unsupported {name}")
    args = _bounded_json(args)
    if isinstance(args, Mapping):
        normalized = dict(args)
    else:
        normalized = {"value": args}
    return kind, normalized


def _coordinate(args: Mapping[str, Any]) -> tuple[int, int]:
    if set(args) < {"x", "y"} or type(args["x"]) is not int or type(args["y"]) is not int:
        raise ValueError("invalid mechanism coordinate")
    if not 0 <= args["x"] <= 63 or not 0 <= args["y"] <= 63:
        raise ValueError("invalid mechanism coordinate")
    return args["x"], args["y"]


def _value_byte(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError("invalid cell value")
    return value


def _canonical_data(value: object) -> tuple[tuple[str, int], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        if any(type(key) is not str or type(item) is not int for key, item in value.items()):
            raise ValueError("invalid action data")
        return tuple(sorted(value.items()))
    if type(value) is tuple and all(
        type(item) is tuple and len(item) == 2 and type(item[0]) is str and type(item[1]) is int
        for item in value
    ):
        return tuple(sorted(value))
    raise ValueError("invalid action data")


def _action(value: object, data: object = None) -> tuple[str, tuple[tuple[str, int], ...]]:
    if type(value) is str:
        name, raw_data = value, data
    elif isinstance(value, Mapping):
        if set(value) != {"name", "data"}:
            raise ValueError("invalid action")
        name, raw_data = value["name"], value["data"]
    else:
        name = getattr(value, "name", None)
        raw_data = getattr(value, "data", data)
    if type(name) is not str or name not in _ACTIONS:
        raise ValueError("invalid action")
    canonical = _canonical_data(raw_data)
    if name == "ACTION6":
        if tuple(key for key, _ in canonical) != ("x", "y"):
            raise ValueError("invalid action data")
        if any(not 0 <= number <= 63 for _, number in canonical):
            raise ValueError("invalid action data")
    elif canonical:
        raise ValueError("invalid action data")
    return name, canonical


def _frame(value: object) -> tuple[tuple[int, ...], ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("invalid mechanism frame")
    rows: list[tuple[int, ...]] = []
    width: int | None = None
    for row in value:
        if not isinstance(row, (list, tuple)) or not row:
            raise ValueError("invalid mechanism frame")
        converted = tuple(_value_byte(item) for item in row)
        if width is None:
            width = len(converted)
        elif len(converted) != width:
            raise ValueError("invalid mechanism frame")
        rows.append(converted)
    if len(rows) * len(rows[0]) > _MAX_FRAME_CELLS:
        raise ValueError("mechanism frame exceeds cap")
    return tuple(rows)


def _mapping_args(args: Mapping[str, Any], required: set[str], optional: set[str] = set()) -> dict[str, Any]:
    if set(args) - required - optional or not required <= set(args):
        raise ValueError("invalid mechanism operation arguments")
    return dict(args)


@dataclass(frozen=True, slots=True)
class MechanismRule:
    """One action rule with pure guards and pure effects."""

    action: str
    guards: tuple[object, ...] = ()
    effects: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        _action(self.action)
        if type(self.guards) is not tuple or len(self.guards) > _MAX_GUARDS:
            raise ValueError("mechanism guard cap exceeded")
        if type(self.effects) is not tuple or len(self.effects) > _MAX_EFFECTS:
            raise ValueError("mechanism effect cap exceeded")
        normalized_guards = []
        for item in self.guards:
            kind, args = _operation(item, _GUARDS, "guard")
            normalized_guards.append((kind, _freeze(args)))
            _validate_guard(kind, args)
        normalized_effects = []
        for item in self.effects:
            kind, args = _operation(item, _EFFECTS, "effect")
            normalized_effects.append((kind, _freeze(args)))
            _validate_effect(kind, args)
        object.__setattr__(self, "action", self.action)
        object.__setattr__(self, "guards", tuple(normalized_guards))
        object.__setattr__(self, "effects", tuple(normalized_effects))

    def mapping(self) -> dict[str, object]:
        return {
            "action": self.action,
            "guards": [{"op": op, "args": _thaw(args)} for op, args in self.guards],
            "effects": [{"op": op, "args": _thaw(args)} for op, args in self.effects],
        }


def _validate_guard(kind: str, args: Mapping[str, Any]) -> None:
    if kind == "state_is":
        if set(args) != {"value"} or type(args["value"]) is not str or not args["value"]:
            raise ValueError("invalid state_is guard")
    elif kind == "level_is":
        if set(args) != {"value"} or type(args["value"]) is not int or args["value"] < 0:
            raise ValueError("invalid level_is guard")
    elif kind in {"cell_equals", "cell_in_bounds"}:
        required = {"x", "y"} | ({"value"} if kind == "cell_equals" else set())
        values = _mapping_args(args, required)
        _coordinate(values)
        if kind == "cell_equals":
            _value_byte(values["value"])
    elif kind == "action_data_equals":
        if set(args) != {"value"}:
            raise ValueError("invalid action_data_equals guard")
        _canonical_data(args["value"])
    elif kind == "entity_attr_equals":
        if set(args) != {"entity", "attr", "value"}:
            raise ValueError("invalid entity_attr_equals guard")
        _id(args["entity"], "entity")
        _id(args["attr"], "attribute")
        _bounded_json(args["value"])


def _validate_effect(kind: str, args: Mapping[str, Any]) -> None:
    if kind == "set_cell":
        values = _mapping_args(args, {"x", "y", "value"})
        _coordinate(values)
        _value_byte(values["value"])
    elif kind == "toggle_cell":
        values = _mapping_args(args, {"x", "y", "values"})
        _coordinate(values)
        raw = values["values"]
        if type(raw) not in (list, tuple) or len(raw) != 2 or raw[0] == raw[1]:
            raise ValueError("invalid toggle_cell values")
        _value_byte(raw[0])
        _value_byte(raw[1])
    elif kind == "translate_cells":
        values = _mapping_args(args, set(), {"dx", "dy", "value", "cells"})
        if "dx" not in values or "dy" not in values or type(values["dx"]) is not int or type(values["dy"]) is not int:
            raise ValueError("invalid translate_cells offset")
        if not -63 <= values["dx"] <= 63 or not -63 <= values["dy"] <= 63:
            raise ValueError("invalid translate_cells offset")
        if "value" in values:
            _value_byte(values["value"])
        if "cells" in values:
            if type(values["cells"]) not in (list, tuple) or len(values["cells"]) > 256:
                raise ValueError("invalid translate_cells cells")
            for item in values["cells"]:
                if type(item) not in (list, tuple) or len(item) != 2:
                    raise ValueError("invalid translate_cells cells")
                _coordinate({"x": item[0], "y": item[1]})
    elif kind == "set_state":
        if set(args) != {"value"} or type(args["value"]) is not str or not args["value"]:
            raise ValueError("invalid set_state effect")
    elif kind == "increment_level":
        if set(args) != {"value"} or type(args["value"]) is not int or not 0 < args["value"] <= 8:
            raise ValueError("invalid increment_level effect")


@dataclass(frozen=True, slots=True)
class MechanismPrediction:
    status: str
    frame: tuple[tuple[int, ...], ...] | None = None
    level: int | None = None
    state: str | None = None
    changed_cells: tuple[tuple[int, int, int, int], ...] = ()
    reason: str | None = None
    rule_count: int = 0

    def __post_init__(self) -> None:
        if self.status not in {"predicted", "unknown", "conflict"}:
            raise ValueError("invalid prediction status")
        if self.frame is not None:
            object.__setattr__(self, "frame", _frame(self.frame))
        if self.level is not None and (type(self.level) is not int or self.level < 0):
            raise ValueError("invalid prediction level")
        if self.state is not None and (type(self.state) is not str or not self.state):
            raise ValueError("invalid prediction state")


@dataclass(frozen=True, slots=True)
class MechanismSpec:
    game_id: str
    seed: int
    win_levels: int
    rules: tuple[MechanismRule, ...]
    revision: int = 0

    def __post_init__(self) -> None:
        _id(self.game_id, "game_id")
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("invalid seed")
        if type(self.win_levels) is not int or self.win_levels <= 0:
            raise ValueError("invalid win_levels")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("invalid revision")
        if type(self.rules) is not tuple or not self.rules or len(self.rules) > _MAX_RULES:
            raise ValueError("invalid mechanism rules")
        if any(type(rule) is not MechanismRule for rule in self.rules):
            raise ValueError("invalid mechanism rules")
        normalized = tuple(sorted(self.rules, key=lambda rule: json.dumps(rule.mapping(), sort_keys=True, separators=(",", ":"))))
        object.__setattr__(self, "rules", normalized)

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": "asterion.prime.p7-mechanism/v1",
            "game_id": self.game_id,
            "seed": self.seed,
            "win_levels": self.win_levels,
            "revision": self.revision,
            "rules": [rule.mapping() for rule in self.rules],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_mapping(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def predict(
        self,
        *,
        frame: object,
        action: object,
        data: object = None,
        level: int,
        state: str,
        entities: Mapping[str, object] | None = None,
    ) -> MechanismPrediction:
        try:
            stable = _frame(frame)
            action_name, action_data = _action(action, data)
            if type(level) is not int or level < 0 or level > self.win_levels:
                return MechanismPrediction("unknown", reason="level")
            if type(state) is not str or not state:
                return MechanismPrediction("unknown", reason="state")
        except (TypeError, ValueError):
            return MechanismPrediction("unknown", reason="input")

        matches: list[MechanismRule] = []
        for rule in self.rules:
            if rule.action != action_name:
                continue
            if _guards_match(rule.guards, stable, action_data, level, state, entities or {}):
                matches.append(rule)
        if not matches:
            return MechanismPrediction("unknown", frame=stable, level=level, state=state, reason="no-rule")
        if len(matches) != 1:
            return MechanismPrediction(
                "conflict", frame=stable, level=level, state=state,
                reason="ambiguous-rules", rule_count=len(matches),
            )
        try:
            after, after_level, after_state = _apply_effects(
                stable, level, state, matches[0].effects, self.win_levels
            )
            count, changed, _ = stable_changed_cells(stable, after)
            if count > 80:
                return MechanismPrediction(
                    "unknown", frame=after, level=after_level, state=after_state,
                    reason="changed-cell-cap",
                )
            return MechanismPrediction(
                "predicted",
                frame=after,
                level=after_level,
                state=after_state,
                changed_cells=changed,
                rule_count=1,
            )
        except (TypeError, ValueError, IndexError):
            return MechanismPrediction("unknown", frame=stable, level=level, state=state, reason="effect")


def _guards_match(
    guards: tuple[tuple[str, Any], ...],
    frame: tuple[tuple[int, ...], ...],
    data: tuple[tuple[str, int], ...],
    level: int,
    state: str,
    entities: Mapping[str, object],
) -> bool:
    for kind, frozen in guards:
        args = _thaw(frozen)
        if kind == "state_is" and state != args["value"]:
            return False
        if kind == "level_is" and level != args["value"]:
            return False
        if kind in {"cell_equals", "cell_in_bounds"}:
            x, y = args["x"], args["y"]
            in_bounds = 0 <= y < len(frame) and 0 <= x < len(frame[0])
            if kind == "cell_in_bounds" and not in_bounds:
                return False
            if kind == "cell_equals" and (not in_bounds or frame[y][x] != args["value"]):
                return False
        if kind == "action_data_equals" and data != _canonical_data(args["value"]):
            return False
        if kind == "entity_attr_equals":
            entity = entities.get(args["entity"])
            if not isinstance(entity, Mapping) or entity.get(args["attr"]) != args["value"]:
                return False
    return True


def _apply_effects(
    frame: tuple[tuple[int, ...], ...],
    level: int,
    state: str,
    effects: tuple[tuple[str, Any], ...],
    win_levels: int,
) -> tuple[tuple[tuple[int, ...], ...], int, str]:
    rows = [list(row) for row in frame]
    current_level, current_state = level, state
    for kind, frozen in effects:
        args = _thaw(frozen)
        if kind == "set_cell":
            x, y = _coordinate(args)
            if y >= len(rows) or x >= len(rows[0]):
                raise ValueError
            rows[y][x] = args["value"]
        elif kind == "toggle_cell":
            x, y = _coordinate(args)
            if y >= len(rows) or x >= len(rows[0]):
                raise ValueError
            values = args["values"]
            if rows[y][x] == values[0]:
                rows[y][x] = values[1]
            elif rows[y][x] == values[1]:
                rows[y][x] = values[0]
            else:
                raise ValueError
        elif kind == "translate_cells":
            dx, dy = args["dx"], args["dy"]
            selected = set()
            if "cells" in args:
                selected = {(item[0], item[1]) for item in args["cells"]}
            else:
                target = args.get("value")
                selected = {
                    (x, y)
                    for y, row in enumerate(rows)
                    for x, value in enumerate(row)
                    if value != 0 and (target is None or value == target)
                }
            moved: list[tuple[int, int, int]] = []
            for x, y in sorted(selected, key=lambda item: (item[1], item[0])):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < len(rows[0]) and 0 <= ny < len(rows)):
                    raise ValueError
                moved.append((nx, ny, rows[y][x]))
            for x, y in selected:
                rows[y][x] = 0
            for x, y, value in moved:
                rows[y][x] = value
        elif kind == "set_state":
            current_state = args["value"]
        elif kind == "increment_level":
            current_level += args["value"]
            if current_level > win_levels:
                raise ValueError
    return tuple(tuple(row) for row in rows), current_level, current_state


@dataclass(frozen=True, slots=True)
class ModelCertificate:
    game_id: str
    seed: int
    win_levels: int
    revision: int
    model_digest: str
    record_count: int
    sequence_start: int
    sequence_end: int
    coverage: str = "mechanism-retrodicted"

    def __post_init__(self) -> None:
        _id(self.game_id, "game_id")
        if type(self.seed) is not int or self.seed < 0 or type(self.win_levels) is not int or self.win_levels <= 0:
            raise ValueError("invalid certificate identity")
        if self.coverage != "mechanism-retrodicted":
            raise ValueError("invalid certificate coverage")
        if type(self.record_count) is not int or self.record_count < 2 or self.sequence_start != 0 or self.sequence_end != self.record_count - 1:
            raise ValueError("invalid certificate coverage")

    @property
    def planner_eligible(self) -> bool:
        return self.coverage == "mechanism-retrodicted"


def validate_mechanism(
    spec: MechanismSpec,
    records: Sequence[ArcHistoryRecord],
) -> ModelCertificate | None:
    """Return a certificate only when the mechanism explains every record."""

    if type(spec) is not MechanismSpec:
        return None
    try:
        rows = tuple(records)
    except (TypeError, ValueError):
        return None
    if (
        len(rows) < 2
        or any(type(record) is not ArcHistoryRecord for record in rows)
        or rows[0].sequence != 0
        or rows[0].game_id != spec.game_id
        or rows[0].seed != spec.seed
    ):
        return None
    for previous, record in zip(rows, rows[1:]):
        if (
            record.sequence != previous.sequence + 1
            or record.game_id != spec.game_id
            or record.seed != spec.seed
            or record.run_id != previous.run_id
            or record.before_state_sha256 != previous.after_state_sha256
            or record.before_frame_sha256 != previous.after_frame_sha256
            or record.before_frame_sha256 != digest(previous.frame)
            or record.after_frame_sha256 != digest(record.frame)
            or record.levels_completed < previous.levels_completed
        ):
            return None
        prediction = spec.predict(
            frame=previous.frame,
            action=record.action,
            data=record.data,
            level=previous.levels_completed,
            state=previous.state,
        )
        if prediction.status != "predicted" or prediction.frame != record.frame or prediction.level != record.levels_completed or prediction.state != record.state:
            return None
        try:
            count, cells, omitted = stable_changed_cells(previous.frame, record.frame)
        except ArcPredictionError:
            return None
        if (
            record.changed_cell_count != count
            or record.changed_cells != cells
            or record.changed_cells_omitted != omitted
            or prediction.changed_cells != cells
        ):
            return None
    return ModelCertificate(
        spec.game_id,
        spec.seed,
        spec.win_levels,
        spec.revision,
        spec.digest,
        len(rows),
        rows[0].sequence,
        rows[-1].sequence,
    )


__all__ = (
    "MechanismPrediction",
    "MechanismRule",
    "MechanismSpec",
    "ModelCertificate",
    "validate_mechanism",
)
