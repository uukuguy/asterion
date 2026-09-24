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
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any

from asterion.applications.prime.p7.game import _read_catalog
from asterion.applications.prime.p7.solutions import load_best_prefix


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class SweepConfig:
    arc_root: Path
    runs_root: Path
    games: tuple[str, ...] = ()
    seed: int = 0
    command: tuple[str, ...] = ("make", "asterion-prime-p7-sweep-attempt")
    repo_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])
    global_token_cap: int = 1_000_000
    wallclock_cap: float = 2 * 60 * 60
    run_timeout: float = 10 * 60
    max_attempts: int | None = None


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


def read_run_usage(run: Path) -> tuple[int, int, bool]:
    """Read only allowlisted token counters from one private run.

    The third value is true when worker activity exists but no valid usage
    event exists.  That condition is deliberately treated as a hard stop by
    the sweep so a missing accounting event cannot silently spend more.
    """

    trace = run / "trace" / "prime-trace.jsonl"
    input_tokens = output_tokens = 0
    usage_count = 0
    try:
        if trace.is_symlink() or not trace.is_file():
            rows: list[dict[str, Any]] = []
        else:
            rows = []
            for line in trace.read_text(encoding="utf-8").splitlines():
                value = json.loads(line)
                if type(value) is dict:
                    rows.append(value)
    except (OSError, UnicodeError, ValueError):
        rows = []
    for row in rows:
        if row.get("kind") != "arc.usage.reported":
            continue
        payload = row.get("payload")
        if type(payload) is not dict:
            continue
        incoming, outgoing = payload.get("input_tokens"), payload.get("output_tokens")
        if (
            isinstance(incoming, bool)
            or type(incoming) is not int
            or incoming < 0
            or isinstance(outgoing, bool)
            or type(outgoing) is not int
            or outgoing < 0
        ):
            continue
        input_tokens += incoming
        output_tokens += outgoing
        usage_count += 1
    worker_cells = run / "worker-cells.jsonl"
    model_activity = False
    try:
        model_activity = worker_cells.is_file() and bool(worker_cells.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError):
        model_activity = False
    return input_tokens, output_tokens, bool(model_activity and usage_count == 0)


class SweepScheduler:
    def __init__(self, config: SweepConfig) -> None:
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
        return tuple(game for game in selected if not metadata or game in metadata)

    def _next_level(self, game_id: str) -> int:
        if game_id in self._progress:
            return self._progress[game_id] + 1
        prefix = load_best_prefix(self.config.arc_root, self.config.runs_root, game_id, self.config.seed)
        return 1 if prefix is None else prefix.levels_completed + 1

    def _is_complete(self, game_id: str, level: int) -> bool:
        metadata = self._metadata()[game_id]
        return level > int(metadata["win_levels"])

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
            if (
                not summary
                or summary.get("replay_verified") is True
                or type(diagnostics) is not dict
                or diagnostics.get("levels_completed") != 1
                or type(diagnostics.get("primitive_actions")) is not int
            ):
                continue
            game_id = _recorded_game_id(run, set(metadata))
            if game_id is None:
                continue
            baseline = tuple(metadata[game_id]["baseline_actions"])
            if len(baseline) >= 2 and diagnostics["primitive_actions"] > sum(baseline[:2]):
                result.add((game_id, 2))
        return frozenset(result)

    def _attempt(self, game_id: str, level: int, timeout: float) -> int:
        before = _run_names(self.config.runs_root)
        try:
            completed = subprocess.run(
                [*self.config.command, f"GAME={game_id}", f"LEVEL={level}"],
                cwd=self.config.repo_root,
                env={**os.environ, "ASTERION_PRIME_P7_SEED": str(self.config.seed)},
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            self._stop_reason = "run-timeout"
            return 124
        new_runs = sorted(_run_names(self.config.runs_root) - before)
        self._new_runs.extend(new_runs)
        for run_id in new_runs:
            usage = read_run_usage(self.config.runs_root / run_id)
            self._input_tokens += usage[0]
            self._output_tokens += usage[1]
            if usage[2]:
                self._stop_reason = "usage-missing-after-model-activity"
        return completed.returncode

    def _attempt_result(self, game_id: str, level: int) -> bool:
        prefix = load_best_prefix(self.config.arc_root, self.config.runs_root, game_id, self.config.seed)
        if prefix is None or prefix.levels_completed < level:
            return False
        self._progress[game_id] = prefix.levels_completed
        return True

    def run(self) -> SweepResult:
        games = self._selected_games()
        if not games:
            return SweepResult(0, (), (), (), 0, 0, "no-games", ())
        active = list(games)
        blocked: list[str] = []
        completed: list[str] = []
        deferred: list[str] = []
        attempted = 0
        started = time.monotonic()
        while active:
            next_active: list[str] = []
            for game_id in active:
                if self._stop_reason != "completed":
                    break
                if time.monotonic() - started >= self.config.wallclock_cap:
                    self._stop_reason = "wallclock-cap"
                    break
                if self._input_tokens + self._output_tokens >= self.config.global_token_cap:
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
                self._attempt(game_id, level, self.config.run_timeout)
                if self._stop_reason != "completed":
                    break
                if self._attempt_result(game_id, level):
                    next_level = self._next_level(game_id)
                    if self._is_complete(game_id, next_level):
                        completed.append(game_id)
                    else:
                        next_active.append(game_id)
                else:
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
    parser.add_argument("--token-cap", type=int, default=1_000_000)
    parser.add_argument("--wallclock-seconds", type=float, default=2 * 60 * 60)
    parser.add_argument("--run-timeout", type=float, default=10 * 60)
    parser.add_argument("--max-attempts", type=int)
    args = parser.parse_args(argv)
    runs_root = args.runs_root or args.operator_root / ".asterion-private" / "prime-p7-live"
    result = SweepScheduler(
        SweepConfig(
            arc_root=args.arc_root,
            runs_root=runs_root,
            games=tuple(args.games),
            seed=args.seed,
            global_token_cap=args.token_cap,
            wallclock_cap=args.wallclock_seconds,
            run_timeout=args.run_timeout,
            max_attempts=args.max_attempts,
        )
    ).run()
    print(json.dumps({"schema": "asterion.prime.p7-sweep/v1", **asdict(result)}, sort_keys=True))
    return 0 if result.stopped_reason in {"completed", "no-games"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
