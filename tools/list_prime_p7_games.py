"""Print a redacted, read-only index of local ARC-AGI-3 P7 evidence."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from typing import Any


_GAME_ID = re.compile(r"^[A-Za-z0-9]+-[A-Za-z0-9]+$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_SAFE_TEXT = re.compile(r"^[^\r\n\t]+$")
_MISSING = "—"


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return value if type(value) is dict else None


def _metadata(arc_root: Path) -> list[dict[str, Any]]:
    root = arc_root / "environment_files"
    if root.is_symlink() or not root.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/*/metadata.json")):
        if any(part.is_symlink() for part in (path, path.parent, path.parent.parent, path.parent.parent.parent)):
            continue
        value = _read_object(path)
        if value is None:
            continue
        game_id = value.get("game_id")
        if type(game_id) is not str or not _GAME_ID.fullmatch(game_id):
            continue
        if game_id != f"{path.parent.parent.name}-{path.parent.name}":
            continue
        tags = value.get("tags", [])
        title = value.get("title", game_id)
        if (
            type(tags) is not list
            or any(type(tag) is not str or not _SAFE_TEXT.fullmatch(tag) for tag in tags)
            or type(title) is not str
            or not _SAFE_TEXT.fullmatch(title)
        ):
            continue
        baseline = value.get("baseline_actions")
        declared_levels = next(
            (value.get(key) for key in ("total_levels", "win_levels", "levels") if type(value.get(key)) is int),
            None,
        )
        total_levels = declared_levels if declared_levels is not None else (
            len(baseline) if type(baseline) is list and baseline else None
        )
        if type(total_levels) is not int or total_levels < 1:
            continue
        result.append(
            {
                "game_id": game_id,
                "title": title,
                "tags": ",".join(tags) if tags else _MISSING,
                "total_levels": total_levels,
            }
        )
    return result


def _recording_identity(run_dir: Path, game_ids: set[str]) -> tuple[str | None, bool]:
    recordings = run_dir / "recordings"
    candidates: list[str] = []
    if not recordings.is_symlink() and recordings.is_dir():
        for path in recordings.rglob("*"):
            if path.is_symlink():
                continue
            if not path.is_file():
                continue
            if not path.name.endswith(".jsonl"):
                continue
            for game_id in game_ids:
                if path.name.startswith(game_id + "-"):
                    candidates.append(game_id)
                    break
            else:
                match = re.match(r"^([A-Za-z0-9]+-[A-Za-z0-9]+)-.+\.jsonl$", path.name)
                if match:
                    candidates.append(match.group(1))
    if len(candidates) > 1:
        return None, False
    return (candidates[0] if candidates else None), True


def _verified_run(run_dir: Path, game_levels: dict[str, int | None]) -> dict[str, Any] | None:
    if run_dir.is_symlink() or not _RUN_ID.fullmatch(run_dir.name):
        return None
    summary_path = run_dir / "summary.json"
    if summary_path.is_symlink():
        return None
    summary = _read_object(summary_path)
    if summary is None or summary.get("schema") != "asterion.prime.p7-live-private-summary/v1":
        return None
    receipt = summary.get("receipt")
    broker = summary.get("broker")
    if (
        type(receipt) is not dict
        or summary.get("sealed_trace") is not True
        or summary.get("replay_verified") is not True
        or summary.get("cleanup_complete") is not True
        or type(broker) is not dict
        or broker.get("terminal_reason") != "level-completed"
        or type(receipt.get("completed_level_count")) is not int
        or receipt["completed_level_count"] < 1
        or broker.get("levels_completed") != receipt["completed_level_count"]
        or type(receipt.get("receipt_sha256")) is not str
        or _SHA256.fullmatch(receipt["receipt_sha256"]) is None
        or type(receipt.get("primitive_action_count")) is not int
        or type(broker.get("primitive_actions")) is not int
        or receipt["primitive_action_count"] != broker["primitive_actions"]
        or receipt["primitive_action_count"] < 0
    ):
        return None
    summary_game_id = broker.get("game_id")
    recording_game_id, recording_valid = _recording_identity(run_dir, set(game_levels))
    if not recording_valid:
        return None
    if type(summary_game_id) is str:
        if summary_game_id not in game_levels:
            return None
        if recording_game_id is not None and recording_game_id != summary_game_id:
            return None
        game_id = summary_game_id
    elif recording_game_id is not None:
        game_id = recording_game_id
    else:
        return None
    run_id = summary.get("run_id")
    score = receipt.get("partial_game_score")
    if (
        type(run_id) is not str
        or run_id != run_dir.name
        or _RUN_ID.fullmatch(run_id) is None
        or type(score) not in (str, int, float)
        or isinstance(score, bool)
        or not _score(str(score)).is_finite()
        or (game_levels[game_id] is not None and receipt["completed_level_count"] > game_levels[game_id])
    ):
        return None
    return {
        "game_id": game_id,
        "run_id": run_id,
        "completed_levels": receipt["completed_level_count"],
        "score": str(score),
    }


def _score(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation:
        return Decimal("-Infinity")


def inventory(arc_root: Path, runs_root: Path) -> list[dict[str, object]]:
    """Return deterministic, redacted local game rows.

    Only sealed, replay-verified, fully cleaned runs with a matching terminal
    broker result contribute progress.  This function never reads game source.
    """
    metadata = _metadata(arc_root)
    game_levels = {
        str(row["game_id"]): (row["total_levels"] if type(row["total_levels"]) is int else None)
        for row in metadata
    }
    best: dict[str, dict[str, Any]] = {}
    if runs_root.is_symlink():
        return [
            {
                **row,
                "completed_levels": 0,
                "run_id": _MISSING,
                "score": _MISSING,
                "status": "no verified run",
            }
            for row in sorted(metadata, key=lambda item: str(item["game_id"]))
        ]
    if runs_root.is_dir():
        for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
            run = _verified_run(run_dir, game_levels)
            if run is None:
                continue
            current = best.get(run["game_id"])
            rank = (run["completed_levels"], _score(run["score"]), run["run_id"])
            if current is None or rank > (
                current["completed_levels"], _score(current["score"]), current["run_id"]
            ):
                best[run["game_id"]] = run
    rows: list[dict[str, object]] = []
    for row in sorted(metadata, key=lambda item: str(item["game_id"])):
        run = best.get(str(row["game_id"]))
        rows.append(
            {
                **row,
                "completed_levels": run["completed_levels"] if run else 0,
                "run_id": run["run_id"] if run else _MISSING,
                "score": run["score"] if run else _MISSING,
                "status": "verified" if run else "no verified run",
            }
        )
    return rows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List local Prime P7 game metadata and verified progress")
    parser.add_argument("--arc-root", type=Path, default=Path.cwd().parent / "external-prime" / "arc-agi-3")
    parser.add_argument("--runs-root", type=Path, default=Path.cwd() / ".asterion-private" / "prime-p7-live")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        rows = inventory(args.arc_root, args.runs_root)
    except (OSError, ValueError):
        print("P7 local inventory unavailable")
        return 1
    if not rows:
        print("P7 local inventory unavailable")
        return 1
    columns = ("game_id", "title", "tags", "total_levels", "completed_levels", "run_id", "score", "status")
    widths = {column: max(len(column), *(len(str(row[column])) for row in rows)) for column in columns}
    print("  ".join(column.ljust(widths[column]) for column in columns))
    for row in rows:
        print("  ".join(str(row[column]).ljust(widths[column]) for column in columns))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
