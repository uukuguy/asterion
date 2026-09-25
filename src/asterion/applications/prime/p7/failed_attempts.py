"""Read and summarize sealed failed P7 attempts for an explicit retry.

This module consumes only the private summary, sealed trace, and recording for
the same run.  It deliberately does not inspect worker cells or model input.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import cast

from .broker import ArcTransition
from .live import read_trace_entries
from .run_story.evidence import _recording


class FailedAttemptEvidenceError(ValueError):
    """Evidence was not a complete, sealed failed attempt."""


@dataclass(frozen=True, slots=True)
class FailedActionFact:
    sequence: int
    action: Mapping[str, object]
    levels_completed: int
    before_sha256: str
    after_sha256: str
    changed_cells: int
    interior_changed_cells: int
    border_changed_cells: int
    border_only: bool
    color_counts: Mapping[int, int]


@dataclass(frozen=True, slots=True)
class FailedRunFacts:
    run_id: str
    terminal_reason: str
    target_level: int
    action_count: int
    input_tokens: int
    output_tokens: int
    actions: tuple[FailedActionFact, ...]


@dataclass(frozen=True, slots=True)
class FailedAttemptAdvice:
    schema: str
    game_id: str
    seed: int
    target_level: int
    source_run_ids: tuple[str, ...]
    source_digest: str
    runs: tuple[FailedRunFacts, ...]

    @property
    def source_count(self) -> int:
        return len(self.runs)

    @property
    def fact_count(self) -> int:
        return sum(len(run.actions) for run in self.runs)


def _fail() -> None:
    raise FailedAttemptEvidenceError("failed-attempt evidence is unavailable")


def _safe_path(root: Path, *parts: str) -> Path:
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        _fail()
    path = root
    for part in parts:
        if not part or Path(part).name != part:
            _fail()
        path = path / part
        if path.is_symlink():
            _fail()
    if not path.is_relative_to(root):
        _fail()
    return path


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _fail()
    return cast(Mapping[str, object], value)


def _int(value: object, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or type(value) is not int or value < minimum:
        _fail()
    return value


def _digest_payload(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":"), sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _transitions(entries: tuple[object, ...]) -> tuple[ArcTransition, ...]:
    result: list[ArcTransition] = []
    for entry in entries:
        if getattr(entry, "kind", None) != "arc.action":
            continue
        payload = _mapping(getattr(entry, "payload", None))
        allowed = {"action", "after_sha256", "before_sha256", "levels_completed", "sequence"}
        if set(payload) not in (allowed, allowed | {"data"}):
            _fail()
        data = payload.get("data", {})
        data_map = _mapping(data)
        sequence = _int(payload.get("sequence"), minimum=1)
        if sequence != len(result) + 1:
            _fail()
        result.append(ArcTransition(
            sequence, payload.get("action"), payload.get("before_sha256"),
            payload.get("after_sha256"), _int(payload.get("levels_completed")),
            tuple(sorted(data_map.items())),
        ))
    if not result:
        _fail()
    return tuple(result)


def _recording_file(run: Path) -> Path:
    recordings = _safe_path(run, "recordings")
    if not recordings.is_dir() or recordings.is_symlink():
        _fail()
    sessions = tuple(item for item in recordings.iterdir() if not item.is_symlink())
    if len(sessions) != 1 or not sessions[0].is_dir():
        _fail()
    files = tuple(item for item in sessions[0].iterdir() if not item.is_symlink())
    if len(files) != 1 or not files[0].is_file() or files[0].suffix != ".jsonl":
        _fail()
    return files[0]


def _grid_facts(before: object, after: object) -> tuple[int, int, int, bool, Mapping[int, int]]:
    # FrameFact.grid is a tuple of rows.  Recordings are required to contain a
    # real 64x64 frame, so malformed synthetic evidence cannot become advice.
    if not isinstance(before, tuple) or not isinstance(after, tuple) or not before or len(before) != len(after):
        _fail()
    height, width = len(before), len(before[0])
    if (height, width) != (64, 64) or any(len(row) != width for row in before + after):
        _fail()
    changed = interior = border = 0
    counts: dict[int, int] = {}
    for y, (row_before, row_after) in enumerate(zip(before, after)):
        for x, (left, right) in enumerate(zip(row_before, row_after)):
            counts[right] = counts.get(right, 0) + 1
            if left != right:
                changed += 1
                if x in {0, width - 1} or y in {0, height - 1}:
                    border += 1
                else:
                    interior += 1
    return changed, interior, border, changed > 0 and interior == 0 and border == changed, dict(sorted(counts.items()))


def _load_one(run: Path, *, game_id: str, seed: int, target_level: int) -> FailedRunFacts:
    if run.is_symlink() or not run.is_dir():
        _fail()
    summary_path = _safe_path(run, "summary.json")
    trace_root = _safe_path(run, "trace")
    trace_path = _safe_path(run, "trace", "prime-trace.jsonl")
    seal_path = _safe_path(run, "trace", "prime-trace.seal.json")
    if not trace_root.is_dir() or not trace_path.is_file() or not seal_path.is_file():
        _fail()
    summary = _mapping(json.loads(summary_path.read_text(encoding="utf-8")))
    if summary.get("schema") != "asterion.prime.p7-live-private-summary/v1" or summary.get("run_id") != run.name:
        _fail()
    if not all(summary.get(key) is True for key in ("sealed_trace", "replay_verified", "cleanup_complete")):
        _fail()
    diagnostics = _mapping(summary.get("diagnostics"))
    sweep = _mapping(diagnostics.get("sweep"))
    if _int(sweep.get("target_level"), minimum=1) != target_level:
        _fail()
    broker = _mapping(summary.get("broker"))
    if broker.get("game_id") != game_id or _int(broker.get("seed")) != seed:
        _fail()
    levels = _int(broker.get("levels_completed"))
    action_count = _int(broker.get("primitive_actions"))
    if levels >= target_level or action_count == 0:
        _fail()
    terminal = broker.get("terminal_reason")
    if terminal not in {"human-baseline", "game-over", "action-cap"}:
        _fail()
    experiment = summary.get("experiment")
    if experiment is not None:
        exp = _mapping(experiment)
        if (exp.get("game_id"), _int(exp.get("seed")), _int(exp.get("target_level"), minimum=1)) != (game_id, seed, target_level):
            _fail()
    entries = read_trace_entries(trace_root)
    seal = _mapping(json.loads(seal_path.read_text(encoding="utf-8")))
    if seal.get("entry_count") != len(entries) or seal.get("final_sha256") != entries[-1].sha256 or type(seal.get("sealed_at")) is not str:
        _fail()
    terminal_entries = tuple(entry for entry in entries if entry.kind == "arc.run.failed")
    if len(terminal_entries) != 1:
        _fail()
    terminal_payload = _mapping(terminal_entries[0].payload)
    if (terminal_payload.get("game_id"), terminal_payload.get("seed"), terminal_payload.get("levels_completed"), terminal_payload.get("primitive_actions"), terminal_payload.get("terminal_reason")) != (game_id, seed, levels, action_count, terminal):
        _fail()
    transitions = _transitions(entries)
    if len(transitions) != action_count:
        _fail()
    recorded_game_id, _win_levels, frames, recorded_actions = _recording(_recording_file(run))
    if recorded_game_id != game_id or len(recorded_actions) != action_count:
        _fail()
    facts: list[FailedActionFact] = []
    for transition, recorded in zip(transitions, recorded_actions):
        if (transition.action, transition.data, transition.before_sha256, transition.after_sha256, transition.levels_completed) != (recorded.name, recorded.data, recorded.before_sha256, recorded.after_sha256, _int(transition.levels_completed)):
            _fail()
        before = frames[recorded.before_frame].grid
        after = frames[recorded.after_frame].grid
        changed, interior, border, border_only, counts = _grid_facts(before, after)
        action = {"name": transition.action}
        if transition.data:
            action["data"] = dict(transition.data)
        facts.append(FailedActionFact(transition.sequence, action, transition.levels_completed, transition.before_sha256, transition.after_sha256, changed, interior, border, border_only, counts))
    usage = [entry.payload for entry in entries if entry.kind == "arc.usage.reported"]
    input_tokens = sum(_int(_mapping(item).get("input_tokens")) for item in usage)
    output_tokens = sum(_int(_mapping(item).get("output_tokens")) for item in usage)
    bounded = tuple(facts[:32] + (facts[-32:] if len(facts) > 64 else []))
    return FailedRunFacts(run.name, terminal, target_level, action_count, input_tokens, output_tokens, bounded)


def _candidate_matches_identity(run: Path, *, game_id: str, seed: int, target_level: int) -> bool:
    """Cheap identity filter used before parsing a candidate's evidence."""
    try:
        summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
        if not isinstance(summary, Mapping):
            return False
        broker = summary.get("broker")
        diagnostics = summary.get("diagnostics")
        sweep = diagnostics.get("sweep") if isinstance(diagnostics, Mapping) else None
        if not isinstance(broker, Mapping) or not isinstance(sweep, Mapping):
            return False
        if (broker.get("game_id"), broker.get("seed"), sweep.get("target_level")) != (game_id, seed, target_level):
            return False
        experiment = summary.get("experiment")
        if experiment is not None and (
            not isinstance(experiment, Mapping)
            or (experiment.get("game_id"), experiment.get("seed"), experiment.get("target_level"))
            != (game_id, seed, target_level)
        ):
            return False
        return True
    except Exception:
        return False


def select_failed_attempt_advice(runs_root: Path, *, game_id: str, seed: int, target_level: int, limit: int = 2) -> FailedAttemptAdvice:
    """Select up to ``limit`` newest sealed failures for one exact identity."""
    if type(game_id) is not str or not game_id or type(seed) is not int or isinstance(seed, bool) or type(target_level) is not int or target_level < 1 or type(limit) is not int or limit < 1:
        _fail()
    if not runs_root.is_absolute() or runs_root.is_symlink() or not runs_root.is_dir():
        _fail()
    candidates: list[FailedRunFacts] = []
    for run in runs_root.iterdir():
        if run.is_symlink() or not run.is_dir():
            continue
        if not _candidate_matches_identity(run, game_id=game_id, seed=seed, target_level=target_level):
            continue
        # Once the cheap identity matches, malformed evidence is a hard
        # failure.  It must not silently become advice for a retry.
        candidate = _load_one(run, game_id=game_id, seed=seed, target_level=target_level)
        candidates.append(candidate)
    candidates.sort(key=lambda item: item.run_id, reverse=True)
    selected = tuple(candidates[:limit])
    payload = [{"run_id": run.run_id, "terminal_reason": run.terminal_reason, "target_level": run.target_level, "action_count": run.action_count, "input_tokens": run.input_tokens, "output_tokens": run.output_tokens, "actions": [{"sequence": action.sequence, "action": dict(action.action), "levels_completed": action.levels_completed, "before_sha256": action.before_sha256, "after_sha256": action.after_sha256, "changed_cells": action.changed_cells, "interior_changed_cells": action.interior_changed_cells, "border_changed_cells": action.border_changed_cells, "border_only": action.border_only, "color_counts": dict(action.color_counts)} for action in run.actions]} for run in selected]
    return FailedAttemptAdvice("asterion.prime.p7-failed-attempt-advice/v1", game_id, seed, target_level, tuple(run.run_id for run in selected), _digest_payload(payload), selected)


def render_failed_attempt_advice(advice: FailedAttemptAdvice) -> str:
    """Render a bounded, private fact block suitable for retry model input."""
    if type(advice) is not FailedAttemptAdvice:
        _fail()
    rows = []
    for run in advice.runs:
        rows.append({"run_id": run.run_id, "terminal_reason": run.terminal_reason, "actions": [{"sequence": fact.sequence, "action": dict(fact.action), "levels_completed": fact.levels_completed, "changed_cells": fact.changed_cells, "interior_changed_cells": fact.interior_changed_cells, "border_changed_cells": fact.border_changed_cells, "border_only": fact.border_only, "color_counts": dict(fact.color_counts)} for fact in run.actions]})
    return "CHECKED LOCAL FAILED-ATTEMPT OBSERVATIONS (not a solution or objective):\n" + json.dumps({"game_id": advice.game_id, "seed": advice.seed, "target_level": advice.target_level, "source_run_ids": list(advice.source_run_ids), "source_digest": advice.source_digest, "runs": rows}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


__all__ = ("FailedAttemptEvidenceError", "FailedActionFact", "FailedRunFacts", "FailedAttemptAdvice", "select_failed_attempt_advice", "render_failed_attempt_advice")
