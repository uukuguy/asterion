"""Exact operator-owned game choices for the native P7 first-level preset."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
from types import MappingProxyType


GAME_ID_ENV = "ASTERION_PRIME_P7_GAME_ID"
SEED_ENV = "ASTERION_PRIME_P7_SEED"
TARGET_LEVEL_ENV = "ASTERION_PRIME_P7_TARGET_LEVEL"
DEFAULT_GAME_ID = "ls20-9607627b"
_MAX_SEED = 2**31 - 1
_GAME_ID = re.compile(r"^[A-Za-z0-9]+-[A-Za-z0-9]+$")
_BASELINES = MappingProxyType(
    {
        "ls20-9607627b": (22, 123, 73, 84, 96, 192, 186),
        "tu93-0768757b": (19, 16, 34, 42, 123, 80, 14, 23, 111),
    }
)


class P7GameSelectionError(RuntimeError):
    """A fixed public-safe preflight failure without game source content."""


@dataclass(frozen=True, slots=True)
class ArcGameContract:
    """Official full-game bounds derived from the SDK's first observation.

    The application supplies the observed win-level count. This contract carries
    no local baseline or authority to replay an official competition session.
    """

    game_id: str
    win_levels: int
    seed: int = 0
    action_cap: int = 1000
    mode: str = "official"

    def __post_init__(self) -> None:
        if (
            type(self.game_id) is not str
            or _GAME_ID.fullmatch(self.game_id) is None
            or type(self.win_levels) is not int
            or self.win_levels < 1
            or type(self.seed) is not int
            or self.seed != 0
            or type(self.action_cap) is not int
            or not 1000 <= self.action_cap <= 5000
            or type(self.mode) is not str
            or self.mode != "official"
        ):
            raise P7GameSelectionError("P7 game selection is unavailable")

    @property
    def target_level(self) -> int:
        return self.win_levels

    @property
    def is_full_game(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class P7GameSelection:
    game_id: str
    seed: int
    target_level: int = 1
    _metadata_baseline_actions: tuple[int, ...] | None = None
    _metadata_win_levels: int | None = None
    # A local sweep may supply the exact remaining budget for a run.  Keeping
    # this opt-in leaves the normal solve and official contracts unchanged.
    action_cap_override: int | None = None

    def __post_init__(self) -> None:
        if (
            type(self.game_id) is not str
            or (self.game_id not in _BASELINES and self._metadata_baseline_actions is None)
            or type(self.seed) is not int
            or not 0 <= self.seed <= _MAX_SEED
            or type(self.target_level) is not int
            or self._metadata_baseline_actions is not None
            and (
                type(self._metadata_baseline_actions) is not tuple
                or not self._metadata_baseline_actions
                or any(type(action) is not int or action <= 0 for action in self._metadata_baseline_actions)
            )
            or self._metadata_win_levels is not None
            and (
                type(self._metadata_win_levels) is not int
                or self._metadata_win_levels != len(self._metadata_baseline_actions or ())
            )
            or self.action_cap_override is not None
            and (
                type(self.action_cap_override) is not int
                or self.action_cap_override <= 0
            )
            or not 1 <= self.target_level <= self._win_levels
        ):
            raise P7GameSelectionError("P7 game selection is unavailable")

    @property
    def is_full_game(self) -> bool:
        return self.target_level == self.win_levels

    @property
    def action_cap(self) -> int:
        if self.action_cap_override is not None:
            return self.action_cap_override
        if self.is_full_game:
            return min(5000, max(1000, 2 * sum(self.baseline_actions)))
        return 500

    @property
    def baseline_actions(self) -> tuple[int, ...]:
        return self._metadata_baseline_actions or _BASELINES[self.game_id]

    @property
    def win_levels(self) -> int:
        return self._win_levels

    @property
    def _win_levels(self) -> int:
        return self._metadata_win_levels or len(self.baseline_actions)


DEFAULT_GAME = P7GameSelection(DEFAULT_GAME_ID, 0)


def resolve_game_selection(
    environment: Mapping[str, str], arc_root: Path
) -> P7GameSelection:
    """Read one selected local game without importing or executing game code."""

    try:
        requested_game_id = environment.get(GAME_ID_ENV, DEFAULT_GAME_ID)
        raw_seed = environment.get(SEED_ENV, "0")
        raw_target_level = environment.get(TARGET_LEVEL_ENV, "1")
        if (
            type(requested_game_id) is not str
            or type(raw_seed) is not str
            or not raw_seed
            or not raw_seed.isascii()
            or not raw_seed.isdecimal()
            or len(raw_seed) > 10
            or type(raw_target_level) is not str
            or not raw_target_level
            or not raw_target_level.isascii()
            or not raw_target_level.isdecimal()
            or len(raw_target_level) > 10
        ):
            raise ValueError
        catalog = _read_catalog(arc_root)
        matches = [
            value
            for value in catalog
            if value["game_id"] == requested_game_id
            or value["alias"] == requested_game_id
        ]
        if len(matches) != 1:
            raise ValueError
        entry = matches[0]
        target_level = (
            entry["win_levels"]
            if TARGET_LEVEL_ENV not in environment
            else int(raw_target_level)
        )
        return P7GameSelection(
            entry["game_id"],
            int(raw_seed),
            target_level,
            entry["baseline_actions"],
            entry["win_levels"],
        )
    except Exception:
        raise P7GameSelectionError("P7 game selection is unavailable") from None


def _read_catalog(arc_root: Path) -> tuple[dict[str, object], ...]:
    """Read validated metadata entries without importing game source."""

    if arc_root.is_symlink() or not arc_root.is_dir():
        raise ValueError
    environment_root = arc_root / "environment_files"
    if environment_root.is_symlink() or not environment_root.is_dir():
        raise ValueError
    resolved_root = arc_root.resolve(strict=True)
    entries: list[dict[str, object]] = []
    for stem_path in sorted(environment_root.iterdir(), key=lambda path: path.name):
        if stem_path.is_symlink() or not stem_path.is_dir() or not re.fullmatch(r"[A-Za-z0-9]+", stem_path.name):
            continue
        for version_path in sorted(stem_path.iterdir(), key=lambda path: path.name):
            if version_path.is_symlink() or not version_path.is_dir() or not re.fullmatch(r"[A-Za-z0-9]+", version_path.name):
                continue
            metadata_path = version_path / "metadata.json"
            source_path = version_path / f"{stem_path.name}.py"
            if (
                metadata_path.is_symlink()
                or source_path.is_symlink()
                or not metadata_path.is_file()
                or not source_path.is_file()
                or not version_path.resolve(strict=True).is_relative_to(resolved_root)
            ):
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                continue
            game_id = metadata.get("game_id") if type(metadata) is dict else None
            baseline = metadata.get("baseline_actions") if type(metadata) is dict else None
            win_levels = metadata.get("win_levels") if type(metadata) is dict else None
            if (
                type(game_id) is not str
                or _GAME_ID.fullmatch(game_id) is None
                or game_id != f"{stem_path.name}-{version_path.name}"
                or type(baseline) is not list
                or not baseline
                or any(type(action) is not int or action <= 0 for action in baseline)
                or game_id in _BASELINES and tuple(baseline) != _BASELINES[game_id]
                or (win_levels is not None and (type(win_levels) is not int or win_levels != len(baseline)))
            ):
                continue
            entries.append(
                {
                    "game_id": game_id,
                    "alias": stem_path.name,
                    "baseline_actions": tuple(baseline),
                    "win_levels": len(baseline) if win_levels is None else win_levels,
                }
            )
    return tuple(entries)


__all__ = (
    "ArcGameContract",
    "DEFAULT_GAME",
    "DEFAULT_GAME_ID",
    "GAME_ID_ENV",
    "P7GameSelection",
    "P7GameSelectionError",
    "SEED_ENV",
    "TARGET_LEVEL_ENV",
    "resolve_game_selection",
)
