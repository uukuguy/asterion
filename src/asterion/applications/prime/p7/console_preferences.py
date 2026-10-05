"""Last console selection, without game state or P7 learning records."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


def valid_selection(value: object, games: dict[str, int]) -> bool:
    return (type(value) is dict and set(value) == {"game_id", "level"}
            and type(value["game_id"]) is str and value["game_id"] in games
            and type(value["level"]) is int
            and 1 <= value["level"] <= games[value["game_id"]])


def _path(root: Path) -> Path:
    path = root / ".asterion-private" / "p7-console-selection.json"
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError
    return path


def read_selection(root: Path, games: dict[str, int]) -> dict | None:
    try:
        with _path(root).open("rb") as stream:
            raw = stream.read(2049)
        if len(raw) > 2048:
            return None
        value = json.loads(raw)
        return value if valid_selection(value, games) else None
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None


def write_selection(root: Path, value: dict, games: dict[str, int]) -> None:
    """Keep a tiny preference; a disk failure cannot affect game execution."""
    temporary = None
    try:
        if not valid_selection(value, games):
            return
        path = _path(root)
        path.parent.mkdir(mode=0o700, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".p7-console-selection-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, _path(root))
    except (OSError, ValueError):
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
