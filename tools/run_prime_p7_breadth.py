"""Run one resumable local P7 breadth resweep over Levels 1 and 2.

This is an operator tool.  It owns a ledger separate from the historical
first and second round ledgers and never creates an official scorecard.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import secrets
import tempfile
from typing import Any

from asterion.applications.prime.p7.game import _read_catalog
from asterion.applications.prime.p7.private_trace import P7_TRACE_IDENTITIES
from asterion.applications.prime.p7.solutions import load_best_prefix

from tools.run_prime_p7_sweep import (
    _ACTION_STALL_SECONDS,
    _RUN_ID,
    _recorded_game_id,
    _read_hash_chained_trace,
    _valid_attempt_summary,
    SweepConfig,
    SweepScheduler,
    read_run_usage,
)


_SCHEMA = "asterion.prime.p7-breadth-campaign/v1"
_PREFLIGHT_SCHEMA = "asterion.prime.p7-breadth-preflight/v1"
_RESULT_SCHEMA = "asterion.prime.p7-breadth-result/v1"
_LEDGER_FILE = "breadth-resweep-campaign.json"
_OUTCOMES = frozenset({
    "verified", "unsolved", "timed-out-unsealed", "execution-failed", "execution-stalled",
})


@dataclass(frozen=True, slots=True)
class BreadthCampaignConfig:
    arc_root: Path
    runs_root: Path
    operator_root: Path
    repo_root: Path
    guest_machine: str | None = "ubuntu"
    seed: int = 0
    run_timeout: float = 30 * 60
    action_stall_seconds: int = _ACTION_STALL_SECONDS


@dataclass(frozen=True, slots=True)
class BreadthCampaignResult:
    attempted: int
    level_one_queue: tuple[str, ...]
    level_two_queue: tuple[str, ...]
    newly_verified_level_one: tuple[str, ...]
    newly_verified_level_two: tuple[str, ...]
    blocked: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    stopped_reason: str
    runs: tuple[str, ...]


class BreadthCampaignController:
    def __init__(self, config: BreadthCampaignConfig) -> None:
        if config.seed != 0:
            raise ValueError("P7 breadth seed must be zero")
        if config.run_timeout != 30 * 60:
            raise ValueError("P7 breadth uses the 30-minute per-game limit")
        if config.action_stall_seconds != _ACTION_STALL_SECONDS:
            raise ValueError("P7 breadth uses the five-minute no-action limit")
        self.config = config

    def _catalog(self) -> tuple[dict[str, Any], ...]:
        return tuple(_read_catalog(self.config.arc_root))

    def _metadata(self) -> dict[str, dict[str, Any]]:
        return {str(row["game_id"]): row for row in self._catalog()}

    def _best_prefix(self, game_id: str) -> Any:
        return load_best_prefix(self.config.arc_root, self.config.runs_root, game_id, self.config.seed)

    def _select_level_one(self) -> tuple[str, ...]:
        return tuple(sorted(game for game in self._metadata() if self._best_prefix(game) is None))

    def _select_level_two(self) -> tuple[str, ...]:
        selected = []
        for game_id, metadata in self._metadata().items():
            prefix = self._best_prefix(game_id)
            if (
                prefix is not None and prefix.levels_completed == 1
                and len(metadata.get("baseline_actions", ())) >= 2
                and metadata.get("win_levels", 0) >= 2
            ):
                selected.append(game_id)
        return tuple(sorted(selected))

    def _already_verified_level_two(self) -> tuple[str, ...]:
        return tuple(sorted(game for game in self._metadata() if (
            (prefix := self._best_prefix(game)) is not None and prefix.levels_completed >= 2
        )))

    def preflight(self) -> dict[str, Any]:
        level_one = self._select_level_one()
        level_two = self._select_level_two()
        return {
            "schema": _PREFLIGHT_SCHEMA,
            "seed": self.config.seed,
            "run_timeout_seconds": int(self.config.run_timeout),
            "no_action_stall_seconds": self.config.action_stall_seconds,
            "level_one": list(level_one),
            "level_two": list(level_two),
            "level_one_count": len(level_one),
            "level_two_count": len(level_two),
            "already_verified_level_two": list(self._already_verified_level_two()),
        }

    def _ledger_path(self) -> Path:
        root = self.config.runs_root
        if root.is_symlink():
            raise ValueError("breadth runs root is a symlink")
        root.mkdir(parents=True, exist_ok=True)
        return root / _LEDGER_FILE

    def _write_ledger(self, ledger: dict[str, Any]) -> None:
        path = self._ledger_path()
        if path.is_symlink():
            raise ValueError("breadth ledger is a symlink")
        fd, temporary = tempfile.mkstemp(prefix=".p7-breadth-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(ledger, stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _load_or_create_ledger(self) -> dict[str, Any]:
        path = self._ledger_path()
        if not path.exists():
            ledger = {
                "schema": _SCHEMA,
                "campaign_id": "breadth-resweep-" + secrets.token_hex(16),
                "seed": 0,
                "run_timeout_seconds": 1800,
                "no_action_stall_seconds": _ACTION_STALL_SECONDS,
                "terminal_attempts": [],
            }
            self._write_ledger(ledger)
            return ledger
        if path.is_symlink():
            raise ValueError("breadth ledger is a symlink")
        try:
            ledger = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            raise ValueError("breadth ledger is invalid") from error
        if (
            type(ledger) is not dict or ledger.get("schema") != _SCHEMA
            or ledger.get("seed") != 0 or ledger.get("run_timeout_seconds") != 1800
            or ledger.get("no_action_stall_seconds") != _ACTION_STALL_SECONDS
            or type(ledger.get("campaign_id")) is not str
            or not ledger["campaign_id"].startswith("breadth-resweep-")
            or type(ledger.get("terminal_attempts")) is not list
        ):
            raise ValueError("breadth ledger is invalid")
        pairs: set[tuple[str, int]] = set()
        runs: set[str] = set()
        for entry in ledger["terminal_attempts"]:
            if type(entry) is not dict:
                raise ValueError("breadth ledger entry is invalid")
            if entry.get("status") == "running":
                raise _RunningEntryRequiresAudit
            pair = (entry.get("game_id"), entry.get("target_level"))
            run_id = entry.get("run_id")
            if (
                type(pair[0]) is not str or type(pair[1]) is not int or pair[1] not in (1, 2)
                or pair in pairs or type(run_id) is not str or not _RUN_ID.fullmatch(run_id)
                or run_id in runs or entry.get("outcome") not in _OUTCOMES
                or not self._terminal_entry_is_valid(entry)
            ):
                raise ValueError("breadth ledger evidence is invalid")
            pairs.add(pair)
            runs.add(run_id)
        return ledger

    def _make_scheduler(self) -> SweepScheduler:
        return SweepScheduler(SweepConfig(
            arc_root=self.config.arc_root,
            runs_root=self.config.runs_root,
            games=(),
            seed=self.config.seed,
            repo_root=self.config.repo_root,
            guest_machine=self.config.guest_machine,
            global_token_cap=None,
            wallclock_cap=None,
            run_timeout=self.config.run_timeout,
            max_attempts=None,
            # Breadth is an explicitly authorized research pass.  This is
            # required when aggregate caps are disabled, while the target
            # level remains controlled by the direct _attempt call below.
            unbounded_second_round=True,
            action_stall_seconds=self.config.action_stall_seconds,
            validate_action_stall=True,
        ))

    @staticmethod
    def _has_terminal(ledger: dict[str, Any], game_id: str, level: int) -> bool:
        return any(
            entry.get("game_id") == game_id and entry.get("target_level") == level
            for entry in ledger["terminal_attempts"]
        )

    def _terminal_entry_is_valid(self, entry: dict[str, Any]) -> bool:
        run_id, game_id, level = entry.get("run_id"), entry.get("game_id"), entry.get("target_level")
        if (
            type(run_id) is not str or _RUN_ID.fullmatch(run_id) is None
            or type(game_id) is not str or type(level) is not int or level not in (1, 2)
            or type(entry.get("action_count")) is not int or entry["action_count"] < 0
            or any(type(entry.get(key)) is not int or entry[key] < 0 for key in ("input_tokens", "output_tokens"))
            or type(entry.get("evidence_sha256")) is not str
        ):
            return False
        run = self.config.runs_root / run_id
        trace_path = run / "trace" / "prime-trace.jsonl"
        if run.is_symlink() or trace_path.is_symlink() or not trace_path.is_file():
            return False
        outcome = entry.get("outcome")
        try:
            in_progress = outcome in {"timed-out-unsealed", "execution-stalled"}
            entries = _read_hash_chained_trace(trace_path, in_progress=in_progress)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError):
            return False
        if not entries or entry["evidence_sha256"] != entries[-1]["sha256"]:
            return False
        if any(row.get("identities") != P7_TRACE_IDENTITIES for row in entries):
            return False
        usage = read_run_usage(run, in_progress=in_progress)
        if usage[3] or usage[2] or (entry["input_tokens"], entry["output_tokens"]) != usage[:2]:
            return False
        actions = sum(row.get("kind") == "arc.action" for row in entries)
        if actions != entry["action_count"] or _recorded_game_id(run, {game_id}) != game_id:
            return False
        metadata = self._metadata().get(game_id)
        baselines = metadata.get("baseline_actions") if metadata else None
        if (
            type(baselines) is not tuple or len(baselines) < level
            or any(type(item) is not int or item <= 0 for item in baselines[:level])
            or actions > sum(baselines[:level])
        ):
            return False
        if outcome == "verified":
            if entries[-1]["kind"] != "trace.sealed":
                return False
            summary_path = run / "summary.json"
            summary = None if summary_path.is_symlink() else self._read_json(summary_path)
            if not _valid_attempt_summary(summary, run_id, game_id, level, 0):
                return False
            prefix = self._best_prefix(game_id)
            return prefix is not None and prefix.source_run_id == run_id and prefix.levels_completed >= level
        if outcome == "unsolved":
            if entries[-1]["kind"] != "trace.sealed":
                return False
            summary_path = run / "summary.json"
            summary = None if summary_path.is_symlink() else self._read_json(summary_path)
            return _valid_attempt_summary(summary, run_id, game_id, level, 1)
        if outcome == "timed-out-unsealed":
            return entries[-1]["kind"] != "trace.sealed" and not (run / "summary.json").exists()
        if outcome == "execution-stalled":
            receipt = self._read_json(run / "stall-receipt.json")
            if not receipt or receipt.get("run_id") != run_id or receipt.get("game_id") != game_id:
                return False
            try:
                return self._make_scheduler()._execution_stalled_is_valid(
                    run_id, game_id, target_level=level, allow_later_progress=True,
                )
            except (AttributeError, OSError, ValueError, KeyError, TypeError):
                return False
        if outcome == "execution-failed":
            try:
                return self._make_scheduler()._execution_failure_is_valid(
                    run_id, game_id, allow_later_progress=True,
                )
            except (AttributeError, OSError, ValueError, KeyError, TypeError):
                return False
        return False

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return None
        return value if type(value) is dict else None

    def _attempt_pair(self, ledger: dict[str, Any], game_id: str, level: int) -> dict[str, Any]:
        running = {
            "status": "running", "game_id": game_id, "target_level": level,
            "started_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        }
        ledger["terminal_attempts"].append(running)
        self._write_ledger(ledger)
        scheduler = self._make_scheduler()
        try:
            returncode = scheduler._attempt(game_id, level, self.config.run_timeout)
        except KeyboardInterrupt:
            raise
        run_ids = tuple(getattr(scheduler, "_new_runs", ()))
        run_id = run_ids[-1] if len(run_ids) == 1 else None
        stop_reason = getattr(scheduler, "_stop_reason", "completed")
        verified = returncode == 0 and bool(scheduler._attempt_result(game_id, level)) if stop_reason == "completed" else False
        outcome = "verified" if verified else {
            "execution-stalled": "execution-stalled",
            "timed-out-unsealed": "timed-out-unsealed",
            "execution-failed": "execution-failed",
        }.get(stop_reason, "unsolved" if stop_reason == "completed" else "execution-failed")
        if run_id is None:
            raise ValueError("breadth attempt did not produce one run")
        run = self.config.runs_root / run_id
        try:
            entries = _read_hash_chained_trace(run / "trace" / "prime-trace.jsonl", in_progress=outcome in {"timed-out-unsealed", "execution-stalled"})
            evidence = entries[-1]["sha256"]
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
            raise ValueError("breadth attempt evidence is invalid") from error
        usage = read_run_usage(run, in_progress=outcome in {"timed-out-unsealed", "execution-stalled"})
        if usage[2] or usage[3]:
            raise ValueError("breadth attempt usage is invalid")
        entry = {
            "game_id": game_id, "target_level": level, "run_id": run_id,
            "outcome": outcome, "action_count": sum(row["kind"] == "arc.action" for row in entries),
            "input_tokens": usage[0], "output_tokens": usage[1],
            "stop_reason": stop_reason, "evidence_sha256": evidence,
        }
        if not self._terminal_entry_is_valid(entry):
            raise ValueError("breadth attempt evidence failed validation")
        ledger["terminal_attempts"][-1] = entry
        self._write_ledger(ledger)
        return {
            "attempted": 1, "verified": verified, "runs": (run_id,),
            "input_tokens": usage[0], "output_tokens": usage[1], "stop_reason": "completed",
        }

    def run(self) -> BreadthCampaignResult:
        try:
            ledger = self._load_or_create_ledger()
        except _RunningEntryRequiresAudit:
            return BreadthCampaignResult(0, (), (), (), (), (), 0, 0, "breadth-running-entry-requires-audit", ())
        except (OSError, ValueError):
            return BreadthCampaignResult(0, (), (), (), (), (), 0, 0, "breadth-ledger-invalid", ())
        level_one = tuple(game for game in self._select_level_one() if not self._has_terminal(ledger, game, 1))
        attempted = 0
        blocked: list[str] = []
        new_l1: list[str] = []
        new_l2: list[str] = []
        runs: list[str] = []
        input_tokens = output_tokens = 0
        for game_id in level_one:
            try:
                outcome = self._attempt_pair(ledger, game_id, 1)
            except (OSError, ValueError):
                return BreadthCampaignResult(attempted, level_one, (), tuple(new_l1), tuple(new_l2), tuple(blocked), input_tokens, output_tokens, "breadth-evidence-invalid", tuple(runs))
            attempted += 1
            runs.extend(outcome["runs"])
            input_tokens += outcome["input_tokens"]
            output_tokens += outcome["output_tokens"]
            if outcome["verified"]:
                new_l1.append(game_id)
            else:
                blocked.append(f"{game_id}:level-1")
        level_two = tuple(game for game in self._select_level_two() if not self._has_terminal(ledger, game, 2))
        for game_id in level_two:
            try:
                outcome = self._attempt_pair(ledger, game_id, 2)
            except (OSError, ValueError):
                return BreadthCampaignResult(attempted, level_one, level_two, tuple(new_l1), tuple(new_l2), tuple(blocked), input_tokens, output_tokens, "breadth-evidence-invalid", tuple(runs))
            attempted += 1
            runs.extend(outcome["runs"])
            input_tokens += outcome["input_tokens"]
            output_tokens += outcome["output_tokens"]
            if outcome["verified"]:
                new_l2.append(game_id)
            else:
                blocked.append(f"{game_id}:level-2")
        reason = "completed" if attempted or level_one or level_two else "no-games"
        return BreadthCampaignResult(attempted, level_one, level_two, tuple(new_l1), tuple(new_l2), tuple(blocked), input_tokens, output_tokens, reason, tuple(runs))


class _RunningEntryRequiresAudit(Exception):
    pass


def _default_runs_root(operator_root: Path) -> Path:
    return operator_root / ".asterion-private" / "prime-p7-live"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-root", type=Path, default=Path.cwd())
    parser.add_argument("--arc-root", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path)
    parser.add_argument("--guest-machine", default=os.environ.get("PRIME_ORB_MACHINE", "ubuntu"))
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    operator_root = args.operator_root.resolve()
    config = BreadthCampaignConfig(
        arc_root=args.arc_root.resolve(),
        runs_root=(args.runs_root or _default_runs_root(operator_root)).resolve(),
        operator_root=operator_root, repo_root=operator_root, guest_machine=args.guest_machine,
    )
    controller = BreadthCampaignController(config)
    if args.preflight_only:
        print(json.dumps(controller.preflight(), sort_keys=True))
        return 0
    result = controller.run()
    print(json.dumps({"schema": _RESULT_SCHEMA, **asdict(result)}, sort_keys=True))
    return 0 if result.stopped_reason in {"completed", "no-games"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
