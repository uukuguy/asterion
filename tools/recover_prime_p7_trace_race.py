#!/usr/bin/env python3
"""Replay an audited P7 trace race or terminal WIN into separate evidence."""

from __future__ import annotations

import argparse
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
from asterion.applications.prime.p7.broker import ArcBroker, ArcRunReceipt, ArcTransition
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
    source = _source_directory(operator_root, source_run_id)
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
    recordings = [_recording(source, group) for group in ("recordings", "replay-recordings")]
    if recordings[0][0] != recordings[1][0]:
        raise ValueError
    if recordings[0][0][-1].get("state") != "WIN" or recordings[0][0][-1].get("levels_completed") != game.win_levels:
        raise ValueError
    if _recorded_actions(recordings[0][0], game.game_id, game.win_levels) != tuple((t.action, t.data) for t in transitions):
        raise ValueError
    hashes["recording_sha256s"] = sorted(item[1] for item in recordings)
    with tempfile.TemporaryDirectory(prefix="asterion-p7-win-audit-") as directory:
        replay_arc_run(transitions, receipt, lambda: live.ArcadeEngine(arc_root=arc_root, recordings_dir=Path(directory), game=game), game=game)
    usage = [row["payload"] for row in rows if row["kind"] == "arc.usage.reported"]
    if any(type(item) is not dict or set(item) != {"input_tokens", "output_tokens"}
           or any(type(value) is not int or value < 0 for value in item.values()) for item in usage):
        raise ValueError
    # The replay itself performs no model execution. Source identity is preserved
    # explicitly, while its original experiment remains attributable to source.
    experiment = {"game_id": game.game_id, "seed": game.seed, "model": identities["model_id"],
                  "target_level": game.win_levels, "prediction_variant": "offline-replay"}
    return _Candidate(source, game, transitions, receipt, hashes,
                      sum(item["input_tokens"] for item in usage), sum(item["output_tokens"] for item in usage),
                      identities, experiment)


def recover_terminal_win(*, operator_root: Path, arc_root: Path, source_run_id: str) -> Path:
    """Independently replay a game WIN; the source model failure stays unchanged."""
    return _recover(operator_root=operator_root, arc_root=arc_root,
                    source_run_id=source_run_id, kind="terminal-game-win")


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
) -> None:
    client = _P7BrokerClient(broker, recorder, identities, variant="legacy")
    for expected in transitions:
        client.act([{"name": expected.action, "data": dict(expected.data)}], _trusted_prefix_replay=True)
        if broker.journal[-1] != expected:
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
            {
                "source_run_id": source_run_id,
                "recovery_kind": kind,
                **dict(candidate.source_hashes),
            },
        )
        _replay_into(broker, recorder, candidate.transitions, identities)
        broker_receipt = broker.seal()
        if broker_receipt != candidate.receipt:
            raise ValueError
        broker.replay(
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
                "recovered_from": source_run_id,
                "recovery_kind": kind,
                "execution_mode": "offline-replay",
                "source_runtime_status": "failed",
                "restoration_actions": len(candidate.transitions),
                "new_solver_actions": 0,
                "source_hashes": dict(candidate.source_hashes),
                "source_usage_input_tokens": candidate.usage_input_tokens,
                "source_usage_output_tokens": candidate.usage_output_tokens,
                "usage_attributed_to_source": True,
                "worker_cell_count": 0,
                "model_call_count": 0,
            },
        )
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
    parser.add_argument("--kind", choices=("concurrent-trace-append", "terminal-game-win"), default="concurrent-trace-append")
    return parser


def main(arguments: list[str] | None = None) -> int:
    try:
        values = _parser().parse_args(arguments)
        recover = recover_terminal_win if values.kind == "terminal-game-win" else recover_trace_race
        run = recover(
            operator_root=values.operator_root,
            arc_root=values.arc_root,
            source_run_id=values.source_run,
        )
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
