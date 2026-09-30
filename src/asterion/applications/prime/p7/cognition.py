"""Persistent, advisory cognition for P7 game types and exact games.

The store deliberately contains no executable route.  Type profiles are
cross-game priors and exact-game records are progress summaries.  A caller
must still validate the current observation before using any remembered
mechanism or route.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from collections.abc import Sequence
from typing import Any


SCHEMA = "asterion.prime.p7-cognition/v1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_INPUT_KINDS = ("keyboard", "click", "keyboard_click", "unknown")
_MAX_FILE_BYTES = 128 * 1024
_MAX_GAMES = 512
_MAX_ACTIONS = 16


def classify_input_kind(available_actions: Sequence[str]) -> str:
    """Classify the input surface without making any gameplay claim."""

    if not isinstance(available_actions, Sequence) or isinstance(
        available_actions, (str, bytes)
    ):
        raise ValueError("available_actions must be a sequence")
    names = {item for item in available_actions if type(item) is str}
    has_click = "ACTION6" in names
    has_keyboard = bool(names - {"ACTION6"})
    if has_keyboard and has_click:
        return "keyboard_click"
    if has_click:
        return "click"
    if has_keyboard:
        return "keyboard"
    return "unknown"


def _merge_input_kind(previous: object, current: str) -> str:
    if previous not in _INPUT_KINDS or previous == current:
        return current
    if previous == "unknown":
        return current
    if current == "unknown":
        return previous
    if {previous, current} <= {"keyboard", "click", "keyboard_click"}:
        return "keyboard_click" if previous != current else current
    return "unknown"


def _safe_id(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"invalid {name}")
    return value


def _safe_int(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or isinstance(value, bool) or value < minimum:
        raise ValueError(f"invalid {name}")
    return value


def _counter(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0


def _identity(game_id: str, seed: int, win_levels: int) -> str:
    _safe_id(game_id, "game_id")
    _safe_int(seed, "seed")
    _safe_int(win_levels, "win_levels", minimum=1)
    return f"{game_id}|{seed}|{win_levels}"


def _empty() -> dict[str, Any]:
    return {"schema": SCHEMA, "type_profiles": {}, "games": {}}


def _normalise_action_names(actions: Sequence[str]) -> list[str]:
    if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes)):
        raise ValueError("available_actions must be a sequence")
    names = sorted({item for item in actions if type(item) is str})
    if len(names) > _MAX_ACTIONS or any(
        not re.fullmatch(r"ACTION[1-7]", name) for name in names
    ):
        raise ValueError("invalid available actions")
    return names


class GameCognitionStore:
    """Bounded persistence for type priors and exact-game experience."""

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError("root must be an absolute path")
        self._path = root / ".asterion-private" / "prime-p7-live" / "cognition.json"
        self._state = self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, Any]:
        try:
            if not self._path.is_file() or self._path.stat().st_size > _MAX_FILE_BYTES:
                return _empty()
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
                return _empty()
            profiles = raw.get("type_profiles")
            games = raw.get("games")
            if (
                not isinstance(profiles, dict)
                or not isinstance(games, dict)
                or any(type(value) is not dict for value in profiles.values())
                or any(type(value) is not dict for value in games.values())
            ):
                return _empty()
            return {"schema": SCHEMA, "type_profiles": profiles, "games": games}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return _empty()

    def _persist(self) -> None:
        payload = json.dumps(self._state, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        encoded = payload.encode("utf-8")
        if len(encoded) > _MAX_FILE_BYTES:
            raise ValueError("cognition store exceeds size cap")
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".cognition-", dir=directory)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                handle.write(payload)
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

    def observe(
        self,
        *,
        game_id: str,
        seed: int,
        win_levels: int,
        available_actions: Sequence[str],
        levels_completed: int,
        primitive_actions: int,
    ) -> None:
        key = _identity(game_id, seed, win_levels)
        kind = classify_input_kind(available_actions)
        names = _normalise_action_names(available_actions)
        levels = _safe_int(levels_completed, "levels_completed")
        actions = _safe_int(primitive_actions, "primitive_actions")
        games = self._state["games"]
        profiles = self._state["type_profiles"]
        game = games.get(key)
        if not isinstance(game, dict):
            game = {
                "game_id": game_id,
                "seed": seed,
                "win_levels": win_levels,
                "input_kind": kind,
                "action_names": names,
                "observations": 0,
                "levels_completed": 0,
                "primitive_actions": None,
            }
        kind = _merge_input_kind(game.get("input_kind"), kind)
        game["input_kind"] = kind
        old_names = game.get("action_names", [])
        if not isinstance(old_names, list):
            old_names = []
        game["action_names"] = sorted(set(item for item in old_names if type(item) is str) | set(names))[:_MAX_ACTIONS]
        game["observations"] = min(_counter(game.get("observations")) + 1, 1_000_000)
        game["levels_completed"] = max(_counter(game.get("levels_completed")), levels)
        previous_actions = game.get("primitive_actions")
        if previous_actions is None or _counter(previous_actions) == 0 or (actions > 0 and actions < _counter(previous_actions)):
            game["primitive_actions"] = actions
        games[key] = game
        if len(games) > _MAX_GAMES:
            oldest = next(iter(games))
            if oldest != key:
                games.pop(oldest, None)
        profile = profiles.setdefault(kind, {"games_seen": 0, "action_names": [], "observations": 0, "authority": "prior-only"})
        profile["authority"] = "prior-only"
        profile_names = profile.get("action_names", [])
        if not isinstance(profile_names, list):
            profile_names = []
        profile["action_names"] = sorted(set(item for item in profile_names if type(item) is str) | set(names))[:_MAX_ACTIONS]
        profile["observations"] = min(_counter(profile.get("observations")) + 1, 1_000_000)
        profile["games_seen"] = len({
            (item.get("game_id"), item.get("seed"), item.get("win_levels"))
            for item in games.values()
            if isinstance(item, dict) and item.get("input_kind") == kind
        })
        self._persist()

    def record_experience(
        self,
        *,
        game_id: str,
        seed: int,
        win_levels: int,
        levels_completed: int,
        primitive_actions: int,
        model_digest: str | None = None,
    ) -> None:
        key = _identity(game_id, seed, win_levels)
        _safe_int(levels_completed, "levels_completed")
        _safe_int(primitive_actions, "primitive_actions")
        if model_digest is not None and _DIGEST.fullmatch(model_digest) is None:
            raise ValueError("invalid model_digest")
        game = self._state["games"].get(key)
        if not isinstance(game, dict):
            game = {"game_id": game_id, "seed": seed, "win_levels": win_levels, "input_kind": "unknown", "action_names": [], "observations": 0, "levels_completed": 0, "primitive_actions": None}
        game["levels_completed"] = max(_counter(game.get("levels_completed")), levels_completed)
        previous = game.get("primitive_actions")
        if previous is None or _counter(previous) == 0 or (primitive_actions > 0 and primitive_actions < _counter(previous)):
            game["primitive_actions"] = primitive_actions
        if model_digest is not None:
            game["model_digest"] = model_digest
        self._state["games"][key] = game
        self._persist()

    def projection(self, *, game_id: str, seed: int, win_levels: int) -> dict[str, Any]:
        key = _identity(game_id, seed, win_levels)
        game = self._state["games"].get(key)
        if not isinstance(game, dict):
            game = None
        kind = game.get("input_kind") if game else None
        if kind not in _INPUT_KINDS:
            candidates = [name for name, profile in self._state["type_profiles"].items() if isinstance(profile, dict) and _counter(profile.get("games_seen")) > 0]
            kind = candidates[0] if len(candidates) == 1 else "unknown"
        profile = self._state["type_profiles"].get(kind, {"games_seen": 0, "action_names": [], "observations": 0, "authority": "prior-only"})
        action_names = profile.get("action_names", [])
        if not isinstance(action_names, list):
            action_names = []
        result: dict[str, Any] = {
            "input_kind": kind,
            "type_profile": {
                "games_seen": _counter(profile.get("games_seen")),
                "action_names": [item for item in action_names if type(item) is str][: _MAX_ACTIONS],
                "observations": _counter(profile.get("observations")),
                "authority": "prior-only",
            },
            "game_experience": {
                "observations": _counter(game.get("observations")) if game else 0,
                "levels_completed": _counter(game.get("levels_completed")) if game else 0,
                "primitive_actions": game.get("primitive_actions") if game else None,
                "model_digest": game.get("model_digest") if game else None,
            },
        }
        return result
