"""Bounded, exact-game private persistence for verified P7 routes."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
from types import MappingProxyType
from collections.abc import Mapping
from typing import Any

from .transition_model import ActionExpectation
from .world_model import WorldFact, WorldModelSnapshot

SCHEMA = "asterion.prime.p7-playbook/v1"
_MAX_BYTES = 256 * 1024
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MAX_VALUE_BYTES = 4096
_MAX_VALUE_DEPTH = 16
_MAX_VALUE_ITEMS = 256
_MAX_TEXT = 1024
_MAX_RECORDS = 256


def _id(value: str, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"invalid {name}")
    return value


def _digest(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError("invalid evidence digest")
    return value


def _canonical_value(value: Any, *, depth: int = 0) -> Any:
    if depth > _MAX_VALUE_DEPTH:
        raise ValueError("checked fact value too deep")
    if value is None or type(value) in (str, bool, int):
        if type(value) is str and len(value) > _MAX_TEXT:
            raise ValueError("checked fact text exceeds cap")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("checked fact value must be finite")
        return value
    if type(value) is tuple:
        value = list(value)
    if type(value) is list:
        if len(value) > _MAX_VALUE_ITEMS:
            raise ValueError("checked fact array exceeds cap")
        return [_canonical_value(item, depth=depth + 1) for item in value]
    if isinstance(value, Mapping):
        if len(value) > _MAX_VALUE_ITEMS or any(type(key) is not str for key in value):
            raise ValueError("checked fact object is invalid")
        return {key: _canonical_value(value[key], depth=depth + 1) for key in sorted(value)}
    raise ValueError("checked fact value is not JSON-safe")


def _validated_value(value: Any) -> Any:
    detached = _canonical_value(value)
    if len(json.dumps(detached, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()) > _MAX_VALUE_BYTES:
        raise ValueError("checked fact value exceeds cap")
    return detached


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


def _unique_sorted(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if type(values) is not tuple or any(type(x) is not str or not x or len(x) > _MAX_TEXT for x in values):
        raise ValueError(f"invalid {name}")
    if any(any(ord(char) < 0x20 or ord(char) == 0x7f for char in item) for item in values):
        raise ValueError(f"invalid {name}")
    if name == "evidence_index" and any(re.fullmatch(r"(?:sha256:[0-9a-f]{64}|[0-9a-fA-F]{16,128})", item) is None for item in values):
        raise ValueError(f"invalid {name}")
    if len(values) > _MAX_RECORDS or len(set(values)) != len(values):
        raise ValueError(f"invalid {name}")
    return tuple(sorted(values))


@dataclass(frozen=True, slots=True)
class PlaybookKey:
    game_id: str
    seed: int
    win_levels: int

    def __post_init__(self) -> None:
        _id(self.game_id, "game_id")
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("invalid seed")
        if type(self.win_levels) is not int or self.win_levels <= 0:
            raise ValueError("invalid win_levels")


@dataclass(frozen=True, slots=True)
class CheckedRoute:
    level: int
    expectations: tuple[ActionExpectation, ...]
    evidence_digest: str

    def __post_init__(self) -> None:
        if type(self.level) is not int or self.level < 0:
            raise ValueError("invalid route level")
        if type(self.expectations) is not tuple or any(type(x) is not ActionExpectation for x in self.expectations):
            raise ValueError("invalid route expectations")
        if len(self.expectations) > _MAX_RECORDS:
            raise ValueError("invalid route expectations")
        _digest(self.evidence_digest)


@dataclass(frozen=True, slots=True)
class CheckedFact:
    layer: str
    key: str
    value: Any
    level: int
    evidence_digests: tuple[str, ...]

    def __getattribute__(self, name: str) -> Any:
        if name == "value":
            return _thaw(object.__getattribute__(self, "value"))
        return object.__getattribute__(self, name)

    def __post_init__(self) -> None:
        if self.layer not in {"mechanics", "entities", "relations"} or _id(self.key, "fact key") != self.key:
            raise ValueError("invalid checked fact")
        if type(self.level) is not int or self.level < 0 or type(self.evidence_digests) is not tuple or not self.evidence_digests:
            raise ValueError("invalid checked fact")
        if any(type(x) is not str or not re.fullmatch(r"[0-9a-fA-F]{16,128}", x) for x in self.evidence_digests):
            raise ValueError("invalid checked fact evidence")
        if len(self.evidence_digests) > _MAX_RECORDS or len(set(self.evidence_digests)) != len(self.evidence_digests):
            raise ValueError("invalid checked fact evidence")
        object.__setattr__(self, "evidence_digests", tuple(sorted(self.evidence_digests)))
        object.__setattr__(self, "value", _freeze(_validated_value(self.value)))


@dataclass(frozen=True, slots=True)
class LevelMemory:
    level: int
    checked_facts: tuple[CheckedFact, ...] = ()
    rejected_branches: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.level) is not int or self.level < 0:
            raise ValueError("invalid memory level")
        if type(self.checked_facts) is not tuple or len(self.checked_facts) > _MAX_RECORDS or any(type(x) is not CheckedFact for x in self.checked_facts):
            raise ValueError("invalid level facts")
        if type(self.rejected_branches) is not tuple or len(self.rejected_branches) > _MAX_RECORDS or any(type(x) is not str or not x or len(x) > _MAX_TEXT for x in self.rejected_branches):
            raise ValueError("invalid rejected branches")
        if len(set(self.rejected_branches)) != len(self.rejected_branches):
            raise ValueError("invalid rejected branches")
        object.__setattr__(self, "rejected_branches", tuple(sorted(self.rejected_branches)))


@dataclass(frozen=True, slots=True)
class PlaybookSnapshot:
    key: PlaybookKey
    confirmed_facts: tuple[CheckedFact, ...] = ()
    checked_routes: tuple[CheckedRoute, ...] = ()
    level_memory: tuple[LevelMemory, ...] = ()
    conflict_metadata: tuple[str, ...] = ()
    evidence_index: tuple[str, ...] = ()
    branch_reasons: tuple[str, ...] = ()
    visual_hypotheses: tuple[CheckedFact, ...] = ()
    effect_summaries: tuple[CheckedFact, ...] = ()
    candidate_summaries: tuple[CheckedFact, ...] = ()
    simulator_summaries: tuple[CheckedFact, ...] = ()

    def __post_init__(self) -> None:
        if type(self.key) is not PlaybookKey:
            raise ValueError("invalid playbook key")
        for name, typ in (("confirmed_facts", CheckedFact), ("checked_routes", CheckedRoute), ("level_memory", LevelMemory), ("visual_hypotheses", CheckedFact), ("effect_summaries", CheckedFact), ("candidate_summaries", CheckedFact), ("simulator_summaries", CheckedFact)):
            value = getattr(self, name)
            if type(value) is not tuple or any(type(item) is not typ for item in value):
                raise ValueError(f"invalid {name}")
        for name in ("conflict_metadata", "evidence_index", "branch_reasons"):
            value = getattr(self, name)
            normalized = _unique_sorted(value, name)
            object.__setattr__(self, name, normalized)
        if any(len(getattr(self, name)) > _MAX_RECORDS for name in ("confirmed_facts", "checked_routes", "level_memory", "visual_hypotheses", "effect_summaries", "candidate_summaries", "simulator_summaries")):
            raise ValueError("playbook record cap exceeded")
        if any(f.level >= self.key.win_levels for f in self.confirmed_facts):
            raise ValueError("confirmed fact level out of range")
        if any(f.level >= self.key.win_levels for f in (*self.effect_summaries, *self.candidate_summaries, *self.simulator_summaries)):
            raise ValueError("experience fact level out of range")
        if any(route.level >= self.key.win_levels for route in self.checked_routes):
            raise ValueError("route level out of range")
        if any(memory.level >= self.key.win_levels or any(f.level >= self.key.win_levels for f in memory.checked_facts)
               for memory in self.level_memory):
            raise ValueError("memory level out of range")
        if any(f.layer != "entities" or not f.key.startswith("visual.level.") or f.level >= self.key.win_levels for f in self.visual_hypotheses):
            raise ValueError("invalid visual hypothesis")
        for name, value, key in (("confirmed_facts", self.confirmed_facts, lambda x: (x.layer, x.key)),
                                 ("checked_routes", self.checked_routes, lambda x: x.level),
                                 ("level_memory", self.level_memory, lambda x: x.level),
                                 ("visual_hypotheses", self.visual_hypotheses, lambda x: (x.layer, x.key)),
                                 ("effect_summaries", self.effect_summaries, lambda x: (x.layer, x.key)),
                                 ("candidate_summaries", self.candidate_summaries, lambda x: (x.layer, x.key)),
                                 ("simulator_summaries", self.simulator_summaries, lambda x: (x.layer, x.key))):
            keys = [key(item) for item in value]
            if len(set(keys)) != len(keys):
                raise ValueError(f"duplicate {name}")
            object.__setattr__(self, name, tuple(sorted(value, key=key)))

    def projection(self, max_bytes: int = 8192) -> dict[str, Any]:
        """Return a detached bounded private working-memory projection."""

        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("invalid projection cap")
        body = json.loads(_json(self).decode("utf-8"))
        encoded = json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > max_bytes:
            raise ValueError("playbook projection exceeds cap")
        return body


def _expectation_json(item: ActionExpectation) -> dict[str, Any]:
    return {"action": item.action, "data": dict(item.data), "prior_state_sha256": item.prior_state_sha256,
            "after_state_sha256": item.after_state_sha256, "after_frame_sha256": item.after_frame_sha256,
            "changed_cells": [list(x) for x in item.changed_cells], "levels_completed": item.levels_completed, "state": item.state}


def _fact_json(item: CheckedFact) -> dict[str, Any]:
    return {"layer": item.layer, "key": item.key, "value": item.value, "level": item.level,
            "evidence_digests": list(item.evidence_digests)}


def _json(snapshot: PlaybookSnapshot) -> bytes:
    body = {"schema": SCHEMA, "key": {"game_id": snapshot.key.game_id, "seed": snapshot.key.seed, "win_levels": snapshot.key.win_levels},
            "checked_model": {"confirmed_facts": [_fact_json(x) for x in sorted(snapshot.confirmed_facts, key=lambda x: (x.layer, x.key))],
                "checked_routes": [{"level": x.level, "expectations": [_expectation_json(e) for e in x.expectations], "evidence_digest": x.evidence_digest} for x in sorted(snapshot.checked_routes, key=lambda x: x.level)],
                "visual_hypotheses": [_fact_json(x) for x in sorted(snapshot.visual_hypotheses, key=lambda x: (x.layer, x.key))]},
            "experience_model": {
                "effects": [_fact_json(x) for x in sorted(snapshot.effect_summaries, key=lambda x: (x.layer, x.key))],
                "candidates": [_fact_json(x) for x in sorted(snapshot.candidate_summaries, key=lambda x: (x.layer, x.key))],
                "simulator": [_fact_json(x) for x in sorted(snapshot.simulator_summaries, key=lambda x: (x.layer, x.key))],
            },
            "level_memory": [{"level": x.level, "checked_facts": [_fact_json(f) for f in sorted(x.checked_facts, key=lambda f: (f.layer, f.key))], "rejected_branches": sorted(x.rejected_branches)} for x in sorted(snapshot.level_memory, key=lambda x: x.level)],
            "conflict_metadata": sorted(snapshot.conflict_metadata), "evidence_index": sorted(snapshot.evidence_index), "branch_reasons": list(snapshot.branch_reasons)}
    encoded = json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > _MAX_BYTES:
        raise ValueError("playbook exceeds size cap")
    return encoded


def _directory(root: Path) -> Path:
    if not isinstance(root, Path) or root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError("invalid operator root")
    root.mkdir(mode=0o750, parents=True, exist_ok=True)
    base = root / ".asterion-private" / "prime-p7-live" / "playbooks"
    for part in (root / ".asterion-private", root / ".asterion-private" / "prime-p7-live", base):
        if part.exists() and (part.is_symlink() or not part.is_dir()):
            raise ValueError("invalid playbook directory")
        part.mkdir(mode=0o750, exist_ok=True)
    return base


def _path(root: Path, key: PlaybookKey) -> Path:
    return _directory(root) / f"{key.game_id}-{key.seed}-{key.win_levels}.json"


def save_playbook(root: Path, snapshot: PlaybookSnapshot) -> None:
    if type(snapshot) is not PlaybookSnapshot:
        raise ValueError("invalid snapshot")
    path = _path(root, snapshot.key)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise ValueError("invalid playbook file")
    payload = _json(snapshot)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise ValueError("playbook unavailable") from None


def _parse_fact(value: Any) -> CheckedFact:
    if type(value) is not dict or set(value) != {"layer", "key", "value", "level", "evidence_digests"}:
        raise ValueError("invalid playbook fact")
    if type(value["evidence_digests"]) is not list:
        raise ValueError("invalid playbook fact")
    return CheckedFact(value["layer"], value["key"], value["value"], value["level"], tuple(value["evidence_digests"]))


def _mapping(value: Any, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError("invalid playbook schema")
    return value


def load_playbook(root: Path, key: PlaybookKey) -> PlaybookSnapshot | None:
    if type(key) is not PlaybookKey:
        raise ValueError("invalid key")
    path = _path(root, key)
    if path.is_symlink():
        raise ValueError("invalid playbook file")
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("invalid playbook file")
    if path.stat().st_size > _MAX_BYTES:
        raise ValueError("playbook exceeds size cap")
    try:
        body = json.loads(path.read_bytes())
        if type(body) is not dict or body.get("schema") != SCHEMA or set(body) not in ({"schema", "key", "checked_model", "level_memory", "conflict_metadata", "evidence_index", "branch_reasons"}, {"schema", "key", "checked_model", "experience_model", "level_memory", "conflict_metadata", "evidence_index", "branch_reasons"}):
            raise ValueError
        rawkey = _mapping(body["key"], {"game_id", "seed", "win_levels"})
        actual = PlaybookKey(rawkey["game_id"], rawkey["seed"], rawkey["win_levels"])
        if actual != key:
            raise ValueError
        raw_model = body["checked_model"]
        if type(raw_model) is not dict or set(raw_model) not in ({"confirmed_facts", "checked_routes"}, {"confirmed_facts", "checked_routes", "visual_hypotheses"}):
            raise ValueError("invalid playbook schema")
        model = raw_model
        if type(model["confirmed_facts"]) is not list or type(model["checked_routes"]) is not list:
            raise ValueError
        facts = tuple(_parse_fact(x) for x in model["confirmed_facts"])
        visual_hypotheses = tuple(_parse_fact(x) for x in model.get("visual_hypotheses", []))
        experience = body.get("experience_model", {})
        if type(experience) is not dict or set(experience) not in ({"effects", "candidates", "simulator"}, set()):
            raise ValueError("invalid experience model")
        effect_summaries = tuple(_parse_fact(x) for x in experience.get("effects", []))
        candidate_summaries = tuple(_parse_fact(x) for x in experience.get("candidates", []))
        simulator_summaries = tuple(_parse_fact(x) for x in experience.get("simulator", []))
        routes = []
        for route in model["checked_routes"]:
            route = _mapping(route, {"level", "expectations", "evidence_digest"})
            if type(route["expectations"]) is not list:
                raise ValueError
            exps = []
            for e in route["expectations"]:
                e = _mapping(e, {"action", "data", "prior_state_sha256", "after_state_sha256", "after_frame_sha256", "changed_cells", "levels_completed", "state"})
                if type(e["data"]) is not dict or type(e["changed_cells"]) is not list:
                    raise ValueError
                data = tuple((k, v) for k, v in e["data"].items())
                if any(type(k) is not str or type(v) is not int for k, v in data):
                    raise ValueError
                cells = tuple(tuple(x) for x in e["changed_cells"])
                exps.append(ActionExpectation(e["action"], data, e["prior_state_sha256"], e["after_state_sha256"], e["after_frame_sha256"], cells, e["levels_completed"], e["state"]))
            routes.append(CheckedRoute(route["level"], tuple(exps), route["evidence_digest"]))
        if type(body["level_memory"]) is not list:
            raise ValueError
        memory_rows = []
        for x in body["level_memory"]:
            x = _mapping(x, {"level", "checked_facts", "rejected_branches"})
            if type(x["checked_facts"]) is not list or type(x["rejected_branches"]) is not list:
                raise ValueError
            memory_rows.append(LevelMemory(x["level"], tuple(_parse_fact(f) for f in x["checked_facts"]), tuple(x["rejected_branches"])))
        memory = tuple(memory_rows)
        for name in ("conflict_metadata", "evidence_index", "branch_reasons"):
            if type(body[name]) is not list:
                raise ValueError
        return PlaybookSnapshot(actual, facts, tuple(routes), memory, tuple(body["conflict_metadata"]), tuple(body["evidence_index"]), tuple(body["branch_reasons"]), visual_hypotheses, effect_summaries, candidate_summaries, simulator_summaries)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, AttributeError):
        raise ValueError("playbook unavailable") from None


def append_checked_route(snapshot: PlaybookSnapshot, route: CheckedRoute) -> PlaybookSnapshot:
    if type(snapshot) is not PlaybookSnapshot or type(route) is not CheckedRoute:
        raise ValueError("invalid playbook route")
    if route.level >= snapshot.key.win_levels:
        raise ValueError("invalid route level")
    evidence_index = tuple(dict.fromkeys((*snapshot.evidence_index, route.evidence_digest)))
    return PlaybookSnapshot(snapshot.key, snapshot.confirmed_facts, (*snapshot.checked_routes, route), snapshot.level_memory, snapshot.conflict_metadata, evidence_index, snapshot.branch_reasons, snapshot.visual_hypotheses, snapshot.effect_summaries, snapshot.candidate_summaries, snapshot.simulator_summaries)


def branch_playbook(snapshot: PlaybookSnapshot, reason: str) -> PlaybookSnapshot:
    if type(snapshot) is not PlaybookSnapshot or type(reason) is not str or not reason or len(reason) > 256:
        raise ValueError("invalid branch")
    return PlaybookSnapshot(snapshot.key, snapshot.confirmed_facts, snapshot.checked_routes, snapshot.level_memory, snapshot.conflict_metadata, snapshot.evidence_index, tuple(sorted(set((*snapshot.branch_reasons, reason)))), snapshot.visual_hypotheses, snapshot.effect_summaries, snapshot.candidate_summaries, snapshot.simulator_summaries)


def capture_completed_level(snapshot: PlaybookSnapshot, world: WorldModelSnapshot, *, level: int) -> PlaybookSnapshot:
    if type(snapshot) is not PlaybookSnapshot or type(world) is not WorldModelSnapshot or (world.game_id, world.seed, world.win_levels) != (snapshot.key.game_id, snapshot.key.seed, snapshot.key.win_levels):
        raise ValueError("playbook identity mismatch")
    if type(level) is not int or not 0 <= level < snapshot.key.win_levels or world.current_level != level:
        raise ValueError("invalid completed level")
    facts = []
    for layer in ("mechanics", "entities", "relations"):
        for fact in getattr(world, layer).values():
            if type(fact) is not WorldFact or fact.status != "confirmed" or (layer != "mechanics" and fact.level != level):
                continue
            digests = tuple(sorted({ref.summary_hash for ref in fact.evidence if ref.summary_hash is not None}))
            if not digests or any(ref.summary_hash is None for ref in fact.evidence):
                raise ValueError("confirmed fact lacks evidence digest")
            facts.append(CheckedFact(layer, fact.key, fact.value, fact.level, digests))
    memory = LevelMemory(level, tuple(sorted(facts, key=lambda x: (x.layer, x.key))))
    visual_hypotheses = []
    for fact in world.hypotheses.values():
        if fact.layer != "entities" or not fact.key.startswith("visual.level.") or fact.level != level:
            continue
        digests = tuple(sorted({ref.summary_hash for ref in fact.evidence if ref.summary_hash is not None}))
        if not digests or any(ref.summary_hash is None for ref in fact.evidence):
            raise ValueError("visual hypothesis lacks evidence digest")
        visual_hypotheses.append(CheckedFact(fact.layer, fact.key, fact.value, fact.level, digests))
    evidence_index = tuple(dict.fromkeys((*snapshot.evidence_index, *(d for f in (*facts, *visual_hypotheses) for d in f.evidence_digests))))
    return PlaybookSnapshot(snapshot.key, tuple(sorted({(f.layer, f.key): f for f in (*snapshot.confirmed_facts, *facts)}.values(), key=lambda x: (x.layer, x.key))), snapshot.checked_routes, (*tuple(m for m in snapshot.level_memory if m.level != level), memory), snapshot.conflict_metadata, evidence_index, snapshot.branch_reasons, tuple(sorted({(f.layer, f.key): f for f in (*snapshot.visual_hypotheses, *visual_hypotheses)}.values(), key=lambda x: (x.layer, x.key))), snapshot.effect_summaries, snapshot.candidate_summaries, snapshot.simulator_summaries)


__all__ = ["PlaybookKey", "PlaybookSnapshot", "CheckedRoute", "CheckedFact", "LevelMemory", "load_playbook", "save_playbook", "append_checked_route", "branch_playbook", "capture_completed_level"]
