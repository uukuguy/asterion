"""Bounded declarative mechanism hypotheses for one P7 game.

This module is deliberately independent from the broker and engine.  A
mechanism can only inspect a supplied observation and apply a small allowlist
of pure frame/state effects; it cannot execute model text or access process,
filesystem, or network services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

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
        "clear_cells",
        "toggle_cell",
        "translate_cells",
        "translate_components",
        "set_state",
        "increment_level",
    }
)
_MAX_RULES = 64
_MAX_GUARDS = 8
_MAX_EFFECTS = 8
_MAX_VALUE_BYTES = 8192
_MAX_SPEC_BYTES = 65536
_MAX_FRAME_CELLS = 4096
_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class _FrozenMap:
    items: tuple[tuple[str, Any], ...]


@dataclass(frozen=True, slots=True)
class _FrozenSeq:
    items: tuple[Any, ...]


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
        return _FrozenMap(tuple((key, _freeze(item)) for key, item in value.items()))
    if type(value) is list:
        return _FrozenSeq(tuple(_freeze(item) for item in value))
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, _FrozenMap):
        return {key: _thaw(item) for key, item in value.items}
    if isinstance(value, _FrozenSeq):
        return [_thaw(item) for item in value.items]
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
    elif type(value) in (tuple, list) and len(cast(Sequence[object], value)) == 2:
        pair = cast(Sequence[object], value)
        kind, args = pair[0], pair[1]
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
        if type(self.action) is not str or self.action not in _ACTIONS:
            raise ValueError("invalid action")
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
            "guards": [{"op": cast(tuple[str, Any], item)[0], "args": _thaw(cast(tuple[str, Any], item)[1])} for item in self.guards],
            "effects": [{"op": cast(tuple[str, Any], item)[0], "args": _thaw(cast(tuple[str, Any], item)[1])} for item in self.effects],
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
    elif kind == "clear_cells":
        values = _mapping_args(args, {"value", "clear", "count"}, {"axis", "direction"})
        _value_byte(values["value"])
        _value_byte(values["clear"])
        if values["value"] == values["clear"]:
            raise ValueError("clear_cells source equals clear")
        if type(values["count"]) is not int or not 1 <= values["count"] <= 64:
            raise ValueError("invalid clear_cells count")
        if values.get("axis", "x") not in {"x", "y", "scan"}:
            raise ValueError("invalid clear_cells axis")
        if values.get("direction", "ascending") not in {"ascending", "descending"}:
            raise ValueError("invalid clear_cells direction")
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
    elif kind == "translate_components":
        values = _mapping_args(args, {"pattern", "clear", "dx", "dy", "count"})
        if type(values["dx"]) is not int or not -63 <= values["dx"] <= 63:
            raise ValueError("invalid translate_components offset")
        if type(values["dy"]) is not int or not -63 <= values["dy"] <= 63:
            raise ValueError("invalid translate_components offset")
        _value_byte(values["clear"])
        if type(values["count"]) is not int or not 1 <= values["count"] <= 64:
            raise ValueError("invalid translate_components count")
        pattern = values["pattern"]
        if type(pattern) not in (list, tuple) or not 1 <= len(pattern) <= 256:
            raise ValueError("invalid translate_components pattern")
        coordinates: set[tuple[int, int]] = set()
        for item in pattern:
            if type(item) not in (list, tuple) or len(item) != 3:
                raise ValueError("invalid translate_components pattern")
            x, y, value = item
            if type(x) is not int or type(y) is not int or not -63 <= x <= 63 or not -63 <= y <= 63:
                raise ValueError("invalid translate_components pattern")
            if (x, y) in coordinates:
                raise ValueError("invalid translate_components pattern")
            coordinates.add((x, y))
            _value_byte(value)
        if values["clear"] in {item[2] for item in pattern}:
            raise ValueError("translate_components source equals clear")
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
    changed_cells_omitted: int = 0
    reason: str | None = None
    rule_count: int = 0

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in {"predicted", "unknown", "conflict"}:
            raise ValueError("invalid prediction status")
        if self.frame is not None:
            object.__setattr__(self, "frame", _frame(self.frame))
        if self.level is not None and (type(self.level) is not int or self.level < 0):
            raise ValueError("invalid prediction level")
        if self.state is not None and (type(self.state) is not str or not self.state):
            raise ValueError("invalid prediction state")
        if type(self.changed_cells) is not tuple or len(self.changed_cells) > 80:
            raise ValueError("invalid prediction changed cells")
        if type(self.changed_cells_omitted) is not int or self.changed_cells_omitted < 0:
            raise ValueError("invalid prediction omitted count")
        for item in self.changed_cells:
            if (
                type(item) is not tuple
                or len(item) != 4
                or any(type(part) is not int for part in item)
                or not 0 <= item[0] <= 63
                or not 0 <= item[1] <= 63
                or not 0 <= item[2] <= 255
                or not 0 <= item[3] <= 255
                or item[2] == item[3]
            ):
                raise ValueError("invalid prediction changed cells")
        coordinates = tuple((item[1], item[0]) for item in self.changed_cells)
        if coordinates != tuple(sorted(set(coordinates))):
            raise ValueError("invalid prediction changed cells")
        if self.reason is not None and (
            type(self.reason) is not str or not self.reason or len(self.reason) > 128
        ):
            raise ValueError("invalid prediction reason")
        if type(self.rule_count) is not int or not 0 <= self.rule_count <= _MAX_RULES:
            raise ValueError("invalid prediction rule count")


@dataclass(frozen=True, slots=True)
class SimPrediction:
    """Pure simulator result with explicit unknown/conflict outcomes."""

    status: str
    next_state: object | None = None
    changed_cells: tuple[tuple[int, int, int, int], ...] = ()
    changed_cells_omitted: int = 0
    rule_ids: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"predicted", "unknown", "conflict"}:
            raise ValueError("invalid simulation status")
        if self.status == "predicted" and self.next_state is None:
            raise ValueError("predicted simulation needs a next state")
        if self.status != "predicted" and self.next_state is not None:
            raise ValueError("unknown/conflict cannot expose a next state")
        if type(self.changed_cells) is not tuple or len(self.changed_cells) > 80:
            raise ValueError("invalid simulation changed cells")
        if type(self.changed_cells_omitted) is not int or self.changed_cells_omitted < 0:
            raise ValueError("invalid simulation omitted count")
        if any(
            type(item) is not tuple or len(item) != 4
            or any(type(part) is not int for part in item)
            or not 0 <= item[0] <= 63 or not 0 <= item[1] <= 63
            or not 0 <= item[2] <= 255 or not 0 <= item[3] <= 255
            or item[2] == item[3]
            for item in self.changed_cells
        ):
            raise ValueError("invalid simulation changed cells")
        if self.reason is not None and (type(self.reason) is not str or not self.reason):
            raise ValueError("invalid simulation reason")


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
        if type(self.rules) is not tuple or len(self.rules) > _MAX_RULES:
            raise ValueError("invalid mechanism rules")
        if any(type(rule) is not MechanismRule for rule in self.rules):
            raise ValueError("invalid mechanism rules")
        normalized = tuple(sorted(self.rules, key=lambda rule: json.dumps(rule.mapping(), sort_keys=True, separators=(",", ":"))))
        object.__setattr__(self, "rules", normalized)
        encoded = json.dumps(
            {
                "schema": "asterion.prime.p7-mechanism/v1",
                "game_id": self.game_id,
                "seed": self.seed,
                "win_levels": self.win_levels,
                "revision": self.revision,
                "rules": [rule.mapping() for rule in normalized],
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_SPEC_BYTES:
            raise ValueError("mechanism spec exceeds cap")

    @classmethod
    def from_mapping(cls, value: object) -> "MechanismSpec":
        if type(value) is not dict or set(value) != {"schema", "game_id", "seed", "win_levels", "revision", "rules"}:
            raise ValueError("invalid mechanism schema")
        if value["schema"] != "asterion.prime.p7-mechanism/v1" or type(value["rules"]) is not list:
            raise ValueError("invalid mechanism schema")
        rules = []
        for item in value["rules"]:
            if type(item) is not dict or set(item) != {"action", "guards", "effects"}:
                raise ValueError("invalid mechanism rule")
            if type(item["guards"]) is not list or type(item["effects"]) is not list:
                raise ValueError("invalid mechanism operations")
            rules.append(MechanismRule(item["action"], tuple(item["guards"]), tuple(item["effects"])))
        return cls(value["game_id"], value["seed"], value["win_levels"], tuple(rules), value["revision"])

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
        encoded = json.dumps(self.to_mapping(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > _MAX_SPEC_BYTES:
            raise ValueError("mechanism spec exceeds cap")
        return encoded

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
            if _guards_match(cast(tuple[tuple[str, Any], ...], rule.guards), stable, action_data, level, state, entities or {}):
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
                stable, level, state, cast(tuple[tuple[str, Any], ...], matches[0].effects), self.win_levels
            )
            count, changed, omitted = stable_changed_cells(stable, after)
            return MechanismPrediction(
                "predicted",
                frame=after,
                level=after_level,
                state=after_state,
                changed_cells=changed,
                changed_cells_omitted=omitted,
                rule_count=1,
            )
        except (TypeError, ValueError, IndexError):
            return MechanismPrediction("unknown", frame=stable, level=level, state=state, reason="effect")


def compile_effect_hypothesis(hypothesis: object) -> MechanismSpec | None:
    """Compile one conservative effect candidate into the pure rule subset.

    Candidates with unsupported or incomplete evidence stay hypotheses.  The
    resulting spec is not a certificate; callers must still retrodict history
    and verify a separate probe before using it for planning.
    """

    from .experience_induction import EffectHypothesis

    if not isinstance(hypothesis, EffectHypothesis):
        return None
    if hypothesis.status != "hypothesis" or hypothesis.template is None:
        return None
    template = hypothesis.template
    if (
        hypothesis.support_count < 2
        and template.outcome not in {"level-transition", "game-over"}
    ):
        return None
    guards: list[object] = [{"op": "level_is", "args": {"value": template.level}}]
    if template.data:
        guards.append({"op": "action_data_equals", "args": {"value": dict(template.data)}})
    effects: list[object] = []
    if template.motions:
        for motion in template.motions:
            pattern = [
                [x, y, motion.source_value]
                for x, y in motion.shape
            ]
            effects.append({"op": "translate_components", "args": {
                "pattern": pattern,
                "clear": motion.clear_value,
                "dx": motion.dx,
                "dy": motion.dy,
                "count": motion.count,
            }})
        # A frame delta can contain an independently changing boundary in
        # addition to the translated component.  Encode a deterministic
        # bounded consumption of that source colour so the complete witness
        # remains replayable instead of discarding the residual change.
        used_pairs = {
            (motion.source_value, motion.clear_value)
            for motion in template.motions
        } | {
            (motion.clear_value, motion.source_value)
            for motion in template.motions
        }
        residual = [
            change for change in template.full_changed_cells
            if (change[2], change[3]) not in used_pairs
        ]
        by_residual: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for x, y, old, new in residual:
            by_residual.setdefault((old, new), []).append((x, y))
        for (old, new), cells in sorted(by_residual.items()):
            if not cells:
                continue
            if any((old, other_new) != (old, new) for _x, _y, _old, other_new in residual):
                return None
            axis = "x" if len({y for _x, y in cells}) == 1 else (
                "y" if len({x for x, _y in cells}) == 1 else "scan"
            )
            direction = "ascending"
            if axis == "x" and len(cells) > 1 and cells[0][0] > cells[-1][0]:
                direction = "descending"
            if axis == "y" and len(cells) > 1 and cells[0][1] > cells[-1][1]:
                direction = "descending"
            effects.append({"op": "clear_cells", "args": {
                "value": old,
                "clear": new,
                "count": len(cells),
                "axis": axis,
                "direction": direction,
            }})
    else:
        if template.changed_cells_omitted:
            return None
        for x, y, old, new in template.changed_cells:
            guards.append({"op": "cell_equals", "args": {"x": x, "y": y, "value": old}})
            effects.append({"op": "set_cell", "args": {"x": x, "y": y, "value": new}})
    if template.levels_completed > template.level:
        effects.append({
            "op": "increment_level",
            "args": {"value": template.levels_completed - template.level},
        })
    if template.state in {"WIN", "GAME_OVER"}:
        effects.append({"op": "set_state", "args": {"value": template.state}})
    try:
        return MechanismSpec(
            hypothesis.game_id, hypothesis.seed, hypothesis.win_levels,
            (MechanismRule(template.action, tuple(guards), tuple(effects)),),
            revision=0,
        )
    except (TypeError, ValueError):
        return None


def simulate_step(spec: MechanismSpec, sim_state: object, action: object) -> SimPrediction:
    """Apply one pure declarative step to a :class:`SimState`.

    Unknown hidden entity state is never treated as a default value.  This is
    intentionally a thin adapter around :meth:`MechanismSpec.predict`, so the
    simulator and checked-history validator share exactly one effect algebra.
    """

    from .experience_induction import SimState

    if not isinstance(spec, MechanismSpec) or not isinstance(sim_state, SimState):
        return SimPrediction("unknown", reason="invalid-input")
    if sim_state.unknown_fields and any(
        kind == "entity_attr_equals"
        for rule in spec.rules
        for kind, _ in cast(tuple[tuple[str, Any], ...], rule.guards)
    ):
        return SimPrediction("unknown", reason="unknown-hidden-state")
    entities = dict(sim_state.entities)
    prediction = spec.predict(
        frame=sim_state.frame,
        action=action,
        level=sim_state.level,
        state=sim_state.state,
        entities=entities,
    )
    if prediction.status != "predicted" or prediction.frame is None or prediction.level is None or prediction.state is None:
        return SimPrediction(prediction.status, reason=prediction.reason)
    try:
        next_state = SimState.from_observation(
            frame=prediction.frame,
            level=prediction.level,
            state=prediction.state,
            available_actions=sim_state.available_actions,
            entities=entities,
            unknown_fields=sim_state.unknown_fields,
        )
    except (TypeError, ValueError):
        return SimPrediction("unknown", reason="next-state")
    return SimPrediction(
        "predicted", next_state=next_state,
        changed_cells=prediction.changed_cells,
        changed_cells_omitted=prediction.changed_cells_omitted,
        rule_ids=(f"rule:{prediction.rule_count}",),
    )


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
        elif kind == "clear_cells":
            source = args["value"]
            clear = args["clear"]
            positions = [
                (x, y)
                for y, row in enumerate(rows)
                for x, value in enumerate(row)
                if value == source
            ]
            axis = args.get("axis", "x")
            if axis == "x":
                positions.sort(key=lambda item: (item[0], item[1]))
            elif axis == "y":
                positions.sort(key=lambda item: (item[1], item[0]))
            else:
                positions.sort(key=lambda item: (item[1], item[0]))
            if args.get("direction", "ascending") == "descending":
                positions.reverse()
            if len(positions) < args["count"]:
                raise ValueError
            for x, y in positions[:args["count"]]:
                rows[y][x] = clear
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
        elif kind == "translate_components":
            pattern = tuple((item[0], item[1], item[2]) for item in args["pattern"])
            dx, dy, clear, expected_count = args["dx"], args["dy"], args["clear"], args["count"]
            height, width = len(rows), len(rows[0])
            origins: list[tuple[int, int]] = []
            for origin_y in range(height):
                for origin_x in range(width):
                    source = {(origin_x + rel_x, origin_y + rel_y): value for rel_x, rel_y, value in pattern}
                    if any(
                        x < 0 or y < 0 or x >= width or y >= height
                        or rows[y][x] != value
                        for (x, y), value in source.items()
                    ):
                        continue
                    destination = {(x + dx, y + dy) for x, y in source}
                    if any(
                        x < 0 or y < 0 or x >= width or y >= height
                        or (
                            rows[y][x] != source.get((x, y), clear)
                            if (x, y) in source
                            else rows[y][x] != clear
                        )
                        for x, y in destination
                    ):
                        continue
                    origins.append((origin_x, origin_y))
            if len(origins) != expected_count:
                raise ValueError
            source_cells: set[tuple[int, int]] = set()
            destination_cells: set[tuple[int, int]] = set()
            for origin_x, origin_y in origins:
                for rel_x, rel_y, _value in pattern:
                    source_cell = (origin_x + rel_x, origin_y + rel_y)
                    destination_cell = (source_cell[0] + dx, source_cell[1] + dy)
                    if source_cell in source_cells or destination_cell in destination_cells:
                        raise ValueError
                    source_cells.add(source_cell)
                    destination_cells.add(destination_cell)
            for x, y in source_cells - destination_cells:
                rows[y][x] = clear
            for origin_x, origin_y in origins:
                for rel_x, rel_y, value in pattern:
                    rows[origin_y + rel_y + dy][origin_x + rel_x + dx] = value
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
    current_frame_sha256: str | None = None
    world_model_version: int | None = None
    # For an evidence-scoped certificate this records the transition
    # sequences that the mechanism actually explains.  A full retrodiction
    # keeps the historical contiguous range for backwards compatibility.
    covered_sequences: tuple[int, ...] = ()
    _validated: bool = field(default=False, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _id(self.game_id, "game_id")
        if (
            type(self.seed) is not int
            or self.seed < 0
            or type(self.win_levels) is not int
            or self.win_levels <= 0
            or type(self.revision) is not int
            or self.revision < 0
            or type(self.model_digest) is not str
            or _HASH.fullmatch(self.model_digest) is None
        ):
            raise ValueError("invalid certificate identity")
        if type(self.coverage) is not str or self.coverage not in {
            "mechanism-retrodicted", "mechanism-evidence", "persisted-confirmed",
        }:
            raise ValueError("invalid certificate coverage")
        if self.current_frame_sha256 is not None and _HASH.fullmatch(self.current_frame_sha256) is None:
            raise ValueError("invalid certificate current frame")
        if self.world_model_version is not None and (
            type(self.world_model_version) is not int or self.world_model_version < 0
        ):
            raise ValueError("invalid certificate world revision")
        if type(self.record_count) is not int or self.record_count < 1:
            raise ValueError("invalid certificate coverage")
        legacy_unissued = (
            self.coverage == "mechanism-retrodicted"
            and self.covered_sequences == ()
            and self.sequence_start == 0
            and self.sequence_end == self.record_count - 1
        )
        if legacy_unissued:
            return
        if (
            type(self.sequence_start) is not int
            or type(self.sequence_end) is not int
            or self.sequence_start < 1
            or self.sequence_end < self.sequence_start
            or type(self.covered_sequences) is not tuple
            or any(type(sequence) is not int or sequence < 1 for sequence in self.covered_sequences)
            or tuple(sorted(set(self.covered_sequences))) != self.covered_sequences
            or len(self.covered_sequences) != (
                self.record_count - 1
                if self.coverage == "mechanism-retrodicted"
                else self.record_count
            )
        ):
            raise ValueError("invalid certificate coverage")
        if self.coverage == "mechanism-retrodicted":
            if self.sequence_start != 1 or self.sequence_end != self.record_count - 1:
                raise ValueError("invalid full certificate coverage")
        elif self.covered_sequences[-1] != self.sequence_end:
            raise ValueError("invalid evidence certificate coverage")

    @classmethod
    def _issued(
        cls, game_id: str, seed: int, win_levels: int, revision: int,
        model_digest: str, record_count: int, sequence_start: int, sequence_end: int,
        *, current_frame_sha256: str | None = None, world_model_version: int | None = None,
        covered_sequences: tuple[int, ...] = (), coverage: str = "mechanism-retrodicted",
    ) -> "ModelCertificate":
        if not covered_sequences:
            covered_sequences = tuple(range(sequence_start, sequence_end + 1))
        certificate = cls(
            game_id, seed, win_levels, revision, model_digest, record_count,
            sequence_start, sequence_end, coverage=coverage,
            current_frame_sha256=current_frame_sha256,
            world_model_version=world_model_version,
            covered_sequences=covered_sequences,
        )
        object.__setattr__(certificate, "_validated", True)
        return certificate

    @property
    def planner_eligible(self) -> bool:
        return self._validated is True and self.coverage in {
            "mechanism-retrodicted", "mechanism-evidence", "persisted-confirmed",
        }


def validate_mechanism(
    spec: MechanismSpec,
    records: Sequence[ArcHistoryRecord],
    *,
    entities: Mapping[str, object] | None = None,
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
            entities=entities or {},
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
            or prediction.changed_cells_omitted != omitted
        ):
            return None
    return ModelCertificate._issued(
        spec.game_id,
        spec.seed,
        spec.win_levels,
        spec.revision,
        spec.digest,
        len(rows),
        rows[1].sequence,
        rows[-1].sequence,
        current_frame_sha256=digest(rows[-1].frame),
        covered_sequences=tuple(record.sequence for record in rows[1:]),
    )


def validate_mechanism_evidence(
    spec: MechanismSpec,
    records: Sequence[ArcHistoryRecord],
    evidence_sequences: Sequence[int],
    *,
    entities: Mapping[str, object] | None = None,
) -> ModelCertificate | None:
    """Certify only the transitions covered by an induced mechanism.

    A game history contains exploratory actions that may be unrelated to a
    candidate rule.  Requiring one small rule to explain every exploratory
    action prevents useful experience from ever becoming a model.  This
    validator keeps the safety property by requiring every selected evidence
    transition to reproduce its exact frame, state, level, and changed-cell
    witness.  Unselected transitions remain unknown and are never treated as
    evidence for the model.

    Ordinary frame effects need two independent observations before they can
    be certified.  A level-transition or terminal effect has a direct outcome
    witness and may be certified from one observation.  The compiler already
    applies the same minimum when creating a candidate.
    """

    if type(spec) is not MechanismSpec:
        return None
    try:
        rows = tuple(records)
        selected = tuple(evidence_sequences)
    except (TypeError, ValueError):
        return None
    if (
        not rows
        or any(type(record) is not ArcHistoryRecord for record in rows)
        or any(type(sequence) is not int or sequence < 1 for sequence in selected)
        or tuple(sorted(set(selected))) != selected
        or not selected
        or len(rows) < 2
    ):
        return None
    by_sequence = {record.sequence: record for record in rows}
    if len(by_sequence) != len(rows):
        return None
    rules = tuple(spec.rules)
    if not rules or any(
        rule.action not in {by_sequence[sequence].action for sequence in selected if sequence in by_sequence}
        for rule in rules
    ):
        return None
    has_direct_terminal = any(
        operation[0] in {"increment_level", "set_state"}
        for rule in rules
        for operation in rule.effects
    )
    minimum = 1 if has_direct_terminal else 2
    if len(selected) < minimum:
        return None
    for sequence in selected:
        record = by_sequence.get(sequence)
        previous = by_sequence.get(sequence - 1)
        if record is None or previous is None:
            return None
        if (
            record.game_id != spec.game_id
            or record.seed != spec.seed
            or previous.game_id != record.game_id
            or previous.seed != record.seed
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
            entities=entities or {},
        )
        if (
            prediction.status != "predicted"
            or prediction.frame != record.frame
            or prediction.level != record.levels_completed
            or prediction.state != record.state
        ):
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
            or prediction.changed_cells_omitted != omitted
        ):
            return None
    return ModelCertificate._issued(
        spec.game_id,
        spec.seed,
        spec.win_levels,
        spec.revision,
        spec.digest,
        len(selected),
        selected[0],
        selected[-1],
        coverage="mechanism-evidence",
        covered_sequences=selected,
        current_frame_sha256=digest(rows[-1].frame),
    )


__all__ = (
    "MechanismPrediction",
    "MechanismRule",
    "MechanismSpec",
    "ModelCertificate",
    "SimPrediction",
    "compile_effect_hypothesis",
    "simulate_step",
    "validate_mechanism",
    "validate_mechanism_evidence",
)
