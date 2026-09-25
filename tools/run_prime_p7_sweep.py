"""Run a bounded breadth-first sweep over local ARC-AGI-3 game levels.

This driver is intentionally an operator tool.  It never talks to the ARC
service and it never submits a scorecard; each child invocation is a normal
local P7 attempt whose sealed private evidence is inspected afterwards.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from dataclasses import dataclass, field
import json
from hashlib import sha256
import math
import os
from pathlib import Path
import re
import signal
import secrets
import subprocess
import sys
import time
from typing import Any

from asterion.applications.prime.p7.game import _read_catalog
from asterion.applications.prime.p7.solutions import load_best_prefix


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FIRST_ROUND_EXCLUDED_GAME_IDS = frozenset({"ls20-9607627b"})
_FIRST_ROUND_REPLAYED_GAME_ID = "ar25-0c556536"
_FIRST_ROUND_CATALOG_SIZE = 25


@dataclass(frozen=True, slots=True)
class SweepConfig:
    arc_root: Path
    runs_root: Path
    games: tuple[str, ...] = ()
    seed: int = 0
    command: tuple[str, ...] = ("make", "asterion-prime-p7-sweep-attempt")
    repo_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])
    # LS20 L1 used 69,248 recorded tokens in 272s for 20 actions.  The 24
    # remaining first-level human baselines total 851 actions, implying ~2.95M
    # tokens and 3h13m at that rate.  Old telemetry omitted cache input; the
    # operator authorized a bounded 3.5M-token / 4h first sweep.
    global_token_cap: int | None = 3_500_000
    wallclock_cap: float | None = 4 * 60 * 60
    run_timeout: float | None = 30 * 60
    max_attempts: int | None = None
    guest_machine: str | None = "ubuntu"
    # This is an explicit, separately authorized local research pass. It
    # visits only games without a verified L1 prefix; no token, wallclock, or
    # per-attempt deadline is installed. The normal sweep stays bounded.
    unbounded_first_round: bool = False


@dataclass(frozen=True, slots=True)
class SweepResult:
    attempted: int
    completed: tuple[str, ...]
    blocked: tuple[str, ...]
    deferred: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    stopped_reason: str
    runs: tuple[str, ...]
    preexisting_level_one: tuple[str, ...] = ()
    newly_verified_level_one: tuple[str, ...] = ()
    attempted_unsolved_level_one: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Usage:
    input_tokens: int
    output_tokens: int
    model_activity_without_usage: bool


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return value if type(value) is dict else None


def read_run_usage(run: Path, *, in_progress: bool = False) -> tuple[int, int, bool, bool]:
    """Read only allowlisted token counters from one private run.

    The third value is true when an attempted run has no valid usage event.
    That condition stops the sweep so missing accounting cannot silently
    spend more, including a model call that never produced a worker cell.
    """

    trace = run / "trace" / "prime-trace.jsonl"
    input_tokens = output_tokens = 0
    usage_count = 0
    integrity_error = False
    try:
        if trace.is_symlink() or not trace.is_file():
            raise ValueError
        entries = _read_hash_chained_trace(trace, in_progress=in_progress)
    except _TraceIntegrityError as error:
        entries = error.rows
        integrity_error = True
    except Exception:
        entries = ()
        integrity_error = True
    for entry in entries:
        if entry["kind"] != "arc.usage.reported":
            continue
        payload = entry["payload"]
        incoming, outgoing = payload.get("input_tokens"), payload.get("output_tokens")
        if (
            isinstance(incoming, bool)
            or type(incoming) is not int
            or incoming < 0
            or isinstance(outgoing, bool)
            or type(outgoing) is not int
            or outgoing < 0
        ):
            integrity_error = True
            continue
        input_tokens += incoming
        output_tokens += outgoing
        usage_count += 1
    return input_tokens, output_tokens, usage_count == 0, integrity_error


class _TraceIntegrityError(ValueError):
    def __init__(self, rows: tuple[dict[str, Any], ...]) -> None:
        super().__init__("trace integrity error")
        self.rows = rows


def _read_hash_chained_trace(path: Path, *, in_progress: bool = False) -> tuple[dict[str, Any], ...]:
    """Validate a trace chain while permitting an interrupted unsealed prefix."""

    if path.is_symlink() or not path.is_file():
        raise ValueError
    rows: list[dict[str, Any]] = []
    previous: str | None = None
    identities: dict[str, Any] | None = None
    data = path.read_bytes()
    # A recorder can be between partial writes. Only complete lines are evidence.
    if in_progress and not data.endswith(b"\n"):
        data = data[:data.rfind(b"\n") + 1]
    for expected_sequence, line in enumerate(data.splitlines(), 1):
        try:
            row = json.loads(line)
            if type(row) is not dict or set(row) != {"identities", "kind", "payload", "previous_sha256", "sequence", "sha256"}:
                raise ValueError
            if row["sequence"] != expected_sequence or row["previous_sha256"] != previous:
                raise ValueError
            if type(row["identities"]) is not dict or type(row["payload"]) is not dict or type(row["kind"]) is not str:
                raise ValueError
            if identities is None:
                identities = row["identities"]
            elif row["identities"] != identities:
                raise ValueError
            digest_input = {"identities": row["identities"], "kind": row["kind"], "payload": row["payload"], "previous_sha256": previous, "sequence": expected_sequence}
            encoded = json.dumps(digest_input, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
            digest = "sha256:" + sha256(encoded).hexdigest()
            if row["sha256"] != digest:
                raise ValueError
            rows.append(row)
            previous = digest
        except (ValueError, UnicodeError, TypeError, KeyError) as error:
            raise _TraceIntegrityError(tuple(rows)) from error
    if not rows and not in_progress:
        raise ValueError
    return tuple(rows)


def _valid_attempt_summary(
    summary: dict[str, Any] | None, run_id: str, game_id: str, level: int, returncode: int,
) -> bool:
    """Accept only a verified puzzle terminal for the requested sweep attempt."""

    if not summary or any(summary.get(key) is not True for key in (
        "replay_verified", "sealed_trace", "cleanup_complete",
    )):
        return False
    broker = summary.get("broker")
    diagnostics = summary.get("diagnostics")
    sweep = diagnostics.get("sweep") if type(diagnostics) is dict else None
    if (
        summary.get("schema") != "asterion.prime.p7-live-private-summary/v1"
        or summary.get("run_id") != run_id
        or type(broker) is not dict
        or type(sweep) is not dict
        or broker.get("game_id") != game_id
        or broker.get("seed") != 0
        or sweep.get("scope") != "offline-research"
        or sweep.get("target_level") != level
        or type(sweep.get("run_action_cap")) is not int
        or type(sweep.get("level_action_cap")) is not int
        or not 0 < sweep["level_action_cap"] <= sweep["run_action_cap"]
        or type(broker.get("primitive_actions")) is not int
        or not 0 <= broker["primitive_actions"] <= sweep["run_action_cap"]
        or type(broker.get("levels_completed")) is not int
    ):
        return False
    if returncode == 0:
        return broker["levels_completed"] >= level and broker.get("terminal_reason") in {"level-completed", "game-won"}
    return (
        broker["levels_completed"] == level - 1
        and broker.get("terminal_reason") in {"human-baseline", "game-over"}
    )


class SweepScheduler:
    def __init__(self, config: SweepConfig) -> None:
        if config.seed != 0:
            raise ValueError("P7 sweep seed must be zero")
        bounded_budget = (
            type(config.global_token_cap) is int and config.global_token_cap > 0
            and type(config.wallclock_cap) in (int, float) and math.isfinite(config.wallclock_cap) and config.wallclock_cap > 0
            and type(config.run_timeout) in (int, float) and math.isfinite(config.run_timeout) and config.run_timeout > 0
        )
        if config.unbounded_first_round:
            if (
                config.global_token_cap not in (None, 3_500_000)
                or config.wallclock_cap not in (None, 4 * 60 * 60)
                or config.run_timeout not in (None, 30 * 60)
                or config.max_attempts is not None
            ):
                raise ValueError("P7 unbounded first round cannot have a budget cap")
        elif not bounded_budget:
            raise ValueError("P7 sweep budget is invalid")
        if config.max_attempts is not None and (type(config.max_attempts) is not int or config.max_attempts < 0):
            raise ValueError("P7 sweep budget is invalid")
        if config.guest_machine is None and config.command == ("make", "asterion-prime-p7-sweep-attempt"):
            raise ValueError("P7 sweep guest containment is required")
        self.config = config
        self._progress: dict[str, int] = {}
        self._new_runs: list[str] = []
        self._input_tokens = 0
        self._output_tokens = 0
        self._stop_reason = "completed"
        self._deferred_levels = self._find_deferred_levels()

    def _catalog(self) -> tuple[dict[str, object], ...]:
        try:
            return _read_catalog(self.config.arc_root)
        except (OSError, ValueError):
            return ()

    def _metadata(self) -> dict[str, dict[str, object]]:
        return {str(row["game_id"]): row for row in self._catalog()}

    def _selected_games(self) -> tuple[str, ...]:
        metadata = self._metadata()
        selected = self.config.games or tuple(sorted(metadata))
        # Explicit selections are still validated against the catalog when it
        # is available.  Keeping them in the empty-catalog case makes the
        # scheduler unit-testable and lets the child report the asset error.
        return tuple(
            game for game in selected
            if (not metadata or game in metadata)
            and (not self.config.unbounded_first_round or game not in _FIRST_ROUND_EXCLUDED_GAME_IDS)
        )

    def _first_round_campaign_is_ready(self, games: tuple[str, ...]) -> bool:
        """Require the pinned local campaign inventory before any attempt."""

        metadata = self._metadata()
        catalog_ids = frozenset(metadata)
        expected = tuple(sorted(catalog_ids - _FIRST_ROUND_EXCLUDED_GAME_IDS))
        if (
            self.config.games
            or len(metadata) != _FIRST_ROUND_CATALOG_SIZE
            or len(catalog_ids) != _FIRST_ROUND_CATALOG_SIZE
            or not _FIRST_ROUND_EXCLUDED_GAME_IDS <= catalog_ids
            or _FIRST_ROUND_REPLAYED_GAME_ID not in catalog_ids
            or games != expected
            or len(games) != _FIRST_ROUND_CATALOG_SIZE - len(_FIRST_ROUND_EXCLUDED_GAME_IDS)
        ):
            return False
        prefix = load_best_prefix(
            self.config.arc_root, self.config.runs_root,
            _FIRST_ROUND_REPLAYED_GAME_ID, self.config.seed,
        )
        return prefix is not None and prefix.levels_completed >= 1

    def _next_level(self, game_id: str) -> int:
        if game_id in self._progress:
            return self._progress[game_id] + 1
        prefix = load_best_prefix(self.config.arc_root, self.config.runs_root, game_id, self.config.seed)
        return 1 if prefix is None else prefix.levels_completed + 1

    def _is_complete(self, game_id: str, level: int) -> bool:
        metadata = self._metadata()[game_id]
        return level > int(metadata["win_levels"])

    def _timeout_for_level(self, game_id: str, level: int) -> float | None:
        """Scale the attempt window from the measured 272s / 20 actions."""

        if self.config.unbounded_first_round:
            return None

        metadata = self._metadata().get(game_id)
        baselines = metadata.get("baseline_actions") if metadata else None
        if type(baselines) is tuple and 0 < level <= len(baselines):
            baseline = baselines[level - 1]
            if type(baseline) is int and baseline > 0:
                return min(self.config.run_timeout, max(600, baseline * (272 / 20) * 1.2))
        return self.config.run_timeout

    def _find_deferred_levels(self) -> frozenset[tuple[str, int]]:
        """Safely defer a known over-baseline, unsealed LS20 L2 attempt."""

        result: set[tuple[str, int]] = set()
        metadata = {str(row["game_id"]): row for row in self._catalog()}
        try:
            runs = tuple(path for path in self.config.runs_root.iterdir() if path.is_dir() and not path.is_symlink())
        except OSError:
            return frozenset()
        for run in runs:
            summary = _read_json(run / "summary.json")
            diagnostics = summary.get("diagnostics") if summary else None
            broker_status = diagnostics.get("broker_status") if type(diagnostics) is dict else None
            if (
                not summary
                or summary.get("replay_verified") is True
                or type(diagnostics) is not dict
                or type(broker_status) is not dict
                or broker_status.get("levels_completed") != 1
                or type(broker_status.get("primitive_actions")) is not int
            ):
                continue
            game_id = _recorded_game_id(run, set(metadata))
            if game_id is None:
                continue
            baseline = tuple(metadata[game_id]["baseline_actions"])
            if len(baseline) >= 2 and broker_status["primitive_actions"] > sum(baseline[:2]):
                result.add((game_id, 2))
        return frozenset(result)

    def _attempt(self, game_id: str, level: int, timeout: float | None) -> int:
        before = _run_names(self.config.runs_root)
        process: subprocess.Popen[str] | None = None
        observed: dict[str, tuple[int, int]] = {}
        deadline = None if timeout is None else time.monotonic() + timeout
        unit = "asterion-p7-" + secrets.token_hex(16) + ".service"
        cleaned = False

        def cleanup_guest() -> None:
            nonlocal cleaned
            if cleaned or self.config.guest_machine is None:
                return
            try:
                result = subprocess.run(
                    ["orb", "-m", self.config.guest_machine, "-u", "root", "-w", "/tmp",
                     "python3", str(self.config.repo_root / "tools/run_prime_p7_guest.py"),
                     "cleanup", "--unit", unit],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=20, check=False,
                )
                cleaned = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                cleaned = False
            if not cleaned:
                self._stop_reason = "guest-cleanup-unconfirmed"


        def stop_child() -> None:
            assert process is not None
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
            cleanup_guest()

        def monitor() -> None:
            new = sorted(_run_names(self.config.runs_root) - before)
            if len(new) > 1:
                self._stop_reason = "child-evidence-ambiguous"
            for run_id in new:
                run = self.config.runs_root / run_id
                trace = run / "trace" / "prime-trace.jsonl"
                # Startup creates directories before opening the trace.
                if not trace.exists() and not trace.is_symlink():
                    continue
                usage = read_run_usage(run, in_progress=True)
                old = observed.get(run_id, (0, 0))
                if usage[3] or usage[0] < old[0] or usage[1] < old[1]:
                    self._stop_reason = "usage-trace-integrity-error"
                observed[run_id] = (max(old[0], usage[0]), max(old[1], usage[1]))
            reported = self._input_tokens + self._output_tokens + sum(sum(value) for value in observed.values())
            if not self.config.unbounded_first_round and self.config.global_token_cap is not None and reported >= self.config.global_token_cap and self._stop_reason == "completed":
                self._stop_reason = "token-cap"

        try:
            process = subprocess.Popen(
                [*self.config.command, f"GAME={game_id}", f"LEVEL={level}",
                 *([f"PRIME_ORB_MACHINE={self.config.guest_machine}"] if self.config.guest_machine else [])],
                cwd=self.config.repo_root,
                env={**os.environ, "ASTERION_PRIME_P7_SEED": "0",
                     "ASTERION_PRIME_P7_ATTEMPT_UNIT": unit,
                     "ASTERION_PRIME_P7_ATTEMPT_SECONDS": "0" if timeout is None else str(min(timeout, 4 * 60 * 60)),
                     "ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND": "1" if self.config.unbounded_first_round else "",
                     "OPERATION_MODE": "offline" if self.config.unbounded_first_round else ""},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                # Usage is reported after calls; this stops on reported tokens.
                # Provider-side in-flight/unreported usage can exceed that ceiling.
                while True:
                    monitor()
                    if self._stop_reason != "completed":
                        stop_child()
                        break
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        self._stop_reason = "run-timeout"
                        stop_child()
                        break
                    try:
                        process.communicate(timeout=0.25 if remaining is None else min(0.25, remaining))
                        monitor()
                        break
                    except subprocess.TimeoutExpired:
                        continue
                cleanup_guest()
                returncode = process.returncode
            except KeyboardInterrupt:
                stop_child()
                raise
        except OSError:
            if process is not None:
                stop_child()
            if self._stop_reason != "guest-cleanup-unconfirmed":
                self._stop_reason = "child-launch-failed"
            return 127
        new_runs = sorted((_run_names(self.config.runs_root) - before) | observed.keys())
        self._new_runs.extend(new_runs)
        if len(new_runs) != 1 and self._stop_reason == "completed":
            self._stop_reason = "child-evidence-missing" if not new_runs else "child-evidence-ambiguous"
        for run_id in new_runs:
            run = self.config.runs_root / run_id
            usage = read_run_usage(run)
            previous = observed.get(run_id, (0, 0))
            self._input_tokens += max(previous[0], usage[0])
            self._output_tokens += max(previous[1], usage[1])
            if usage[3] and self._stop_reason == "completed":
                self._stop_reason = "usage-trace-integrity-error"
            elif usage[2] and self._stop_reason == "completed":
                self._stop_reason = "usage-missing-after-model-activity"
            if len(new_runs) == 1 and self._stop_reason == "completed":
                summary = _read_json(run / "summary.json")
                try:
                    sealed = _read_hash_chained_trace(run / "trace" / "prime-trace.jsonl")[-1]["kind"] == "trace.sealed"
                except (OSError, UnicodeError, ValueError, KeyError, TypeError):
                    sealed = False
                if not sealed or not _valid_attempt_summary(summary, run_id, game_id, level, returncode):
                    self._stop_reason = "child-evidence-invalid"
        return returncode

    def _attempt_result(self, game_id: str, level: int) -> bool:
        prefix = load_best_prefix(self.config.arc_root, self.config.runs_root, game_id, self.config.seed)
        if prefix is None or prefix.levels_completed < level:
            return False
        self._progress[game_id] = prefix.levels_completed
        return True

    def run(self) -> SweepResult:
        games = self._selected_games()
        if self.config.unbounded_first_round and not self._first_round_campaign_is_ready(games):
            return SweepResult(0, (), (), (), 0, 0, "first-round-catalog-invalid", ())
        if not games:
            return SweepResult(0, (), (), (), 0, 0, "no-games", ())
        # A resumed sweep must finish untouched first levels before advancing
        # a previously verified game to its second level.
        active = sorted(games, key=lambda game_id: (self._next_level(game_id), game_id))
        blocked: list[str] = []
        completed: list[str] = []
        deferred: list[str] = []
        attempted = 0
        preexisting_level_one: list[str] = []
        newly_verified_level_one: list[str] = []
        attempted_unsolved_level_one: list[str] = []
        started = time.monotonic()
        if self.config.unbounded_first_round:
            unstarted: list[str] = []
            for game_id in active:
                if self._next_level(game_id) == 1:
                    unstarted.append(game_id)
                else:
                    preexisting_level_one.append(game_id)
            active = unstarted
        while active:
            next_active: list[str] = []
            for game_id in active:
                if self._stop_reason != "completed":
                    break
                if not self.config.unbounded_first_round and self.config.wallclock_cap is not None and time.monotonic() - started >= self.config.wallclock_cap:
                    self._stop_reason = "wallclock-cap"
                    break
                if not self.config.unbounded_first_round and self.config.global_token_cap is not None and self._input_tokens + self._output_tokens >= self.config.global_token_cap:
                    self._stop_reason = "token-cap"
                    break
                if self.config.max_attempts is not None and attempted >= self.config.max_attempts:
                    self._stop_reason = "attempt-cap"
                    break
                level = self._next_level(game_id)
                if self._is_complete(game_id, level):
                    completed.append(game_id)
                    continue
                if (game_id, level) in self._deferred_levels:
                    deferred.append(f"{game_id}:level-{level}")
                    blocked.append(game_id)
                    continue
                attempted += 1
                print(f"[p7-sweep] attempt game={game_id} level={level}", file=sys.stderr, flush=True)
                remaining = None if self.config.unbounded_first_round or self.config.wallclock_cap is None else self.config.wallclock_cap - (time.monotonic() - started)
                level_timeout = self._timeout_for_level(game_id, level)
                timeout = level_timeout if remaining is None else min(level_timeout, remaining)
                returncode = self._attempt(game_id, level, timeout)
                if self._stop_reason == "run-timeout" and not self.config.unbounded_first_round and self.config.wallclock_cap is not None and time.monotonic() - started >= self.config.wallclock_cap:
                    self._stop_reason = "wallclock-cap"
                if self._stop_reason != "completed":
                    print(f"[p7-sweep] stopped game={game_id} level={level} reason={self._stop_reason}", file=sys.stderr, flush=True)
                    break
                succeeded = self._attempt_result(game_id, level)
                if returncode == 0 and not succeeded:
                    self._stop_reason = "verified-prefix-missing"
                    break
                print(
                    f"[p7-sweep] result game={game_id} level={level} success={str(succeeded).lower()} "
                    f"input_tokens={self._input_tokens} output_tokens={self._output_tokens}",
                    file=sys.stderr,
                    flush=True,
                )
                if succeeded:
                    if self.config.unbounded_first_round and level == 1:
                        newly_verified_level_one.append(game_id)
                    if self.config.unbounded_first_round:
                        continue
                    next_level = self._next_level(game_id)
                    if self._is_complete(game_id, next_level):
                        completed.append(game_id)
                    else:
                        next_active.append(game_id)
                else:
                    if self.config.unbounded_first_round and level == 1:
                        attempted_unsolved_level_one.append(game_id)
                    blocked.append(game_id)
            if self._stop_reason != "completed":
                break
            active = next_active
        return SweepResult(
            attempted,
            tuple(sorted(set(completed))),
            tuple(sorted(set(blocked))),
            tuple(sorted(set(deferred))),
            self._input_tokens,
            self._output_tokens,
            self._stop_reason,
            tuple(self._new_runs),
            tuple(sorted(set(preexisting_level_one))),
            tuple(sorted(set(newly_verified_level_one))),
            tuple(sorted(set(attempted_unsolved_level_one))),
        )


def _run_names(runs_root: Path) -> set[str]:
    try:
        return {path.name for path in runs_root.iterdir() if path.is_dir() and not path.is_symlink() and _RUN_ID.fullmatch(path.name)}
    except OSError:
        return set()


def _recorded_game_id(run: Path, known: set[str]) -> str | None:
    recordings = run / "recordings"
    try:
        for path in recordings.rglob("*.jsonl"):
            if path.is_symlink():
                continue
            for game_id in known:
                if path.name.startswith(game_id + "-"):
                    return game_id
    except OSError:
        return None
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-root", type=Path, default=Path.cwd())
    parser.add_argument("--arc-root", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path)
    parser.add_argument("--game", action="append", dest="games", default=[])
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--token-cap", type=int, default=int(os.environ.get("ASTERION_PRIME_P7_SWEEP_TOKEN_CAP", "3500000")))
    parser.add_argument("--wallclock-seconds", type=float, default=float(os.environ.get("ASTERION_PRIME_P7_SWEEP_WALLCLOCK_SECONDS", "14400")))
    parser.add_argument("--guest-machine", default=os.environ.get("PRIME_ORB_MACHINE", "ubuntu"))
    parser.add_argument("--run-timeout", type=float, default=30 * 60)
    parser.add_argument("--max-attempts", type=int)
    parser.add_argument("--unbounded-first-round", action="store_true")
    args = parser.parse_args(argv)
    if args.seed != 0:
        parser.error("--seed must be 0; the P7 Makefile fixes the official game seed")
    runs_root = args.runs_root or args.operator_root / ".asterion-private" / "prime-p7-live"
    result = SweepScheduler(
        SweepConfig(
            arc_root=args.arc_root,
            runs_root=runs_root,
            games=tuple(args.games),
            seed=args.seed,
            global_token_cap=None if args.unbounded_first_round else args.token_cap,
            wallclock_cap=None if args.unbounded_first_round else args.wallclock_seconds,
            run_timeout=None if args.unbounded_first_round else args.run_timeout,
            max_attempts=args.max_attempts,
            repo_root=args.operator_root,
            guest_machine=args.guest_machine,
            unbounded_first_round=args.unbounded_first_round,
        )
    ).run()
    print(json.dumps({"schema": "asterion.prime.p7-sweep/v1", **asdict(result)}, sort_keys=True))
    return 0 if result.stopped_reason in {"completed", "no-games"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
