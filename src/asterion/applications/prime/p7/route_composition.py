"""Explicit two-source saved routes and their immutable offline provenance."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import re

from asterion.agents.prime.trace import _plain
from .broker import ArcTransition, _snapshot_observation, _observation_digest
from .live import read_trace_entries
from .private_trace import trace_identities_for
from .score import digest, replay_sha256

KIND = "saved-route-composition"
_RUN = re.compile(r"p7-live-[0-9]{14}-[0-9a-f]{24}\Z")
_SEGMENT = {"source_run_id", "source_start_sequence", "source_end_sequence",
            "destination_start_sequence", "destination_end_sequence", "source_hashes", "worldmap_revision"}


def compose_transitions(prefix: tuple[ArcTransition, ...], suffix: tuple[ArcTransition, ...]) -> tuple[ArcTransition, ...]:
    """Describe expected replay; the materializer must check every actual result."""
    if not prefix or not suffix:
        raise ValueError
    if any(right.before_sha256 != left.after_sha256 for left, right in zip(suffix, suffix[1:])):
        raise ValueError
    return (*prefix, *(replace(item, sequence=len(prefix) + index,
                              before_sha256=prefix[-1].after_sha256 if index == 1 else item.before_sha256)
                      for index, item in enumerate(suffix, 1)))


def _entries(run: Path):
    from .solutions import _private_path
    if (_private_path(run, "trace", "prime-trace.jsonl").stat().st_size > 32 * 1024 * 1024
            or _private_path(run, "trace", "prime-trace.seal.json").stat().st_size > 1024 * 1024):
        raise ValueError
    entries = read_trace_entries(_private_path(run, "trace"))
    seal = json.loads(_private_path(run, "trace", "prime-trace.seal.json").read_text())
    if (not entries or type(seal) is not dict or set(seal) != {"entry_count", "final_sha256", "sealed_at"}
            or seal["entry_count"] != len(entries) or seal["final_sha256"] != entries[-1].sha256
            or type(seal["sealed_at"]) is not str):
        raise ValueError
    return entries


def _recording(run: Path, group: str) -> Path:
    from .solutions import _private_path
    sessions = tuple(_private_path(run, group).iterdir())
    if len(sessions) != 1:
        raise ValueError
    session = _private_path(run, group, sessions[0].name)
    files = tuple(session.glob("*.jsonl"))
    if len(files) != 1:
        raise ValueError
    return _private_path(run, group, session.name, files[0].name)


def _source(run: Path):
    from .solutions import (VerifiedPrefix, _load_direct_resume_worldmap, _private_path,
                            _transitions, _truncate, _partial_summary_matches, _summary_matches, _prefix_values)
    summary_path = _private_path(run, "summary.json")
    if summary_path.stat().st_size > 1024 * 1024:
        raise ValueError
    summary = json.loads(summary_path.read_text())
    if (type(summary) is not dict or summary.get("schema") != "asterion.prime.p7-live-private-summary/v1"
            or summary.get("run_id") != run.name or not _RUN.fullmatch(run.name)
            or any(summary.get(key) is not True for key in ("sealed_trace", "replay_verified", "cleanup_complete"))):
        raise ValueError
    experiment = summary.get("experiment")
    if (type(experiment) is not dict or experiment.get("prediction_variant") != "verified"
            or type(experiment.get("seed")) is not int):
        raise ValueError
    entries = _entries(run)
    if any(dict(entry.identities) != trace_identities_for(experiment["model"]) for entry in entries):
        raise ValueError
    completed = [entry.payload for entry in entries if entry.kind == "arc.run.completed"]
    partial = [entry.payload for entry in entries if entry.kind == "arc.run.partial"]
    if (len(completed), len(partial)) not in {(1, 0), (0, 1)}:
        raise ValueError
    scope = summary.get("completed_prefix") if partial else summary.get("broker")
    if (type(scope) is not dict or scope.get("game_id") != experiment.get("game_id")
            or scope.get("seed") != experiment["seed"] or type(scope.get("win_levels")) is not int
            or type(scope.get("levels_completed")) is not int):
        raise ValueError
    transitions = _transitions(entries)
    values = _prefix_values(partial[0] if partial else completed[0], scope["game_id"], scope["seed"],
                            scope["win_levels"], is_partial=bool(partial))
    if values != (scope["levels_completed"], scope["primitive_actions"], scope["terminal_reason"], scope["replay_sha256"]):
        raise ValueError
    if partial:
        if not _partial_summary_matches(summary, partial[0]):
            raise ValueError
        transitions = _truncate(transitions, scope["levels_completed"])
    elif not _summary_matches(summary, scope["game_id"], scope["seed"], scope["win_levels"],
                              scope["levels_completed"], len(transitions), scope["terminal_reason"], scope["replay_sha256"]):
        raise ValueError
    if (len(transitions) != scope["primitive_actions"]
            or replay_sha256(transitions, terminal_reason=scope["terminal_reason"]) != scope["replay_sha256"]):
        raise ValueError
    prefix = VerifiedPrefix(scope["game_id"], scope["seed"], scope["win_levels"], scope["levels_completed"], transitions, run.name, scope["replay_sha256"])
    prior = _load_direct_resume_worldmap(run, prefix)
    if prior is None:
        raise ValueError
    world_scope = {"game_id": prefix.game_id, "seed": prefix.seed, "win_levels": prefix.win_levels,
                   "run_id": run.name, "attempt_id": run.name}
    workspace = ("research", digest(world_scope)[7:])
    paths = [_private_path(run, "summary.json"), _private_path(run, "trace", "prime-trace.jsonl"),
             _private_path(run, "trace", "prime-trace.seal.json"), _recording(run, "recordings"),
             _private_path(run, *workspace, "current.json"),
             _private_path(run, *workspace, "revisions", prior["source_revision"][7:] + ".json")]
    for group in ("replay-recordings", "prefix-replay-recordings"):
        if (run / group).exists() or (run / group).is_symlink():
            paths.append(_recording(run, group))
    if (run / "console-events.jsonl").exists() or (run / "console-events.jsonl").is_symlink():
        paths.append(_private_path(run, "console-events.jsonl"))
    if any(path.stat().st_size > 32 * 1024 * 1024 for path in paths):
        raise ValueError
    hashes = {path.relative_to(run).as_posix(): sha256(path.read_bytes()).hexdigest() for path in paths}
    return summary, prefix, prior, hashes


def _boundary(run: Path, sequence: int, win_levels: int):
    rows = [json.loads(line)["data"] for line in _recording(run, "recordings").read_text().splitlines()]
    actions, started = [], False
    for row in rows:
        if not started and row["action_input"]["id"] == "RESET":
            continue
        started = True
        actions.append(row)
    observation = _snapshot_observation(actions[sequence - 1], win_levels=win_levels)
    return _observation_digest(observation), _observation_digest(replace(observation, frame=(observation.frame[-1],)))


def plan_composition(prefix_run: Path, suffix_run: Path, through_level: int):
    """Pin two native source scopes; callers independently replay them first."""
    from .solutions import _truncate
    first, last = _source(prefix_run), _source(suffix_run)
    a, b = first[1], last[1]
    if (prefix_run == suffix_run or type(through_level) is not int
            or not 1 <= through_level < a.win_levels or through_level > a.levels_completed
            or b.levels_completed != b.win_levels
            or any(getattr(a, key) != getattr(b, key) for key in ("game_id", "seed", "win_levels"))
            or first[0]["experiment"]["model"] != last[0]["experiment"]["model"]):
        raise ValueError
    prefix = _truncate(a.transitions, through_level)
    cut = len(_truncate(b.transitions, through_level))
    suffix = b.transitions[cut:]
    left, right = _boundary(prefix_run, len(prefix), a.win_levels), _boundary(suffix_run, cut, a.win_levels)
    if left[0] != prefix[-1].after_sha256 or right[0] != suffix[0].before_sha256 or left[1] != right[1]:
        raise ValueError
    seam = {"through_level": through_level, "prefix_after_sha256": left[0],
            "suffix_before_sha256": right[0], "settled_sha256": left[1]}
    segments = []
    for run, item, start, end, destination in (
            (prefix_run, first, 1, len(prefix), 1),
            (suffix_run, last, cut + 1, len(b.transitions), len(prefix) + 1)):
        segments.append({"source_run_id": run.name, "source_start_sequence": start, "source_end_sequence": end,
                         "destination_start_sequence": destination, "destination_end_sequence": destination + end - start,
                         "source_hashes": item[3], "worldmap_revision": item[2]["source_revision"]})
    return segments, seam, compose_transitions(prefix, suffix), first[0]["experiment"]


def composition_sources(run: Path, summary: Mapping[str, object]) -> tuple[tuple[dict, Path, dict], ...] | None:
    """Validate explicit source attribution; official admission still SDK-replays."""
    from .solutions import _private_path, _transitions, _summary_matches
    try:
        diagnostics = summary.get("diagnostics")
        if (not isinstance(diagnostics, Mapping) or diagnostics.get("recovery_kind") != KIND
                or diagnostics.get("execution_mode") != "offline-replay"
                or any(type(diagnostics.get(key)) is not int for key in ("model_call_count", "new_solver_actions", "restoration_actions"))
                or diagnostics.get("model_call_count") != 0 or diagnostics.get("new_solver_actions") != 0):
            return None
        segments, seam = diagnostics.get("route_sources"), diagnostics.get("composition_seam")
        if type(segments) is not list or len(segments) != 2 or type(seam) is not dict:
            return None
        sources = []
        for segment in segments:
            if (type(segment) is not dict or set(segment) != _SEGMENT
                    or type(segment["source_run_id"]) is not str or not _RUN.fullmatch(segment["source_run_id"])
                    or segment["source_run_id"] == run.name
                    or any(type(segment[key]) is not int for key in ("source_start_sequence", "source_end_sequence", "destination_start_sequence", "destination_end_sequence"))):
                return None
            sources.append(_private_path(run.parent, segment["source_run_id"]))
        expected, expected_seam, transitions, experiment = plan_composition(*sources, seam["through_level"])
        if segments != expected or seam != expected_seam:
            return None
        own_experiment = summary.get("experiment")
        broker = summary.get("broker")
        if (type(own_experiment) is not dict or own_experiment.get("prediction_variant") != "offline-replay"
                or type(own_experiment.get("seed")) is not int or type(broker) is not dict
                or any(own_experiment.get(key) != experiment.get(key) for key in ("game_id", "seed", "model"))
                or summary.get("run_id") != run.name
                or any(summary.get(key) is not True for key in ("sealed_trace", "replay_verified", "cleanup_complete"))
                or broker.get("terminal_reason") != "game-won"
                or broker.get("levels_completed") != broker.get("win_levels")
                or own_experiment.get("target_level") != broker["win_levels"]
                or diagnostics.get("restoration_actions") != len(transitions)):
            return None
        entries = _entries(run)
        marker = {"recovery_kind": KIND, "route_sources": segments, "composition_seam": seam}
        if ([ _plain(entry.payload) for entry in entries if entry.kind == "arc.recovery.source"] != [marker]
                or any(dict(entry.identities) != trace_identities_for(experiment["model"]) for entry in entries)
                or _transitions(entries) != transitions
                or not _summary_matches(summary, experiment["game_id"], experiment["seed"], broker["win_levels"],
                                        broker["win_levels"], len(transitions), "game-won", replay_sha256(transitions, terminal_reason="game-won"))):
            return None
        return tuple((segment, source, json.loads((source / "summary.json").read_text())) for segment, source in zip(segments, sources))
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return None
