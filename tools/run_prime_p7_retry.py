"""Run exactly one supervised, local P7 retry for an explicitly selected game.

The retry has its own manifest and never reads or writes a breadth campaign
ledger.  This module is deliberately an operator tool: ``--preflight-only``
does not start Orb or a model.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from asterion.applications.prime.p7.game import _read_catalog
from asterion.applications.prime.p7.solutions import load_best_prefix
from asterion.applications.prime.p7.failed_attempts import select_failed_attempt_advice
from asterion.applications.prime.p7.failed_attempts import render_failed_attempt_advice
from asterion.applications.prime.p7.prompt import P7_SOLVE_PROMPT, build_p7_retry_prompt
from asterion.capabilities.prime_arc_agi_3_solver.provider import _valid_p7_input


def _load_sweep_module() -> Any:
    try:
        from tools import run_prime_p7_sweep
        return run_prime_p7_sweep
    except ModuleNotFoundError as error:
        if error.name != "tools":
            raise
        spec = importlib.util.spec_from_file_location(
            "asterion_prime_p7_sweep", Path(__file__).with_name("run_prime_p7_sweep.py")
        )
        if spec is None or spec.loader is None:
            raise ImportError("cannot load P7 sweep helper")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module


_GAME = re.compile(r"^[A-Za-z0-9]+-[A-Za-z0-9]+$")
_MANIFEST_SCHEMA = "asterion.prime.p7-retry-manifest/v1"
_PREFLIGHT_SCHEMA = "asterion.prime.p7-retry-preflight/v1"
_RESULT_SCHEMA = "asterion.prime.p7-retry-result/v1"


@dataclass(frozen=True, slots=True)
class RetryConfig:
    operator_root: Path
    arc_root: Path
    runs_root: Path
    game: str
    seed: int = 0
    run_timeout_seconds: int = 30 * 60
    no_action_stall_seconds: int = 5 * 60
    guest_machine: str = "ubuntu"


def resolve_game(arc_root: Path, requested: str) -> dict[str, Any]:
    """Resolve one alias or exact game ID from the validated local catalog."""
    if type(requested) is not str or not requested:
        raise ValueError("GAME is required")
    rows = tuple(_read_catalog(arc_root))
    matches = tuple(row for row in rows if row.get("game_id") == requested or row.get("alias") == requested)
    if len(matches) != 1:
        raise ValueError("GAME does not identify one local ARC game")
    row = matches[0]
    game_id = row.get("game_id")
    if type(game_id) is not str or _GAME.fullmatch(game_id) is None:
        raise ValueError("local game identity is invalid")
    return dict(row)


def next_unresolved_level(arc_root: Path, runs_root: Path, metadata: dict[str, Any], seed: int) -> int:
    """Return the next level after the locally verified prefix."""
    game_id = str(metadata["game_id"])
    prefix = load_best_prefix(arc_root, runs_root, game_id, seed)
    completed = 0 if prefix is None else prefix.levels_completed
    win_levels = metadata.get("win_levels")
    if type(win_levels) is not int or not 1 <= win_levels:
        raise ValueError("local game metadata has no level count")
    level = completed + 1
    if level > win_levels:
        raise ValueError("all local levels are already verified")
    return level


def _safe_summary(run: Path) -> dict[str, Any] | None:
    try:
        value = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return value if type(value) is dict else None


def _run_metrics(runs_root: Path, run_id: str | None) -> dict[str, Any]:
    if not run_id:
        return {"run_id": None, "status": "no-run", "action_count": 0, "input_tokens": 0, "output_tokens": 0}
    run = runs_root / run_id
    summary = _safe_summary(run) or {}
    diagnostics = summary.get("diagnostics") or {}
    sweep = diagnostics.get("sweep") or {}
    broker = summary.get("broker") or {}
    broker_status = diagnostics.get("broker_status") or {}
    receipt = summary.get("receipt") or {}
    status = receipt.get("status")
    try:
        trace = run / "trace" / "prime-trace.jsonl"
        rows = tuple(json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeError, ValueError):
        rows = ()
    actions = tuple(row for row in rows if type(row) is dict and row.get("kind") == "arc.action")
    usage = tuple(row.get("payload", {}) for row in rows if type(row) is dict and row.get("kind") == "arc.usage.reported")
    return {
        "run_id": run_id,
        "status": status or summary.get("status") or broker.get("terminal_reason") or summary.get("reason"),
        "action_count": len(actions),
        "completed_level_count": receipt.get("completed_level_count", broker.get("levels_completed", broker_status.get("levels_completed", sweep.get("levels_completed")))),
        "input_tokens": sum(item.get("input_tokens", 0) for item in usage if type(item.get("input_tokens")) is int),
        "output_tokens": sum(item.get("output_tokens", 0) for item in usage if type(item.get("output_tokens")) is int),
        "failed_attempt_advice": diagnostics.get("failed_attempt_advice"),
    }


def _validate_advice_binding(metrics: dict[str, Any], preflight_result: dict[str, Any]) -> None:
    """Require the guest run to record the exact advice selected before launch."""
    advice = metrics.get("failed_attempt_advice")
    if type(advice) is not dict:
        raise ValueError("retry run did not record failed-attempt advice")
    expected_ids = list(preflight_result["source_run_ids"])
    if (
        advice.get("source_run_ids") != expected_ids
        or advice.get("source_digest") != preflight_result["source_digest"]
        or advice.get("source_count") != preflight_result["source_count"]
        or advice.get("fact_count") != preflight_result["fact_count"]
    ):
        raise ValueError("retry run advice does not match preflight selection")


def _manifest_path(config: RetryConfig, game_id: str, level: int) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = config.runs_root / "retry-manifests"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root / f"{stamp}-{game_id}-level-{level}.json"


def preflight(config: RetryConfig) -> dict[str, Any]:
    if config.seed != 0 or config.run_timeout_seconds != 1800 or config.no_action_stall_seconds != 300:
        raise ValueError("P7 retry controls are fixed to seed 0, 30 minutes, and 5 minutes")
    metadata = resolve_game(config.arc_root, config.game)
    level = next_unresolved_level(config.arc_root, config.runs_root, metadata, config.seed)
    advice = select_failed_attempt_advice(
        config.runs_root, game_id=str(metadata["game_id"]), seed=config.seed, target_level=level,
    )
    if advice.source_count < 1:
        raise ValueError("no sealed same-game failed attempt is available for retry")
    if not _valid_p7_input(
        build_p7_retry_prompt(P7_SOLVE_PROMPT, render_failed_attempt_advice(advice))
    ):
        raise ValueError("installed P7 retry input is unavailable")
    return {
        "schema": _PREFLIGHT_SCHEMA,
        "ready": True,
        "game_id": metadata["game_id"],
        "target_level": level,
        "seed": config.seed,
        "run_timeout_seconds": config.run_timeout_seconds,
        "no_action_stall_seconds": config.no_action_stall_seconds,
        "source_run_ids": list(advice.source_run_ids),
        "source_digest": advice.source_digest,
        "source_count": advice.source_count,
        "fact_count": sum(len(run.actions) for run in advice.runs),
    }


def run_once(config: RetryConfig) -> dict[str, Any]:
    """Perform the one authorized attempt and write a private comparison manifest."""
    check = preflight(config)
    metadata = resolve_game(config.arc_root, config.game)
    level = int(check["target_level"])
    sweep = _load_sweep_module()
    scheduler = sweep.SweepScheduler(sweep.SweepConfig(
        arc_root=config.arc_root, runs_root=config.runs_root, games=(str(metadata["game_id"]),), seed=0,
        repo_root=config.operator_root, guest_machine=config.guest_machine,
        run_timeout= config.run_timeout_seconds, global_token_cap=None, wallclock_cap=None,
        unbounded_first_round=True, action_stall_seconds=config.no_action_stall_seconds,
        validate_action_stall=True,
    ))
    os.environ["ASTERION_PRIME_P7_RETRY_MODE"] = "same-game-failed-attempt"
    scheduler._attempt(str(metadata["game_id"]), level, config.run_timeout_seconds)
    run_id = scheduler._new_runs[-1] if len(scheduler._new_runs) == 1 else None
    metrics = _run_metrics(config.runs_root, run_id)
    if run_id is None:
        raise ValueError("retry produced ambiguous run evidence")
    _validate_advice_binding(metrics, check)
    result = {
        "schema": _RESULT_SCHEMA, "manifest_schema": _MANIFEST_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "game_id": metadata["game_id"], "target_level": level, "seed": 0,
        "source_run_ids": check["source_run_ids"], "source_digest": check["source_digest"],
        "run": metrics, "scheduler_stop_reason": scheduler._stop_reason,
        "breadth_ledger_touched": False,
    }
    path = _manifest_path(config, str(metadata["game_id"]), level)
    path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-root", type=Path, default=Path.cwd())
    parser.add_argument("--arc-root", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path)
    parser.add_argument("--game", required=True)
    parser.add_argument("--guest-machine", default=os.environ.get("PRIME_ORB_MACHINE", "ubuntu"))
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    root = args.operator_root.resolve()
    config = RetryConfig(root, args.arc_root.resolve(), (args.runs_root or root / ".asterion-private" / "prime-p7-live").resolve(), args.game, guest_machine=args.guest_machine)
    try:
        result = preflight(config) if args.preflight_only else run_once(config)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"schema": _PREFLIGHT_SCHEMA if args.preflight_only else _RESULT_SCHEMA, "ready": False, "error": str(error)}, sort_keys=True))
        return 1
    if args.preflight_only:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ready", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
