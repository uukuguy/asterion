"""Operator-only offline attempt at one game's next replay-verified P7 level."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import sys
from typing import Any

from asterion.applications.prime.p7.broker import ArcTransition
from asterion.applications.prime.p7.game import _read_catalog
from asterion.applications.prime.p7.private_trace import P7_TRACE_IDENTITIES
from asterion.applications.prime.p7.score import replay_sha256
from asterion.applications.prime.p7.solutions import VerifiedPrefix, load_best_prefix

if __package__:
    from tools.run_prime_p7_sweep import (
        SweepConfig, SweepScheduler, _read_hash_chained_trace, _read_json,
        _valid_attempt_summary,
    )
else:
    from run_prime_p7_sweep import (
        SweepConfig, SweepScheduler, _read_hash_chained_trace, _read_json,
        _valid_attempt_summary,
    )


_TIMEOUT_SECONDS = 30 * 60
_STALL_SECONDS = 5 * 60
_RUN_ID = re.compile(r"p7-live-[0-9]{14}-[0-9a-f]{24}\Z")
_SCHEMA = "asterion.prime.p7-next-level/v1"


def _new_manifest_path(operator_root: Path) -> Path:
    private = operator_root / ".asterion-private" / "prime-p7-next-level"
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    if private.is_symlink() or not private.is_dir():
        raise ValueError("P7 next-level evidence root is invalid")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return private / f"next-level-{stamp}-{secrets.token_hex(8)}.json"


def _save_manifest(path: Path, value: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True, indent=2, allow_nan=False)
        output.write("\n")


def _verified_success(
    arc_root: Path, runs_root: Path, run_id: str, game_id: str,
    level: int, baseline: int, prefix: VerifiedPrefix,
) -> dict[str, Any]:
    """Require the new run's seal, exact action prefix, replay and cleanup."""

    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("P7 new run ID is invalid")
    run = runs_root / run_id
    summary_path = run / "summary.json"
    trace_path = run / "trace" / "prime-trace.jsonl"
    seal_path = run / "trace" / "prime-trace.seal.json"
    if any(path.is_symlink() for path in (run, summary_path, trace_path, seal_path)):
        raise ValueError("P7 new run evidence path is invalid")
    summary = _read_json(summary_path)
    entries = _read_hash_chained_trace(trace_path)
    seal = _read_json(seal_path)
    if (
        not _valid_attempt_summary(summary, run_id, game_id, level, 0)
        or not entries or entries[-1]["kind"] != "trace.sealed"
        or any(row["identities"] != P7_TRACE_IDENTITIES for row in entries)
        or [row["kind"] for row in entries[-2:]] != ["arc.run.completed", "trace.sealed"]
        or any(row["kind"] not in {"arc.action", "arc.usage.reported"} for row in entries[:-2])
        or type(seal) is not dict
        or set(seal) != {"entry_count", "final_sha256", "sealed_at"}
        or seal["entry_count"] != len(entries)
        or seal["final_sha256"] != entries[-1]["sha256"]
        or type(seal["sealed_at"]) is not str
        or entries[-1]["payload"] != {
            "entry_count": len(entries) - 1, "final_sha256": entries[-2]["sha256"],
        }
    ):
        raise ValueError("P7 new run seal or summary is invalid")
    assert summary is not None
    broker = summary["broker"]
    sweep = summary["diagnostics"]["sweep"]
    cap = len(prefix.transitions) + baseline
    if (
        sweep.get("prefix_actions") != len(prefix.transitions)
        or sweep.get("level_action_cap") != baseline
        or sweep.get("run_action_cap") != cap
        or broker.get("win_levels") != prefix.win_levels
        or broker.get("levels_completed") != level
        or entries[-2]["payload"] != broker
    ):
        raise ValueError("P7 new run identity or action cap is invalid")
    transitions = []
    previous_hash = None
    previous_level = 0
    for row in entries:
        if row["kind"] != "arc.action":
            continue
        action = row["payload"]
        data = action.get("data", {})
        sequence = len(transitions) + 1
        if (
            set(action) not in (
                {"sequence", "action", "before_sha256", "after_sha256", "levels_completed"},
                {"sequence", "action", "before_sha256", "after_sha256", "levels_completed", "data"},
            )
            or type(action.get("sequence")) is not int or action["sequence"] != sequence
            or type(action.get("action")) is not str
            or any(type(action.get(key)) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", action[key]) is None
                   for key in ("before_sha256", "after_sha256"))
            or (previous_hash is not None and action["before_sha256"] != previous_hash)
            or type(action.get("levels_completed")) is not int
            or not previous_level <= action["levels_completed"] <= previous_level + 1
            or type(data) is not dict
            or any(type(key) is not str or type(value) is not int for key, value in data.items())
        ):
            raise ValueError("P7 new run action trace is invalid")
        transitions.append(ArcTransition(
            sequence, action["action"], action["before_sha256"],
            action["after_sha256"], action["levels_completed"],
            tuple(sorted(data.items())),
        ))
        previous_hash = action["after_sha256"]
        previous_level = action["levels_completed"]
    if (
        tuple(transitions[:len(prefix.transitions)]) != prefix.transitions
        or len(transitions) != broker["primitive_actions"]
        or len(transitions) > cap
        or len(transitions) <= len(prefix.transitions)
        or previous_level != level
        or replay_sha256(transitions, terminal_reason=broker["terminal_reason"])
        != broker.get("replay_sha256")
    ):
        raise ValueError("P7 new run prefix or replay digest is invalid")
    verified = load_best_prefix(arc_root, runs_root, game_id, 0)
    if (
        verified is None or verified.source_run_id != run_id
        or verified.levels_completed != level
        or verified.transitions != tuple(transitions)
    ):
        raise ValueError("P7 new run replay is not verified")
    return {
        "run_id": run_id,
        "level_actions": len(transitions) - len(prefix.transitions),
        "trace_final_sha256": entries[-1]["sha256"],
        "replay_sha256": verified.replay_sha256,
    }


def run_next_level(
    operator_root: Path, arc_root: Path, game: str, *, guest_machine: str = "ubuntu",
) -> dict[str, Any]:
    operator_root = operator_root.resolve(strict=True)
    arc_root = arc_root.resolve(strict=True)
    if not guest_machine or re.fullmatch(r"[A-Za-z0-9._-]+", guest_machine) is None:
        raise ValueError("P7 guest machine is invalid")
    catalog = _read_catalog(arc_root)
    matches = [row for row in catalog if game in {row["game_id"], row.get("alias")}]
    if len(matches) != 1:
        raise ValueError("P7 game is absent or ambiguous in the exact local catalog")
    metadata = matches[0]
    game_id = metadata["game_id"]
    runs_root = operator_root / ".asterion-private" / "prime-p7-live"
    prefix = load_best_prefix(arc_root, runs_root, game_id, 0)
    if (
        prefix is None or prefix.game_id != game_id or prefix.seed != 0
        or prefix.win_levels != metadata["win_levels"]
        or not 0 < prefix.levels_completed <= prefix.win_levels
        or not prefix.transitions
    ):
        raise ValueError("replay-verified P7 prefix is unavailable")
    if prefix.levels_completed == prefix.win_levels:
        raise ValueError("P7 game is already complete")
    level = prefix.levels_completed + 1
    baselines = metadata["baseline_actions"]
    if level > len(baselines):
        raise ValueError("P7 next-level baseline is unavailable")
    baseline = baselines[level - 1]
    if type(baseline) is not int or baseline <= 0 or len(prefix.transitions) + baseline > 5000:
        raise ValueError("P7 next-level action cap is invalid")
    manifest = {
        "schema": _SCHEMA, "game_id": game_id, "seed": 0,
        "target_level": level, "prefix_run_id": prefix.source_run_id,
        "prefix_replay_sha256": prefix.replay_sha256,
        "prefix_actions": len(prefix.transitions), "level_action_cap": baseline,
        "run_action_cap": len(prefix.transitions) + baseline,
        "timeout_seconds": _TIMEOUT_SECONDS,
        "no_action_stall_seconds": _STALL_SECONDS,
        "status": "unverified", "stop_reason": "not-started", "run_ids": [],
    }
    path = _new_manifest_path(operator_root)
    config = SweepConfig(
        arc_root=arc_root, runs_root=runs_root, games=(game_id,), seed=0,
        repo_root=operator_root, guest_machine=guest_machine,
        global_token_cap=None, wallclock_cap=None,
        run_timeout=_TIMEOUT_SECONDS, unbounded_second_round=True,
    )
    scheduler = SweepScheduler(config)
    try:
        current = load_best_prefix(arc_root, runs_root, game_id, 0)
        if current != prefix:
            raise ValueError("P7 verified prefix changed before attempt")
        returncode = scheduler._attempt(game_id, level, _TIMEOUT_SECONDS)
        manifest["run_ids"] = list(scheduler._new_runs)
        manifest["stop_reason"] = scheduler._stop_reason
        manifest["returncode"] = returncode
        if scheduler._stop_reason == "completed" and returncode == 0 and len(scheduler._new_runs) == 1:
            try:
                manifest.update(_verified_success(
                    arc_root, runs_root, scheduler._new_runs[0], game_id,
                    level, baseline, prefix,
                ))
                manifest["status"] = "verified"
            except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
                manifest["stop_reason"] = f"evidence-invalid:{type(error).__name__}"
    finally:
        _save_manifest(path, manifest)
    manifest["manifest"] = str(path)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-root", type=Path, default=Path.cwd())
    parser.add_argument("--arc-root", type=Path, required=True)
    parser.add_argument("--game", required=True)
    parser.add_argument("--guest-machine", default="ubuntu")
    args = parser.parse_args(argv)
    try:
        result = run_next_level(args.operator_root, args.arc_root, args.game,
                                guest_machine=args.guest_machine)
    except (OSError, ValueError):
        print("[p7-next-level] preflight or evidence invalid", file=sys.stderr)
        return 1
    public = {key: result[key] for key in (
        "status", "game_id", "target_level", "stop_reason", "run_ids",
    )}
    if result["status"] == "verified":
        public["level_actions"] = result["level_actions"]
    print(json.dumps(public, sort_keys=True))
    return 0 if result["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
