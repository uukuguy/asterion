#!/usr/bin/env python3
"""Replay an audited P7 trace race or terminal WIN into separate evidence."""

from __future__ import annotations

import argparse
import fcntl
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from asterion.agents.prime.trace import PrimeTraceRecorder, _entry_digest
from asterion.applications.prime.p7 import live
from asterion.applications.prime.p7.broker import ArcBroker, ArcObservation, ArcRunReceipt, ArcTransition
from asterion.applications.prime.p7.diagnostics import analyze_trace
from asterion.applications.prime.p7.game import (
    GAME_ID_ENV,
    SEED_ENV,
    TARGET_LEVEL_ENV,
    P7GameSelection,
    resolve_game_selection,
)
from asterion.applications.prime.p7.model_selection import declared_model_selection
from asterion.applications.prime.p7.operator import _P7BrokerClient
from asterion.applications.prime.p7.private_trace import (
    P7PrivateTraceReceipt,
    are_p7_trace_identities,
    trace_identities_for,
)
from asterion.applications.prime.p7.replay import replay_arc_run
from asterion.applications.prime.p7.score import replay_sha256


_RUN_ID = re.compile(r"^p7-live-[0-9]{14}-[0-9a-f]{24}$")
_ENTRY_FIELDS = {
    "identities",
    "kind",
    "payload",
    "previous_sha256",
    "sequence",
    "sha256",
}
_SUMMARY_SCHEMA = "asterion.prime.p7-live-private-summary/v1"


class RecoveryError(RuntimeError):
    """The private source did not prove the one supported recovery case."""


@dataclass(frozen=True, slots=True)
class _Candidate:
    source: Path
    game: P7GameSelection
    transitions: tuple[ArcTransition, ...]
    receipt: ArcRunReceipt
    source_hashes: Mapping[str, object]
    usage_input_tokens: int
    usage_output_tokens: int
    identities: Mapping[str, str] | None = None
    experiment: Mapping[str, object] | None = None
    composition: Mapping[str, object] | None = None
    observations: tuple[ArcObservation, ...] | None = None
    source_receipt: Mapping[str, object] | None = None
    source_identity: str | None = None


def _digest_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _reject_symlink_components(base: Path, path: Path) -> None:
    base = base.absolute()
    path = path.absolute()
    try:
        relative = path.relative_to(base)
    except ValueError:
        raise ValueError from None
    current = base
    if current.is_symlink():
        raise ValueError
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError


def _inside_file(root: Path, path: Path) -> Path:
    _reject_symlink_components(root, path)
    if path.is_symlink() or not path.is_file():
        raise ValueError
    resolved_root = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(resolved_root):
        raise ValueError
    return path


def _source_directory(operator_root: Path, source_run_id: str) -> Path:
    if type(source_run_id) is not str or _RUN_ID.fullmatch(source_run_id) is None:
        raise ValueError
    runs = operator_root / ".asterion-private" / "prime-p7-live"
    source = runs / source_run_id
    _reject_symlink_components(operator_root, source)
    if runs.is_symlink() or source.is_symlink() or not source.is_dir():
        raise ValueError
    if not source.resolve(strict=True).is_relative_to(runs.resolve(strict=True)):
        raise ValueError
    return source


def _read_rows(source: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    trace = _inside_file(source, source / "trace" / "prime-trace.jsonl")
    seal_path = _inside_file(source, source / "trace" / "prime-trace.seal.json")
    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if len(rows) < 5 or type(seal) is not dict:
        raise ValueError
    if set(seal) != {"entry_count", "final_sha256", "sealed_at"}:
        raise ValueError
    if seal["entry_count"] != len(rows) or seal["final_sha256"] != rows[-1].get("sha256"):
        raise ValueError
    for row in rows:
        if type(row) is not dict or set(row) != _ENTRY_FIELDS:
            raise ValueError
        if not are_p7_trace_identities(row["identities"]):
            raise ValueError
        if row["sha256"] != _entry_digest(
            row["sequence"],
            row["kind"],
            row["identities"],
            row["payload"],
            row["previous_sha256"],
        ):
            raise ValueError
    duplicates = {
        value
        for value in (row["sequence"] for row in rows)
        if sum(other["sequence"] == value for other in rows) == 2
    }
    if len(duplicates) != 1:
        raise ValueError
    duplicate = duplicates.pop()
    positions = [index for index, row in enumerate(rows) if row["sequence"] == duplicate]
    if positions != [duplicate - 1, duplicate]:
        raise ValueError
    left, right = rows[positions[0]], rows[positions[1]]
    if (
        left["kind"] != "arc.usage.reported"
        or right["kind"] != "arc.action"
        or left["previous_sha256"] != right["previous_sha256"]
    ):
        raise ValueError
    for physical, row in enumerate(rows, 1):
        expected_sequence = physical - 1 if physical == duplicate + 1 else physical
        if row["sequence"] != expected_sequence:
            raise ValueError
        expected_previous = None if physical == 1 else rows[physical - 2]["sha256"]
        if physical == duplicate + 1:
            expected_previous = rows[physical - 3]["sha256"] if physical > 2 else None
        if row["previous_sha256"] != expected_previous:
            raise ValueError
    last = rows[-1]
    if (
        last["kind"] != "trace.sealed"
        or last["payload"]
        != {"entry_count": len(rows) - 1, "final_sha256": last["previous_sha256"]}
    ):
        raise ValueError
    return rows, seal


def _recording(source: Path, group: str) -> tuple[list[dict[str, object]], str]:
    root = source / group
    if root.is_symlink() or not root.is_dir():
        raise ValueError
    sessions = tuple(root.iterdir())
    if len(sessions) != 1 or sessions[0].is_symlink() or not sessions[0].is_dir():
        raise ValueError
    files = tuple(sessions[0].glob("*.jsonl"))
    if len(files) != 1:
        raise ValueError
    path = _inside_file(source, files[0])
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    data = [row.get("data") for row in rows if type(row) is dict]
    if not data or any(type(item) is not dict for item in data):
        raise ValueError
    normalized = [{key: value for key, value in item.items() if key != "guid"} for item in data]
    return normalized, _digest_file(path)


def _recorded_actions(
    rows: list[dict[str, object]], game_id: str, win_levels: int
) -> tuple[tuple[str, tuple[tuple[str, int], ...]], ...]:
    actions: list[tuple[str, tuple[tuple[str, int], ...]]] = []
    started = False
    resets = 0
    for row in rows:
        if row.get("game_id") != game_id or row.get("win_levels") != win_levels:
            raise ValueError
        action = row.get("action_input")
        if (
            type(action) is not dict
            or set(action) not in ({"id", "data"}, {"id", "data", "reasoning"})
            or (
                "reasoning" in action
                and action["reasoning"] is not None
                and type(action["reasoning"]) is not str
            )
        ):
            raise ValueError
        name, data = action["id"], action["data"]
        if type(name) is not str or type(data) is not dict:
            raise ValueError
        if name == "RESET" and not started:
            resets += 1
            if data:
                raise ValueError
            continue
        started = True
        if any(type(key) is not str or type(value) is not int for key, value in data.items()):
            raise ValueError
        actions.append((name, tuple(data.items())))
    if resets < 1 or not actions:
        raise ValueError
    return tuple(actions)


def _candidate(operator_root: Path, arc_root: Path, source_run_id: str) -> _Candidate:
    source = _source_directory(operator_root, source_run_id)
    summary_path = _inside_file(source, source / "summary.json")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if (
        type(summary) is not dict
        or summary.get("schema") != _SUMMARY_SCHEMA
        or summary.get("run_id") != source_run_id
        or summary.get("cleanup_complete") is not True
        or summary.get("replay_verified") is not True
        or summary.get("sealed_trace") is not False
        or summary.get("completed_prefix") is not None
        or summary.get("failure")
        != {"message": "trace is unavailable", "type": "PrimeTraceError"}
    ):
        raise ValueError
    broker = summary.get("broker")
    receipt_value = summary.get("receipt")
    if type(broker) is not dict or type(receipt_value) is not dict:
        raise ValueError
    if (
        set(broker)
        != {
            "game_id",
            "levels_completed",
            "primitive_actions",
            "replay_sha256",
            "seed",
            "terminal_reason",
            "win_levels",
        }
        or broker["levels_completed"] != 1
        or broker["terminal_reason"] != "level-completed"
        or broker["seed"] != 0
        or receipt_value.get("completed_level_count") != 1
        or receipt_value.get("primitive_action_count") != broker["primitive_actions"]
    ):
        raise ValueError
    rows, _ = _read_rows(source)
    payloads = [row["payload"] for row in rows if row["kind"] == "arc.action"]
    transitions = tuple(
        ArcTransition(
            payload["sequence"],
            payload["action"],
            payload["before_sha256"],
            payload["after_sha256"],
            payload["levels_completed"],
            tuple(payload.get("data", {}).items()),
        )
        for payload in payloads
        if type(payload) is dict
    )
    receipt = ArcRunReceipt(
        broker["game_id"],
        broker["seed"],
        broker["primitive_actions"],
        broker["levels_completed"],
        broker["terminal_reason"],
        broker["replay_sha256"],
    )
    if (
        len(transitions) != receipt.primitive_actions
        or tuple(item.sequence for item in transitions)
        != tuple(range(1, len(transitions) + 1))
        or replay_sha256(transitions, terminal_reason="level-completed")
        != receipt.replay_sha256
    ):
        raise ValueError
    game = resolve_game_selection(
        {
            GAME_ID_ENV: receipt.game_id,
            SEED_ENV: str(receipt.seed),
            TARGET_LEVEL_ENV: "1",
        },
        arc_root,
    )
    if game.win_levels != broker["win_levels"]:
        raise ValueError
    recordings = [_recording(source, group) for group in (
        "recordings", "replay-recordings", "prefix-replay-recordings"
    )]
    if not (recordings[0][0] == recordings[1][0] == recordings[2][0]):
        raise ValueError
    recorded = _recorded_actions(recordings[0][0], game.game_id, game.win_levels)
    if recorded != tuple((item.action, item.data) for item in transitions):
        raise ValueError
    with tempfile.TemporaryDirectory(prefix="asterion-p7-recovery-audit-") as directory:
        replay_arc_run(
            transitions,
            receipt,
            lambda: live.ArcadeEngine(
                arc_root=arc_root, recordings_dir=Path(directory), game=game
            ),
            game=game,
        )
    usage = [row["payload"] for row in rows if row["kind"] == "arc.usage.reported"]
    if any(
        type(item) is not dict
        or set(item) != {"input_tokens", "output_tokens"}
        or any(type(item[key]) is not int or item[key] < 0 for key in item)
        for item in usage
    ):
        raise ValueError
    return _Candidate(
        source,
        game,
        transitions,
        receipt,
        {
            "summary_sha256": _digest_file(summary_path),
            "trace_sha256": _digest_file(source / "trace" / "prime-trace.jsonl"),
            "trace_seal_sha256": _digest_file(source / "trace" / "prime-trace.seal.json"),
            "recording_sha256s": sorted(value[1] for value in recordings),
        },
        sum(item["input_tokens"] for item in usage),
        sum(item["output_tokens"] for item in usage),
    )


def _terminal_candidate(operator_root: Path, arc_root: Path, source_run_id: str) -> _Candidate:
    source = _source_directory(operator_root, source_run_id).resolve(strict=True)
    summary_path = _inside_file(source, source / "summary.json")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if (
        type(summary) is not dict or summary.get("schema") != _SUMMARY_SCHEMA
        or summary.get("run_id") != source_run_id
        or summary.get("cleanup_complete") is not True
        or summary.get("replay_verified") is not True
        or type(summary.get("sealed_trace")) is not bool
        or type(summary.get("failure")) is not dict
        or summary.get("receipt") != {} or summary.get("completed_prefix") is not None
    ):
        raise ValueError
    broker = summary.get("broker")
    if (
        type(broker) is not dict
        or set(broker) != {"game_id", "seed", "win_levels", "levels_completed",
                           "primitive_actions", "terminal_reason", "replay_sha256"}
        or broker["terminal_reason"] != "game-won"
        or type(broker["win_levels"]) is not int or broker["win_levels"] < 1
        or type(broker["levels_completed"]) is not int
        or broker["levels_completed"] != broker["win_levels"]
        or type(broker["seed"]) is not int
        or type(broker["primitive_actions"]) is not int
    ):
        raise ValueError
    trace = _inside_file(source, source / "trace" / "prime-trace.jsonl")
    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    previous = None
    identities = None
    for sequence, row in enumerate(rows, 1):
        if (type(row) is not dict or set(row) != _ENTRY_FIELDS
                or type(row["sequence"]) is not int or row["sequence"] != sequence
                or not are_p7_trace_identities(row["identities"])
                or row["previous_sha256"] != previous
                or row["sha256"] != _entry_digest(sequence, row["kind"], row["identities"], row["payload"], previous)):
            raise ValueError
        if identities is None:
            identities = row["identities"]
        if row["identities"] != identities:
            raise ValueError
        previous = row["sha256"]
    if identities is None or any(row["kind"] in {"arc.run.completed", "arc.run.partial", "arc.run.failed"} for row in rows):
        raise ValueError
    source_experiment = summary.get("experiment")
    if (type(source_experiment) is not dict
            or source_experiment.get("game_id") != broker["game_id"]
            or type(source_experiment.get("seed")) is not int
            or source_experiment["seed"] != broker["seed"]
            or source_experiment.get("model") != identities["model_id"]):
        raise ValueError
    seal_path = source / "trace" / "prime-trace.seal.json"
    hashes = {"summary_sha256": _digest_file(summary_path), "trace_sha256": _digest_file(trace)}
    if summary["sealed_trace"]:
        seal = json.loads(_inside_file(source, seal_path).read_text())
        entries = live.read_trace_entries(source / "trace")
        if (set(seal) != {"entry_count", "final_sha256", "sealed_at"}
                or seal["entry_count"] != len(entries) or seal["final_sha256"] != entries[-1].sha256
                or type(seal["sealed_at"]) is not str
                or [row["payload"] for row in rows if row["kind"] == "arc.run.game-won"] != [broker]):
            raise ValueError
        hashes["trace_seal_sha256"] = _digest_file(seal_path)
    elif seal_path.exists() or seal_path.is_symlink() or any(row["kind"] in {"trace.sealed", "arc.run.game-won"} for row in rows):
        raise ValueError
    from asterion.agents.prime.trace import PrimeTraceEntry
    from asterion.applications.prime.p7.solutions import _transitions
    transitions = _transitions(tuple(PrimeTraceEntry(**row) for row in rows))
    receipt = ArcRunReceipt(*(broker[key] for key in (
        "game_id", "seed", "primitive_actions", "levels_completed", "terminal_reason", "replay_sha256")))
    if len(transitions) != receipt.primitive_actions or replay_sha256(transitions, terminal_reason="game-won") != receipt.replay_sha256:
        raise ValueError
    game = resolve_game_selection({GAME_ID_ENV: receipt.game_id, SEED_ENV: str(receipt.seed), TARGET_LEVEL_ENV: str(receipt.levels_completed)}, arc_root)
    if game.win_levels != broker["win_levels"]:
        raise ValueError
    from asterion.applications.prime.p7.broker import _snapshot_observation
    from asterion.applications.prime.p7.replay import observations_match
    from asterion.applications.prime.p7.solutions import recorded_observations
    recordings = [_recording(source, group) for group in ("recordings", "replay-recordings")]
    original, replayed = (item[0] for item in recordings)
    if len(original) != len(replayed) or any(
        {key: value for key, value in left.items() if key != "frame"}
        != {key: value for key, value in right.items() if key != "frame"}
        or not observations_match(
            _snapshot_observation(left, win_levels=game.win_levels),
            _snapshot_observation(right, win_levels=game.win_levels),
        ) for left, right in zip(original, replayed)
    ):
        raise ValueError
    if original[-1].get("state") != "WIN" or original[-1].get("levels_completed") != game.win_levels:
        raise ValueError
    if _recorded_actions(original, game.game_id, game.win_levels) != tuple((t.action, t.data) for t in transitions):
        raise ValueError
    # Bind every original animation pixel to its trace. Admission is static;
    # materialization and verify_for_save provide two independent fresh passes.
    observations = recorded_observations(source, transitions, game.game_id, game.win_levels)
    if observations is None:
        raise ValueError
    hashes["recording_sha256s"] = sorted(item[1] for item in recordings)
    usage = [row["payload"] for row in rows if row["kind"] == "arc.usage.reported"]
    if any(type(item) is not dict or set(item) != {"input_tokens", "output_tokens"}
           or any(type(value) is not int or value < 0 for value in item.values()) for item in usage):
        raise ValueError
    # The replay itself performs no model execution. Source identity is preserved
    # explicitly, while its original experiment remains attributable to source.
    experiment = {"game_id": game.game_id, "seed": game.seed, "model": identities["model_id"],
                  "target_level": game.win_levels, "prediction_variant": "offline-replay"}
    from asterion.applications.prime.p7.solution_certificates import _source_identity
    return _Candidate(source, game, transitions, receipt, hashes,
                      sum(item["input_tokens"] for item in usage), sum(item["output_tokens"] for item in usage),
                      identities, experiment, observations=observations, source_identity=_source_identity(source))


def recover_terminal_win(*, operator_root: Path, arc_root: Path, source_run_id: str) -> Path:
    """Independently replay a game WIN; the source model failure stays unchanged."""
    return _recover(operator_root=operator_root, arc_root=arc_root,
                    source_run_id=source_run_id, kind="terminal-game-win")


def compose_saved_route(*, operator_root: Path, arc_root: Path, source_run_id: str,
                       suffix_run_id: str, through_level: int) -> Path:
    """Replay a new sealed prefix followed only by an old saved suffix."""
    from asterion.applications.prime.p7.route_composition import KIND, plan_composition
    from asterion.applications.prime.p7.solutions import load_exact_prefix
    try:
        source = _source_directory(operator_root, source_run_id)
        suffix = _source_directory(operator_root, suffix_run_id)
        segments, seam, transitions, experiment = plan_composition(source, suffix, through_level)
        for run in (source, suffix):
            if load_exact_prefix(arc_root, run.parent, run.name, experiment["game_id"], experiment["seed"],
                                 expected_model_id=experiment["model"]) is None:
                raise ValueError
        if plan_composition(source, suffix, through_level)[:3] != (segments, seam, transitions):
            raise ValueError
        game = resolve_game_selection({GAME_ID_ENV: experiment["game_id"], SEED_ENV: str(experiment["seed"]),
                                       TARGET_LEVEL_ENV: str(transitions[-1].levels_completed)}, arc_root)
        terminal = "game-won" if game.target_level == game.win_levels else "level-completed"
        receipt = ArcRunReceipt(game.game_id, game.seed, len(transitions), game.target_level,
                                terminal, replay_sha256(transitions, terminal_reason=terminal))
        candidate = _Candidate(source, game, transitions, receipt, {}, 0, 0,
                               trace_identities_for(experiment["model"]),
                               {"game_id": game.game_id, "seed": game.seed, "model": experiment["model"],
                                "target_level": game.target_level, "prediction_variant": "offline-replay"},
                               {"route_sources": segments, "composition_seam": seam})
    except Exception:
        raise RecoveryError("composition source is unavailable") from None
    return _materialize(operator_root=operator_root, arc_root=arc_root, source_run_id=source_run_id,
                        kind=KIND, candidate=candidate)


def recover_animation_replay(*, operator_root: Path, arc_root: Path, source_run_id: str) -> Path:
    """Verify every settled observation, then write distinct offline evidence."""
    from asterion.applications.prime.p7.animation_replay import KIND, native_evidence
    try:
        source = _source_directory(operator_root, source_run_id)
        summary, transitions, observations, receipt, hashes = native_evidence(source)
        game = resolve_game_selection({GAME_ID_ENV: receipt.game_id, SEED_ENV: str(receipt.seed),
            TARGET_LEVEL_ENV: str(receipt.levels_completed)}, arc_root)
        with tempfile.TemporaryDirectory(prefix="asterion-p7-animation-audit-") as directory:
            replay_arc_run(transitions, receipt, lambda: live.ArcadeEngine(
                arc_root=arc_root, recordings_dir=Path(directory), game=game),
                game=game, observations=observations)
        experiment = {key: summary["experiment"][key] for key in ("game_id", "seed", "model", "target_level")}
        experiment["prediction_variant"] = "offline-replay"
        usage = [entry.payload for entry in live.read_trace_entries(source / "trace")
                 if entry.kind == "arc.usage.reported"]
        if any(set(item) != {"input_tokens", "output_tokens"}
               or any(type(value) is not int or value < 0 for value in item.values()) for item in usage):
            raise ValueError
        candidate = _Candidate(source, game, transitions, receipt, hashes,
            sum(item["input_tokens"] for item in usage), sum(item["output_tokens"] for item in usage),
            trace_identities_for(experiment["model"]), experiment,
            observations=observations, source_receipt=summary["receipt"])
    except Exception:
        raise RecoveryError("animation recovery source is unavailable") from None
    return _materialize(operator_root=operator_root, arc_root=arc_root, source_run_id=source_run_id,
        kind=KIND, candidate=candidate)


def _receipt_mapping(value: object) -> dict[str, object]:
    names = (
        "completed_level_count",
        "partial_game_score",
        "primitive_action_count",
        "promotion",
        "receipt_sha256",
        "run_id",
        "scope",
    )
    receipt = {name: getattr(value, name) for name in names}
    digest = receipt["receipt_sha256"]
    if type(digest) is not str or not digest.startswith("sha256:"):
        raise ValueError
    receipt["receipt_sha256"] = digest.removeprefix("sha256:")
    return receipt


def _replay_into(
    broker: ArcBroker,
    recorder: PrimeTraceRecorder,
    transitions: tuple[ArcTransition, ...],
    identities: Mapping[str, str],
    observations: tuple[ArcObservation, ...] | None = None,
) -> None:
    from asterion.applications.prime.p7.replay import authenticate_observations, observation_matches_digest
    if observations is not None:
        authenticate_observations(transitions, observations)
    client = _P7BrokerClient(broker, recorder, identities, variant="legacy")
    for expected in transitions:
        if not observation_matches_digest(broker.observe(), expected.before_sha256,
                None if observations is None else observations[expected.sequence - 1]):
            raise ValueError
        client.act([{"name": expected.action, "data": dict(expected.data)}], _trusted_prefix_replay=True)
        actual = broker.journal[-1]
        if (actual.action != expected.action or actual.data != expected.data
                or actual.sequence != expected.sequence or actual.levels_completed != expected.levels_completed
                or not observation_matches_digest(broker.replay_observations[-1], expected.after_sha256,
                    None if observations is None else observations[expected.sequence])):
            raise ValueError
    snapshot = broker.terminal_snapshot()
    if snapshot.status.levels_completed != transitions[-1].levels_completed:
        raise ValueError


def recover_trace_race(
    *, operator_root: Path, arc_root: Path, source_run_id: str
) -> Path:
    """Create a new sealed run after proving the one known append race."""

    return _recover(operator_root=operator_root, arc_root=arc_root,
                    source_run_id=source_run_id, kind="concurrent-trace-append")


def _recover(*, operator_root: Path, arc_root: Path, source_run_id: str, kind: str) -> Path:
    try:
        candidate = (_terminal_candidate if kind == "terminal-game-win" else _candidate)(operator_root, arc_root, source_run_id)
    except Exception:
        raise RecoveryError("recovery source is unavailable") from None
    return _materialize(operator_root=operator_root, arc_root=arc_root, source_run_id=source_run_id,
                        kind=kind, candidate=candidate)


def _register_terminal_rejection(arc_root: Path, run: Path, candidate: _Candidate, witness: object) -> None:
    """Account for this immutable non-authoritative source, never other new rows."""
    from asterion.applications.prime.p7 import solution_certificates as cert, solutions
    from asterion.applications.prime.p7.game import _read_catalog
    from asterion.applications.prime.p7.run_story.storage import write_atomic_file

    model = candidate.identities["model_id"]
    if type(witness) is not cert._ReplayWitness or candidate.source_identity is None:
        raise ValueError("recovery verification witness unavailable")
    source = candidate.source
    if cert._source_identity(source) != candidate.source_identity:
        raise ValueError("recovery source changed")
    evidence = solutions._read_one(arc_root, run, candidate.game.game_id, candidate.game.seed,
                                   None, model, strict_model=True)
    if evidence is None:
        raise ValueError("recovery evidence unavailable")
    prefix, receipt, _ = evidence
    if (prefix.transitions != witness.transitions or receipt != witness.receipt
            or prefix.observations != witness.observations
            or cert.capture_verification_identity(arc_root, prefix.game_id) != witness.verification_identity
            or solutions.recovery_source(run, cert._json(run / "summary.json"))[0] != source):
        raise ValueError("recovery verification witness stale")
    catalog = tuple(game for game in _read_catalog(arc_root) if game["game_id"] == prefix.game_id)
    registry = cert._safe(run.parent / "solution-certificates")
    with cert._safe(registry / "registry.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = cert._pointer(registry, prefix.game_id, model)
        pointer = cert._json(path)
        if (set(pointer) != {"schema", "game_id", "seed", "model_id", "winner", "eligible_sources", "rejected_sources"}
                or pointer["schema"] != cert._REGISTRY or pointer["game_id"] != prefix.game_id
                or pointer["seed"] != prefix.seed or pointer["model_id"] != model
                or type(pointer["eligible_sources"]) is not dict or type(pointer["rejected_sources"]) is not dict):
            raise ValueError("recovery registry unavailable")
        inventory, rejected = pointer["eligible_sources"], pointer["rejected_sources"]
        potential = set(cert._potential_sources(run.parent, catalog, model)[prefix.game_id])
        if (source.name in inventory or potential != set(inventory) | set(rejected) | {run.name} | ({source.name} if source.name in potential else set())):
            raise ValueError("recovery registry has unrelated changes")
        for descriptor in (*inventory.values(), *rejected.values()):
            if not cert._metadata_matches(run.parent, descriptor):
                raise ValueError("recovery registry has changed sources")
        winner_id = pointer["winner"]["source_run_id"]
        if winner_id not in inventory:
            raise ValueError("recovery registry winner unavailable")
        old_evidence = solutions._read_one(arc_root, run.parent / winner_id, prefix.game_id,
                                          prefix.seed, None, model, strict_model=True)
        if old_evidence is None:
            raise ValueError("recovery registry winner unavailable")
        old_prefix, old_receipt, _ = old_evidence
        cert._check_certificate(registry, old_prefix, old_receipt, cert._source_identity(run.parent / winner_id),
                                witness.verification_identity, model,
                                compatible_identities=cert.compatible_deployed_identities(arc_root, prefix.game_id))
        if solutions._read_one(arc_root, source, prefix.game_id, prefix.seed, None, model, strict_model=True) is not None:
            raise ValueError("original recovery source is authoritative")
        if source.name not in potential or source.name in rejected:
            return
        descriptor = cert._source_identity(source, descriptor=True)
        if descriptor["source_identity"] != candidate.source_identity:
            raise ValueError("recovery source changed")
        updated = {**pointer, "rejected_sources": {**rejected, source.name: descriptor}}
        encoded = cert._bytes(updated)
        if len(encoded) > cert._MAX_REGISTRY_BYTES:
            raise cert.SourceProvenanceCapacityError()
        if (cert._json(path) != pointer or cert._source_identity(source) != candidate.source_identity
                or cert.capture_verification_identity(arc_root, prefix.game_id) != witness.verification_identity):
            raise ValueError("recovery registry changed")
        write_atomic_file(path, encoded)


def _materialize(*, operator_root: Path, arc_root: Path, source_run_id: str,
                 kind: str, candidate: _Candidate) -> Path:
    from asterion.applications.prime.p7.solution_certificates import verify_for_save
    from asterion.applications.prime.p7.operator import _publish_save_certificate

    run_id = live.safe_run_id()
    private = live.private_root(operator_root, run_id)
    trace_root = private / "trace"
    trace_root.mkdir(mode=0o700)
    engine = None
    recorder = None
    try:
        engine = live.ArcadeEngine(
            arc_root=arc_root,
            recordings_dir=private / "recordings",
            game=candidate.game,
        )
        broker = ArcBroker(engine=engine, game=candidate.game)
        recorder = PrimeTraceRecorder(trace_root)
        identities = candidate.identities or trace_identities_for(
            declared_model_selection(
                {
                    **live._dotenv_values(operator_root / ".env"),
                    **os.environ,
                }
            ).model
        )
        evidence = P7PrivateTraceReceipt(broker, recorder, identities)
        recorder.append(
            "arc.recovery.source",
            identities,
            ({"recovery_kind": kind, **dict(candidate.composition)} if candidate.composition else {
                "source_run_id": source_run_id,
                "recovery_kind": kind,
                **dict(candidate.source_hashes),
            }),
        )
        _replay_into(broker, recorder, candidate.transitions, identities, candidate.observations)
        broker_receipt = broker.seal()
        if candidate.observations is None and broker_receipt != candidate.receipt:
            raise ValueError
        if candidate.observations is not None and any(getattr(broker_receipt, key) != getattr(candidate.receipt, key)
                for key in ("game_id", "seed", "primitive_actions", "levels_completed", "terminal_reason")):
            raise ValueError
        _, verification_witness = verify_for_save(
            arc_root, candidate.game, broker.journal, broker_receipt, broker.replay_observations,
            lambda: live.ArcadeEngine(
                arc_root=arc_root,
                recordings_dir=private / "replay-recordings",
                game=candidate.game,
            )
        )
        expected = evidence.expected_receipt_sha256(run_id=run_id)
        receipt = evidence.get_receipt(run_id=run_id, receipt_sha256=expected)
        analyze_trace(live.read_trace_entries(trace_root))
        engine.close()
        engine = None
        live.write_summary(
            operator_root,
            private,
            run_id=run_id,
            receipt=_receipt_mapping(receipt),
            broker_receipt=broker_receipt,
            game=candidate.game,
            replay_verified=True,
            sealed_trace=True,
            cleanup_complete=True,
            comparison_report=None,
            reason=None,
            failure=None,
            experiment=candidate.experiment,
            diagnostics={
                **dict(candidate.composition or {}),
                "recovered_from": source_run_id,
                "recovery_kind": kind,
                "execution_mode": "offline-replay",
                "source_runtime_status": "completed" if kind == "animation-replay" else "mixed" if candidate.composition else "failed",
                **({"source_receipt": dict(candidate.source_receipt)} if candidate.source_receipt is not None else {}),
                "restoration_actions": len(candidate.transitions),
                "new_solver_actions": 0,
                **({} if candidate.composition else {
                    "source_hashes": dict(candidate.source_hashes),
                    "source_usage_input_tokens": candidate.usage_input_tokens,
                    "source_usage_output_tokens": candidate.usage_output_tokens,
                    "usage_attributed_to_source": True,
                }),
                "worker_cell_count": 0,
                "model_call_count": 0,
            },
        )
        if kind == "terminal-game-win" and verification_witness is not None:
            _register_terminal_rejection(arc_root, private, candidate, verification_witness)
        _publish_save_certificate(
            arc_root, private, verification_witness,
            expected_model_id=identities["model_id"], eligible=True,
        )
        if kind == "terminal-game-win" and verification_witness is not None:
            status = json.loads((private / "solution-certification-status.json").read_text())
            if status.get("status") != "ready":
                raise ValueError("recovery certification pending")
        return private
    except Exception:
        if recorder is not None:
            try:
                recorder.close()
            except Exception:
                pass
        raise RecoveryError("recovery materialization failed") from None
    finally:
        if engine is not None:
            try:
                engine.close()
            except Exception:
                pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operator-root", required=True, type=Path)
    parser.add_argument("--arc-root", required=True, type=Path)
    parser.add_argument("--source-run", required=True)
    parser.add_argument("--kind", choices=("concurrent-trace-append", "terminal-game-win", "saved-route-composition", "animation-replay"), default="concurrent-trace-append")
    parser.add_argument("--suffix-run")
    parser.add_argument("--through-level", type=int)
    return parser


def main(arguments: list[str] | None = None) -> int:
    try:
        values = _parser().parse_args(arguments)
        if values.kind == "saved-route-composition":
            run = compose_saved_route(operator_root=values.operator_root, arc_root=values.arc_root,
                                      source_run_id=values.source_run, suffix_run_id=values.suffix_run,
                                      through_level=values.through_level)
        else:
            recover = recover_animation_replay if values.kind == "animation-replay" else recover_terminal_win if values.kind == "terminal-game-win" else recover_trace_race
            run = recover(operator_root=values.operator_root, arc_root=values.arc_root,
                          source_run_id=values.source_run)
        summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
        print(
            json.dumps(
                {
                    "actions": summary["broker"]["primitive_actions"],
                    "game_id": summary["broker"]["game_id"],
                    "level": summary["broker"]["levels_completed"],
                    "run_id": run.name,
                    "status": "recovered",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    except Exception:
        print('{"status":"recovery-unavailable"}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
