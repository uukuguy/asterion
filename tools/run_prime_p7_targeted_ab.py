"""Operator-only, finite OFFLINE P7 level-two legacy/verified comparison.

Run only after explicit operator authorization for the two model attempts. This
script reuses the sweep supervisor but never invokes its campaign runner.
"""

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
from asterion.applications.prime.p7.private_trace import are_p7_trace_identities
from asterion.applications.prime.p7.score import replay_sha256
from asterion.applications.prime.p7.solutions import VerifiedPrefix, load_best_prefix
# Direct ``python tools/...`` execution puts tools/ on sys.path; module imports
# use the repository root. Both paths bind the same supervisor implementation.
if __package__:
    from tools.run_prime_p7_sweep import (
        SweepConfig, SweepScheduler, _read_hash_chained_trace, _read_json,
        _valid_attempt_summary, read_run_usage,
    )
else:
    from run_prime_p7_sweep import (
        SweepConfig, SweepScheduler, _read_hash_chained_trace, _read_json,
        _valid_attempt_summary, read_run_usage,
    )

_TIMEOUT_SECONDS = 30 * 60
_STALL_SECONDS = 5 * 60
_RUN_ID = re.compile(r"p7-live-[0-9]{14}-[0-9a-f]{24}\Z")
_SCHEMA = "asterion.prime.p7-targeted-ab/v1"


def _manifest_path(operator_root: Path) -> Path:
    private = operator_root / ".asterion-private" / "prime-p7-targeted-ab"
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    if private.is_symlink() or not private.is_dir():
        raise ValueError("private A/B root is invalid")
    name = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return private / f"targeted-ab-{name}-{secrets.token_hex(8)}.json"


def _write_manifest(path: Path, value: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True, indent=2, allow_nan=False)
        output.write("\n")


def _read_arm(
    runs_root: Path, run_id: str, game_id: str, variant: str, returncode: int,
    prefix: VerifiedPrefix, baseline: int,
) -> dict[str, Any]:
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("A/B run ID is invalid")
    run = runs_root / run_id
    summary_path = run / "summary.json"
    trace_path = run / "trace" / "prime-trace.jsonl"
    seal_path = run / "trace" / "prime-trace.seal.json"
    if (run.is_symlink() or not run.is_dir() or summary_path.is_symlink()
            or trace_path.is_symlink() or seal_path.is_symlink()):
        raise ValueError("A/B private evidence is invalid")
    summary = _read_json(summary_path)
    entries = _read_hash_chained_trace(trace_path)
    seal = _read_json(seal_path)
    if (
        not entries or entries[-1]["kind"] != "trace.sealed"
        or any(not are_p7_trace_identities(row["identities"]) for row in entries)
        or [row["kind"] for row in entries[-2:]] != ["arc.run.completed", "trace.sealed"]
        or any(row["kind"] not in {"arc.action", "arc.usage.reported"} for row in entries[:-2])
        or entries[-1]["payload"] != {
            "entry_count": len(entries) - 1,
            "final_sha256": entries[-2]["sha256"],
        }
        or type(seal) is not dict
        or set(seal) != {"entry_count", "final_sha256", "sealed_at"}
        or seal["entry_count"] != len(entries)
        or seal["final_sha256"] != entries[-1]["sha256"]
        or type(seal["sealed_at"]) is not str
    ):
        raise ValueError("A/B sealed trace evidence is invalid")
    if not _valid_attempt_summary(summary, run_id, game_id, 2, returncode):
        raise ValueError("A/B summary or cleanup is invalid")
    assert summary is not None
    diagnostics = summary["diagnostics"]
    sweep = diagnostics["sweep"]
    experiment = summary.get("experiment")
    prefix_actions = len(prefix.transitions)
    cap = prefix_actions + baseline
    if (
        diagnostics.get("prediction_variant") != variant
        or sweep.get("prefix_actions") != prefix_actions
        or sweep.get("level_action_cap") != baseline
        or sweep.get("run_action_cap") != cap
        or type(experiment) is not dict
        or experiment.get("prediction_variant") != variant
        or experiment.get("model") != "deepseek-v4-flash"
        or experiment.get("game_id") != game_id
        or experiment.get("seed") != 0
        or experiment.get("target_level") != 2
        or experiment.get("action_cap") != cap
        or experiment.get("deadline_ms") is not None
        or experiment.get("stall_seconds") is not None
    ):
        raise ValueError("A/B variant or constraints differ")
    broker = summary["broker"]
    completed = entries[-2]["payload"]
    if (
        broker.get("win_levels") != prefix.win_levels
        or completed != broker
        or set(completed) != {
            "game_id", "seed", "win_levels", "levels_completed",
            "primitive_actions", "terminal_reason", "replay_sha256",
        }
    ):
        raise ValueError("A/B completed-run evidence is invalid")
    transitions = []
    previous_hash = None
    previous_level = 0
    for sequence, row in enumerate(
        (row for row in entries if row["kind"] == "arc.action"), 1,
    ):
        payload = row["payload"]
        data = payload.get("data", {})
        if (
            set(payload) not in (
                {"sequence", "action", "before_sha256", "after_sha256", "levels_completed"},
                {"sequence", "action", "before_sha256", "after_sha256", "levels_completed", "data"},
            )
            or type(payload.get("sequence")) is not int or payload["sequence"] != sequence
            or type(payload.get("action")) is not str
            or type(payload.get("before_sha256")) is not str
            or type(payload.get("after_sha256")) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", payload["before_sha256"]) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", payload["after_sha256"]) is None
            or (previous_hash is not None and payload["before_sha256"] != previous_hash)
            or type(payload.get("levels_completed")) is not int
            or not previous_level <= payload["levels_completed"] <= previous_level + 1
            or (sequence < prefix_actions and payload["levels_completed"] != 0)
            or (sequence >= prefix_actions and sequence <= prefix_actions
                and payload["levels_completed"] != 1)
            or (sequence > prefix_actions and payload["levels_completed"] < 1)
            or type(data) is not dict
            or any(type(key) is not str or type(value) is not int for key, value in data.items())
        ):
            raise ValueError("A/B action trace is invalid")
        transitions.append(ArcTransition(
            sequence, payload["action"], payload["before_sha256"],
            payload["after_sha256"], payload["levels_completed"],
            tuple(sorted(data.items())),
        ))
        previous_hash = payload["after_sha256"]
        previous_level = payload["levels_completed"]
    count = broker["primitive_actions"]
    if (
        len(transitions) != count or count < prefix_actions
        or tuple(transitions[:prefix_actions]) != prefix.transitions
        or previous_level != broker["levels_completed"]
        or replay_sha256(transitions, terminal_reason=broker["terminal_reason"])
        != broker.get("replay_sha256")
        or (broker["terminal_reason"] == "human-baseline" and count != cap)
        or (broker["terminal_reason"] == "game-over" and count >= cap)
    ):
        raise ValueError("A/B action accounting or replay digest is invalid")
    input_tokens, output_tokens, usage_missing, usage_invalid = read_run_usage(run)
    if usage_missing or usage_invalid:
        raise ValueError("A/B token accounting is invalid")
    outcome = "verified" if returncode == 0 else "unsolved"
    return {
        "variant": variant,
        "run_id": run_id,
        "outcome": outcome,
        "terminal_reason": summary["broker"]["terminal_reason"],
        "levels_completed": summary["broker"]["levels_completed"],
        "level_two_actions": count - prefix_actions,
        "primitive_actions": count,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "trace_final_sha256": entries[-1]["sha256"],
        "evidence": str(run.relative_to(runs_root.parent.parent)),
    }


def run_targeted_ab(
    operator_root: Path, arc_root: Path, game_id: str, *, guest_machine: str = "ubuntu",
) -> dict[str, Any]:
    """Run exactly one legacy arm and one verified arm from a sealed L1 prefix."""

    operator_root = operator_root.resolve(strict=True)
    arc_root = arc_root.resolve(strict=True)
    if not guest_machine or not re.fullmatch(r"[A-Za-z0-9._-]+", guest_machine):
        raise ValueError("P7 guest machine is invalid")
    catalog = _read_catalog(arc_root)
    matches = [row for row in catalog if game_id in {row["game_id"], row.get("alias")}]
    if len(matches) != 1 or len(matches[0]["baseline_actions"]) < 2:
        raise ValueError("P7 game is absent or ambiguous in the exact local catalog")
    metadata = matches[0]
    game_id = metadata["game_id"]
    baseline = metadata["baseline_actions"][1]
    runs_root = operator_root / ".asterion-private" / "prime-p7-live"
    prefix = load_best_prefix(arc_root, runs_root, game_id, 0, max_level=1)
    if (
        prefix is None or prefix.game_id != game_id or prefix.seed != 0
        or prefix.win_levels != metadata["win_levels"]
        or prefix.levels_completed != 1 or not prefix.transitions
        or len(prefix.transitions) + baseline > 5000
    ):
        raise ValueError("verified P7 level-one start is unavailable")
    manifest = {
        "schema": _SCHEMA, "game_id": game_id, "seed": 0, "target_level": 2,
        "model": "deepseek-v4-flash", "prefix_run_id": prefix.source_run_id,
        "prefix_replay_sha256": prefix.replay_sha256,
        "prefix_actions": len(prefix.transitions), "level_two_action_cap": baseline,
        "run_action_cap": len(prefix.transitions) + baseline,
        "timeout_seconds": _TIMEOUT_SECONDS, "no_action_stall_seconds": _STALL_SECONDS,
        "status": "incomplete", "arms": [],
    }
    path = _manifest_path(operator_root)
    config = SweepConfig(
        arc_root=arc_root, runs_root=runs_root, games=(game_id,), seed=0,
        repo_root=operator_root, guest_machine=guest_machine,
        global_token_cap=None, wallclock_cap=None,
        run_timeout=_TIMEOUT_SECONDS, unbounded_second_round=True,
    )
    try:
        for variant in ("legacy", "verified"):
            current = load_best_prefix(arc_root, runs_root, game_id, 0, max_level=1)
            if current is None or (
                current.source_run_id, current.replay_sha256, current.transitions
            ) != (prefix.source_run_id, prefix.replay_sha256, prefix.transitions):
                raise ValueError("verified P7 start changed between arms")
            scheduler = SweepScheduler(config)
            prior_variant = os.environ.get("ASTERION_PRIME_P7_HISTORY_VARIANT")
            os.environ["ASTERION_PRIME_P7_HISTORY_VARIANT"] = variant
            try:
                returncode = scheduler._attempt(game_id, 2, _TIMEOUT_SECONDS)
            finally:
                if prior_variant is None:
                    os.environ.pop("ASTERION_PRIME_P7_HISTORY_VARIANT", None)
                else:
                    os.environ["ASTERION_PRIME_P7_HISTORY_VARIANT"] = prior_variant
            if scheduler._stop_reason != "completed" or len(scheduler._new_runs) != 1:
                raise ValueError(f"A/B arm {variant} stopped: {scheduler._stop_reason}")
            arm = _read_arm(
                runs_root, scheduler._new_runs[0], game_id, variant, returncode,
                prefix, baseline,
            )
            if any(existing["run_id"] == arm["run_id"] for existing in manifest["arms"]):
                raise ValueError("A/B arms reused one run directory")
            manifest["arms"].append(arm)
        first, second = manifest["arms"]
        manifest["status"] = "complete"
        manifest["comparison"] = {
            "verified_level_two_passed": second["outcome"] == "verified",
            "legacy_level_two_passed": first["outcome"] == "verified",
            "verified_minus_legacy_level_two_actions": second["level_two_actions"] - first["level_two_actions"],
            "verified_minus_legacy_total_tokens": (
                second["input_tokens"] + second["output_tokens"]
                - first["input_tokens"] - first["output_tokens"]
            ),
        }
    except Exception as error:
        manifest["status"] = "aborted"
        manifest["abort_reason"] = type(error).__name__
        _write_manifest(path, manifest)
        raise
    _write_manifest(path, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-root", type=Path, default=Path.cwd())
    parser.add_argument("--arc-root", type=Path, required=True)
    parser.add_argument("--game", required=True)
    parser.add_argument("--guest-machine", default="ubuntu")
    args = parser.parse_args(argv)
    try:
        manifest = run_targeted_ab(args.operator_root, args.arc_root, args.game,
                                   guest_machine=args.guest_machine)
    except (OSError, ValueError) as error:
        print(f"[p7-targeted-ab] {error}", file=sys.stderr)
        return 1
    print(json.dumps({"schema": _SCHEMA, "status": manifest["status"],
                      "game_id": manifest["game_id"], "arm_count": len(manifest["arms"])},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
