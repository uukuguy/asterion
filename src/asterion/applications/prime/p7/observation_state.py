"""Immutable, bounded observation state for P7 game reasoning.

The native ARC broker currently exposes a frame-centric mapping.  This module
keeps that wire shape as an input while giving planning code one stable state
object that can also carry HUD values, timers, resources, object relations and
recent events.  The class deliberately contains observations only: it does not
infer roles, authorize actions, or execute game code.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import math
import re
from types import MappingProxyType


_MAX_DEPTH = 8
_MAX_STRING = 512
_MAX_MAPPING_ITEMS = 64
_MAX_LIST_ITEMS = 256
_MAX_ENTITIES = 128
_MAX_RELATIONS = 256
_MAX_EVENTS = 256
_MAX_ACTIONS = 32
_MAX_FRAME_CELLS = 262_144
_MAX_PROJECTION_BYTES = 512 * 1024
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ACTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_INPUT_KINDS = frozenset(("keyboard", "click", "keyboard_click", "unknown"))


class ObservationStateError(ValueError):
    """Raised when a P7 observation cannot become a bounded JSON state."""



def _validate_string(value: object, name: str, *, pattern: re.Pattern[str] | None = None) -> str:
    if type(value) is not str or not value or len(value) > _MAX_STRING:
        raise ObservationStateError(f"invalid {name}")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ObservationStateError(f"invalid {name}")
    return value


def _freeze_json(value: object, *, path: str = "value", depth: int = 0) -> object:
    """Copy JSON values into immutable bounded containers."""

    if depth > _MAX_DEPTH:
        raise ObservationStateError(f"{path} is too deeply nested")
    if value is None or type(value) in (str, bool, int):
        if type(value) is str and len(value) > _MAX_STRING:
            raise ObservationStateError(f"{path} string is too long")
        if type(value) is int and isinstance(value, bool):
            raise ObservationStateError(f"{path} is not JSON-safe")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ObservationStateError(f"{path} must be finite")
        return value
    if isinstance(value, Mapping):
        if len(value) > _MAX_MAPPING_ITEMS:
            raise ObservationStateError(f"{path} has too many fields")
        if any(type(key) is not str or len(key) > _MAX_STRING for key in value):
            raise ObservationStateError(f"{path} has an invalid key")
        result: dict[str, object] = {}
        for key in sorted(value):
            result[key] = _freeze_json(value[key], path=f"{path}.{key}", depth=depth + 1)
        return MappingProxyType(result)
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_LIST_ITEMS:
            raise ObservationStateError(f"{path} has too many items")
        return tuple(_freeze_json(item, path=f"{path}[]", depth=depth + 1) for item in value)
    raise ObservationStateError(f"{path} is not JSON-safe")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise ObservationStateError(f"{name} must be an object")
    frozen = _freeze_json(value, path=name)
    if not isinstance(frozen, Mapping):  # pragma: no cover - guarded above
        raise ObservationStateError(f"{name} must be an object")
    return frozen


def _frame(value: object) -> object:
    """Validate a 2-D or 3-D uint8 frame and freeze its shape."""

    if not isinstance(value, (list, tuple)) or not value:
        raise ObservationStateError("frame must be a non-empty 2-D or 3-D array")
    rows_or_layers = value
    # A frame projection from the broker is normally [layer][row][cell], while
    # compact tests and adapters may provide [row][cell].
    is_2d = all(isinstance(row, (list, tuple)) and row and all(type(cell) is int and not isinstance(cell, bool) for cell in row) for row in rows_or_layers)
    if is_2d:
        rows = []
        width: int | None = None
        for row in rows_or_layers:
            assert isinstance(row, (list, tuple))
            if width is None:
                width = len(row)
            elif len(row) != width:
                raise ObservationStateError("frame rows must be rectangular")
            rows.append(tuple(row))
        cells = len(rows) * (width or 0)
        if cells > _MAX_FRAME_CELLS:
            raise ObservationStateError("frame is too large")
        if any(cell < 0 or cell > 255 for row in rows for cell in row):
            raise ObservationStateError("frame cells must be uint8 values")
        return tuple(rows)
    layers = []
    width: int | None = None
    height: int | None = None
    cells = 0
    for layer in rows_or_layers:
        if not isinstance(layer, (list, tuple)) or not layer:
            raise ObservationStateError("frame layers must be non-empty")
        layer_rows = []
        for row in layer:
            if not isinstance(row, (list, tuple)) or not row:
                raise ObservationStateError("frame rows must be non-empty")
            if any(type(cell) is not int or isinstance(cell, bool) or not 0 <= cell <= 255 for cell in row):
                raise ObservationStateError("frame cells must be uint8 values")
            if width is None:
                width = len(row)
            elif len(row) != width:
                raise ObservationStateError("frame rows must be rectangular")
            layer_rows.append(tuple(row))
        if height is None:
            height = len(layer_rows)
        elif len(layer_rows) != height:
            raise ObservationStateError("frame layers must have equal dimensions")
        cells += len(layer_rows) * (width or 0)
        if cells > _MAX_FRAME_CELLS:
            raise ObservationStateError("frame is too large")
        layers.append(tuple(layer_rows))
    return tuple(layers)


def _attributes(raw: Mapping[str, object], consumed: set[str]) -> Mapping[str, object]:
    """Retain all unrecognised object fields in an immutable attributes map."""

    nested = raw.get("attributes", {})
    if nested is None:
        nested = {}
    if not isinstance(nested, Mapping):
        raise ObservationStateError("attributes must be an object")
    attrs: dict[str, object] = dict(nested)
    if any(key in consumed for key in attrs):
        raise ObservationStateError("attributes contain reserved fields")
    for key, value in raw.items():
        if key not in consumed and key != "attributes":
            attrs[key] = value
    return _mapping(attrs, "attributes")


def _record_id(raw: Mapping[str, object], *, keys: tuple[str, ...], index: int) -> str:
    for key in keys:
        if key in raw:
            return _validate_string(raw[key], key, pattern=_ID)
    raise ObservationStateError(f"record {index} has no identifier")


@dataclass(frozen=True, slots=True)
class EntityObservation:
    """One detected entity and its bounded attributes."""

    entity_id: str
    kind: str | None = None
    attributes: Mapping[str, object] = MappingProxyType({})

    def __post_init__(self) -> None:
        _validate_string(self.entity_id, "entity_id", pattern=_ID)
        if self.kind is not None:
            _validate_string(self.kind, "kind", pattern=_ID)
        object.__setattr__(self, "attributes", _mapping(self.attributes, "attributes"))

    def __hash__(self) -> int:
        return hash(_canonical_json(self.to_projection()))

    def to_projection(self) -> dict[str, object]:
        body: dict[str, object] = {"id": self.entity_id}
        if self.kind is not None:
            body["kind"] = self.kind
        body.update(_thaw_json(self.attributes))  # type: ignore[arg-type]
        return body


@dataclass(frozen=True, slots=True)
class RelationObservation:
    """A directed relation between two detected entities."""

    source: str
    relation: str
    target: str
    attributes: Mapping[str, object] = MappingProxyType({})

    def __post_init__(self) -> None:
        _validate_string(self.source, "source", pattern=_ID)
        _validate_string(self.relation, "relation", pattern=_ID)
        _validate_string(self.target, "target", pattern=_ID)
        object.__setattr__(self, "attributes", _mapping(self.attributes, "attributes"))

    def __hash__(self) -> int:
        return hash(_canonical_json(self.to_projection()))

    def to_projection(self) -> dict[str, object]:
        body: dict[str, object] = {
            "source": self.source,
            "relation": self.relation,
            "target": self.target,
        }
        body.update(_thaw_json(self.attributes))  # type: ignore[arg-type]
        return body


@dataclass(frozen=True, slots=True)
class EventObservation:
    """A bounded event emitted by the game or inferred from a transition."""

    kind: str
    attributes: Mapping[str, object] = MappingProxyType({})
    sequence: int | None = None

    def __post_init__(self) -> None:
        _validate_string(self.kind, "event kind", pattern=_ID)
        if self.sequence is not None and (type(self.sequence) is not int or self.sequence < 0):
            raise ObservationStateError("invalid event sequence")
        object.__setattr__(self, "attributes", _mapping(self.attributes, "attributes"))

    def __hash__(self) -> int:
        return hash(_canonical_json(self.to_projection()))

    def to_projection(self) -> dict[str, object]:
        body: dict[str, object] = {"kind": self.kind}
        if self.sequence is not None:
            body["sequence"] = self.sequence
        body.update(_thaw_json(self.attributes))  # type: ignore[arg-type]
        return body


def _canonical_json(value: object) -> str:
    return json.dumps(_thaw_json(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _classify_input(actions: tuple[str, ...]) -> str:
    has_click = "ACTION6" in actions
    has_keyboard = any(action != "ACTION6" for action in actions)
    if has_click and has_keyboard:
        return "keyboard_click"
    if has_click:
        return "click"
    if has_keyboard:
        return "keyboard"
    return "unknown"


def _entity_records(value: object) -> tuple[EntityObservation, ...]:
    if value is None:
        return ()
    records: list[EntityObservation] = []
    if isinstance(value, Mapping):
        iterable = []
        for key, item in value.items():
            if type(key) is not str or not isinstance(item, Mapping):
                raise ObservationStateError("entity mapping is invalid")
            iterable.append({"id": key, **dict(item)})
    elif isinstance(value, (list, tuple)):
        iterable = list(value)
    else:
        raise ObservationStateError("entities must be an object or array")
    if len(iterable) > _MAX_ENTITIES:
        raise ObservationStateError("too many entities")
    seen: set[str] = set()
    for index, item in enumerate(iterable):
        if not isinstance(item, Mapping):
            raise ObservationStateError(f"entity {index} is invalid")
        entity_id = _record_id(item, keys=("id", "entity_id", "name"), index=index)
        if entity_id in seen:
            raise ObservationStateError("duplicate entity id")
        seen.add(entity_id)
        kind = item.get("kind", item.get("type"))
        if kind is not None:
            _validate_string(kind, "kind", pattern=_ID)
        records.append(EntityObservation(entity_id, kind, _attributes(item, {"id", "entity_id", "name", "kind", "type"})))
    return tuple(sorted(records, key=lambda item: item.entity_id))


def _relation_records(value: object) -> tuple[RelationObservation, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ObservationStateError("relations must be an array")
    if len(value) > _MAX_RELATIONS:
        raise ObservationStateError("too many relations")
    records: list[RelationObservation] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ObservationStateError(f"relation {index} is invalid")
        source = item.get("source", item.get("from"))
        target = item.get("target", item.get("to"))
        relation = item.get("relation", item.get("kind"))
        source = _validate_string(source, "source", pattern=_ID)
        target = _validate_string(target, "target", pattern=_ID)
        relation = _validate_string(relation, "relation", pattern=_ID)
        records.append(RelationObservation(source, relation, target, _attributes(item, {"source", "from", "target", "to", "relation", "kind"})))
    return tuple(sorted(records, key=lambda item: (item.source, item.relation, item.target, _canonical_json(item.attributes))))


def _event_records(value: object) -> tuple[EventObservation, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ObservationStateError("events must be an array")
    if len(value) > _MAX_EVENTS:
        raise ObservationStateError("too many events")
    records: list[EventObservation] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ObservationStateError(f"event {index} is invalid")
        kind = item.get("kind", item.get("event"))
        kind = _validate_string(kind, "event kind", pattern=_ID)
        sequence = item.get("sequence")
        if sequence is not None and (type(sequence) is not int or sequence < 0):
            raise ObservationStateError("invalid event sequence")
        records.append(EventObservation(kind, _attributes(item, {"kind", "event", "sequence"}), sequence))
    return tuple(sorted(records, key=lambda item: (item.sequence is None, item.sequence if item.sequence is not None else 0, item.kind, _canonical_json(item.attributes))))


@dataclass(frozen=True, slots=True, repr=False)
class ObservationState:
    """One immutable, bounded observation suitable for model state keys."""

    frame: object
    available_actions: tuple[str, ...] = ()
    levels_completed: int = 0
    state: str = "NOT_FINISHED"
    win_levels: int | None = None
    input_kind: str = "unknown"
    hud: Mapping[str, object] = MappingProxyType({})
    timers: Mapping[str, object] = MappingProxyType({})
    resources: Mapping[str, object] = MappingProxyType({})
    entities: tuple[EntityObservation, ...] = ()
    relations: tuple[RelationObservation, ...] = ()
    events: tuple[EventObservation, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "frame", _frame(self.frame))
        if type(self.available_actions) is not tuple:
            raise ObservationStateError("available_actions must be a tuple")
        actions = tuple(_validate_string(item, "action", pattern=_ACTION) for item in self.available_actions)
        if len(actions) > _MAX_ACTIONS or len(set(actions)) != len(actions) or tuple(sorted(actions)) != actions:
            raise ObservationStateError("available_actions must be sorted and unique")
        object.__setattr__(self, "available_actions", actions)
        if type(self.levels_completed) is not int or self.levels_completed < 0:
            raise ObservationStateError("invalid levels_completed")
        _validate_string(self.state, "state")
        if self.win_levels is not None and (type(self.win_levels) is not int or self.win_levels <= 0 or self.levels_completed > self.win_levels):
            raise ObservationStateError("invalid win_levels")
        if self.input_kind not in _INPUT_KINDS:
            raise ObservationStateError("invalid input_kind")
        derived = _classify_input(actions)
        if self.input_kind != "unknown" and self.input_kind != derived:
            raise ObservationStateError("input_kind does not match available_actions")
        object.__setattr__(self, "input_kind", derived if self.input_kind == "unknown" else self.input_kind)
        object.__setattr__(self, "hud", _mapping(self.hud, "hud"))
        object.__setattr__(self, "timers", _mapping(self.timers, "timers"))
        object.__setattr__(self, "resources", _mapping(self.resources, "resources"))
        if type(self.entities) is not tuple or len(self.entities) > _MAX_ENTITIES or any(type(item) is not EntityObservation for item in self.entities):
            raise ObservationStateError("invalid entities")
        entities = tuple(sorted(self.entities, key=lambda item: item.entity_id))
        if len({item.entity_id for item in entities}) != len(entities):
            raise ObservationStateError("duplicate entity id")
        object.__setattr__(self, "entities", entities)
        if type(self.relations) is not tuple or len(self.relations) > _MAX_RELATIONS or any(type(item) is not RelationObservation for item in self.relations):
            raise ObservationStateError("invalid relations")
        relations = tuple(sorted(self.relations, key=lambda item: (item.source, item.relation, item.target, _canonical_json(item.attributes))))
        object.__setattr__(self, "relations", relations)
        if type(self.events) is not tuple or len(self.events) > _MAX_EVENTS or any(type(item) is not EventObservation for item in self.events):
            raise ObservationStateError("invalid events")
        events = tuple(sorted(self.events, key=lambda item: (item.sequence is None, item.sequence if item.sequence is not None else 0, item.kind, _canonical_json(item.attributes))))
        object.__setattr__(self, "events", events)
        projection = self.to_projection()
        if len(_canonical_json(projection).encode("utf-8")) > _MAX_PROJECTION_BYTES:
            raise ObservationStateError("observation projection is too large")

    def __repr__(self) -> str:
        return "ObservationState(redacted)"

    def __hash__(self) -> int:
        return hash(self.digest)

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(_canonical_json(self.to_projection()).encode("utf-8")).hexdigest()

    def to_projection(self) -> dict[str, object]:
        return {
            "available_actions": list(self.available_actions),
            "frame": _thaw_json(self.frame),
            "levels_completed": self.levels_completed,
            "state": self.state,
            "win_levels": self.win_levels,
            "input_kind": self.input_kind,
            "hud": _thaw_json(self.hud),
            "timers": _thaw_json(self.timers),
            "resources": _thaw_json(self.resources),
            "entities": [item.to_projection() for item in self.entities],
            "relations": [item.to_projection() for item in self.relations],
            "events": [item.to_projection() for item in self.events],
        }

    @classmethod
    def from_observation(cls, observation: object) -> "ObservationState":
        """Build from a native broker mapping or ``ArcObservation`` object."""

        if isinstance(observation, Mapping):
            return cls.from_projection(observation)
        fields = ("available_actions", "frame", "levels_completed", "state", "win_levels")
        if all(hasattr(observation, field) for field in fields):
            projection = {field: getattr(observation, field) for field in fields}
            for field in ("hud", "timers", "resources", "entities", "relations", "events", "input_kind"):
                if hasattr(observation, field):
                    projection[field] = getattr(observation, field)
            return cls.from_projection(projection)
        raise ObservationStateError("observation must be an object")

    @classmethod
    def from_projection(cls, projection: Mapping[str, object]) -> "ObservationState":
        """Build from an observation or operator projection.

        A projection may wrap the broker mapping under ``observation``; known
        metadata fields at the outer level are merged over that nested mapping.
        Unknown fields are ignored so private transport payloads cannot enter
        the persistent state accidentally.
        """

        if not isinstance(projection, Mapping):
            raise ObservationStateError("projection must be an object")
        nested = projection.get("observation")
        if nested is not None:
            if not isinstance(nested, Mapping):
                raise ObservationStateError("observation must be an object")
            source: dict[str, object] = dict(nested)
            for key in ("hud", "timers", "resources", "entities", "relations", "events", "input_kind"):
                if key in projection:
                    source[key] = projection[key]
        else:
            source = dict(projection)
        if "frame" not in source:
            raise ObservationStateError("projection has no frame")
        available = source.get("available_actions", ())
        if not isinstance(available, (list, tuple)):
            raise ObservationStateError("available_actions must be an array")
        actions = tuple(sorted(_validate_string(item, "action", pattern=_ACTION) for item in available))
        if len(set(actions)) != len(actions):
            raise ObservationStateError("available_actions must be unique")
        levels = source.get("levels_completed", 0)
        state = source.get("state", "NOT_FINISHED")
        if "win_levels" in source:
            win_levels = source["win_levels"]
        else:
            win_levels = levels + 1 if type(levels) is int else None
        input_kind = source.get("input_kind", "unknown")
        return cls(
            frame=source["frame"],
            available_actions=actions,
            levels_completed=levels,
            state=state,
            win_levels=win_levels,
            input_kind=input_kind,
            hud=source.get("hud", {}),
            timers=source.get("timers", {}),
            resources=source.get("resources", {}),
            entities=_entity_records(source.get("entities")),
            relations=_relation_records(source.get("relations")),
            events=_event_records(source.get("events")),
        )


__all__ = (
    "EntityObservation",
    "EventObservation",
    "ObservationState",
    "ObservationStateError",
    "RelationObservation",
)
