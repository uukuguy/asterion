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
from .score import replay_sha256
from .private_trace import P7_TRACE_IDENTITIES


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
    source_type: str = "sealed-failure"
    prefix_action_count: int = 0
    evidence_digest: str = ""


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
    return _transitions_from_payloads(tuple(
        getattr(entry, "payload", None)
        for entry in entries if getattr(entry, "kind", None) == "arc.action"
    ))


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


def _raw_trace(run: Path, *, sealed: bool) -> tuple[dict[str, object], ...]:
    """Read a trace with the same chain rules as the recorder.

    ``read_trace_entries`` deliberately rejects an unsealed file.  A stall is
    useful evidence only when its final complete line is independently
    verified, so the retry reader has its own strict, application local check.
    An unterminated last line is rejected rather than silently truncated.
    """
    path = _safe_path(run, "trace", "prime-trace.jsonl")
    if not path.is_file():
        _fail()
    data = path.read_bytes()
    if not data.endswith(b"\n"):
        _fail()
    rows: list[dict[str, object]] = []
    previous: str | None = None
    identities: object = None
    for expected, line in enumerate(data.splitlines(), 1):
        try:
            value = json.loads(line)
        except (UnicodeError, json.JSONDecodeError):
            _fail()
        if not isinstance(value, dict) or set(value) != {"identities", "kind", "payload", "previous_sha256", "sequence", "sha256"}:
            _fail()
        if value["sequence"] != expected or value["previous_sha256"] != previous:
            _fail()
        if type(value["identities"]) is not dict or type(value["kind"]) is not str or type(value["payload"]) is not dict:
            _fail()
        if identities is None:
            identities = value["identities"]
        elif value["identities"] != identities:
            _fail()
        if value["identities"] != P7_TRACE_IDENTITIES:
            _fail()
        encoded = json.dumps({"identities": value["identities"], "kind": value["kind"], "payload": value["payload"], "previous_sha256": previous, "sequence": expected}, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
        if value["sha256"] != digest:
            _fail()
        rows.append(value)
        previous = digest
    if not rows or (sealed and rows[-1]["kind"] != "trace.sealed") or (not sealed and rows[-1]["kind"] == "trace.sealed"):
        _fail()
    return tuple(rows)


def _action_facts(
    run: Path, rows: tuple[dict[str, object], ...], *, game_id: str,
    action_count: int, levels: int,
) -> tuple[tuple[FailedActionFact, ...], tuple[ArcTransition, ...]]:
    def field(row: object, name: str) -> object:
        return row.get(name) if isinstance(row, Mapping) else getattr(row, name, None)
    transitions = _transitions_from_payloads(tuple(field(row, "payload") for row in rows if field(row, "kind") == "arc.action"))
    if len(transitions) != action_count:
        _fail()
    recorded_game_id, _win_levels, frames, recorded_actions = _recording(_recording_file(run))
    if recorded_game_id != game_id or len(recorded_actions) != action_count:
        _fail()
    facts: list[FailedActionFact] = []
    for transition, recorded in zip(transitions, recorded_actions):
        if (transition.action, transition.data, transition.before_sha256, transition.after_sha256, transition.levels_completed) != (recorded.name, recorded.data, recorded.before_sha256, recorded.after_sha256, frames[recorded.after_frame].levels_completed):
            _fail()
        before = frames[recorded.before_frame].grid
        after = frames[recorded.after_frame].grid
        changed, interior, border, border_only, counts = _grid_facts(before, after)
        action = {"name": transition.action}
        if transition.data:
            action["data"] = dict(transition.data)
        facts.append(FailedActionFact(transition.sequence, action, transition.levels_completed, transition.before_sha256, transition.after_sha256, changed, interior, border, border_only, counts))
    if transitions and transitions[-1].levels_completed != levels:
        _fail()
    return tuple(facts), transitions


def _transitions_from_payloads(payloads: tuple[object, ...]) -> tuple[ArcTransition, ...]:
    result: list[ArcTransition] = []
    for payload in payloads:
        value = _mapping(payload)
        allowed = {"action", "after_sha256", "before_sha256", "levels_completed", "sequence"}
        if set(value) not in (allowed, allowed | {"data"}):
            _fail()
        data = _mapping(value.get("data", {}))
        sequence = _int(value.get("sequence"), minimum=1)
        if sequence != len(result) + 1:
            _fail()
        result.append(ArcTransition(sequence, value.get("action"), value.get("before_sha256"), value.get("after_sha256"), _int(value.get("levels_completed")), tuple(sorted(data.items()))))
    if not result:
        _fail()
    return tuple(result)


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
    terminal_entries = tuple(entry for entry in entries if entry.kind in {"arc.run.failed", "arc.run.partial"})
    if len(terminal_entries) != 1:
        _fail()
    terminal_payload = _mapping(terminal_entries[0].payload)
    if terminal_entries[0].kind == "arc.run.failed":
        if (terminal_payload.get("game_id"), terminal_payload.get("seed"), terminal_payload.get("levels_completed"), terminal_payload.get("primitive_actions"), terminal_payload.get("terminal_reason")) != (game_id, seed, levels, action_count, terminal):
            _fail()
        source_type, prefix_count = "sealed-failure", 0
    else:
        prefix = _mapping(summary.get("completed_prefix"))
        required = {"game_id", "seed", "win_levels", "levels_completed", "primitive_actions", "replay_sha256", "terminal_reason"}
        if set(terminal_payload) != required or terminal_payload != prefix or terminal_payload.get("game_id") != game_id or terminal_payload.get("seed") != seed or terminal_payload.get("levels_completed") != levels - 0 or terminal_payload.get("terminal_reason") != "level-completed":
            _fail()
        prefix_count = _int(terminal_payload.get("primitive_actions"), minimum=1)
        if prefix_count > action_count or _int(terminal_payload.get("levels_completed"), minimum=1) != levels:
            _fail()
        if prefix_count > len(tuple(entry for entry in entries if entry.kind == "arc.action")):
            _fail()
        if transitions := _transitions(entries):
            if transitions[prefix_count - 1].levels_completed != levels or any(item.levels_completed >= levels for item in transitions[:prefix_count - 1]):
                _fail()
        source_type = "sealed-partial-failure"
        if len(entries) < 2 or entries[-2].kind != "arc.run.partial" or entries[-1].kind != "trace.sealed":
            _fail()
    transitions = _transitions(entries)
    facts, transitions = _action_facts(run, entries, game_id=game_id, action_count=action_count, levels=levels)
    if source_type == "sealed-partial-failure":
        if terminal_payload.get("replay_sha256") != replay_sha256(transitions[:prefix_count], terminal_reason="level-completed"):
            _fail()
    usage = [entry.payload for entry in entries if entry.kind == "arc.usage.reported"]
    input_tokens = sum(_int(_mapping(item).get("input_tokens")) for item in usage)
    output_tokens = sum(_int(_mapping(item).get("output_tokens")) for item in usage)
    bounded = facts[:32] + (facts[-32:] if len(facts) > 64 else ())
    evidence_digest = terminal_payload.get("replay_sha256") if source_type == "sealed-partial-failure" else entries[-1].sha256
    if type(evidence_digest) is not str:
        _fail()
    return FailedRunFacts(run.name, terminal, target_level, action_count, input_tokens, output_tokens, bounded, source_type, prefix_count, evidence_digest)


def _load_stall(run: Path, *, game_id: str, seed: int, target_level: int) -> FailedRunFacts:
    receipt_path = _safe_path(run, "stall-receipt.json")
    receipt = _mapping(json.loads(receipt_path.read_text(encoding="utf-8")))
    required = {"schema", "game_id", "run_id", "seed", "action_count", "stall_seconds", "cleanup_complete", "trace_final_sha256"}
    if set(receipt) != required or receipt.get("schema") != "asterion.prime.p7-stall-receipt/v1" or receipt.get("game_id") != game_id or receipt.get("run_id") != run.name or _int(receipt.get("seed")) != seed or receipt.get("cleanup_complete") is not True or _int(receipt.get("action_count"), minimum=1) <= 0 or _int(receipt.get("stall_seconds"), minimum=300) < 300:
        _fail()
    rows = _raw_trace(run, sealed=False)
    if receipt.get("trace_final_sha256") != rows[-1]["sha256"] or any(row["kind"] not in {"arc.action", "arc.usage.reported", "arc.run.partial"} for row in rows):
        _fail()
    action_count = _int(receipt.get("action_count"), minimum=1)
    if sum(row["kind"] == "arc.action" for row in rows) != action_count:
        _fail()
    transitions = _transitions_from_payloads(tuple(row["payload"] for row in rows if row["kind"] == "arc.action"))
    levels = max(item.levels_completed for item in transitions)
    if target_level <= 1 or levels != target_level - 1:
        _fail()
    facts, transitions = _action_facts(run, rows, game_id=game_id, action_count=action_count, levels=levels)
    prefix_count = next((item.sequence for item in transitions if item.levels_completed == levels), 0)
    if prefix_count <= 0 or not _matches_verified_prefix(run.parent, game_id=game_id, seed=seed, transitions=transitions, prefix_count=prefix_count):
        _fail()
    usage = [row["payload"] for row in rows if row["kind"] == "arc.usage.reported"]
    input_tokens = sum(_int(_mapping(item).get("input_tokens")) for item in usage)
    output_tokens = sum(_int(_mapping(item).get("output_tokens")) for item in usage)
    bounded = facts[:32] + (facts[-32:] if len(facts) > 64 else ())
    evidence_digest = _digest_payload({"trace_final_sha256": receipt["trace_final_sha256"], "prefix_replay_sha256": replay_sha256(transitions[:prefix_count], terminal_reason="level-completed")})
    return FailedRunFacts(run.name, "execution-stalled", target_level, action_count, input_tokens, output_tokens, bounded, "execution-stall-observation", prefix_count, evidence_digest)


def _matches_verified_prefix(
    runs_root: Path, *, game_id: str, seed: int,
    transitions: tuple[ArcTransition, ...], prefix_count: int,
) -> bool:
    """Bind a stall's retained prefix to a separately sealed level witness."""
    for candidate in runs_root.iterdir():
        if candidate.is_symlink() or not candidate.is_dir() or (candidate / "summary.json").is_symlink():
            continue
        try:
            summary = _mapping(json.loads((candidate / "summary.json").read_text(encoding="utf-8")))
            broker = _mapping(summary.get("broker"))
            if (
                summary.get("schema") != "asterion.prime.p7-live-private-summary/v1"
                or summary.get("run_id") != candidate.name
                or summary.get("sealed_trace") is not True
                or summary.get("replay_verified") is not True
                or summary.get("cleanup_complete") is not True
                or broker.get("game_id") != game_id or _int(broker.get("seed")) != seed
                or broker.get("levels_completed") != transitions[prefix_count - 1].levels_completed
                or broker.get("terminal_reason") != "level-completed"
                or _int(broker.get("primitive_actions"), minimum=1) != prefix_count
            ):
                continue
            entries = read_trace_entries(_safe_path(candidate, "trace"))
            historical = _transitions(entries)
            if len(historical) != prefix_count or historical != transitions[:prefix_count]:
                continue
            if broker.get("replay_sha256") != replay_sha256(historical, terminal_reason="level-completed"):
                continue
            return True
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, IndexError, FailedAttemptEvidenceError):
            continue
    return False


def _candidate_matches_identity(run: Path, *, game_id: str, seed: int, target_level: int) -> bool:
    """Cheap identity filter used before parsing a candidate's evidence."""
    try:
        summary_file = run / "summary.json"
        if not summary_file.exists() and (run / "stall-receipt.json").is_file():
            receipt = json.loads((run / "stall-receipt.json").read_text(encoding="utf-8"))
            if not isinstance(receipt, Mapping) or (receipt.get("game_id"), receipt.get("seed")) != (game_id, seed):
                return False
            rows = _raw_trace(run, sealed=False)
            actions = tuple(row["payload"] for row in rows if row["kind"] == "arc.action")
            return bool(actions) and max(
                item.get("levels_completed") for item in actions if isinstance(item, Mapping)
            ) == target_level - 1
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        if not isinstance(summary, Mapping):
            return False
        broker = summary.get("broker")
        diagnostics = summary.get("diagnostics")
        sweep = diagnostics.get("sweep") if isinstance(diagnostics, Mapping) else None
        if not isinstance(broker, Mapping) or not isinstance(sweep, Mapping):
            return False
        if (broker.get("game_id"), broker.get("seed"), sweep.get("target_level")) != (game_id, seed, target_level):
            return False
        if (
            broker.get("terminal_reason") not in {"human-baseline", "game-over", "action-cap"}
            or type(broker.get("levels_completed")) is not int
            or broker["levels_completed"] >= target_level
        ):
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
    matching = sorted((run for run in runs_root.iterdir() if not run.is_symlink() and run.is_dir() and _candidate_matches_identity(run, game_id=game_id, seed=seed, target_level=target_level)), key=lambda item: item.name, reverse=True)
    malformed_newest = False
    for run in matching:
        # A newer valid attempt supersedes an older malformed attempt.  If the
        # newest matching attempt is malformed, fail closed immediately.
        try:
            if (run / "stall-receipt.json").is_file() and not (run / "summary.json").exists():
                candidate = _load_stall(run, game_id=game_id, seed=seed, target_level=target_level)
            else:
                candidate = _load_one(run, game_id=game_id, seed=seed, target_level=target_level)
        except FailedAttemptEvidenceError:
            if not candidates:
                malformed_newest = True
                break
            continue
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    if malformed_newest:
        _fail()
    selected = tuple(candidates[:limit])
    payload = [{"run_id": run.run_id, "source_type": run.source_type, "prefix_action_count": run.prefix_action_count, "evidence_digest": run.evidence_digest, "terminal_reason": run.terminal_reason, "target_level": run.target_level, "action_count": run.action_count, "input_tokens": run.input_tokens, "output_tokens": run.output_tokens, "actions": [{"sequence": action.sequence, "action": dict(action.action), "levels_completed": action.levels_completed, "before_sha256": action.before_sha256, "after_sha256": action.after_sha256, "changed_cells": action.changed_cells, "interior_changed_cells": action.interior_changed_cells, "border_changed_cells": action.border_changed_cells, "border_only": action.border_only, "color_counts": dict(action.color_counts)} for action in run.actions]} for run in selected]
    return FailedAttemptAdvice("asterion.prime.p7-failed-attempt-advice/v1", game_id, seed, target_level, tuple(run.run_id for run in selected), _digest_payload(payload), selected)


def render_failed_attempt_advice(advice: FailedAttemptAdvice) -> str:
    """Render a bounded, private fact block suitable for retry model input."""
    if type(advice) is not FailedAttemptAdvice:
        _fail()
    rows = []
    for run in advice.runs:
        rows.append({"run_id": run.run_id, "source_type": run.source_type, "prefix_action_count": run.prefix_action_count, "evidence_digest": run.evidence_digest, "terminal_reason": run.terminal_reason, "actions": [{"sequence": fact.sequence, "action": dict(fact.action), "levels_completed": fact.levels_completed, "changed_cells": fact.changed_cells, "interior_changed_cells": fact.interior_changed_cells, "border_changed_cells": fact.border_changed_cells, "border_only": fact.border_only, "color_counts": dict(fact.color_counts)} for fact in run.actions]})
    return "CHECKED LOCAL FAILED-ATTEMPT OBSERVATIONS (not a solution or objective):\n" + json.dumps({"game_id": advice.game_id, "seed": advice.seed, "target_level": advice.target_level, "source_run_ids": list(advice.source_run_ids), "source_digest": advice.source_digest, "runs": rows}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


__all__ = ("FailedAttemptEvidenceError", "FailedActionFact", "FailedRunFacts", "FailedAttemptAdvice", "select_failed_attempt_advice", "render_failed_attempt_advice")
