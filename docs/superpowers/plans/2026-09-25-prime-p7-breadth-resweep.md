# Prime P7 Breadth Resweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one resumable, local OFFLINE breadth-first P7 campaign that revisits only unresolved Level 1 and Level 2 prefixes without touching old campaign ledgers or official scorecards.

**Architecture:** Keep the existing paid attempt path inside `SweepScheduler._attempt()` and add a small operator-only controller that owns new BFS selection, a new independent ledger, and public-safe preflight output. Split five-minute action-stall monitoring from the old second-round mode so Level 1 and Level 2 breadth attempts can both stop after five minutes without a new `arc.action`. Evidence validation remains strict: success comes only from `load_best_prefix()` and terminal outcomes must bind to one exact run.

**Tech Stack:** Python 3.10+, `unittest`, Make, isolated `uv run --no-project --isolated`, existing ARC wheels, existing Orb guest runner, existing P7 private run evidence under `.asterion-private/prime-p7-live/`.

## Global Constraints

- Do not run paid model work while implementing or verifying this plan.
- Do not modify existing first-round or second-round campaign ledgers, run directories, or official scorecards.
- The source of progress is `load_best_prefix()` against sealed, replay-verified, guest-cleaned runs, never a previous campaign's outcome label.
- `make p7-breadth-preflight` is the primary zero-model preflight command; it aliases `make asterion-prime-p7-breadth-preflight` and prints safe counts and game IDs selected for Level 1 and Level 2.
- `make p7-breadth` is the primary run command; it aliases `make asterion-prime-p7-breadth`, builds an isolated wheel, loads the existing local ARC wheels, and requires no `GAME`, seed, token, or time arguments.
- Level 1 candidates are sorted by canonical game ID and attempted first; Level 2 candidates are recomputed after Level 1 finishes.
- Each `(game_id, target_level)` is attempted at most once in this new campaign; command reruns resume from the new ledger.
- Every attempted game has a 30-minute wall-time limit and a five-minute no-action stall limit, including Level 1.
- No aggregate token or wall-time cap is added.
- The campaign fails closed on uncertain guest cleanup, run identity, prefix replay, usage accounting, ledger consistency, or evidence validation.
- Do not create an official scorecard or official submission path in this work.

---

## File Map

- Create `tools/run_prime_p7_breadth.py`: operator-only BFS controller, independent breadth ledger, zero-model preflight, resume/recovery, result JSON.
- Modify `tools/run_prime_p7_sweep.py`: extract and parameterize action-stall monitoring and stalled-evidence validation so callers can validate Level 1 and Level 2 stalls without depending on `unbounded_second_round`.
- Modify `Makefile`: add short aliases `p7-breadth-preflight` and `p7-breadth`, plus full targets `asterion-prime-p7-breadth-preflight` and `asterion-prime-p7-breadth`, using the same isolated wheel and ARC wheel pattern as current P7 targets.
- Modify `tests/test_prime_p7_sweep.py`: focused regression tests for the shared stall switch and old ledger behavior.
- Create `tests/test_prime_p7_breadth.py`: zero-model controller, ledger, preflight, resume, token accounting, and Makefile tests.

## Interfaces

- `tools.run_prime_p7_breadth.BreadthCampaignConfig(arc_root: Path, runs_root: Path, operator_root: Path, repo_root: Path, guest_machine: str | None = "ubuntu", seed: int = 0, run_timeout: float = 1800.0, action_stall_seconds: int = 300)`
- `tools.run_prime_p7_breadth.BreadthCampaignResult`: JSON-safe dataclass with `attempted`, `level_one_queue`, `level_two_queue`, `newly_verified_level_one`, `newly_verified_level_two`, `blocked`, `input_tokens`, `output_tokens`, `stopped_reason`, and `runs`.
- `tools.run_prime_p7_breadth.BreadthCampaignController.preflight() -> dict[str, Any]`
- `tools.run_prime_p7_breadth.BreadthCampaignController.run() -> BreadthCampaignResult`
- `tools.run_prime_p7_breadth.main(argv: list[str] | None = None) -> int`
- `tools.run_prime_p7_sweep.SweepConfig.action_stall_seconds: int | None`
- `tools.run_prime_p7_sweep.SweepConfig.validate_action_stall: bool`
- `tools.run_prime_p7_sweep.SweepScheduler._execution_stalled_is_valid(run_id: str, game_id: str, *, target_level: int = 2, allow_later_progress: bool = False) -> bool`

### Task 1: Separate Five-Minute Stall Control From Old Second-Round Mode

**Files:**
- Modify: `tools/run_prime_p7_sweep.py`
- Modify: `tests/test_prime_p7_sweep.py`

**Interfaces:**
- Consumes: existing `SweepConfig`, `SweepScheduler._attempt()`, `_action_stall_reached()`, `_write_stall_receipt()`, and `_execution_stalled_is_valid()`.
- Produces: `SweepConfig.action_stall_seconds`, `SweepConfig.validate_action_stall`, and Level-1-capable stall validation without changing old first/second campaign schemas.

- [ ] **Step 1: Write failing tests for explicit stall control**

Add these tests to `tests/test_prime_p7_sweep.py`:

```python
def test_action_stall_monitoring_is_controlled_by_config_not_second_round(self) -> None:
    from types import SimpleNamespace
    from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        process = SimpleNamespace(returncode=1, communicate=lambda **_kwargs: ("", ""))
        scheduler = SweepScheduler(SweepConfig(
            root / "arc", root / "runs", command=("attempt",), guest_machine=None,
            action_stall_seconds=300, validate_action_stall=True,
        ))
        scheduler._attempt("bp35-0a0ad940", 1, 1800)

    self.assertEqual(scheduler.config.action_stall_seconds, 300)
    self.assertTrue(scheduler.config.validate_action_stall)


def test_level_one_execution_stall_validator_does_not_require_l1_reached(self) -> None:
    from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

    scheduler = SweepScheduler(SweepConfig(
        Path("arc"), Path("runs"), action_stall_seconds=300, validate_action_stall=True,
    ))
    self.assertFalse(scheduler.config.unbounded_second_round)
    self.assertTrue(scheduler.config.validate_action_stall)
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_sweep.TestPrimeP7Sweep.test_action_stall_monitoring_is_controlled_by_config_not_second_round tests.test_prime_p7_sweep.TestPrimeP7Sweep.test_level_one_execution_stall_validator_does_not_require_l1_reached
```

Expected: FAIL because `SweepConfig` has no `action_stall_seconds` or `validate_action_stall`.

- [ ] **Step 3: Add the minimal config fields and validation**

In `SweepConfig`, add:

```python
    action_stall_seconds: int | None = None
    validate_action_stall: bool = False
```

In `SweepScheduler.__init__`, add:

```python
        if config.action_stall_seconds is not None and (
            type(config.action_stall_seconds) is not int
            or config.action_stall_seconds != _ACTION_STALL_SECONDS
        ):
            raise ValueError("P7 action-stall limit is invalid")
        if config.validate_action_stall and config.action_stall_seconds != _ACTION_STALL_SECONDS:
            raise ValueError("P7 action-stall validation requires the five-minute limit")
```

- [ ] **Step 4: Use the new fields in `_attempt()`**

Replace second-round-only action monitoring checks with:

```python
                if self.config.action_stall_seconds == _ACTION_STALL_SECONDS and self._stop_reason == "completed":
                    action_count = _trace_action_count(run)
                    if action_count is not None and action_count > last_action_count:
                        last_action_count = action_count
                        last_action_at = time.monotonic()
```

and:

```python
                self.config.action_stall_seconds == _ACTION_STALL_SECONDS
                and self._stop_reason == "completed"
                and started_at
                and _action_stall_reached(started_at, last_action_at or started_at, time.monotonic())
```

Keep old `unbounded_second_round=True` behavior by passing `action_stall_seconds=_ACTION_STALL_SECONDS` from existing second-round and next-level construction points when needed.

- [ ] **Step 5: Allow Level 1 stalled evidence when explicitly requested**

In `_execution_stalled_is_valid()`, replace the first guard with:

```python
        if (
            not (self.config.unbounded_second_round or self.config.validate_action_stall)
            or not _RUN_ID.fullmatch(run_id)
            or type(target_level) is not int
            or target_level < 1
        ):
            return False
```

Then change the `level reached` requirement to:

```python
                or (target_level > 1 and not _trace_reached_level(entries, target_level - 1))
```

and keep the verified-prefix comparison only when `target_level > 1`.

- [ ] **Step 6: Run focused regressions**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_sweep tests.test_prime_p7_next_level
```

Expected: PASS. Existing second-round tests still prove the old ledger and L2 behavior are unchanged.

- [ ] **Step 7: Commit**

```bash
git add tools/run_prime_p7_sweep.py tests/test_prime_p7_sweep.py
git commit -m "refactor(p7): parameterize sweep action stalls"
```

### Task 2: Add the Independent Breadth Ledger and Selection Logic

**Files:**
- Create: `tools/run_prime_p7_breadth.py`
- Create: `tests/test_prime_p7_breadth.py`

**Interfaces:**
- Consumes: `load_best_prefix()`, `_read_catalog()`, `SweepConfig`, `SweepScheduler`, `read_run_usage()`, `_read_json()`, `_run_names()`.
- Produces: `BreadthCampaignConfig`, `BreadthCampaignController.preflight()`, atomic `.asterion-private/prime-p7-live/breadth-resweep-campaign.json`.

- [ ] **Step 1: Write failing selection and preflight tests**

Create `tests/test_prime_p7_breadth.py` with:

```python
from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest


class TestPrimeP7Breadth(unittest.TestCase):
    def test_preflight_selects_unverified_l1_then_exact_l1_prefixes_for_l2(self) -> None:
        from tools.run_prime_p7_breadth import BreadthCampaignConfig, BreadthCampaignController

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = BreadthCampaignController(BreadthCampaignConfig(
                arc_root=root / "arc", runs_root=root / "runs",
                operator_root=root, repo_root=root, guest_machine=None,
            ))
            controller._catalog = lambda: (
                {"game_id": "aa11-00000000", "alias": "AA11", "baseline_actions": (5, 7), "win_levels": 2},
                {"game_id": "bb22-00000000", "alias": "BB22", "baseline_actions": (6, 8), "win_levels": 2},
                {"game_id": "cc33-00000000", "alias": "CC33", "baseline_actions": (4, 9), "win_levels": 2},
            )

            def prefix(_game: str):
                return {
                    "aa11-00000000": None,
                    "bb22-00000000": SimpleNamespace(levels_completed=1),
                    "cc33-00000000": SimpleNamespace(levels_completed=2),
                }[_game]

            controller._best_prefix = prefix
            data = controller.preflight()

        self.assertEqual(data["schema"], "asterion.prime.p7-breadth-preflight/v1")
        self.assertEqual(data["level_one"], ["aa11-00000000"])
        self.assertEqual(data["level_two"], ["bb22-00000000"])
        self.assertEqual(data["already_verified_level_two"], ["cc33-00000000"])

    def test_preflight_cli_never_runs_attempts(self) -> None:
        from tools.run_prime_p7_breadth import BreadthCampaignController, main

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            BreadthCampaignController, "preflight",
            return_value={"schema": "asterion.prime.p7-breadth-preflight/v1", "level_one": [], "level_two": []},
        ), patch.object(BreadthCampaignController, "run") as run, contextlib.redirect_stdout(output):
            result = main(["--operator-root", directory, "--arc-root", directory, "--preflight-only"])

        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["schema"], "asterion.prime.p7-breadth-preflight/v1")
        run.assert_not_called()
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_breadth
```

Expected: FAIL with import error for `tools.run_prime_p7_breadth`.

- [ ] **Step 3: Implement config, preflight, and atomic ledger skeleton**

Create `tools/run_prime_p7_breadth.py` with:

```python
"""Run one resumable local P7 breadth resweep over unresolved Levels 1 and 2."""

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
from asterion.applications.prime.p7.solutions import load_best_prefix

from tools.run_prime_p7_sweep import _ACTION_STALL_SECONDS, SweepConfig, SweepScheduler


_SCHEMA = "asterion.prime.p7-breadth-campaign/v1"
_PREFLIGHT_SCHEMA = "asterion.prime.p7-breadth-preflight/v1"
_RESULT_SCHEMA = "asterion.prime.p7-breadth-result/v1"
_LEDGER_FILE = "breadth-resweep-campaign.json"


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

    def _best_prefix(self, game_id: str) -> Any:
        return load_best_prefix(self.config.arc_root, self.config.runs_root, game_id, self.config.seed)

    def _metadata(self) -> dict[str, dict[str, Any]]:
        return {str(row["game_id"]): row for row in self._catalog()}

    def _select_level_one(self) -> tuple[str, ...]:
        return tuple(sorted(
            game_id for game_id in self._metadata()
            if self._best_prefix(game_id) is None
        ))

    def _select_level_two(self) -> tuple[str, ...]:
        selected = []
        for game_id, metadata in self._metadata().items():
            prefix = self._best_prefix(game_id)
            if prefix is not None and prefix.levels_completed == 1 and metadata.get("win_levels", 0) >= 2:
                selected.append(game_id)
        return tuple(sorted(selected))

    def _already_verified_level_two(self) -> tuple[str, ...]:
        selected = []
        for game_id in self._metadata():
            prefix = self._best_prefix(game_id)
            if prefix is not None and prefix.levels_completed >= 2:
                selected.append(game_id)
        return tuple(sorted(selected))

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
```

- [ ] **Step 4: Implement `main()` preflight**

Add:

```python
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
        operator_root=operator_root,
        repo_root=operator_root,
        guest_machine=args.guest_machine,
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
```

- [ ] **Step 5: Add ledger helpers**

Implement `_ledger_path()`, `_write_ledger()`, and `_load_or_create_ledger()` in `BreadthCampaignController`. The ledger must be:

```python
{
    "schema": "asterion.prime.p7-breadth-campaign/v1",
    "campaign_id": "breadth-resweep-" + secrets.token_hex(16),
    "seed": 0,
    "run_timeout_seconds": 1800,
    "no_action_stall_seconds": 300,
    "terminal_attempts": []
}
```

Use `tempfile.mkstemp(prefix=".p7-breadth-", dir=runs_root)`, `json.dump(..., sort_keys=True, separators=(",", ":"))`, `fsync`, `chmod(0o600)`, and `os.replace()`. Reject symlinked roots, symlinked ledger paths, unknown schemas, duplicate `(game_id, target_level)`, duplicate `run_id`, missing terminal evidence, and non-terminal `running` entries unless Task 4 recovery can finalize them.

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_breadth
```

Expected: PASS for the initial preflight and ledger skeleton tests.

- [ ] **Step 7: Commit**

```bash
git add tools/run_prime_p7_breadth.py tests/test_prime_p7_breadth.py
git commit -m "feat(p7): add breadth resweep preflight and ledger"
```

### Task 3: Implement BFS Execution, Resume, and Evidence Accounting

**Files:**
- Modify: `tools/run_prime_p7_breadth.py`
- Modify: `tests/test_prime_p7_breadth.py`

**Interfaces:**
- Consumes: Task 2 ledger, `SweepScheduler._attempt()`, `SweepScheduler._attempt_result()`, `_execution_stalled_is_valid()`, `read_run_usage()`, and `load_best_prefix()`.
- Produces: BFS `run()` that attempts L1 queue first, recomputes L2 queue, skips terminal ledger entries, records per-run tokens, and stops for manual audit on ambiguous running evidence.

- [ ] **Step 1: Write failing BFS ordering and newly solved L1 tests**

Add:

```python
def test_run_attempts_l1_first_then_recomputes_l2(self) -> None:
    from tools.run_prime_p7_breadth import BreadthCampaignConfig, BreadthCampaignController

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        controller = BreadthCampaignController(BreadthCampaignConfig(
            arc_root=root / "arc", runs_root=root / "runs",
            operator_root=root, repo_root=root, guest_machine=None,
        ))
        controller._catalog = lambda: (
            {"game_id": "aa11-00000000", "baseline_actions": (5, 7), "win_levels": 2},
            {"game_id": "bb22-00000000", "baseline_actions": (6, 8), "win_levels": 2},
        )
        progress = {"aa11-00000000": 0, "bb22-00000000": 1}
        attempts: list[tuple[str, int, float | None]] = []

        def best(game_id: str):
            level = progress[game_id]
            return None if level == 0 else SimpleNamespace(levels_completed=level)

        def attempt(game_id: str, level: int, timeout: float | None) -> int:
            attempts.append((game_id, level, timeout))
            progress[game_id] = level
            controller._scheduler._new_runs.append(f"run-{game_id}-{level}")
            return 0

        controller._best_prefix = best
        controller._make_scheduler = lambda: SimpleNamespace(
            _new_runs=[], _input_tokens=0, _output_tokens=0, _stop_reason="completed",
            _attempt=attempt, _attempt_result=lambda game_id, level: progress[game_id] >= level,
            _execution_stalled_is_valid=lambda *_args, **_kwargs: True,
        )
        result = controller.run()

    self.assertEqual(attempts, [
        ("aa11-00000000", 1, 1800),
        ("aa11-00000000", 2, 1800),
        ("bb22-00000000", 2, 1800),
    ])
    self.assertEqual(result.newly_verified_level_one, ("aa11-00000000",))
    self.assertEqual(result.newly_verified_level_two, ("aa11-00000000", "bb22-00000000"))
```

- [ ] **Step 2: Write failing resume and token tests**

Add:

```python
def test_terminal_pair_is_not_retried_on_resume_and_tokens_are_reported(self) -> None:
    from tools.run_prime_p7_breadth import BreadthCampaignConfig, BreadthCampaignController

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runs = root / "runs"
        runs.mkdir()
        ledger = {
            "schema": "asterion.prime.p7-breadth-campaign/v1",
            "campaign_id": "breadth-resweep-0123456789abcdef0123456789abcdef",
            "seed": 0,
            "run_timeout_seconds": 1800,
            "no_action_stall_seconds": 300,
            "terminal_attempts": [{
                "game_id": "aa11-00000000", "target_level": 1,
                "run_id": "run-aa", "outcome": "verified",
                "action_count": 5, "input_tokens": 100, "output_tokens": 7,
                "stop_reason": "completed", "evidence_sha256": "sha256:" + "a" * 64,
            }],
        }
        (runs / "breadth-resweep-campaign.json").write_text(json.dumps(ledger), encoding="utf-8")
        controller = BreadthCampaignController(BreadthCampaignConfig(
            arc_root=root / "arc", runs_root=runs, operator_root=root, repo_root=root, guest_machine=None,
        ))
        controller._catalog = lambda: ({"game_id": "aa11-00000000", "baseline_actions": (5, 7), "win_levels": 2},)
        controller._best_prefix = lambda _game: SimpleNamespace(levels_completed=1)
        controller._terminal_entry_is_valid = lambda _entry: True
        controller._make_scheduler = lambda: SimpleNamespace(
            _new_runs=[], _input_tokens=0, _output_tokens=0, _stop_reason="completed",
            _attempt=lambda *_args: self.fail("resume retried a terminal pair"),
            _attempt_result=lambda *_args: False,
        )
        result = controller.run()

    self.assertEqual(result.attempted, 0)
    self.assertEqual(result.stopped_reason, "completed")
```

- [ ] **Step 3: Run the failing tests**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_breadth
```

Expected: FAIL because `run()` and terminal entry validation are incomplete.

- [ ] **Step 4: Implement scheduler construction**

Add:

```python
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
            action_stall_seconds=self.config.action_stall_seconds,
            validate_action_stall=True,
        ))
```

- [ ] **Step 5: Implement terminal pair lookup and validation**

Use `terminal_attempts` entries with exact keys:

```python
{
    "game_id": str,
    "target_level": int,
    "run_id": str,
    "outcome": "verified" | "unsolved" | "timed-out-unsealed" | "execution-failed" | "execution-stalled",
    "action_count": int,
    "input_tokens": int,
    "output_tokens": int,
    "stop_reason": str,
    "evidence_sha256": "sha256:<64 hex>",
}
```

Implement `_terminal_entry_is_valid(entry)` so:

- `verified` requires `load_best_prefix(...).levels_completed >= target_level`.
- `execution-stalled` requires `SweepScheduler(...)._execution_stalled_is_valid(run_id, game_id, target_level=target_level, allow_later_progress=True)`.
- `unsolved`, `timed-out-unsealed`, and `execution-failed` require one existing run directory, valid nonnegative token counts, matching game ID, and no symlinked evidence path.
- All outcomes require valid `(game_id, target_level)`, `seed == 0`, nonnegative `action_count`, nonnegative `input_tokens`, nonnegative `output_tokens`, and `evidence_sha256` matching the run trace final hash or summary hash used by the validator.

- [ ] **Step 6: Implement `run()` BFS**

Algorithm:

```python
    def run(self) -> BreadthCampaignResult:
        ledger = self._load_or_create_ledger()
        attempted = 0
        blocked: list[str] = []
        newly_l1: list[str] = []
        newly_l2: list[str] = []
        runs: list[str] = []
        input_tokens = output_tokens = 0

        level_one = tuple(game for game in self._select_level_one() if not self._has_terminal(ledger, game, 1))
        for game_id in level_one:
            outcome = self._attempt_pair(ledger, game_id, 1)
            attempted += outcome["attempted"]
            runs.extend(outcome["runs"])
            input_tokens += outcome["input_tokens"]
            output_tokens += outcome["output_tokens"]
            if outcome["stop_reason"] != "completed":
                return BreadthCampaignResult(attempted, level_one, (), tuple(newly_l1), tuple(newly_l2), tuple(sorted(set(blocked))), input_tokens, output_tokens, outcome["stop_reason"], tuple(runs))
            if outcome["verified"]:
                newly_l1.append(game_id)
            else:
                blocked.append(f"{game_id}:level-1")

        level_two = tuple(game for game in self._select_level_two() if not self._has_terminal(ledger, game, 2))
        for game_id in level_two:
            outcome = self._attempt_pair(ledger, game_id, 2)
            attempted += outcome["attempted"]
            runs.extend(outcome["runs"])
            input_tokens += outcome["input_tokens"]
            output_tokens += outcome["output_tokens"]
            if outcome["stop_reason"] != "completed":
                return BreadthCampaignResult(attempted, level_one, level_two, tuple(newly_l1), tuple(newly_l2), tuple(sorted(set(blocked))), input_tokens, output_tokens, outcome["stop_reason"], tuple(runs))
            if outcome["verified"]:
                newly_l2.append(game_id)
            else:
                blocked.append(f"{game_id}:level-2")

        reason = "completed" if attempted or level_one or level_two else "no-games"
        return BreadthCampaignResult(attempted, level_one, level_two, tuple(newly_l1), tuple(newly_l2), tuple(sorted(set(blocked))), input_tokens, output_tokens, reason, tuple(runs))
```

`_attempt_pair()` must create a `running` ledger entry before launching, call `scheduler._attempt(game_id, target_level, 1800)`, finalize exactly one run into a terminal entry, and write the ledger atomically before continuing. If an interrupted `running` entry cannot be finalized from complete matching evidence, return `stopped_reason="breadth-running-entry-requires-audit"` and do not retry.

- [ ] **Step 7: Run focused tests**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_breadth tests.test_prime_p7_sweep
```

Expected: PASS. No model process is launched because all attempts are mocked.

- [ ] **Step 8: Commit**

```bash
git add tools/run_prime_p7_breadth.py tests/test_prime_p7_breadth.py
git commit -m "feat(p7): run resumable breadth resweep campaign"
```

### Task 4: Add Short Make Targets and Installed-Wheel Zero-Model Verification

**Files:**
- Modify: `Makefile`
- Modify: `tests/test_prime_p7_breadth.py`

**Interfaces:**
- Consumes: `tools/run_prime_p7_breadth.py main()`.
- Produces: primary short commands `make p7-breadth-preflight` and `make p7-breadth`, plus full compatibility targets `make asterion-prime-p7-breadth-preflight` and `make asterion-prime-p7-breadth`.

- [ ] **Step 1: Write failing Makefile tests**

Add:

```python
def test_makefile_exposes_breadth_preflight_and_run_targets(self) -> None:
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text(encoding="utf-8")
    self.assertIn(".PHONY: p7-breadth-preflight", makefile)
    self.assertIn(".PHONY: p7-breadth", makefile)
    self.assertIn(".PHONY: asterion-prime-p7-breadth-preflight", makefile)
    self.assertIn(".PHONY: asterion-prime-p7-breadth", makefile)
    self.assertIn("tools/run_prime_p7_breadth.py", makefile)
    self.assertIn("--preflight-only", makefile)
    self.assertIn("arc_agi-0.9.9-py3-none-any.whl", makefile)
    self.assertIn("arcengine-0.9.3-py3-none-any.whl", makefile)
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_breadth.TestPrimeP7Breadth.test_makefile_exposes_breadth_preflight_and_run_targets
```

Expected: FAIL because the targets are absent.

- [ ] **Step 3: Add phony declarations and help text**

In `Makefile`, add:

```make
.PHONY: asterion-prime-p7-breadth-preflight
.PHONY: asterion-prime-p7-breadth
.PHONY: p7-breadth-preflight
.PHONY: p7-breadth
```

Add help lines beside the other P7 commands:

```make
	@echo "Asterion Prime local ARC-AGI-3 L1/L2 breadth resweep preflight: p7-breadth-preflight"
	@echo "Asterion Prime local ARC-AGI-3 L1/L2 breadth resweep: p7-breadth"
```

- [ ] **Step 4: Add installed-wheel target recipes**

Add recipes using the same pattern as `asterion-prime-p7-second-round`:

```make
p7-breadth-preflight: asterion-prime-p7-breadth-preflight

p7-breadth: asterion-prime-p7-breadth

asterion-prime-p7-breadth-preflight:
	@printf '[asterion-prime-p7-breadth-preflight] local L1/L2 breadth resweep readiness; zero model calls\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p7-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; \
		$(UV_BIN) run --no-project --isolated --with "$$1" --with "$(ASTERION_PRIME_ARC_ROOT)/wheels/arc_agi-0.9.9-py3-none-any.whl" --with "$(ASTERION_PRIME_ARC_ROOT)/wheels/arcengine-0.9.3-py3-none-any.whl" python -I tools/run_prime_p7_breadth.py --operator-root "$(CURDIR)" --arc-root "$(ASTERION_PRIME_ARC_ROOT)" --guest-machine "$(PRIME_ORB_MACHINE)" --preflight-only'

asterion-prime-p7-breadth:
	@printf '[asterion-prime-p7-breadth] local L1/L2 breadth resweep; 30 minutes per game, 5 minutes without action stops the attempt\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p7-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; \
		$(UV_BIN) run --no-project --isolated --with "$$1" --with "$(ASTERION_PRIME_ARC_ROOT)/wheels/arc_agi-0.9.9-py3-none-any.whl" --with "$(ASTERION_PRIME_ARC_ROOT)/wheels/arcengine-0.9.3-py3-none-any.whl" python -I tools/run_prime_p7_breadth.py --operator-root "$(CURDIR)" --arc-root "$(ASTERION_PRIME_ARC_ROOT)" --guest-machine "$(PRIME_ORB_MACHINE)"'
```

- [ ] **Step 5: Run zero-model installed-wheel preflight**

Run:

```bash
make p7-breadth-preflight
```

Expected: PASS with JSON schema `asterion.prime.p7-breadth-preflight/v1`. It must print only selected game IDs, counts, seed, and fixed controls; it must not start Orb guest work and must not create or modify a campaign ledger.

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_breadth tests.test_prime_p7_sweep
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add Makefile tests/test_prime_p7_breadth.py
git commit -m "feat(p7): expose breadth resweep make targets"
```

### Task 5: Verification, Review, and Execution Readiness Gate

**Files:**
- Modify: `tests/test_prime_p7_breadth.py`
- No production changes unless tests expose a concrete bug.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a zero-model acceptance record and a focused code-review gate before paid execution.

- [ ] **Step 1: Add regression tests for old-ledger isolation**

Add:

```python
def test_breadth_uses_new_ledger_and_does_not_touch_old_campaign_files(self) -> None:
    from tools.run_prime_p7_breadth import BreadthCampaignConfig, BreadthCampaignController

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runs = root / "runs"
        runs.mkdir()
        old_first = runs / "first-round-campaign.json"
        old_second = runs / "second-round-campaign.json"
        old_first.write_text('{"old":"first"}\n', encoding="utf-8")
        old_second.write_text('{"old":"second"}\n', encoding="utf-8")
        controller = BreadthCampaignController(BreadthCampaignConfig(
            arc_root=root / "arc", runs_root=runs, operator_root=root, repo_root=root, guest_machine=None,
        ))
        controller._catalog = lambda: ()
        result = controller.run()

    self.assertEqual(result.stopped_reason, "no-games")
    self.assertEqual(old_first.read_text(encoding="utf-8"), '{"old":"first"}\n')
    self.assertEqual(old_second.read_text(encoding="utf-8"), '{"old":"second"}\n')
```

- [ ] **Step 2: Add regression tests for malformed evidence and running-entry recovery**

Add tests that write a `breadth-resweep-campaign.json` with:

```python
{"status": "running", "game_id": "aa11-00000000", "target_level": 1, "run_id": "missing"}
```

Expected result: `controller.run().stopped_reason == "breadth-running-entry-requires-audit"` and `_attempt()` is not called.

Add a second ledger with duplicate `(game_id, target_level)` terminal entries. Expected: `ValueError` from `_load_or_create_ledger()`.

- [ ] **Step 3: Run full zero-model P7 controller tests**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_breadth tests.test_prime_p7_sweep tests.test_prime_p7_next_level tests.test_prime_p7_solutions
```

Expected: PASS.

- [ ] **Step 4: Run lint and docs checks**

Run:

```bash
uv run ruff check tools/run_prime_p7_breadth.py tools/run_prime_p7_sweep.py tests/test_prime_p7_breadth.py tests/test_prime_p7_sweep.py
make docs-check
```

Expected: PASS.

- [ ] **Step 5: Run installed-wheel zero-model acceptance**

Run:

```bash
make p7-breadth-preflight
```

Expected: PASS and no model call. Confirm:

- JSON schema is `asterion.prime.p7-breadth-preflight/v1`.
- `level_one_count` and `level_two_count` match the printed arrays.
- No `.asterion-private/prime-p7-live/breadth-resweep-campaign.json` is created by preflight.
- Existing `first-round-campaign.json`, `second-round-campaign.json`, official scorecard files, and run directories are unchanged.

- [ ] **Step 6: Focused code review**

Review these points before any paid breadth run:

- `load_best_prefix()` is the only source for verified progress.
- Level 2 queue is recomputed after Level 1 attempts finish.
- Every `(game_id, target_level)` terminal entry is validated on resume.
- `running` entries never cause automatic paid retries.
- Token counts are read from run usage and carried into the breadth ledger and result JSON.
- Five-minute no-action stall applies to both Level 1 and Level 2 when invoked by the breadth controller.
- Make preflight is zero-model and does not write a ledger.
- Old first/second-round ledgers are read neither as progress authority nor modified.

- [ ] **Step 7: Commit final verification tests**

```bash
git add tests/test_prime_p7_breadth.py
git commit -m "test(p7): verify breadth resweep safety gates"
```

## Acceptance Criteria

- `uv run python -m unittest -v tests.test_prime_p7_breadth tests.test_prime_p7_sweep tests.test_prime_p7_next_level tests.test_prime_p7_solutions` passes.
- `uv run ruff check tools/run_prime_p7_breadth.py tools/run_prime_p7_sweep.py tests/test_prime_p7_breadth.py tests/test_prime_p7_sweep.py` passes.
- `make docs-check` passes.
- `make p7-breadth-preflight` passes from an installed wheel and performs zero model actions.
- `make p7-breadth-preflight` does not create or modify `.asterion-private/prime-p7-live/breadth-resweep-campaign.json`.
- Existing `first-round-campaign.json`, `second-round-campaign.json`, run directories, and official scorecard files remain byte-for-byte unchanged during implementation verification.
- The paid `make p7-breadth` command is available but is not run until after review approval.

## Self-Review

- Spec coverage: The plan covers short operator commands, full compatibility targets, new independent ledger, L1/L2 BFS ordering, recomputed L2 after new L1 successes, 5-minute L1/L2 stalls, resume behavior, token accounting, Make/preflight, zero-model installed-wheel acceptance, and focused review.
- Placeholder scan: No `TBD`, `TODO`, `implement later`, or open-ended "add appropriate handling" placeholders remain.
- Interface consistency: `BreadthCampaignConfig`, `BreadthCampaignController.preflight()`, `BreadthCampaignController.run()`, `SweepConfig.action_stall_seconds`, and `SweepConfig.validate_action_stall` are introduced before later tasks use them.
- Risk: The hardest implementation risk is evidence validation for `timed-out-unsealed` and `execution-stalled` Level 1 runs. Keep that code minimal and fail closed; a false negative costs a manual audit, while a false positive can corrupt the breadth ledger.
