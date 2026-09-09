"""Fail-closed reader for one explicitly selected private P7 run."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

from asterion.agents.prime.trace import PrimeTraceEntry, validate_trace
from asterion.applications.prime.p7.broker import digest
from asterion.applications.prime.p7.score import P7_ACTION_CAP

from .model import ActionFact, FrameFact, ReasoningCellFact, RunEvidence, RunStoryError


_SUMMARY_KEYS = {
    "broker",
    "cleanup_complete",
    "comparison_report",
    "diagnostics",
    "failure",
    "reason",
    "receipt",
    "replay_verified",
    "run_id",
    "schema",
    "sealed_trace",
}
_DIGEST_KEYS = ("summary", "trace", "trace_seal", "recording", "worker_cells")


def _reject() -> None:
    raise RunStoryError("evidence-invalid")


def _regular_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        _reject()
    return path


def _json(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(_regular_file(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _reject()
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        _reject()
    return value


def _jsonl(path: Path) -> tuple[Mapping[str, object], ...]:
    try:
        lines = _regular_file(path).read_text(encoding="utf-8").splitlines()
        values = tuple(json.loads(line) for line in lines)
    except (OSError, UnicodeError, json.JSONDecodeError):
        _reject()
    if not values or any(not isinstance(value, Mapping) for value in values):
        _reject()
    return values  # type: ignore[return-value]


def _sha(path: Path) -> str:
    try:
        return "sha256:" + sha256(_regular_file(path).read_bytes()).hexdigest()
    except OSError:
        _reject()


def _integer(value: object, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or type(value) is not int or value < minimum:
        _reject()
    return value


def _text(value: object) -> str:
    if type(value) is not str or not value or "\x00" in value:
        _reject()
    return value


def _trace(path: Path, seal_path: Path) -> tuple[PrimeTraceEntry, ...]:
    raw_entries = _jsonl(path)
    try:
        entries = validate_trace(
            tuple(
                PrimeTraceEntry(
                    sequence=value["sequence"],  # type: ignore[arg-type]
                    kind=value["kind"],  # type: ignore[arg-type]
                    identities=value["identities"],  # type: ignore[arg-type]
                    payload=value["payload"],  # type: ignore[arg-type]
                    previous_sha256=value["previous_sha256"],  # type: ignore[arg-type]
                    sha256=value["sha256"],  # type: ignore[arg-type]
                )
                for value in raw_entries
                if set(value)
                == {
                    "identities",
                    "kind",
                    "payload",
                    "previous_sha256",
                    "sequence",
                    "sha256",
                }
            )
        )
    except Exception:
        _reject()
    if len(entries) != len(raw_entries):
        _reject()
    seal = _json(seal_path)
    if (
        set(seal) != {"entry_count", "final_sha256", "sealed_at"}
        or seal.get("entry_count") != len(entries)
        or seal.get("final_sha256") != entries[-1].sha256
        or type(seal.get("sealed_at")) is not str
    ):
        _reject()
    return entries


def _grids(value: object) -> tuple[tuple[tuple[int, ...], ...], ...]:
    if type(value) is not list or not value:
        _reject()
    grids: list[tuple[tuple[int, ...], ...]] = []
    for layer in value:
        if type(layer) is not list or len(layer) != 64:
            _reject()
        rows: list[tuple[int, ...]] = []
        for row in layer:
            if (
                type(row) is not list
                or len(row) != 64
                or any(type(cell) is not int or not 0 <= cell <= 255 for cell in row)
            ):
                _reject()
            rows.append(tuple(row))
        grids.append(tuple(rows))
    return tuple(grids)


def _available(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        _reject()
    names: list[str] = []
    for item in value:
        if isinstance(item, bool) or type(item) is not int or not 1 <= item <= 7:
            _reject()
        names.append(f"ACTION{item}")
    if tuple(sorted(set(names))) != tuple(names):
        _reject()
    return tuple(names)


@dataclass(frozen=True, slots=True)
class _RecordedObservation:
    action: str
    game_id: str
    timestamp: str
    state: str
    levels_completed: int
    grids: tuple[tuple[tuple[int, ...], ...], ...]
    observation_sha256: str


@dataclass(frozen=True, slots=True)
class _RecordedAction:
    name: str
    before_frame: int
    after_frame: int
    before_sha256: str
    after_sha256: str


def _recorded_observation(row: Mapping[str, object]) -> _RecordedObservation:
    if set(row) != {"timestamp", "data"} or not isinstance(row["data"], Mapping):
        _reject()
    data = row["data"]
    required = {
        "action_input",
        "available_actions",
        "frame",
        "full_reset",
        "game_id",
        "guid",
        "levels_completed",
        "state",
        "win_levels",
    }
    if set(data) != required or not isinstance(data["action_input"], Mapping):
        _reject()
    grids = _grids(data["frame"])
    levels = _integer(data["levels_completed"])
    state = _text(data["state"])
    available = _available(data["available_actions"])
    if _integer(data["win_levels"], minimum=1) != 7:
        _reject()
    timestamp = row["timestamp"]
    if type(timestamp) is not str or not timestamp:
        _reject()
    action_id = data["action_input"].get("id")
    if type(action_id) is not str:
        _reject()
    observation_sha = digest(
        {
            "available_actions": available,
            "frame": grids,
            "levels_completed": levels,
            "state": state,
            "win_levels": 7,
        }
    )
    return _RecordedObservation(
        action_id,
        _text(data["game_id"]),
        timestamp,
        state,
        levels,
        grids,
        observation_sha,
    )


def _recording(
    path: Path,
) -> tuple[str, tuple[FrameFact, ...], tuple[_RecordedAction, ...]]:
    rows = _jsonl(path)
    parsed = [_recorded_observation(row) for row in rows]
    game_ids = {observation.game_id for observation in parsed}
    if len(game_ids) != 1:
        _reject()
    retained: list[_RecordedObservation] = []
    for observation in parsed:
        if (
            observation.action == "RESET"
            and retained
            and retained[-1].observation_sha256 == observation.observation_sha256
        ):
            continue
        retained.append(observation)
    if not retained:
        _reject()
    actions: list[_RecordedAction] = []
    frames: list[FrameFact] = []
    previous: _RecordedObservation | None = None
    for observation_index, observation in enumerate(retained):
        first_frame = len(frames)
        for grid in observation.grids:
            frames.append(
                FrameFact(
                    len(frames),
                    observation.timestamp,
                    observation.state,
                    observation.levels_completed,
                    grid,
                    digest({"grid": grid}),
                )
            )
        if observation_index == 0:
            if observation.action != "RESET":
                _reject()
        else:
            if observation.action not in {
                f"ACTION{number}" for number in range(1, 8)
            }:
                _reject()
            assert previous is not None
            actions.append(
                _RecordedAction(
                    observation.action,
                    first_frame - 1,
                    len(frames) - 1,
                    previous.observation_sha256,
                    observation.observation_sha256,
                )
            )
        previous = observation
    return next(iter(game_ids)), tuple(frames), tuple(actions)


def _reasoning(path: Path) -> tuple[ReasoningCellFact, ...]:
    values = _jsonl(path)
    cells: list[ReasoningCellFact] = []
    required = {
        "cell_count",
        "code",
        "code_sha256",
        "is_error",
        "output",
        "output_sha256",
    }
    for index, value in enumerate(values, start=1):
        if (
            set(value) != required
            or _integer(value["cell_count"], minimum=1) != index
            or type(value["is_error"]) is not bool
            or type(value["code"]) is not str
            or type(value["output"]) is not str
        ):
            _reject()
        code_sha = _text(value["code_sha256"])
        output_sha = _text(value["output_sha256"])
        if len(code_sha) != 64 or len(output_sha) != 64:
            _reject()
        cells.append(ReasoningCellFact(index, value["is_error"], code_sha, output_sha))
    return tuple(cells)


def read_run_evidence(run_root: Path) -> RunEvidence:
    """Read and reconcile one explicit absolute private run directory."""

    if (
        not isinstance(run_root, Path)
        or not run_root.is_absolute()
        or run_root.is_symlink()
        or not run_root.is_dir()
    ):
        _reject()
    summary_path = run_root / "summary.json"
    trace_path = run_root / "trace" / "prime-trace.jsonl"
    seal_path = run_root / "trace" / "prime-trace.seal.json"
    worker_path = run_root / "worker-cells.jsonl"
    recordings = tuple((run_root / "recordings").glob("*/*.jsonl"))
    if len(recordings) != 1:
        _reject()
    recording_path = recordings[0]
    summary = _json(summary_path)
    if set(summary) != _SUMMARY_KEYS or summary.get("schema") != "asterion.prime.p7-live-private-summary/v1":
        _reject()
    trace = _trace(trace_path, seal_path)
    game_id, frames, recording_actions = _recording(recording_path)
    cells = _reasoning(worker_path)
    action_entries = tuple(entry for entry in trace if entry.kind == "arc.action")
    if len(action_entries) != len(recording_actions):
        _reject()
    actions: list[ActionFact] = []
    for index, (entry, recorded) in enumerate(
        zip(action_entries, recording_actions, strict=True), start=1
    ):
        payload = entry.payload
        if (
            set(payload)
            != {
                "action",
                "after_sha256",
                "before_sha256",
                "levels_completed",
                "sequence",
            }
            or payload.get("sequence") != index
            or payload.get("action") != recorded.name
            or payload.get("before_sha256") != recorded.before_sha256
            or payload.get("after_sha256") != recorded.after_sha256
        ):
            _reject()
        actions.append(
            ActionFact(
                index,
                recorded.name,
                recorded.before_frame,
                recorded.after_frame,
                recorded.before_sha256,
                recorded.after_sha256,
                _integer(payload["levels_completed"]),
            )
        )
    receipt = summary.get("receipt")
    broker = summary.get("broker")
    diagnostics = summary.get("diagnostics")
    if not all(isinstance(item, Mapping) for item in (receipt, broker, diagnostics)):
        _reject()
    assert isinstance(receipt, Mapping)
    assert isinstance(broker, Mapping)
    assert isinstance(diagnostics, Mapping)
    action_count = _integer(receipt.get("primitive_action_count"))
    levels = _integer(receipt.get("completed_level_count"))
    worker_count = _integer(diagnostics.get("worker_cell_count"))
    if action_count != len(actions) or levels != frames[-1].levels_completed or worker_count != len(cells):
        _reject()
    usage_entries = tuple(entry.payload for entry in trace if entry.kind == "arc.usage.reported")
    usage: Mapping[str, int] | None = None
    if usage_entries:
        input_total = 0
        output_total = 0
        for value in usage_entries:
            if set(value) != {"input_tokens", "output_tokens"}:
                _reject()
            input_total += _integer(value["input_tokens"])
            output_total += _integer(value["output_tokens"])
        usage = MappingProxyType(
            {"input_tokens": input_total, "output_tokens": output_total}
        )
    if summary.get("replay_verified") is not True or summary.get("sealed_trace") is not True:
        _reject()
    source_paths = (summary_path, trace_path, seal_path, recording_path, worker_path)
    source_digests = MappingProxyType(
        {name: _sha(path) for name, path in zip(_DIGEST_KEYS, source_paths, strict=True)}
    )
    identities = trace[0].identities
    return RunEvidence(
        run_id=_text(summary.get("run_id")),
        game_id=game_id,
        identities=identities,
        frames=frames,
        actions=tuple(actions),
        reasoning_cells=cells,
        score=_text(receipt.get("partial_game_score")),
        action_limit=P7_ACTION_CAP,
        levels_completed=levels,
        terminal_reason=_text(broker.get("terminal_reason")),
        verification="VERIFIED",
        replay_verified=True,
        sealed_trace=True,
        worker_cell_count=worker_count,
        usage=usage,
        source_digests=source_digests,
    )


__all__ = ("read_run_evidence",)
