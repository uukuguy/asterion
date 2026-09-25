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
import tempfile
import time
from typing import Any

from asterion.applications.prime.p7.broker import ArcTransition
from asterion.applications.prime.p7.private_trace import P7_TRACE_IDENTITIES
from asterion.applications.prime.p7.score import replay_sha256
from asterion.applications.prime.p7.game import _read_catalog
from asterion.applications.prime.p7.solutions import load_best_prefix


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FIRST_ROUND_CATALOG_GAME_IDS = (
    "ar25-0c556536", "bp35-0a0ad940", "cd82-fb555c5d", "cn04-2fe56bfb",
    "dc22-fdcac232", "ft09-0d8bbf25", "g50t-5849a774", "ka59-38d34dbb",
    "lf52-271a04aa", "lp85-305b61c3", "ls20-9607627b", "m0r0-492f87ba",
    "r11l-495a7899", "re86-8af5384d", "s5i5-18d95033", "sb26-7fbdac44",
    "sc25-635fd71a", "sk48-d8078629", "sp80-589a99af", "su15-1944f8ab",
    "tn36-ef4dde99", "tr87-cd924810", "tu93-0768757b", "vc33-5430563c",
    "wa30-ee6fef47",
)
_FIRST_ROUND_EXCLUDED_GAME_IDS = frozenset({"ls20-9607627b"})
_FIRST_ROUND_REPLAYED_GAME_ID = "ar25-0c556536"
_FIRST_ROUND_CATALOG_SIZE = len(_FIRST_ROUND_CATALOG_GAME_IDS)
_FIRST_ROUND_CAMPAIGN_SCHEMA = "asterion.prime.p7-first-round-campaign/v1"
_FIRST_ROUND_CAMPAIGN_FILE = "first-round-campaign.json"
_FIRST_ROUND_CAMPAIGN_ID = re.compile(r"^first-round-[0-9a-f]{32}$")
_SECOND_ROUND_GAME_IDS = (
    "ar25-0c556536", "cn04-2fe56bfb", "dc22-fdcac232", "ft09-0d8bbf25",
    "lf52-271a04aa", "lp85-305b61c3", "ls20-9607627b", "m0r0-492f87ba",
    "r11l-495a7899", "re86-8af5384d", "sb26-7fbdac44", "sc25-635fd71a",
    "sp80-589a99af", "su15-1944f8ab", "tr87-cd924810", "vc33-5430563c",
    "wa30-ee6fef47",
)
_SECOND_ROUND_CAMPAIGN_SCHEMA = "asterion.prime.p7-second-round-campaign/v1"
_SECOND_ROUND_CAMPAIGN_FILE = "second-round-campaign.json"
_SECOND_ROUND_CAMPAIGN_ID = re.compile(r"^second-round-[0-9a-f]{32}$")
_ACTION_STALL_SECONDS = 5 * 60
_STALL_RECEIPT_FILE = "stall-receipt.json"


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
    # visits only games without a verified L1 prefix and keeps a 30-minute
    # per-game limit. It has no aggregate token or wallclock budget.
    unbounded_first_round: bool = False
    unbounded_second_round: bool = False
    # Optional explicit five-minute action stall control for operator passes.
    # The legacy second round remains enabled by its existing flag for compatibility.
    action_stall_seconds: int | None = None
    validate_action_stall: bool = False


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
    previously_attempted_unsolved_level_one: tuple[str, ...] = ()
    interrupted_without_evidence_level_one: tuple[str, ...] = ()
    timed_out_unsealed_level_one: tuple[str, ...] = ()
    preexisting_level_two: tuple[str, ...] = ()
    newly_verified_level_two: tuple[str, ...] = ()
    attempted_unsolved_level_two: tuple[str, ...] = ()
    previously_attempted_unsolved_level_two: tuple[str, ...] = ()
    timed_out_unsealed_level_two: tuple[str, ...] = ()
    execution_failed_level_two: tuple[str, ...] = ()
    previously_execution_failed_level_two: tuple[str, ...] = ()
    execution_stalled_level_two: tuple[str, ...] = ()
    previously_execution_stalled_level_two: tuple[str, ...] = ()


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


def _action_stall_reached(started_at: float, last_action_at: float, now: float) -> bool:
    """Return true after five minutes without an action, including startup."""

    return now - max(started_at, last_action_at) >= _ACTION_STALL_SECONDS


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


def _trace_action_count(run: Path) -> int | None:
    """Read the count of valid action rows from an in-progress trace."""

    try:
        entries = _read_hash_chained_trace(run / "trace" / "prime-trace.jsonl", in_progress=True)
    except _TraceIntegrityError as error:
        entries = error.rows
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        return None
    return sum(entry["kind"] == "arc.action" for entry in entries)


def _write_stall_receipt(
    run: Path, *, game_id: str, run_id: str, action_count: int,
    expected_action_count: int, stall_seconds: float, cleanup_complete: bool,
) -> bool:
    """Persist the supervisor's evidence when SIGTERM leaves no application summary."""

    if action_count < 0 or action_count != expected_action_count or stall_seconds < _ACTION_STALL_SECONDS or not cleanup_complete:
        return False
    try:
        entries = _read_hash_chained_trace(run / "trace" / "prime-trace.jsonl", in_progress=True)
        if not entries or entries[-1]["kind"] == "trace.sealed":
            return False
        payload = {
            "schema": "asterion.prime.p7-stall-receipt/v1",
            "game_id": game_id, "run_id": run_id, "seed": 0,
            "action_count": action_count,
            "stall_seconds": int(stall_seconds),
            "cleanup_complete": True,
            "trace_final_sha256": entries[-1]["sha256"],
        }
        path = run / _STALL_RECEIPT_FILE
        if path.is_symlink():
            return False
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
        return True
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        return False


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
        if config.unbounded_first_round and config.unbounded_second_round:
            raise ValueError("P7 research round selection is ambiguous")
        if config.unbounded_second_round and config.run_timeout != 30 * 60:
            raise ValueError("P7 second round requires a 30-minute attempt limit")
        if config.action_stall_seconds is not None and (
            type(config.action_stall_seconds) is not int
            or config.action_stall_seconds != _ACTION_STALL_SECONDS
        ):
            raise ValueError("P7 action-stall limit is invalid")
        if config.validate_action_stall and config.action_stall_seconds != _ACTION_STALL_SECONDS:
            raise ValueError("P7 action-stall validation requires the five-minute limit")
        bounded_budget = (
            type(config.global_token_cap) is int and config.global_token_cap > 0
            and type(config.wallclock_cap) in (int, float) and math.isfinite(config.wallclock_cap) and config.wallclock_cap > 0
            and type(config.run_timeout) in (int, float) and math.isfinite(config.run_timeout) and config.run_timeout > 0
        )
        if self._is_research_round(config):
            if (
                config.global_token_cap not in (None, 3_500_000)
                or config.wallclock_cap not in (None, 4 * 60 * 60)
                or config.run_timeout not in (None, 30 * 60)
                or config.max_attempts is not None
            ):
                label = "second round" if config.unbounded_second_round else "first round"
                raise ValueError(f"P7 unbounded {label} cannot have a budget cap")
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

    @staticmethod
    def _is_research_round(config: SweepConfig) -> bool:
        return config.unbounded_first_round or config.unbounded_second_round

    def _catalog(self) -> tuple[dict[str, object], ...]:
        try:
            return _read_catalog(self.config.arc_root)
        except (OSError, ValueError):
            return ()

    def _metadata(self) -> dict[str, dict[str, object]]:
        return {str(row["game_id"]): row for row in self._catalog()}

    def _selected_games(self) -> tuple[str, ...]:
        metadata = self._metadata()
        selected = self.config.games or (
            _SECOND_ROUND_GAME_IDS if self.config.unbounded_second_round else tuple(sorted(metadata))
        )
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
        expected = tuple(sorted(set(_FIRST_ROUND_CATALOG_GAME_IDS) - _FIRST_ROUND_EXCLUDED_GAME_IDS))
        if (
            self.config.games
            or len(metadata) != _FIRST_ROUND_CATALOG_SIZE
            or len(catalog_ids) != _FIRST_ROUND_CATALOG_SIZE
            or catalog_ids != frozenset(_FIRST_ROUND_CATALOG_GAME_IDS)
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

    def _first_round_catalog_ids(self) -> tuple[str, ...]:
        return _FIRST_ROUND_CATALOG_GAME_IDS

    def _second_round_campaign_is_ready(self, games: tuple[str, ...]) -> bool:
        metadata = self._metadata()
        if (
            self.config.games
            or len(metadata) != _FIRST_ROUND_CATALOG_SIZE
            or frozenset(metadata) != frozenset(_FIRST_ROUND_CATALOG_GAME_IDS)
            or games != _SECOND_ROUND_GAME_IDS
        ):
            return False
        for game_id in games:
            prefix = load_best_prefix(self.config.arc_root, self.config.runs_root, game_id, self.config.seed)
            if prefix is None or prefix.levels_completed < 1:
                return False
        return True

    def _campaign_ids(self) -> tuple[str, ...]:
        return _SECOND_ROUND_GAME_IDS if self.config.unbounded_second_round else self._first_round_catalog_ids()

    def _campaign_path(self) -> Path:
        name = _SECOND_ROUND_CAMPAIGN_FILE if self.config.unbounded_second_round else _FIRST_ROUND_CAMPAIGN_FILE
        return self.config.runs_root / name

    def _write_campaign(self, campaign: dict[str, Any]) -> None:
        root = self.config.runs_root
        if root.is_symlink():
            raise ValueError
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not root.is_dir():
            raise ValueError
        path = self._campaign_path()
        if path.is_symlink():
            raise ValueError
        descriptor, temporary_name = tempfile.mkstemp(prefix=".p7-research-round-", dir=root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(campaign, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _load_or_create_campaign(self) -> dict[str, Any]:
        second = self.config.unbounded_second_round
        schema = _SECOND_ROUND_CAMPAIGN_SCHEMA if second else _FIRST_ROUND_CAMPAIGN_SCHEMA
        identity = _SECOND_ROUND_CAMPAIGN_ID if second else _FIRST_ROUND_CAMPAIGN_ID
        label = "second-round-" if second else "first-round-"
        path = self._campaign_path()
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file():
                raise ValueError
            campaign = _read_json(path)
            if not campaign:
                raise ValueError
        else:
            campaign = {
                "schema": schema,
                "campaign_id": label + secrets.token_hex(16),
                "catalog_game_ids": list(self._campaign_ids()),
                "terminal_attempts": [],
            }
            self._write_campaign(campaign)
            return campaign
        attempts = campaign.get("terminal_attempts")
        catalog = campaign.get("catalog_game_ids")
        campaign_id = campaign.get("campaign_id")
        if (
            set(campaign) != {"schema", "campaign_id", "catalog_game_ids", "terminal_attempts"}
            or campaign.get("schema") != schema
            or type(campaign_id) is not str or identity.fullmatch(campaign_id) is None
            or catalog != list(self._campaign_ids())
            or type(attempts) is not list
        ):
            raise ValueError
        seen_games: set[str] = set()
        seen_runs: set[str] = set()
        for attempt in attempts:
            if (
                type(attempt) is not dict
                or set(attempt) != {"game_id", "run_id", "outcome"}
                or attempt.get("game_id") not in self._campaign_ids()
                or attempt["game_id"] in seen_games
                or type(attempt.get("run_id")) is not str or _RUN_ID.fullmatch(attempt["run_id"]) is None
                or attempt["run_id"] in seen_runs
                or attempt.get("outcome") not in {"verified", "unsolved", "timed-out-unsealed", "execution-failed", "execution-stalled"}
                or not self._campaign_entry_is_valid(attempt)
            ):
                raise ValueError
            seen_games.add(attempt["game_id"])
            seen_runs.add(attempt["run_id"])
        return campaign

    def _campaign_entry_is_valid(self, attempt: dict[str, Any]) -> bool:
        game_id = attempt["game_id"]
        run_id = attempt["run_id"]
        outcome = attempt["outcome"]
        if outcome in {"execution-failed", "execution-stalled"}:
            validator = self._execution_stalled_is_valid if outcome == "execution-stalled" else self._execution_failure_is_valid
            return validator(run_id, game_id, allow_later_progress=True)
        run = self.config.runs_root / run_id
        if run.is_symlink() or not run.is_dir():
            return False
        trace = run / "trace" / "prime-trace.jsonl"
        try:
            entries = _read_hash_chained_trace(trace, in_progress=outcome == "timed-out-unsealed")
        except (OSError, UnicodeError, ValueError, KeyError, TypeError):
            return False
        sealed = bool(entries) and entries[-1]["kind"] == "trace.sealed"
        if outcome == "timed-out-unsealed":
            usage = read_run_usage(run, in_progress=True)
            return (
                not sealed
                and not usage[2]
                and not usage[3]
                and _recorded_game_id(run, {game_id}) == game_id
                and (not self.config.unbounded_second_round or _trace_reached_level(entries, 1))
            )
        summary = _read_json(run / "summary.json")
        returncode = 0 if outcome == "verified" else 1
        level = 2 if self.config.unbounded_second_round else 1
        if not sealed or not _valid_attempt_summary(summary, run_id, game_id, level, returncode):
            return False
        if outcome == "verified":
            prefix = load_best_prefix(self.config.arc_root, self.config.runs_root, game_id, self.config.seed)
            return prefix is not None and prefix.levels_completed >= level
        return True

    def _execution_failure_is_valid(self, run_id: str, game_id: str, *, allow_later_progress: bool = False) -> bool:
        """Admit only a cleaned L2 execution failure with a sealed L1 prefix."""

        if not self.config.unbounded_second_round or not _RUN_ID.fullmatch(run_id):
            return False
        run = self.config.runs_root / run_id
        try:
            if run.is_symlink() or not run.is_dir() or (run / "summary.json").is_symlink():
                return False
            summary = _read_json(run / "summary.json")
            entries = _read_hash_chained_trace(run / "trace" / "prime-trace.jsonl")
            if not summary or (
                summary.get("schema") != "asterion.prime.p7-live-private-summary/v1"
                or summary.get("run_id") != run_id
                or any(summary.get(key) is not True for key in ("cleanup_complete", "replay_verified", "sealed_trace"))
                or summary.get("broker") is not None
                or type(summary.get("failure")) is not dict
                or summary["failure"].get("type") not in {"ApplicationRunError"}
                or len(entries) < 3
                or [row["kind"] for row in entries[-2:]] != ["arc.run.partial", "trace.sealed"]
                or any(row["identities"] != P7_TRACE_IDENTITIES for row in entries)
                or any(row["kind"] not in {"arc.action", "arc.usage.reported"} for row in entries[:-2])
                or entries[-1]["payload"] != {"entry_count": len(entries) - 1, "final_sha256": entries[-2]["sha256"]}
            ):
                return False
            prefix = summary.get("completed_prefix")
            metadata = self._metadata()[game_id]
            diagnostics = summary["diagnostics"]
            sweep, status = diagnostics["sweep"], diagnostics["broker_status"]
            if (
                type(prefix) is not dict or prefix != entries[-2]["payload"]
                or prefix.get("game_id") != game_id
                or type(prefix.get("seed")) is not int or prefix["seed"] != 0
                or type(prefix.get("levels_completed")) is not int or prefix["levels_completed"] != 1
                or prefix.get("win_levels") != metadata["win_levels"]
                or prefix.get("terminal_reason") != "level-completed"
                or type(prefix.get("primitive_actions")) is not int or prefix["primitive_actions"] <= 0
                or type(sweep) is not dict or type(status) is not dict
                or sweep.get("scope") != "offline-research"
                or any(type(sweep.get(key)) is not int for key in ("target_level", "prefix_actions", "level_action_cap", "run_action_cap"))
                or sweep["target_level"] != 2 or sweep["prefix_actions"] != prefix["primitive_actions"]
                or sweep["level_action_cap"] != metadata["baseline_actions"][1]
                or sweep["run_action_cap"] != sweep["prefix_actions"] + sweep["level_action_cap"]
                or not 0 < sweep["run_action_cap"] <= 5000
                or any(type(status.get(key)) is not int for key in ("primitive_actions", "levels_completed", "actions_remaining", "target_level"))
                or status["target_level"] != 2 or status["levels_completed"] != 1
                or status.get("terminal_reason") != "active"
                or not prefix["primitive_actions"] <= status["primitive_actions"] < sweep["run_action_cap"]
                or status["actions_remaining"] != sweep["run_action_cap"] - status["primitive_actions"]
            ):
                return False
            actions = tuple(row["payload"] for row in entries if row["kind"] == "arc.action")
            if len(actions) != status["primitive_actions"]:
                return False
            transitions: list[ArcTransition] = []
            previous_level = 0
            for sequence, action in enumerate(actions, 1):
                level = action.get("levels_completed")
                if (
                    type(action.get("sequence")) is not int or action["sequence"] != sequence
                    or type(level) is not int or not previous_level <= level <= 1
                    or (sequence < prefix["primitive_actions"] and level != 0)
                    or (sequence >= prefix["primitive_actions"] and level != 1)
                    or (transitions and action.get("before_sha256") != transitions[-1].after_sha256)
                    or any(type(action.get(key)) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", action[key]) is None for key in ("before_sha256", "after_sha256"))
                ):
                    return False
                transitions.append(ArcTransition(sequence, action["action"], action["before_sha256"], action["after_sha256"], level, tuple(sorted(action.get("data", {}).items()))))
                previous_level = level
            if prefix.get("replay_sha256") != replay_sha256(transitions[:prefix["primitive_actions"]], terminal_reason="level-completed"):
                return False
            usage = read_run_usage(run)
            if usage[2] or usage[3]:
                return False
            verified = load_best_prefix(self.config.arc_root, self.config.runs_root, game_id, 0)
            return verified is not None and (
                verified.levels_completed >= 1 if allow_later_progress else verified.levels_completed == 1
            )
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
            return False

    def _historical_prefix_matches(self, game_id: str, actions: tuple[dict[str, Any], ...]) -> bool:
        """Match a stalled run's L1 prefix to a sealed local L1 run without replay."""

        metadata = self._metadata().get(game_id)
        if not metadata or type(metadata.get("baseline_actions")) is not tuple:
            return False
        try:
            for historical in sorted(self.config.runs_root.iterdir(), key=lambda item: item.name):
                if historical.is_symlink() or not historical.is_dir():
                    continue
                summary = _read_json(historical / "summary.json")
                broker = summary.get("broker") if summary else None
                receipt = summary.get("receipt") if summary else None
                if (
                    not summary
                    or summary.get("schema") != "asterion.prime.p7-live-private-summary/v1"
                    or summary.get("run_id") != historical.name
                    or summary.get("replay_verified") is not True
                    or summary.get("sealed_trace") is not True
                    or summary.get("cleanup_complete") is not True
                    or type(broker) is not dict
                    or broker.get("game_id") != game_id
                    or broker.get("seed") != self.config.seed
                    or broker.get("levels_completed") != 1
                    or broker.get("terminal_reason") != "level-completed"
                    or type(broker.get("primitive_actions")) is not int
                    or broker["primitive_actions"] <= 0
                    or broker["primitive_actions"] > metadata["baseline_actions"][0]
                    or type(receipt) is not dict
                    or receipt.get("completed_level_count") != 1
                    or receipt.get("primitive_action_count") != broker["primitive_actions"]
                    or receipt.get("scope") != "p7-solving"
                ):
                    continue
                trace_path = historical / "trace" / "prime-trace.jsonl"
                seal_path = historical / "trace" / "prime-trace.seal.json"
                if trace_path.is_symlink() or seal_path.is_symlink() or not seal_path.is_file():
                    continue
                entries = _read_hash_chained_trace(trace_path)
                seal = _read_json(seal_path)
                if (
                    not entries
                    or entries[-1]["kind"] != "trace.sealed"
                    or not seal
                    or set(seal) != {"entry_count", "final_sha256", "sealed_at"}
                    or seal["entry_count"] != len(entries)
                    or seal["final_sha256"] != entries[-1]["sha256"]
                    or any(row["identities"] != P7_TRACE_IDENTITIES for row in entries)
                ):
                    continue
                historical_actions = tuple(row["payload"] for row in entries if row["kind"] == "arc.action")
                count = broker["primitive_actions"]
                if len(historical_actions) != count or len(actions) < count:
                    continue
                historical_first_level = next(
                    (index for index, action in enumerate(historical_actions) if action.get("levels_completed") == 1),
                    None,
                )
                if historical_first_level is None or historical_first_level + 1 != count:
                    continue
                if tuple(actions[:count]) != historical_actions:
                    continue
                transitions = tuple(
                    ArcTransition(
                        row["payload"]["sequence"], row["payload"]["action"],
                        row["payload"]["before_sha256"], row["payload"]["after_sha256"],
                        row["payload"]["levels_completed"],
                        tuple(sorted(row["payload"].get("data", {}).items())),
                    )
                    for row in entries if row["kind"] == "arc.action"
                )
                if broker.get("replay_sha256") != replay_sha256(transitions, terminal_reason="level-completed"):
                    continue
                return True
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, IndexError):
            return False
        return False

    def _execution_stalled_is_valid(
        self, run_id: str, game_id: str, *, target_level: int = 2,
        allow_later_progress: bool = False,
    ) -> bool:
        """Admit a supervisor stall with a hash-valid unsealed trace and receipt."""

        if (
            not (self.config.unbounded_second_round or self.config.validate_action_stall)
            or not _RUN_ID.fullmatch(run_id)
            or type(target_level) is not int or target_level < 1
        ):
            return False
        run = self.config.runs_root / run_id
        try:
            receipt_path = run / _STALL_RECEIPT_FILE
            trace_path = run / "trace" / "prime-trace.jsonl"
            if run.is_symlink() or receipt_path.is_symlink() or trace_path.is_symlink():
                return False
            receipt = _read_json(run / _STALL_RECEIPT_FILE)
            entries = _read_hash_chained_trace(run / "trace" / "prime-trace.jsonl", in_progress=True)
            if (
                not receipt or set(receipt) != {"schema", "game_id", "run_id", "seed", "action_count", "stall_seconds", "cleanup_complete", "trace_final_sha256"}
                or receipt.get("schema") != "asterion.prime.p7-stall-receipt/v1"
                or receipt.get("game_id") != game_id or receipt.get("run_id") != run_id
                or receipt.get("seed") != 0 or receipt.get("cleanup_complete") is not True
                or type(receipt.get("action_count")) is not int or receipt["action_count"] <= 0
                or type(receipt.get("stall_seconds")) is not int or receipt["stall_seconds"] < _ACTION_STALL_SECONDS
                or receipt.get("trace_final_sha256") != entries[-1]["sha256"]
                or entries[-1]["kind"] == "trace.sealed"
                or any(row["identities"] != P7_TRACE_IDENTITIES for row in entries)
                or any(row["kind"] not in {"arc.action", "arc.usage.reported", "arc.run.partial"} for row in entries)
                or sum(row["kind"] == "arc.action" for row in entries) != receipt["action_count"]
                or _recorded_game_id(run, {game_id}) != game_id
                or (target_level > 1 and not _trace_reached_level(entries, target_level - 1))
            ):
                return False
            usage = read_run_usage(run, in_progress=True)
            if usage[2] or usage[3]:
                return False
            metadata = self._metadata()[game_id]
            baselines = metadata.get("baseline_actions")
            if (
                type(baselines) is not tuple or target_level > len(baselines)
                or any(type(item) is not int or item <= 0 for item in baselines[:target_level])
                or receipt["action_count"] > sum(baselines[:target_level])
            ):
                return False
            actions = tuple(row["payload"] for row in entries if row["kind"] == "arc.action")
            if not actions:
                return False
            prefix = load_best_prefix(self.config.arc_root, self.config.runs_root, game_id, self.config.seed)
            if target_level == 1:
                # A Level 1 stall is valid only for a game without an already
                # verified Level 1 prefix; actions must remain at level zero.
                if prefix is not None and prefix.levels_completed >= 1:
                    return False
                if len(actions) > baselines[0]:
                    return False
            if target_level > 2 and (
                prefix is None or prefix.levels_completed != target_level - 1
                or not prefix.transitions or len(actions) < len(prefix.transitions)
            ):
                return False
            previous_level = 0
            for sequence, action in enumerate(actions, 1):
                level = action.get("levels_completed")
                if (
                    action.get("sequence") != sequence
                    or type(level) is not int
                    or not previous_level <= level <= previous_level + 1
                    or level > target_level - 1
                    or any(
                        type(action.get(key)) is not str
                        or re.fullmatch(r"sha256:[0-9a-f]{64}", action[key]) is None
                        for key in ("before_sha256", "after_sha256")
                    )
                ):
                    return False
                if sequence > 1 and action.get("before_sha256") != actions[sequence - 2].get("after_sha256"):
                    return False
                previous_level = level
            if target_level == 1:
                return True
            if target_level > 2 and prefix is not None:
                prefix_actions = len(prefix.transitions)
                if (
                    prefix.levels_completed != target_level - 1
                    or not prefix.transitions
                    or prefix.transitions[-1].levels_completed != prefix.levels_completed
                    or len(actions) < prefix_actions
                ):
                    return False
                observed_prefix = tuple(
                    ArcTransition(
                        action["sequence"], action["action"], action["before_sha256"],
                        action["after_sha256"], action["levels_completed"],
                        tuple(sorted(action.get("data", {}).items())),
                    ) for action in actions[:prefix_actions]
                )
                if observed_prefix != prefix.transitions:
                    return False
                if len(actions) - prefix_actions > baselines[target_level - 1]:
                    return False
                return allow_later_progress or prefix.levels_completed == target_level - 1
            if target_level != 2:
                return False
            first_level_two = next(
                (index for index, action in enumerate(actions) if action["levels_completed"] >= 1),
                None,
            )
            if first_level_two is None or any(action["levels_completed"] != 0 for action in actions[:first_level_two]):
                return False
            if any(action["levels_completed"] != 1 for action in actions[first_level_two:]):
                return False
            actual_prefix_actions = first_level_two + 1
            if len(actions) - actual_prefix_actions > baselines[1]:
                return False
            if not self._historical_prefix_matches(game_id, actions):
                return False
            return True
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
            return False

    def adopt_execution_failure(self, run_id: str) -> str:
        """Record one explicitly selected existing failure without launching work."""

        if not self.config.unbounded_second_round or not _RUN_ID.fullmatch(run_id):
            raise ValueError("P7 execution failure evidence is invalid")
        summary = _read_json(self.config.runs_root / run_id / "summary.json")
        prefix = None if summary is None else summary.get("completed_prefix")
        game_id = prefix.get("game_id") if type(prefix) is dict else None
        if (
            game_id not in self._campaign_ids()
            or not self._second_round_campaign_is_ready(self._selected_games())
            or not self._execution_failure_is_valid(run_id, game_id)
        ):
            raise ValueError("P7 execution failure evidence is invalid")
        campaign = self._load_or_create_campaign()
        if any(item["game_id"] == game_id or item["run_id"] == run_id for item in campaign["terminal_attempts"]):
            raise ValueError("P7 execution failure is already recorded")
        campaign["terminal_attempts"].append({"game_id": game_id, "run_id": run_id, "outcome": "execution-failed"})
        self._write_campaign(campaign)
        return game_id

    def adopt_execution_stalled(self, run_id: str) -> str:
        """Record one explicitly selected valid supervisor stall without launching work."""

        if not self.config.unbounded_second_round or not _RUN_ID.fullmatch(run_id):
            raise ValueError("P7 execution stall evidence is invalid")
        run = self.config.runs_root / run_id
        game_id = _recorded_game_id(run, set(self._campaign_ids()))
        if (
            game_id not in self._campaign_ids()
            or not self._second_round_campaign_is_ready(self._selected_games())
            or not self._execution_stalled_is_valid(run_id, game_id)
        ):
            raise ValueError("P7 execution stall evidence is invalid")
        campaign = self._load_or_create_campaign()
        if any(item["game_id"] == game_id or item["run_id"] == run_id for item in campaign["terminal_attempts"]):
            raise ValueError("P7 execution stall is already recorded")
        campaign["terminal_attempts"].append({"game_id": game_id, "run_id": run_id, "outcome": "execution-stalled"})
        self._write_campaign(campaign)
        return game_id

    def _record_campaign_attempt(self, campaign: dict[str, Any], game_id: str, outcome: str) -> None:
        if outcome not in {"verified", "unsolved", "timed-out-unsealed", "execution-failed", "execution-stalled"} or not self._new_runs:
            raise ValueError
        if outcome == "execution-failed" and not self._execution_failure_is_valid(self._new_runs[-1], game_id):
            raise ValueError
        if outcome == "execution-stalled" and not self._execution_stalled_is_valid(self._new_runs[-1], game_id):
            raise ValueError
        attempts = campaign["terminal_attempts"]
        if any(item["game_id"] == game_id for item in attempts):
            raise ValueError
        attempts.append({"game_id": game_id, "run_id": self._new_runs[-1], "outcome": outcome})
        self._write_campaign(campaign)

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

        if self._is_research_round(self.config):
            return self.config.run_timeout

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
        started_at = 0.0
        last_action_at = 0.0
        last_action_count = 0
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
            nonlocal last_action_at, last_action_count
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
                if (
                    (self.config.unbounded_second_round
                     or self.config.action_stall_seconds == _ACTION_STALL_SECONDS)
                    and self._stop_reason == "completed"
                ):
                    action_count = _trace_action_count(run)
                    if action_count is not None and action_count > last_action_count:
                        last_action_count = action_count
                        last_action_at = time.monotonic()
            reported = self._input_tokens + self._output_tokens + sum(sum(value) for value in observed.values())
            if not self._is_research_round(self.config) and self.config.global_token_cap is not None and reported >= self.config.global_token_cap and self._stop_reason == "completed":
                self._stop_reason = "token-cap"
            if (
                (self.config.unbounded_second_round
                 or self.config.action_stall_seconds == _ACTION_STALL_SECONDS)
                and self._stop_reason == "completed"
                and started_at
                and _action_stall_reached(started_at, last_action_at or started_at, time.monotonic())
            ):
                self._stop_reason = "execution-stalled"

        try:
            process = subprocess.Popen(
                [*self.config.command, f"GAME={game_id}", f"LEVEL={level}",
                 *([f"PRIME_ORB_MACHINE={self.config.guest_machine}"] if self.config.guest_machine else [])],
                cwd=self.config.repo_root,
                env={**os.environ, "ASTERION_PRIME_P7_SEED": "0",
                     "ASTERION_PRIME_P7_ATTEMPT_UNIT": unit,
                     "ASTERION_PRIME_P7_ATTEMPT_SECONDS": "0" if timeout is None else str(min(
                         timeout + 30 if self._is_research_round(self.config) else timeout, 4 * 60 * 60)),
                     "ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND": "1" if self._is_research_round(self.config) else "",
                     "OPERATION_MODE": "offline" if self._is_research_round(self.config) else ""},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            started_at = time.monotonic()
            last_action_at = started_at
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
        if self._stop_reason == "execution-stalled" and len(new_runs) == 1:
            run = self.config.runs_root / new_runs[0]
            action_count = _trace_action_count(run)
            cleanup_complete = self.config.guest_machine is None or cleaned
            if action_count is None or not _write_stall_receipt(
                run, game_id=game_id, run_id=new_runs[0], action_count=action_count,
                expected_action_count=last_action_count,
                stall_seconds=time.monotonic() - last_action_at, cleanup_complete=cleanup_complete,
            ):
                self._stop_reason = "execution-stalled-evidence-invalid"
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
            if len(new_runs) == 1 and self._stop_reason in {"completed", "run-timeout", "execution-stalled"}:
                summary = _read_json(run / "summary.json")
                try:
                    entries = _read_hash_chained_trace(
                        run / "trace" / "prime-trace.jsonl", in_progress=self._stop_reason == "run-timeout",
                    )
                    sealed = entries[-1]["kind"] == "trace.sealed"
                except (OSError, UnicodeError, ValueError, KeyError, TypeError):
                    sealed = False
                if self._stop_reason == "execution-stalled":
                    if not self._execution_stalled_is_valid(run_id, game_id, target_level=level):
                        self._stop_reason = "execution-stalled-evidence-invalid"
                elif self._stop_reason == "run-timeout":
                    if (
                        not sealed
                        and not usage[2]
                        and not usage[3]
                        and _recorded_game_id(run, {game_id}) == game_id
                        and (not self.config.unbounded_second_round or _trace_reached_level(entries, 1))
                    ):
                        self._stop_reason = "timed-out-unsealed"
                    else:
                        self._stop_reason = "run-timeout-evidence-invalid"
                elif returncode != 0 and level == 2 and self._execution_failure_is_valid(run_id, game_id):
                    self._stop_reason = "execution-failed"
                elif not sealed or not _valid_attempt_summary(summary, run_id, game_id, level, returncode):
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
        if self.config.unbounded_second_round and not self._second_round_campaign_is_ready(games):
            return SweepResult(0, (), (), (), 0, 0, "second-round-catalog-invalid", ())
        campaign: dict[str, Any] | None = None
        if self._is_research_round(self.config):
            try:
                campaign = self._load_or_create_campaign()
            except (OSError, ValueError):
                label = "second-round" if self.config.unbounded_second_round else "first-round"
                return SweepResult(0, (), (), (), 0, 0, f"{label}-campaign-invalid", ())
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
        previously_attempted_unsolved_level_one: list[str] = []
        interrupted_without_evidence_level_one: list[str] = []
        timed_out_unsealed_level_one: list[str] = []
        preexisting_level_two: list[str] = []
        newly_verified_level_two: list[str] = []
        attempted_unsolved_level_two: list[str] = []
        previously_attempted_unsolved_level_two: list[str] = []
        timed_out_unsealed_level_two: list[str] = []
        execution_failed_level_two: list[str] = []
        previously_execution_failed_level_two: list[str] = []
        execution_stalled_level_two: list[str] = []
        previously_execution_stalled_level_two: list[str] = []
        started = time.monotonic()
        if self.config.unbounded_first_round:
            assert campaign is not None
            prior_unsolved = {
                item["game_id"] for item in campaign["terminal_attempts"]
                if item["outcome"] in {"unsolved", "timed-out-unsealed"}
            }
            unstarted: list[str] = []
            for game_id in active:
                if game_id in prior_unsolved:
                    previously_attempted_unsolved_level_one.append(game_id)
                elif self._next_level(game_id) == 1:
                    unstarted.append(game_id)
                else:
                    preexisting_level_one.append(game_id)
            active = unstarted
        if self.config.unbounded_second_round:
            assert campaign is not None
            prior = {item["game_id"]: item["outcome"] for item in campaign["terminal_attempts"]}
            unstarted = []
            for game_id in active:
                if game_id in prior:
                    if prior[game_id] == "verified":
                        preexisting_level_two.append(game_id)
                    elif prior[game_id] == "execution-failed":
                        previously_execution_failed_level_two.append(game_id)
                    elif prior[game_id] == "execution-stalled":
                        previously_execution_stalled_level_two.append(game_id)
                    else:
                        previously_attempted_unsolved_level_two.append(game_id)
                elif self._next_level(game_id) == 2:
                    unstarted.append(game_id)
                else:
                    preexisting_level_two.append(game_id)
            active = unstarted
        while active:
            next_active: list[str] = []
            for game_id in active:
                if self._stop_reason != "completed":
                    break
                if not self._is_research_round(self.config) and self.config.wallclock_cap is not None and time.monotonic() - started >= self.config.wallclock_cap:
                    self._stop_reason = "wallclock-cap"
                    break
                if not self._is_research_round(self.config) and self.config.global_token_cap is not None and self._input_tokens + self._output_tokens >= self.config.global_token_cap:
                    self._stop_reason = "token-cap"
                    break
                if self.config.max_attempts is not None and attempted >= self.config.max_attempts:
                    self._stop_reason = "attempt-cap"
                    break
                level = self._next_level(game_id)
                if self._is_complete(game_id, level):
                    completed.append(game_id)
                    continue
                if not self.config.unbounded_second_round and (game_id, level) in self._deferred_levels:
                    deferred.append(f"{game_id}:level-{level}")
                    blocked.append(game_id)
                    continue
                attempted += 1
                print(f"[p7-sweep] attempt game={game_id} level={level}", file=sys.stderr, flush=True)
                remaining = None if self._is_research_round(self.config) or self.config.wallclock_cap is None else self.config.wallclock_cap - (time.monotonic() - started)
                level_timeout = self._timeout_for_level(game_id, level)
                timeout = level_timeout if remaining is None else min(level_timeout, remaining)
                returncode = self._attempt(game_id, level, timeout)
                if self.config.unbounded_second_round and self._stop_reason == "execution-failed":
                    try:
                        self._record_campaign_attempt(campaign, game_id, "execution-failed")
                    except (OSError, ValueError):
                        self._stop_reason = "second-round-campaign-write-failed"
                        break
                    execution_failed_level_two.append(game_id)
                    blocked.append(game_id)
                    self._stop_reason = "completed"
                    continue
                if self.config.unbounded_second_round and self._stop_reason == "execution-stalled":
                    try:
                        self._record_campaign_attempt(campaign, game_id, "execution-stalled")
                    except (OSError, ValueError):
                        self._stop_reason = "second-round-campaign-write-failed"
                        break
                    execution_stalled_level_two.append(game_id)
                    blocked.append(game_id)
                    self._stop_reason = "completed"
                    continue
                if self._is_research_round(self.config) and self._stop_reason == "timed-out-unsealed":
                    try:
                        self._record_campaign_attempt(campaign, game_id, "timed-out-unsealed")
                    except (OSError, ValueError):
                        self._stop_reason = "research-round-campaign-write-failed"
                        break
                    if self.config.unbounded_second_round:
                        timed_out_unsealed_level_two.append(game_id)
                    else:
                        timed_out_unsealed_level_one.append(game_id)
                    blocked.append(game_id)
                    self._stop_reason = "completed"
                    continue
                if self._stop_reason == "run-timeout" and not self._is_research_round(self.config) and self.config.wallclock_cap is not None and time.monotonic() - started >= self.config.wallclock_cap:
                    self._stop_reason = "wallclock-cap"
                if self._stop_reason != "completed":
                    if self.config.unbounded_first_round and level == 1 and self._stop_reason.startswith("run-timeout"):
                        interrupted_without_evidence_level_one.append(game_id)
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
                        try:
                            self._record_campaign_attempt(campaign, game_id, "verified")
                        except (OSError, ValueError):
                            self._stop_reason = "first-round-campaign-write-failed"
                            break
                        newly_verified_level_one.append(game_id)
                    if self.config.unbounded_second_round:
                        try:
                            self._record_campaign_attempt(campaign, game_id, "verified")
                        except (OSError, ValueError):
                            self._stop_reason = "second-round-campaign-write-failed"
                            break
                        newly_verified_level_two.append(game_id)
                    if self.config.unbounded_first_round:
                        continue
                    if self.config.unbounded_second_round:
                        continue
                    next_level = self._next_level(game_id)
                    if self._is_complete(game_id, next_level):
                        completed.append(game_id)
                    else:
                        next_active.append(game_id)
                else:
                    if self.config.unbounded_first_round and level == 1:
                        try:
                            self._record_campaign_attempt(campaign, game_id, "unsolved")
                        except (OSError, ValueError):
                            self._stop_reason = "first-round-campaign-write-failed"
                            break
                        attempted_unsolved_level_one.append(game_id)
                    if self.config.unbounded_second_round:
                        try:
                            self._record_campaign_attempt(campaign, game_id, "unsolved")
                        except (OSError, ValueError):
                            self._stop_reason = "second-round-campaign-write-failed"
                            break
                        attempted_unsolved_level_two.append(game_id)
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
            tuple(sorted(set(previously_attempted_unsolved_level_one))),
            tuple(sorted(set(interrupted_without_evidence_level_one))),
            tuple(sorted(set(timed_out_unsealed_level_one))),
            tuple(sorted(set(preexisting_level_two))),
            tuple(sorted(set(newly_verified_level_two))),
            tuple(sorted(set(attempted_unsolved_level_two))),
            tuple(sorted(set(previously_attempted_unsolved_level_two))),
            tuple(sorted(set(timed_out_unsealed_level_two))),
            tuple(sorted(set(execution_failed_level_two))),
            tuple(sorted(set(previously_execution_failed_level_two))),
            tuple(sorted(set(execution_stalled_level_two))),
            tuple(sorted(set(previously_execution_stalled_level_two))),
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


def _trace_reached_level(entries: tuple[dict[str, Any], ...], level: int) -> bool:
    return any(
        entry["kind"] == "arc.action"
        and type(entry["payload"].get("levels_completed")) is int
        and entry["payload"]["levels_completed"] >= level
        for entry in entries
    )


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
    parser.add_argument("--unbounded-second-round", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--adopt-execution-failure")
    parser.add_argument("--adopt-execution-stalled")
    args = parser.parse_args(argv)
    if args.seed != 0:
        parser.error("--seed must be 0; the P7 Makefile fixes the official game seed")
    runs_root = args.runs_root or args.operator_root / ".asterion-private" / "prime-p7-live"
    scheduler = SweepScheduler(
        SweepConfig(
            arc_root=args.arc_root,
            runs_root=runs_root,
            games=tuple(args.games),
            seed=args.seed,
            global_token_cap=None if args.unbounded_first_round or args.unbounded_second_round else args.token_cap,
            wallclock_cap=None if args.unbounded_first_round or args.unbounded_second_round else args.wallclock_seconds,
            run_timeout=args.run_timeout,
            max_attempts=args.max_attempts,
            repo_root=args.operator_root,
            guest_machine=args.guest_machine,
            unbounded_first_round=args.unbounded_first_round,
            unbounded_second_round=args.unbounded_second_round,
        )
    )
    if args.adopt_execution_failure is not None and args.adopt_execution_stalled is not None:
        parser.error("choose one execution evidence adoption option")
    if args.adopt_execution_failure is not None:
        if not args.unbounded_second_round or args.preflight_only:
            parser.error("--adopt-execution-failure requires only --unbounded-second-round")
        try:
            game_id = scheduler.adopt_execution_failure(args.adopt_execution_failure)
        except (OSError, ValueError):
            print(json.dumps({"schema": "asterion.prime.p7-second-round-recovery/v1", "recorded": False}))
            return 1
        print(json.dumps({"schema": "asterion.prime.p7-second-round-recovery/v1", "recorded": True, "game_id": game_id, "outcome": "execution-failed"}, sort_keys=True))
        return 0
    if args.adopt_execution_stalled is not None:
        if not args.unbounded_second_round or args.preflight_only:
            parser.error("--adopt-execution-stalled requires only --unbounded-second-round")
        try:
            game_id = scheduler.adopt_execution_stalled(args.adopt_execution_stalled)
        except (OSError, ValueError):
            print(json.dumps({"schema": "asterion.prime.p7-second-round-recovery/v1", "recorded": False}))
            return 1
        print(json.dumps({"schema": "asterion.prime.p7-second-round-recovery/v1", "recorded": True, "game_id": game_id, "outcome": "execution-stalled"}, sort_keys=True))
        return 0
    if args.preflight_only:
        if not args.unbounded_second_round:
            parser.error("--preflight-only requires --unbounded-second-round")
        games = scheduler._selected_games()
        ready = scheduler._second_round_campaign_is_ready(games)
        campaign_path = scheduler._campaign_path()
        if ready and (campaign_path.exists() or campaign_path.is_symlink()):
            try:
                scheduler._load_or_create_campaign()
            except (OSError, ValueError):
                ready = False
        print(json.dumps({"schema": "asterion.prime.p7-second-round-preflight/v1", "ready": ready, "games": games}, sort_keys=True))
        return 0 if ready else 1
    result = scheduler.run()
    print(json.dumps({"schema": "asterion.prime.p7-sweep/v1", **asdict(result)}, sort_keys=True))
    return 0 if result.stopped_reason in {"completed", "no-games"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
