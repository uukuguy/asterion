"""Bounded, exact-game private persistence for verified P7 routes."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any

from .transition_model import ActionExpectation
from .world_model import WorldFact, WorldModelSnapshot

SCHEMA = "asterion.prime.p7-playbook/v1"
_MAX_BYTES = 256 * 1024
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _id(value: str, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"invalid {name}")
    return value


def _digest(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError("invalid evidence digest")
    return value


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
        _digest(self.evidence_digest)


@dataclass(frozen=True, slots=True)
class CheckedFact:
    layer: str
    key: str
    value: Any
    level: int
    evidence_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.layer not in {"mechanics", "entities", "relations"} or _id(self.key, "fact key") != self.key:
            raise ValueError("invalid checked fact")
        if type(self.level) is not int or self.level < 0 or type(self.evidence_digests) is not tuple or not self.evidence_digests:
            raise ValueError("invalid checked fact")
        if any(type(x) is not str or not re.fullmatch(r"[0-9a-fA-F]{16,128}", x) for x in self.evidence_digests):
            raise ValueError("invalid checked fact evidence")


@dataclass(frozen=True, slots=True)
class LevelMemory:
    level: int
    checked_facts: tuple[CheckedFact, ...] = ()
    rejected_branches: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.level) is not int or self.level < 0:
            raise ValueError("invalid memory level")
        if type(self.checked_facts) is not tuple or any(type(x) is not CheckedFact for x in self.checked_facts):
            raise ValueError("invalid level facts")
        if type(self.rejected_branches) is not tuple or any(type(x) is not str or not x for x in self.rejected_branches):
            raise ValueError("invalid rejected branches")


@dataclass(frozen=True, slots=True)
class PlaybookSnapshot:
    key: PlaybookKey
    confirmed_facts: tuple[CheckedFact, ...] = ()
    checked_routes: tuple[CheckedRoute, ...] = ()
    level_memory: tuple[LevelMemory, ...] = ()
    conflict_metadata: tuple[str, ...] = ()
    evidence_index: tuple[str, ...] = ()
    branch_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.key) is not PlaybookKey:
            raise ValueError("invalid playbook key")
        for name, typ in (("confirmed_facts", CheckedFact), ("checked_routes", CheckedRoute), ("level_memory", LevelMemory)):
            value = getattr(self, name)
            if type(value) is not tuple or any(type(item) is not typ for item in value):
                raise ValueError(f"invalid {name}")
        for name in ("conflict_metadata", "evidence_index", "branch_reasons"):
            value = getattr(self, name)
            if type(value) is not tuple or any(type(item) is not str or not item for item in value):
                raise ValueError(f"invalid {name}")


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
                "checked_routes": [{"level": x.level, "expectations": [_expectation_json(e) for e in x.expectations], "evidence_digest": x.evidence_digest} for x in sorted(snapshot.checked_routes, key=lambda x: x.level)]},
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
    return CheckedFact(value["layer"], value["key"], value["value"], value["level"], tuple(value["evidence_digests"]))


def load_playbook(root: Path, key: PlaybookKey) -> PlaybookSnapshot | None:
    if type(key) is not PlaybookKey:
        raise ValueError("invalid key")
    path = _path(root, key)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("invalid playbook file")
    if path.stat().st_size > _MAX_BYTES:
        raise ValueError("playbook exceeds size cap")
    try:
        body = json.loads(path.read_bytes())
        if type(body) is not dict or body.get("schema") != SCHEMA or set(body) != {"schema", "key", "checked_model", "level_memory", "conflict_metadata", "evidence_index", "branch_reasons"}:
            raise ValueError
        rawkey = body["key"]
        actual = PlaybookKey(rawkey["game_id"], rawkey["seed"], rawkey["win_levels"])
        if actual != key:
            raise ValueError
        model = body["checked_model"]
        facts = tuple(_parse_fact(x) for x in model["confirmed_facts"])
        routes = []
        for route in model["checked_routes"]:
            exps = []
            for e in route["expectations"]:
                exps.append(ActionExpectation(e["action"], tuple((k, v) for k, v in e["data"].items()), e["prior_state_sha256"], e["after_state_sha256"], e["after_frame_sha256"], tuple(tuple(x) for x in e["changed_cells"]), e["levels_completed"], e["state"]))
            routes.append(CheckedRoute(route["level"], tuple(exps), route["evidence_digest"]))
        memory = tuple(LevelMemory(x["level"], tuple(_parse_fact(f) for f in x["checked_facts"]), tuple(x["rejected_branches"])) for x in body["level_memory"])
        return PlaybookSnapshot(actual, facts, tuple(routes), memory, tuple(body["conflict_metadata"]), tuple(body["evidence_index"]), tuple(body["branch_reasons"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("playbook unavailable") from None


def append_checked_route(snapshot: PlaybookSnapshot, route: CheckedRoute) -> PlaybookSnapshot:
    if type(snapshot) is not PlaybookSnapshot or type(route) is not CheckedRoute:
        raise ValueError("invalid playbook route")
    if route.level >= snapshot.key.win_levels:
        raise ValueError("invalid route level")
    return PlaybookSnapshot(snapshot.key, snapshot.confirmed_facts, (*snapshot.checked_routes, route), snapshot.level_memory, snapshot.conflict_metadata, (*snapshot.evidence_index, route.evidence_digest), snapshot.branch_reasons)


def branch_playbook(snapshot: PlaybookSnapshot, reason: str) -> PlaybookSnapshot:
    if type(snapshot) is not PlaybookSnapshot or type(reason) is not str or not reason or len(reason) > 256:
        raise ValueError("invalid branch")
    return PlaybookSnapshot(snapshot.key, snapshot.confirmed_facts, snapshot.checked_routes, snapshot.level_memory, snapshot.conflict_metadata, snapshot.evidence_index, (*snapshot.branch_reasons, reason))


def capture_completed_level(snapshot: PlaybookSnapshot, world: WorldModelSnapshot, *, level: int) -> PlaybookSnapshot:
    if type(snapshot) is not PlaybookSnapshot or type(world) is not WorldModelSnapshot or (world.game_id, world.seed, world.win_levels) != (snapshot.key.game_id, snapshot.key.seed, snapshot.key.win_levels):
        raise ValueError("playbook identity mismatch")
    facts = []
    for layer in ("mechanics", "entities", "relations"):
        for fact in getattr(world, layer).values():
            if type(fact) is not WorldFact or fact.status != "confirmed" or (layer != "mechanics" and fact.level != level):
                continue
            digests = tuple(ref.summary_hash for ref in fact.evidence if ref.summary_hash is not None)
            if not digests or len(digests) != len(fact.evidence):
                raise ValueError("confirmed fact lacks evidence digest")
            facts.append(CheckedFact(layer, fact.key, fact.value, fact.level, digests))
    memory = LevelMemory(level, tuple(sorted(facts, key=lambda x: (x.layer, x.key))))
    return PlaybookSnapshot(snapshot.key, tuple(sorted({(f.layer, f.key): f for f in (*snapshot.confirmed_facts, *facts)}.values(), key=lambda x: (x.layer, x.key))), snapshot.checked_routes, (*snapshot.level_memory, memory), snapshot.conflict_metadata, (*snapshot.evidence_index, *(d for f in facts for d in f.evidence_digests)), snapshot.branch_reasons)


__all__ = ["PlaybookKey", "PlaybookSnapshot", "CheckedRoute", "CheckedFact", "LevelMemory", "load_playbook", "save_playbook", "append_checked_route", "branch_playbook", "capture_completed_level"]
