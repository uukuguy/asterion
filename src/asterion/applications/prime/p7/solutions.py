"""Private, replay-verified P7 action prefixes suitable for reuse."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
import json
from pathlib import Path
import tempfile

from .broker import ArcRunReceipt, ArcTransition
from .game import GAME_ID_ENV, SEED_ENV, TARGET_LEVEL_ENV, P7GameSelection, resolve_game_selection
from .live import ArcadeEngine, read_trace_entries
from .replay import replay_arc_run
from .score import replay_sha256


@dataclass(frozen=True, slots=True)
class VerifiedPrefix:
    game_id: str
    seed: int
    win_levels: int
    levels_completed: int
    transitions: tuple[ArcTransition, ...]
    source_run_id: str
    replay_sha256: str


def _fresh_engine(arc_root: Path, game: P7GameSelection, recordings: Path) -> object:
    return ArcadeEngine(arc_root=arc_root, recordings_dir=recordings, game=game)


def load_best_prefix(
    arc_root: Path,
    runs_root: Path,
    game_id: str,
    seed: int,
    *,
    max_level: int | None = None,
) -> VerifiedPrefix | None:
    """Return the strongest sealed local prefix for one exact identity."""

    candidates: list[VerifiedPrefix] = []
    try:
        if runs_root.is_symlink() or not runs_root.is_dir() or type(seed) is not int:
            return None
        for run in sorted(runs_root.iterdir(), key=lambda item: item.name):
            if run.is_symlink() or not run.is_dir():
                continue
            prefix = _load_one(arc_root, run, game_id, seed, max_level)
            if prefix is not None:
                candidates.append(prefix)
    except OSError:
        return None
    if not candidates:
        return None
    return min(candidates, key=lambda value: (-value.levels_completed, len(value.transitions), value.source_run_id))


def list_verified_prefixes(
    arc_root: Path, runs_root: Path, game_ids: tuple[str, ...], seed: int
) -> tuple[VerifiedPrefix, ...]:
    """List one best verified prefix per selected exact game ID."""

    if type(game_ids) is not tuple or len(set(game_ids)) != len(game_ids):
        return ()
    return tuple(
        sorted(
            (prefix for game_id in game_ids if (prefix := load_best_prefix(arc_root, runs_root, game_id, seed)) is not None),
            key=lambda value: value.game_id,
        )
    )


def _load_one(arc_root: Path, run: Path, expected_game_id: str, seed: int, max_level: int | None) -> VerifiedPrefix | None:
    try:
        summary_path = _private_path(run, "summary.json")
        trace_root = _private_path(run, "trace")
        trace_path = _private_path(run, "trace", "prime-trace.jsonl")
        seal_path = _private_path(run, "trace", "prime-trace.seal.json")
        if not all(path.is_file() for path in (summary_path, trace_path, seal_path)):
            return None
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if type(summary) is not dict or summary.get("schema") != "asterion.prime.p7-live-private-summary/v1":
            return None
        if (
            summary.get("replay_verified") is not True
            or summary.get("sealed_trace") is not True
            or summary.get("cleanup_complete") is not True
        ):
            return None
        run_id = summary.get("run_id")
        if type(run_id) is not str or run_id != run.name:
            return None
        entries = read_trace_entries(trace_root)
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        if (
            type(seal) is not dict or set(seal) != {"entry_count", "final_sha256", "sealed_at"}
            or seal.get("entry_count") != len(entries) or seal.get("final_sha256") != entries[-1].sha256
            or type(seal.get("sealed_at")) is not str
        ):
            return None
        transitions = _transitions(entries)
        completed = tuple(entry.payload for entry in entries if entry.kind == "arc.run.completed")
        partial = tuple(entry.payload for entry in entries if entry.kind == "arc.run.partial")
        if (len(completed), len(partial)) not in {(1, 0), (0, 1)}:
            return None
        is_partial = bool(partial)
        evidence = partial[0] if is_partial else completed[0]
        if not isinstance(evidence, Mapping):
            return None
        identity = _recording_identity(run, transitions)
        if identity is None:
            return None
        recorded_game_id, win_levels = identity
        if recorded_game_id != expected_game_id:
            return None
        values = _prefix_values(
            evidence, recorded_game_id, seed, win_levels, is_partial=is_partial
        )
        if values is None:
            return None
        levels, actions, terminal, recorded_digest = values
        if is_partial:
            if not _partial_summary_matches(summary, evidence):
                return None
            transitions = _truncate(transitions, levels)
            if len(transitions) != actions or not transitions:
                return None
            if replay_sha256(transitions, terminal_reason=terminal) != recorded_digest:
                return None
        else:
            if actions != len(transitions) or replay_sha256(transitions, terminal_reason=terminal) != recorded_digest:
                return None
            if not _summary_matches(summary, recorded_game_id, seed, win_levels, levels, actions, terminal, recorded_digest):
                return None
        if max_level is not None:
            if type(max_level) is not int or max_level < 1:
                return None
            levels = min(levels, max_level)
            transitions = _truncate(transitions, levels)
            if not transitions:
                return None
            terminal = "level-completed"
            recorded_digest = replay_sha256(transitions, terminal_reason=terminal)
        game = resolve_game_selection({GAME_ID_ENV: recorded_game_id, SEED_ENV: str(seed), TARGET_LEVEL_ENV: str(levels)}, arc_root)
        if game.win_levels != win_levels:
            return None
        receipt = ArcRunReceipt(recorded_game_id, seed, len(transitions), levels, terminal, recorded_digest)
        with tempfile.TemporaryDirectory(prefix="asterion-p7-prefix-") as directory:
            replay_arc_run(transitions, receipt, lambda: _fresh_engine(arc_root, game, Path(directory)), game=game)
        return VerifiedPrefix(recorded_game_id, seed, win_levels, levels, transitions, run_id, recorded_digest)
    except Exception:
        return None


def _transitions(entries: tuple[object, ...]) -> tuple[ArcTransition, ...]:
    values: list[ArcTransition] = []
    for entry in entries:
        if getattr(entry, "kind", None) != "arc.action":
            continue
        payload = entry.payload
        if set(payload) not in ({"action", "after_sha256", "before_sha256", "levels_completed", "sequence"}, {"action", "after_sha256", "before_sha256", "levels_completed", "sequence", "data"}):
            raise ValueError
        data = payload.get("data", {})
        if not isinstance(data, Mapping):
            raise ValueError
        transition = ArcTransition(payload["sequence"], payload["action"], payload["before_sha256"], payload["after_sha256"], payload["levels_completed"], tuple(data.items()))
        if transition.sequence != len(values) + 1:
            raise ValueError
        values.append(transition)
    if not values:
        raise ValueError
    return tuple(values)


def _recording_identity(run: Path, transitions: tuple[ArcTransition, ...]) -> tuple[str, int] | None:
    recordings_root = _private_path(run, "recordings")
    sessions = tuple(recordings_root.iterdir())
    if len(sessions) != 1:
        return None
    session = _private_path(run, "recordings", sessions[0].name)
    if not session.is_dir():
        return None
    recordings = tuple(session.glob("*.jsonl"))
    if len(recordings) != 1 or recordings[0].is_symlink() or not recordings[0].is_file():
        return None
    _private_path(run, "recordings", session.name, recordings[0].name)
    rows = [json.loads(row) for row in recordings[0].read_text(encoding="utf-8").splitlines()]
    data = [row.get("data") for row in rows if type(row) is dict and type(row.get("data")) is dict]
    if not data or type(data[0].get("game_id")) is not str or type(data[0].get("win_levels")) is not int:
        return None
    game_id, win_levels = data[0]["game_id"], data[0]["win_levels"]
    actions = []
    started = False
    for item in data:
        action = item.get("action_input")
        if type(action) is not dict or type(action.get("id")) is not str or type(action.get("data")) is not dict:
            return None
        name, action_data = action["id"], tuple(action["data"].items())
        if name == "RESET" and not started:
            if action_data:
                return None
            continue
        started = True
        actions.append((name, action_data))
    if tuple((item.action, item.data) for item in transitions) != tuple(actions):
        return None
    return game_id, win_levels


def _private_path(run: Path, *parts: str) -> Path:
    """Resolve one evidence component without traversing symlinks or escaping run."""

    root = run.resolve(strict=True)
    if run.is_symlink() or not root.is_dir():
        raise ValueError
    path = run
    for part in parts:
        if not part or Path(part).name != part:
            raise ValueError
        path = path / part
        if path.is_symlink():
            raise ValueError
    if not path.resolve(strict=True).is_relative_to(root):
        raise ValueError
    return path


def _truncate(transitions: tuple[ArcTransition, ...], level: int) -> tuple[ArcTransition, ...]:
    for index, transition in enumerate(transitions, start=1):
        if transition.levels_completed == level:
            return transitions[:index]
    return ()


def _prefix_values(
    value: Mapping[object, object], game_id: str, seed: int, win_levels: int, *, is_partial: bool
) -> tuple[int, int, str, str] | None:
    """Validate a strict partial marker or either completed marker format."""

    result_fields = {
        "levels_completed",
        "primitive_actions",
        "replay_sha256",
        "terminal_reason",
    }
    identity_fields = {"game_id", "seed", "win_levels"}
    fields = set(value)
    has_identity = fields == result_fields | identity_fields
    if not has_identity and (is_partial or fields != result_fields):
        return None
    if has_identity and (
        value["game_id"] != game_id
        or value["seed"] != seed
        or value["win_levels"] != win_levels
    ):
        return None
    levels, actions = value["levels_completed"], value["primitive_actions"]
    terminal, digest = value["terminal_reason"], value["replay_sha256"]
    if (
        type(levels) is not int
        or type(actions) is not int
        or type(terminal) is not str
        or type(digest) is not str
        or not 1 <= levels <= win_levels
        or actions < 1
        or (is_partial and terminal != "level-completed")
    ):
        return None
    return levels, actions, terminal, digest


def _summary_matches(summary: dict[object, object], game_id: str, seed: int, win_levels: int, levels: int, actions: int, terminal: str, digest: str) -> bool:
    broker, receipt = summary.get("broker"), summary.get("receipt")
    if type(broker) is not dict or type(receipt) is not dict:
        return False
    for key, value in (("levels_completed", levels), ("primitive_actions", actions), ("terminal_reason", terminal), ("replay_sha256", digest)):
        if broker.get(key) != value:
            return False
    for key, value in (("completed_level_count", levels), ("primitive_action_count", actions)):
        if receipt.get(key) != value:
            return False
    return all(broker.get(key, value) == value for key, value in (("game_id", game_id), ("seed", seed), ("win_levels", win_levels)))


def _partial_summary_matches(summary: dict[object, object], evidence: Mapping[object, object]) -> bool:
    """Require failure evidence to independently repeat the sealed prefix."""

    return (
        summary.get("completed_prefix") == dict(evidence)
        and summary.get("receipt") == {}
        and type(summary.get("failure")) is dict
        and bool(summary["failure"])
    )


__all__ = ("VerifiedPrefix", "list_verified_prefixes", "load_best_prefix")
