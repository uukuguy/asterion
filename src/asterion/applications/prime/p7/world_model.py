"""Validated, provider-neutral world model records for one game."""
from __future__ import annotations

from dataclasses import dataclass
import copy
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

_LAYERS = ("mechanics", "entities", "relations")
_LAYER_SET = frozenset(_LAYERS)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MAX_HYPOTHESES = 64
_MAX_VALUE_BYTES = 4096


def _identity(value: str, name: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ValueError(f"invalid {name}")
    return value


def _canonical(value: Any, path: str = "value") -> Any:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain finite numbers")
        return value
    if type(value) is list:
        return [_canonical(item, f"{path}[]") for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise TypeError(f"{path} object keys must be strings")
        return {key: _canonical(value[key], f"{path}.{key}") for key in sorted(value)}
    raise TypeError(f"{path} is not JSON-safe")


def _validated_value(value: Any) -> Any:
    detached = _canonical(value)
    encoded = json.dumps(detached, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > _MAX_VALUE_BYTES:
        raise ValueError("world model value exceeds cap")
    return detached


def _freeze(value: Any) -> Any:
    """Recursively convert validated JSON values to immutable containers."""
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """Return a detached, JSON-shaped copy for the public value accessor."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


def _valid_level(level: int, win_levels: int) -> int:
    if type(level) is not int or not 0 <= level < win_levels:
        raise ValueError("invalid level")
    return level


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    frame_id: str | None = None
    action_id: str | None = None
    source_run: str | None = None
    summary_hash: str | None = None

    def __post_init__(self) -> None:
        values = (self.frame_id, self.action_id, self.source_run, self.summary_hash)
        if not any(value is not None for value in values):
            raise ValueError("evidence reference must identify an observation")
        for name, value in zip(("frame_id", "action_id", "source_run", "summary_hash"), values):
            if value is not None:
                _identity(value, name)
        if self.summary_hash is not None and re.fullmatch(r"[0-9a-fA-F]{16,128}", self.summary_hash) is None:
            raise ValueError("invalid summary_hash")


@dataclass(frozen=True, slots=True)
class WorldFact:
    layer: str
    key: str
    value: Any
    level: int
    evidence: tuple[EvidenceRef, ...]
    status: str = "hypothesis"

    def __getattribute__(self, name: str) -> Any:
        # Keep the stored value recursively immutable while preserving the
        # existing JSON-shaped accessor contract for callers.
        value = object.__getattribute__(self, "value") if name == "value" else None
        if name == "value":
            return _thaw(value)
        return object.__getattribute__(self, name)

    def __post_init__(self) -> None:
        if self.layer not in _LAYER_SET:
            raise ValueError("unknown world model layer")
        _identity(self.key, "fact key")
        if type(self.level) is not int or self.level < 0:
            raise ValueError("invalid fact level")
        if self.status not in ("hypothesis", "confirmed", "conflict"):
            raise ValueError("invalid fact status")
        if not self.evidence or any(not isinstance(ref, EvidenceRef) for ref in self.evidence):
            raise ValueError("fact requires evidence")
        object.__setattr__(self, "value", _freeze(_validated_value(self.value)))
        object.__setattr__(self, "evidence", tuple(self.evidence))

    def confirmed(self, evidence: Sequence[EvidenceRef]) -> "WorldFact":
        return WorldFact(self.layer, self.key, self.value, self.level, (*self.evidence, *evidence), "confirmed")

    def public_projection(self) -> dict[str, Any]:
        # Evidence identities can correlate private runs, so expose only a count.
        return {"key": self.key, "value": copy.deepcopy(self.value), "level": self.level,
                "status": self.status, "evidence_count": len(self.evidence)}


@dataclass(frozen=True, slots=True)
class WorldModelSnapshot:
    game_id: str
    seed: int
    win_levels: int
    mechanics: Mapping[str, WorldFact]
    entities: Mapping[str, WorldFact]
    relations: Mapping[str, WorldFact]
    current_level: int
    version: int
    conflicts: tuple[WorldFact, ...] = ()
    hypotheses: Mapping[str, WorldFact] = MappingProxyType({})

    def __post_init__(self) -> None:
        _identity(self.game_id, "game_id")
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("invalid seed")
        if type(self.win_levels) is not int or self.win_levels <= 0:
            raise ValueError("invalid win_levels")
        if type(self.current_level) is not int or not 0 <= self.current_level < self.win_levels:
            raise ValueError("invalid current_level")
        if type(self.version) is not int or self.version < 0:
            raise ValueError("invalid version")
        normalized: dict[str, Mapping[str, WorldFact]] = {}
        for layer in _LAYERS:
            source = getattr(self, layer)
            if any(key != fact.key or fact.layer != layer for key, fact in source.items()):
                raise ValueError("invalid world fact mapping")
            normalized[layer] = MappingProxyType(dict(sorted(source.items())))
        object.__setattr__(self, "mechanics", normalized["mechanics"])
        object.__setattr__(self, "entities", normalized["entities"])
        object.__setattr__(self, "relations", normalized["relations"])
        object.__setattr__(self, "conflicts", tuple(self.conflicts))
        object.__setattr__(self, "hypotheses", MappingProxyType(dict(sorted(self.hypotheses.items()))))

    def projection(self, max_bytes: int = 8192) -> dict[str, object]:
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("invalid max_bytes")
        body: dict[str, object] = {
            "game_id": self.game_id, "seed": self.seed, "win_levels": self.win_levels,
            "current_level": self.current_level, "version": self.version,
            "confirmed": {
                layer: {key: fact.public_projection() for key, fact in sorted(getattr(self, layer).items())}
                for layer in _LAYERS
            },
            "hypotheses": {key: fact.public_projection() for key, fact in sorted(self.hypotheses.items())},
            "conflicts": [fact.public_projection() for fact in sorted(self.conflicts, key=lambda item: (item.layer, item.key, item.level))],
        }
        encoded = json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > max_bytes:
            raise ValueError("world model projection exceeds max_bytes")
        return copy.deepcopy(body)


class WorldModelStore:
    def __init__(self, game_id: str, seed: int, win_levels: int) -> None:
        self._game_id = _identity(game_id, "game_id")
        if type(seed) is not int or seed < 0:
            raise ValueError("invalid seed")
        if type(win_levels) is not int or win_levels <= 0:
            raise ValueError("invalid win_levels")
        self._seed, self._win_levels = seed, win_levels
        self._layers: dict[str, dict[str, WorldFact]] = {layer: {} for layer in _LAYERS}
        self._hypotheses: dict[tuple[str, str], WorldFact] = {}
        self._conflicts: list[WorldFact] = []
        self._level = 0
        self._version = 0

    @property
    def mechanics(self) -> Mapping[str, WorldFact]:
        return self.snapshot.mechanics

    @property
    def entities(self) -> Mapping[str, WorldFact]:
        return self.snapshot.entities

    @property
    def relations(self) -> Mapping[str, WorldFact]:
        return self.snapshot.relations

    @property
    def current_level(self) -> int:
        return self._level

    @property
    def version(self) -> int:
        return self._version

    @property
    def conflicts(self) -> tuple[WorldFact, ...]:
        return tuple(self._conflicts)

    def _refs(self, evidence: EvidenceRef | Sequence[EvidenceRef]) -> tuple[EvidenceRef, ...]:
        refs = (evidence,) if isinstance(evidence, EvidenceRef) else tuple(evidence)
        if not refs or any(not isinstance(ref, EvidenceRef) for ref in refs):
            raise ValueError("evidence is required")
        return refs

    @property
    def snapshot(self) -> WorldModelSnapshot:
        hypotheses = {f"{layer}:{key}": fact for (layer, key), fact in self._hypotheses.items()}
        return WorldModelSnapshot(self._game_id, self._seed, self._win_levels,
                                  self._layers["mechanics"], self._layers["entities"], self._layers["relations"],
                                  self._level, self._version, tuple(self._conflicts), hypotheses)

    def record_hypothesis(self, layer: str, key: str, value: Any, *, level: int,
                          evidence: EvidenceRef | Sequence[EvidenceRef]) -> WorldFact:
        if layer not in _LAYER_SET:
            raise ValueError("unknown world model layer")
        _identity(key, "fact key")
        level = _valid_level(level, self._win_levels)
        if key in self._layers[layer] or (layer, key) in self._hypotheses:
            raise ValueError("duplicate fact key")
        if len(self._hypotheses) >= _MAX_HYPOTHESES:
            raise ValueError("hypothesis cap exceeded")
        fact = WorldFact(layer, key, value, level, self._refs(evidence))
        self._hypotheses = {**self._hypotheses, (layer, key): fact}
        self._version += 1
        return fact

    def record_visual_candidates(
        self,
        candidates: Sequence[tuple[str, Any]],
        *,
        level: int,
        evidence: EvidenceRef | Sequence[EvidenceRef],
    ) -> int:
        """Store bounded visual regularities as entity hypotheses.

        Candidate facts are deliberately kept out of ``mechanics`` and are
        never confirmed by this method.  Re-observing a level is idempotent;
        action evidence or the explicit hypothesis API is still required to
        promote a candidate into a confirmed fact.
        """

        level = _valid_level(level, self._win_levels)
        if type(candidates) not in (tuple, list):
            raise ValueError("visual candidates must be a sequence")
        refs = self._refs(evidence)
        added = 0
        for key, value in candidates[:32]:
            if type(key) is not str or not key:
                raise ValueError("invalid visual candidate key")
            suffix = key.removeprefix("visual.")
            base_key = key if key.startswith("visual.level.") else f"visual.level.{level}.{suffix}"
            if type(base_key) is not str or not base_key.startswith(f"visual.level.{level}."):
                raise ValueError("invalid visual candidate key")
            if base_key in self._layers["entities"] or ("entities", base_key) in self._hypotheses:
                continue
            self.record_hypothesis("entities", base_key, value, level=level, evidence=refs)
            added += 1
        return added

    def confirm(self, layer: str, key: str, *, evidence: EvidenceRef | Sequence[EvidenceRef],
                observed_value: Any = None) -> WorldFact:
        if layer not in _LAYER_SET:
            raise ValueError("unknown world model layer")
        hypothesis = self._hypotheses.get((layer, key))
        if hypothesis is None:
            raise ValueError("no matching hypothesis")
        if observed_value is not None and _validated_value(observed_value) != hypothesis.value:
            raise ValueError("observed value does not match hypothesis")
        fact = hypothesis.confirmed(self._refs(evidence))
        self._hypotheses = {item: value for item, value in self._hypotheses.items() if item != (layer, key)}
        self._layers[layer] = {**self._layers[layer], key: fact}
        self._version += 1
        return fact

    def conflict(self, layer: str, key: str, *, observed_value: Any,
                 evidence: EvidenceRef | Sequence[EvidenceRef]) -> WorldModelSnapshot:
        if layer not in _LAYER_SET:
            raise ValueError("unknown world model layer")
        existing = self._layers[layer].get(key) or self._hypotheses.get((layer, key))
        if existing is None:
            raise ValueError("unknown fact key")
        branch = WorldFact(layer, key, observed_value, existing.level, self._refs(evidence), "conflict")
        self._conflicts = [*self._conflicts, branch]
        self._version += 1
        return self.snapshot

    def refresh_level(self, level: int) -> WorldModelSnapshot:
        level = _valid_level(level, self._win_levels)
        # A level refresh keeps only observations belonging to the requested level.
        for layer in ("entities", "relations"):
            self._layers[layer] = {key: fact for key, fact in self._layers[layer].items() if fact.level == level}
        self._hypotheses = {item: fact for item, fact in self._hypotheses.items()
                            if item[0] == "mechanics" or fact.level == level}
        self._level = level
        self._version += 1
        return self.snapshot

    def projection(self, max_bytes: int = 8192) -> dict[str, object]:
        return self.snapshot.projection(max_bytes)
