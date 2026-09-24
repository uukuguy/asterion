"""Exact operator-owned game choices for the native P7 first-level preset."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType


GAME_ID_ENV = "ASTERION_PRIME_P7_GAME_ID"
SEED_ENV = "ASTERION_PRIME_P7_SEED"
TARGET_LEVEL_ENV = "ASTERION_PRIME_P7_TARGET_LEVEL"
DEFAULT_GAME_ID = "ls20-9607627b"
_MAX_SEED = 2**31 - 1
_BASELINES = MappingProxyType(
    {
        "ls20-9607627b": (22, 123, 73, 84, 96, 192, 186),
        "tu93-0768757b": (19, 16, 34, 42, 123, 80, 14, 23, 111),
    }
)


class P7GameSelectionError(RuntimeError):
    """A fixed public-safe preflight failure without game source content."""


@dataclass(frozen=True, slots=True)
class P7GameSelection:
    game_id: str
    seed: int
    target_level: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.game_id) is not str
            or self.game_id not in _BASELINES
            or type(self.seed) is not int
            or not 0 <= self.seed <= _MAX_SEED
            or type(self.target_level) is not int
            or not 1 <= self.target_level <= len(_BASELINES[self.game_id])
        ):
            raise P7GameSelectionError("P7 game selection is unavailable")

    @property
    def baseline_actions(self) -> tuple[int, ...]:
        return _BASELINES[self.game_id]

    @property
    def win_levels(self) -> int:
        return len(self.baseline_actions)


DEFAULT_GAME = P7GameSelection(DEFAULT_GAME_ID, 0)


def resolve_game_selection(
    environment: Mapping[str, str], arc_root: Path
) -> P7GameSelection:
    """Read one selected local game without importing or executing game code."""

    try:
        game_id = environment.get(GAME_ID_ENV, DEFAULT_GAME_ID)
        raw_seed = environment.get(SEED_ENV, "0")
        raw_target_level = environment.get(TARGET_LEVEL_ENV, "1")
        if (
            type(game_id) is not str
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
        selected = P7GameSelection(game_id, int(raw_seed))
        stem, version = game_id.split("-", 1)
        game_root = arc_root / "environment_files" / stem / version
        metadata_path = game_root / "metadata.json"
        source_path = game_root / f"{stem}.py"
        resolved_root = arc_root.resolve(strict=True)
        if (
            (arc_root / "environment_files").is_symlink()
            or (arc_root / "environment_files" / stem).is_symlink()
            or game_root.is_symlink()
            or metadata_path.is_symlink()
            or source_path.is_symlink()
            or not metadata_path.is_file()
            or not source_path.is_file()
            or not game_root.resolve(strict=True).is_relative_to(resolved_root)
            or not metadata_path.resolve(strict=True).is_relative_to(resolved_root)
            or not source_path.resolve(strict=True).is_relative_to(resolved_root)
        ):
            raise ValueError
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            type(metadata) is not dict
            or metadata.get("game_id") != game_id
            or metadata.get("baseline_actions") != list(selected.baseline_actions)
        ):
            raise ValueError
        return P7GameSelection(game_id, int(raw_seed), int(raw_target_level))
    except Exception:
        raise P7GameSelectionError("P7 game selection is unavailable") from None


__all__ = (
    "DEFAULT_GAME",
    "DEFAULT_GAME_ID",
    "GAME_ID_ENV",
    "P7GameSelection",
    "P7GameSelectionError",
    "SEED_ENV",
    "TARGET_LEVEL_ENV",
    "resolve_game_selection",
)
