"""Print a redacted, read-only index of local ARC-AGI-3 P7 evidence."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from collections.abc import Mapping
from typing import Any

from asterion.applications.prime.p7.broker import ArcTransition
from asterion.applications.prime.p7.live import read_trace_entries
from asterion.applications.prime.p7.score import replay_sha256


_GAME_ID = re.compile(r"^[A-Za-z0-9]+-[A-Za-z0-9]+$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_TEXT = re.compile(r"^[^\r\n\t]+$")
_SCORE = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
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
        or broker.get("terminal_reason") not in {"level-completed", "game-won"}
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
    elif recording_game_id in game_levels:
        game_id = recording_game_id
    else:
        return None
    run_id = summary.get("run_id")
    score = receipt.get("partial_game_score")
    full_win = broker["terminal_reason"] == "game-won"
    if (
        type(run_id) is not str
        or run_id != run_dir.name
        or _RUN_ID.fullmatch(run_id) is None
        or type(score) is not str
        or _SCORE.fullmatch(score) is None
        or not Decimal("0") <= _score(score) <= Decimal("100")
        or (game_levels[game_id] is not None and receipt["completed_level_count"] > game_levels[game_id])
        or (full_win and receipt["completed_level_count"] != game_levels[game_id])
    ):
        return None
    return {
        "game_id": game_id,
        "run_id": run_id,
        "completed_levels": receipt["completed_level_count"],
        "score": str(score),
        "full_win": full_win,
    }


def _verified_partial_run(run_dir: Path, game_levels: dict[str, int | None]) -> dict[str, Any] | None:
    """Project sealed failure evidence without loading or replaying game source."""

    try:
        if run_dir.is_symlink() or not _RUN_ID.fullmatch(run_dir.name):
            return None
        summary_path = run_dir / "summary.json"
        trace_root = run_dir / "trace"
        trace_path = trace_root / "prime-trace.jsonl"
        seal_path = trace_root / "prime-trace.seal.json"
        if any(path.is_symlink() for path in (summary_path, trace_root, trace_path, seal_path)):
            return None
        summary = _read_object(summary_path)
        if (
            summary is None
            or summary.get("schema") != "asterion.prime.p7-live-private-summary/v1"
            or summary.get("run_id") != run_dir.name
            or summary.get("sealed_trace") is not True
            or summary.get("replay_verified") is not True
            or summary.get("cleanup_complete") is not True
            or summary.get("receipt") != {}
            or type(summary.get("failure")) is not dict
            or not summary["failure"]
        ):
            return None
        entries = read_trace_entries(trace_root)
        seal = _read_object(seal_path)
        if (
            seal is None
            or set(seal) != {"entry_count", "final_sha256", "sealed_at"}
            or seal.get("entry_count") != len(entries)
            or seal.get("final_sha256") != entries[-1].sha256
            or type(seal.get("sealed_at")) is not str
        ):
            return None
        markers = tuple(entry.payload for entry in entries if entry.kind == "arc.run.partial")
        if len(markers) != 1 or any(entry.kind == "arc.run.completed" for entry in entries):
            return None
        marker = markers[0]
        if not isinstance(marker, Mapping) or summary.get("completed_prefix") != dict(marker):
            return None
        required = {
            "game_id", "seed", "win_levels", "levels_completed", "primitive_actions",
            "replay_sha256", "terminal_reason",
        }
        if set(marker) != required:
            return None
        game_id = marker["game_id"]
        levels, actions, win_levels = marker["levels_completed"], marker["primitive_actions"], marker["win_levels"]
        if (
            type(game_id) is not str
            or game_id not in game_levels
            or type(marker["seed"]) is not int
            or type(win_levels) is not int
            or type(levels) is not int
            or type(actions) is not int
            or not 1 <= levels <= win_levels
            or actions < 1
            or marker["terminal_reason"] != "level-completed"
            or type(marker["replay_sha256"]) is not str
            or _DIGEST.fullmatch(marker["replay_sha256"]) is None
            or (game_levels[game_id] is not None and win_levels != game_levels[game_id])
        ):
            return None
        transitions = _trace_transitions(entries, win_levels)
        if transitions is None or len(transitions) < actions:
            return None
        prefix = transitions[:actions]
        if prefix[-1].levels_completed != levels or replay_sha256(prefix, terminal_reason="level-completed") != marker["replay_sha256"]:
            return None
        if _partial_recording_identity(run_dir, game_id, win_levels, transitions) is False:
            return None
        return {"game_id": game_id, "run_id": run_dir.name, "completed_levels": levels, "score": _MISSING, "full_win": False}
    except Exception:
        return None


def _trace_transitions(entries: tuple[object, ...], win_levels: int) -> tuple[ArcTransition, ...] | None:
    transitions: list[ArcTransition] = []
    for entry in entries:
        if getattr(entry, "kind", None) != "arc.action":
            continue
        payload = entry.payload
        if set(payload) not in ({"action", "after_sha256", "before_sha256", "levels_completed", "sequence"}, {"action", "after_sha256", "before_sha256", "levels_completed", "sequence", "data"}):
            return None
        data = payload.get("data", {})
        if not isinstance(data, Mapping):
            return None
        transition = ArcTransition(payload["sequence"], payload["action"], payload["before_sha256"], payload["after_sha256"], payload["levels_completed"], tuple(data.items()))
        if (
            transition.sequence != len(transitions) + 1
            or type(transition.levels_completed) is not int
            or not 0 <= transition.levels_completed <= win_levels
            or (transitions and not transitions[-1].levels_completed <= transition.levels_completed <= transitions[-1].levels_completed + 1)
        ):
            return None
        transitions.append(transition)
    return tuple(transitions) if transitions else None


def _partial_recording_identity(run_dir: Path, game_id: str, win_levels: int, transitions: tuple[ArcTransition, ...]) -> bool:
    recordings_root = run_dir / "recordings"
    if recordings_root.is_symlink() or not recordings_root.is_dir():
        return False
    sessions = tuple(recordings_root.iterdir())
    if len(sessions) != 1 or sessions[0].is_symlink() or not sessions[0].is_dir():
        return False
    files = tuple(sessions[0].glob("*.jsonl"))
    if len(files) != 1 or files[0].is_symlink() or not files[0].is_file():
        return False
    rows = [json.loads(row) for row in files[0].read_text(encoding="utf-8").splitlines()]
    actions: list[tuple[str, tuple[tuple[str, object], ...]]] = []
    started = False
    for row in rows:
        data = row.get("data") if type(row) is dict else None
        action = data.get("action_input") if type(data) is dict else None
        if (
            type(data) is not dict
            or data.get("game_id") != game_id
            or data.get("win_levels") != win_levels
            or type(action) is not dict
            or type(action.get("id")) is not str
            or type(action.get("data")) is not dict
        ):
            return False
        value = (action["id"], tuple(action["data"].items()))
        if value[0] == "RESET" and not started:
            if value[1]:
                return False
            continue
        started = True
        actions.append(value)
    return tuple((item.action, item.data) for item in transitions) == tuple(actions)


def _score(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation:
        return Decimal("-Infinity")


def inventory(arc_root: Path, runs_root: Path) -> list[dict[str, object]]:
    """Return deterministic, redacted local game rows.

    Sealed, replay-verified, fully cleaned success receipts and failure prefixes
    contribute progress. This function never reads game source.
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
                "full_win": False,
            }
            for row in sorted(metadata, key=lambda item: str(item["game_id"]))
        ]
    if runs_root.is_dir():
        for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
            run = _verified_run(run_dir, game_levels) or _verified_partial_run(run_dir, game_levels)
            if run is None:
                continue
            current = best.get(run["game_id"])
            rank = (run["full_win"], run["completed_levels"], _score(run["score"]), run["run_id"])
            if current is None or rank > (
                current["full_win"], current["completed_levels"], _score(current["score"]), current["run_id"]
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
                "status": (
                    "full-game WIN" if run and run["full_win"]
                    else "verified level witness" if run else "no verified run"
                ),
                "full_win": bool(run and run["full_win"]),
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
    columns = ("game_id", "title", "tags", "total_levels", "completed_levels", "run_id", "score", "status", "full_win")
    widths = {column: max(len(column), *(len(str(row[column])) for row in rows)) for column in columns}
    print("  ".join(column.ljust(widths[column]) for column in columns))
    for row in rows:
        print("  ".join(str(row[column]).ljust(widths[column]) for column in columns))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
