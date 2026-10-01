"""Persistent game-wide mechanism memory for P7.

This module stores *evidence about* reusable game mechanics.  It intentionally
has no planner, executor, or certificate authority: loading a mechanism never
makes it eligible for action dispatch.  A mechanism can be scoped to a level
while living in the same game namespace, or scoped to the game and explicitly
bound to several levels after independent observations.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import copy
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

SCHEMA = "asterion.prime.p7-game-mechanics/v1"
_MAX_FILE_BYTES = 512 * 1024
_MAX_RECORDS = 256
_MAX_VALUE_BYTES = 16 * 1024
_MAX_VALUE_DEPTH = 16
_MAX_VALUE_ITEMS = 256
_MAX_TEXT = 2048
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _id(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"invalid {name}")
    return value


def _int(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or isinstance(value, bool) or value < minimum:
        raise ValueError(f"invalid {name}")
    return value


def _json_value(value: Any, *, depth: int = 0) -> Any:
    """Detach and bound JSON values used in rules and evidence."""

    if depth > _MAX_VALUE_DEPTH:
        raise ValueError("mechanism value is too deep")
    if value is None or type(value) in (str, bool, int):
        if type(value) is str and len(value) > _MAX_TEXT:
            raise ValueError("mechanism text exceeds cap")
        return value
    if type(value) is float:
        # JSON floats can carry NaN or infinity; reject them for deterministic
        # persistence and digesting.
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("mechanism value must be finite")
        return value
    if isinstance(value, Mapping):
        if len(value) > _MAX_VALUE_ITEMS or any(type(key) is not str for key in value):
            raise ValueError("mechanism object is invalid")
        return {key: _json_value(value[key], depth=depth + 1) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_VALUE_ITEMS:
            raise ValueError("mechanism array is too large")
        return [_json_value(item, depth=depth + 1) for item in value]
    raise ValueError("mechanism value is not JSON-safe")


def _value(value: Any) -> Any:
    detached = _json_value(value)
    if len(json.dumps(detached, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()) > _MAX_VALUE_BYTES:
        raise ValueError("mechanism value exceeds cap")
    return detached


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sequence(value: object, name: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or len(value) > _MAX_VALUE_ITEMS:
        raise ValueError(f"invalid {name}")
    return [_value(item) for item in value]


def _evidence(value: object) -> list[dict[str, Any]]:
    if value is None or not isinstance(value, (list, tuple)) or not value:
        raise ValueError("evidence is required")
    if len(value) > _MAX_VALUE_ITEMS:
        raise ValueError("evidence exceeds cap")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("evidence entries must be objects")
        normalized = _value(dict(item))
        if not normalized:
            raise ValueError("evidence entry is empty")
        encoded = _canonical_json(normalized)
        if encoded not in seen:
            result.append(normalized)
            seen.add(encoded)
    if not result:
        raise ValueError("evidence is required")
    return result


def _levels(value: object, name: str = "levels") -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError(f"invalid {name}")
    result = sorted({_int(item, name) for item in value})
    return tuple(result)


def _scope(scope: object, *, levels: object, win_levels: int) -> tuple[dict[str, Any], tuple[int, ...]]:
    if scope is None:
        scope = "game"
    if isinstance(scope, str):
        if scope not in {"game", "level"}:
            raise ValueError("invalid mechanism scope")
        raw_kind = scope
        raw_levels = levels
    elif isinstance(scope, Mapping):
        keys = set(scope)
        if keys - {"kind", "levels"} or "kind" not in scope:
            raise ValueError("invalid mechanism scope")
        raw_kind = scope["kind"]
        raw_levels = scope.get("levels", levels)
    else:
        raise ValueError("invalid mechanism scope")
    if raw_kind not in {"game", "level"}:
        raise ValueError("invalid mechanism scope")
    bound = _levels(raw_levels)
    if any(level >= win_levels for level in bound):
        raise ValueError("mechanism level exceeds game")
    if raw_kind == "level" and len(bound) != 1:
        raise ValueError("level scope requires exactly one level")
    return {"kind": raw_kind, "levels": list(bound)}, bound


def _merge_dicts(existing: Sequence[dict[str, Any]], additions: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    result = [copy.deepcopy(item) for item in existing]
    seen = {_canonical_json(item) for item in result}
    for item in additions:
        marker = _canonical_json(item)
        if marker not in seen:
            result.append(copy.deepcopy(item))
            seen.add(marker)
    return result


@dataclass(frozen=True, slots=True)
class GameMechanism:
    """One advisory mechanism in a game-wide namespace."""

    mechanism_id: str
    rules: Any
    conditions: Any
    effects: Any
    scope: Any
    evidence: Any
    status: str = "hypothesis"
    bound_levels: tuple[int, ...] = ()
    conflicts: Any = ()
    revision: int = 0

    def __getattribute__(self, name: str) -> Any:
        if name in {"rules", "conditions", "effects", "scope", "evidence", "conflicts"}:
            value = object.__getattribute__(self, name)
            return copy.deepcopy(value)
        return object.__getattribute__(self, name)

    def __post_init__(self) -> None:
        _id(self.mechanism_id, "mechanism_id")
        if self.status not in {"hypothesis", "confirmed", "conflict"}:
            raise ValueError("invalid mechanism status")
        if type(self.bound_levels) is not tuple or any(type(level) is not int or level < 0 for level in self.bound_levels):
            raise ValueError("invalid bound levels")
        if tuple(sorted(set(self.bound_levels))) != self.bound_levels:
            raise ValueError("invalid bound levels")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("invalid mechanism revision")
        # Internal values are detached at construction and remain detached in
        # public accessors.  The store passes already-normalized mappings.
        object.__setattr__(self, "rules", tuple(copy.deepcopy(self.rules)))
        object.__setattr__(self, "conditions", tuple(copy.deepcopy(self.conditions)))
        object.__setattr__(self, "effects", tuple(copy.deepcopy(self.effects)))
        object.__setattr__(self, "scope", copy.deepcopy(self.scope))
        object.__setattr__(self, "evidence", tuple(copy.deepcopy(self.evidence)))
        object.__setattr__(self, "conflicts", tuple(copy.deepcopy(self.conflicts)))

    @property
    def key(self) -> str:
        return self.mechanism_id

    @property
    def planner_eligible(self) -> bool:
        """Loading memory never grants execution authority."""

        return False

    def to_mapping(self) -> dict[str, Any]:
        return {
            "mechanism_id": self.mechanism_id,
            "rules": copy.deepcopy(list(self.rules)),
            "conditions": copy.deepcopy(list(self.conditions)),
            "effects": copy.deepcopy(list(self.effects)),
            "scope": copy.deepcopy(self.scope),
            "bound_levels": list(self.bound_levels),
            "evidence": copy.deepcopy(list(self.evidence)),
            "status": self.status,
            "conflicts": copy.deepcopy(list(self.conflicts)),
            "revision": self.revision,
            "planner_eligible": False,
        }


class GameMechanicsStore:
    """Bounded atomic persistence for reusable game mechanics.

    The identity is a whole game instance (``game_id``, ``seed``,
    ``win_levels``), while each mechanism records its own scope and level
    bindings.  The store is intentionally advisory and does not expose an
    execution callback or certificate authority.
    """

    def __init__(self, root: Path, game_id: str, seed: int, win_levels: int) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError("root must be an absolute path")
        self._root = root
        self._game_id = _id(game_id, "game_id")
        self._seed = _int(seed, "seed")
        self._win_levels = _int(win_levels, "win_levels", minimum=1)
        # Keep each exact game instance in its own private file.  A shared
        # WorldMap root can therefore retain several games without allowing
        # one game's mechanism namespace to bleed into another's load.
        self._path = root / ".asterion-private" / "prime-p7-live" / f"game-mechanics-{self._game_id}-{self._seed}-{self._win_levels}.json"
        self._version = 0
        self._records: dict[str, GameMechanism] = {}
        self._load_file()

    @classmethod
    def load(cls, root: Path, game_id: str, seed: int, win_levels: int) -> "GameMechanicsStore":
        """Load advisory records for one exact game identity."""

        return cls(root, game_id=game_id, seed=seed, win_levels=win_levels)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def version(self) -> int:
        return self._version

    def get(self, mechanism_id: str) -> GameMechanism | None:
        _id(mechanism_id, "mechanism_id")
        return self._records.get(mechanism_id)

    def records(self) -> tuple[GameMechanism, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def _empty_payload(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "game": {"game_id": self._game_id, "seed": self._seed, "win_levels": self._win_levels},
            "version": 0,
            "mechanisms": [],
        }

    def _load_file(self) -> None:
        try:
            if not self._path.is_file() or self._path.stat().st_size > _MAX_FILE_BYTES:
                return
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping) or payload.get("schema") != SCHEMA:
                return
            identity = payload.get("game")
            if not isinstance(identity, Mapping):
                return
            if (identity.get("game_id"), identity.get("seed"), identity.get("win_levels")) != (
                self._game_id, self._seed, self._win_levels
            ):
                raise ValueError("game mechanics identity mismatch")
            version = payload.get("version", 0)
            if type(version) is not int or version < 0:
                return
            mechanisms = payload.get("mechanisms")
            if not isinstance(mechanisms, list) or len(mechanisms) > _MAX_RECORDS:
                return
            restored: dict[str, GameMechanism] = {}
            for item in mechanisms:
                fact = self._from_mapping(item)
                if fact.mechanism_id in restored:
                    return
                restored[fact.mechanism_id] = fact
            self._records = restored
            self._version = version
        except ValueError as exc:
            # A corrupt private cache is advisory data; baseline P7 can still
            # run.  A cache for another exact game must never be silently
            # attached to this game namespace.
            if str(exc) == "game mechanics identity mismatch":
                raise
        except (OSError, TypeError, json.JSONDecodeError):
            # Private memory is optional; malformed or unreadable state falls
            # back to an empty advisory store.
            return

    def _from_mapping(self, item: object) -> GameMechanism:
        if not isinstance(item, Mapping):
            raise ValueError("invalid mechanism record")
        required = {"mechanism_id", "rules", "conditions", "effects", "scope", "bound_levels", "evidence", "status", "conflicts", "revision"}
        if set(item) != required and set(item) != required | {"planner_eligible"}:
            raise ValueError("invalid mechanism record")
        mechanism_id = _id(item["mechanism_id"], "mechanism_id")
        scope, scope_levels = _scope(item["scope"], levels=item["bound_levels"], win_levels=self._win_levels)
        bound = _levels(item["bound_levels"])
        if bound != scope_levels:
            raise ValueError("scope levels mismatch")
        evidence = _evidence(item["evidence"])
        conflicts = _sequence(item["conflicts"], "conflicts")
        return GameMechanism(
            mechanism_id,
            _sequence(item["rules"], "rules"),
            _sequence(item["conditions"], "conditions"),
            _sequence(item["effects"], "effects"),
            scope,
            evidence,
            item["status"],
            bound,
            conflicts,
            _int(item["revision"], "revision"),
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "game": {"game_id": self._game_id, "seed": self._seed, "win_levels": self._win_levels},
            "version": self._version,
            "mechanisms": [self._records[key].to_mapping() for key in sorted(self._records)],
        }

    def _persist(self) -> None:
        encoded = _canonical_json(self._payload()).encode("utf-8")
        if len(encoded) > _MAX_FILE_BYTES:
            raise ValueError("game mechanics store exceeds size cap")
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".game-mechanics-", dir=directory)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
            os.chmod(self._path, 0o600)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _commit(self, records: dict[str, GameMechanism], version: int) -> None:
        previous_records, previous_version = self._records, self._version
        self._records, self._version = records, version
        try:
            self._persist()
        except Exception:
            self._records, self._version = previous_records, previous_version
            raise

    def record(
        self,
        mechanism_id: str,
        *,
        rules: Sequence[Any] = (),
        conditions: Sequence[Any] = (),
        effects: Sequence[Any] = (),
        scope: object = "game",
        level: int | None = None,
        levels: Sequence[int] | None = None,
        evidence: Sequence[Mapping[str, Any]] | None = None,
    ) -> GameMechanism:
        _id(mechanism_id, "mechanism_id")
        if mechanism_id in self._records:
            raise ValueError("duplicate mechanism id")
        if len(self._records) >= _MAX_RECORDS:
            raise ValueError("mechanism record cap exceeded")
        if level is not None:
            if levels is not None:
                raise ValueError("level and levels are mutually exclusive")
            levels = [level]
        normalized_scope, bound = _scope(scope, levels=levels, win_levels=self._win_levels)
        fact = GameMechanism(
            mechanism_id,
            _sequence(rules, "rules"),
            _sequence(conditions, "conditions"),
            _sequence(effects, "effects"),
            normalized_scope,
            _evidence(evidence),
            "hypothesis",
            bound,
            (),
            0,
        )
        updated = dict(self._records)
        updated[mechanism_id] = fact
        self._commit(updated, self._version + 1)
        return fact

    def confirm(
        self,
        mechanism_id: str,
        *,
        evidence: Sequence[Mapping[str, Any]],
        levels: Sequence[int] | None = None,
    ) -> GameMechanism:
        _id(mechanism_id, "mechanism_id")
        current = self._records.get(mechanism_id)
        if current is None:
            raise ValueError("unknown mechanism id")
        if current.status != "hypothesis":
            raise ValueError("only hypotheses can be confirmed")
        additions = _evidence(evidence)
        requested = _levels(levels)
        if any(level >= self._win_levels for level in requested):
            raise ValueError("mechanism level exceeds game")
        if current.scope["kind"] == "level" and requested and tuple(requested) != current.bound_levels:
            raise ValueError("level mechanism cannot bind another level")
        bound = tuple(sorted(set(current.bound_levels) | set(requested)))
        scope = copy.deepcopy(current.scope)
        if scope["kind"] == "game":
            scope["levels"] = list(bound)
        fact = GameMechanism(
            current.mechanism_id, current.rules, current.conditions, current.effects,
            scope, _merge_dicts(current.evidence, additions), "confirmed", bound,
            current.conflicts, current.revision + 1,
        )
        updated = dict(self._records)
        updated[mechanism_id] = fact
        self._commit(updated, self._version + 1)
        return fact

    def conflict(
        self,
        mechanism_id: str,
        *,
        observed: Any,
        evidence: Sequence[Mapping[str, Any]],
        reason: str = "prediction-mismatch",
    ) -> GameMechanism:
        _id(mechanism_id, "mechanism_id")
        current = self._records.get(mechanism_id)
        if current is None:
            raise ValueError("unknown mechanism id")
        if type(reason) is not str or not reason or len(reason) > _MAX_TEXT:
            raise ValueError("invalid conflict reason")
        additions = _evidence(evidence)
        conflict = {"observed": _value(observed), "evidence": additions, "reason": reason}
        fact = GameMechanism(
            current.mechanism_id, current.rules, current.conditions, current.effects,
            current.scope, _merge_dicts(current.evidence, additions), "conflict", current.bound_levels,
            _merge_dicts(current.conflicts, [conflict]), current.revision + 1,
        )
        updated = dict(self._records)
        updated[mechanism_id] = fact
        self._commit(updated, self._version + 1)
        return fact

    def projection(self, *, max_bytes: int = _MAX_FILE_BYTES) -> dict[str, Any]:
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("invalid max_bytes")
        result = {
            "schema": SCHEMA,
            "game": {"game_id": self._game_id, "seed": self._seed, "win_levels": self._win_levels},
            "version": self._version,
            "execution_authority": "none",
            "mechanisms": [self._records[key].to_mapping() for key in sorted(self._records)],
        }
        if len(_canonical_json(result).encode("utf-8")) > max_bytes:
            raise ValueError("game mechanics projection exceeds max_bytes")
        return copy.deepcopy(result)


__all__ = ["SCHEMA", "GameMechanism", "GameMechanicsStore"]
