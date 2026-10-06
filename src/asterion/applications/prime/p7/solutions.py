"""Private, replay-verified P7 action prefixes suitable for reuse."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from collections.abc import Mapping
import json
from hashlib import sha256
from pathlib import Path
import re
import tempfile

from .broker import ArcObservation, ArcRunReceipt, ArcTransition, _snapshot_observation
from .game import GAME_ID_ENV, SEED_ENV, TARGET_LEVEL_ENV, P7GameSelection, resolve_game_selection
from .live import ArcadeEngine, read_trace_entries
from .private_trace import (
    are_p7_trace_identities,
    trace_identities_for,
)
from .replay import authenticate_observations, replay_arc_run
from .score import replay_sha256


_HISTORICAL_P7_TRACE_IDENTITIES = {
    "application_id": "prime.arc-agi-3-solving",
    "application_version": "1.0.0",
    "model_id": "deepseek-v4-flash",
    "reasoning_id": "asterion.prime",
    "runtime_id": "asterion.prime",
}
def _known_trace_identities(
    identities: object, expected_model_id: str | None
) -> bool:
    """Report whether one trace identity may be reused as a P7 prefix.

    Without an expected model this stays permissive so offline tooling can
    read runs produced by any operator selection. The runtime path names the
    model it resolved, so a trace from a different selection is rejected.
    """

    if not are_p7_trace_identities(identities):
        return False
    if expected_model_id is None:
        return True
    as_mapping = dict(identities)
    if as_mapping == trace_identities_for(expected_model_id):
        return True
    # Prefixes recorded before the model became selectable stay reusable.
    return as_mapping == _HISTORICAL_P7_TRACE_IDENTITIES


@dataclass(frozen=True, slots=True)
class VerifiedPrefix:
    game_id: str
    seed: int
    win_levels: int
    levels_completed: int
    transitions: tuple[ArcTransition, ...]
    source_run_id: str
    replay_sha256: str
    observations: tuple[ArcObservation, ...] | None = None


@dataclass(frozen=True, slots=True)
class VerifiedAttempt:
    """A sealed, replay-verified attempt that did not reach the target.

    Attempts are diagnostic exploration evidence.  They intentionally have a
    separate type from :class:`VerifiedPrefix`, so callers cannot accidentally
    use a failed route as an official or progress prefix.
    """

    game_id: str
    seed: int
    win_levels: int
    levels_completed: int
    transitions: tuple[ArcTransition, ...]
    source_run_id: str
    terminal_reason: str
    replay_sha256: str


def load_verified_attempt(
    arc_root: Path,
    runs_root: Path,
    game_id: str,
    seed: int,
    *,
    expected_model_id: str | None = None,
) -> VerifiedAttempt | None:
    """Load one exact, failed run as exploratory route evidence.

    Only a sealed failed trace with the complete action journal is accepted.
    A ``partial`` marker is accepted only when the trace also contains the
    complete failed route and a terminal broker status.  This loader never
    returns a ``VerifiedPrefix``; callers must opt into treating the result as
    a failed attempt explicitly.
    """

    candidates: list[VerifiedAttempt] = []
    try:
        if runs_root.is_symlink() or not runs_root.is_dir() or type(seed) is not int:
            return None
        for run in sorted(runs_root.iterdir(), key=lambda item: item.name):
            if run.is_symlink() or not run.is_dir():
                continue
            attempt = _load_attempt_one(
                arc_root, run, game_id, seed, expected_model_id
            )
            if attempt is not None:
                candidates.append(attempt)
    except OSError:
        return None
    if not candidates:
        return None
    return min(candidates, key=lambda value: (len(value.transitions), value.source_run_id))


def _fresh_engine(arc_root: Path, game: P7GameSelection, recordings: Path) -> object:
    return ArcadeEngine(arc_root=arc_root, recordings_dir=recordings, game=game)


def load_best_prefix(
    arc_root: Path,
    runs_root: Path,
    game_id: str,
    seed: int,
    *,
    max_level: int | None = None,
    expected_model_id: str | None = None,
) -> VerifiedPrefix | None:
    """Return the strongest sealed local prefix for one exact identity."""

    candidates: list[VerifiedPrefix] = []
    try:
        if runs_root.is_symlink() or not runs_root.is_dir() or type(seed) is not int:
            return None
        for run in sorted(runs_root.iterdir(), key=lambda item: item.name):
            if run.is_symlink() or not run.is_dir():
                continue
            prefix = _load_one(
                arc_root, run, game_id, seed, max_level, expected_model_id
            )
            if prefix is not None:
                candidates.append(prefix)
    except OSError:
        return None
    if not candidates:
        return None
    return min(candidates, key=lambda value: (-value.levels_completed, len(value.transitions), value.source_run_id))


def load_exact_prefix(
    arc_root: Path,
    runs_root: Path,
    source_run_id: str,
    game_id: str,
    seed: int,
    *,
    expected_model_id: str | None = None,
) -> VerifiedPrefix | None:
    """Replay only the explicitly selected sealed run; never choose a fallback."""

    try:
        if (
            type(source_run_id) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,159}", source_run_id) is None
            or type(seed) is not int
            or runs_root.is_symlink()
            or not runs_root.is_dir()
        ):
            return None
        run = runs_root / source_run_id
        if run.is_symlink() or not run.is_dir():
            return None
        return _load_one(
            arc_root, run, game_id, seed, None, expected_model_id,
            strict_model=True,
        )
    except (OSError, ValueError):
        return None


def recovery_source(run: Path, summary: Mapping[str, object]) -> tuple[Path, dict] | None:
    """Resolve one immutable original run behind an offline WIN replay.

    This grants only source attribution. Actual saved-solution authorization
    still requires the ordinary sealed-trace and SDK replay checks.
    """
    from asterion.agents.prime.trace import _entry_digest, _plain

    if isinstance(summary.get("diagnostics"), Mapping) and summary["diagnostics"].get("recovery_kind") == "animation-replay":
        from .animation_replay import recovery_source as animation_source
        return animation_source(run, summary)
    try:
        diagnostics = summary.get("diagnostics")
        if not isinstance(diagnostics, Mapping) or diagnostics.get("recovery_kind") != "terminal-game-win":
            return None
        source_id = diagnostics.get("recovered_from")
        if (type(source_id) is not str or re.fullmatch(r"p7-live-[0-9]{14}-[0-9a-f]{24}", source_id) is None
                or source_id == run.name or diagnostics.get("execution_mode") != "offline-replay"):
            return None
        source = _private_path(run.parent, source_id)
        summary_path = _private_path(source, "summary.json")
        trace_path = _private_path(source, "trace", "prime-trace.jsonl")
        hashes = diagnostics.get("source_hashes")
        if (type(hashes) is not dict or summary_path.stat().st_size > 1024 * 1024
                or trace_path.stat().st_size > 16 * 1024 * 1024
                or sha256(summary_path.read_bytes()).hexdigest() != hashes.get("summary_sha256")
                or sha256(trace_path.read_bytes()).hexdigest() != hashes.get("trace_sha256")):
            return None
        original = json.loads(summary_path.read_text(encoding="utf-8"))
        if type(original) is not dict:
            return None
        experiment = original.get("experiment")
        broker = original.get("broker")
        if (original.get("schema") != "asterion.prime.p7-live-private-summary/v1"
                or original.get("run_id") != source_id or original.get("cleanup_complete") is not True
                or original.get("replay_verified") is not True or type(original.get("failure")) is not dict
                or original.get("receipt") != {} or type(experiment) is not dict
                or type(broker) is not dict or broker != summary.get("broker")
                or broker.get("terminal_reason") != "game-won"
                or broker.get("levels_completed") != broker.get("win_levels")
                or experiment.get("game_id") != broker.get("game_id")
                or type(experiment.get("seed")) is not int or experiment["seed"] != broker.get("seed")):
            return None
        replay_experiment = summary.get("experiment")
        if (type(replay_experiment) is not dict
                or replay_experiment.get("prediction_variant") != "offline-replay"
                or type(replay_experiment.get("seed")) is not int
                or any(replay_experiment.get(key) != experiment.get(key) for key in ("game_id", "seed", "model"))
                or type(replay_experiment.get("target_level")) is not int
                or replay_experiment["target_level"] != broker.get("win_levels")):
            return None
        expected_hashes = {"summary_sha256", "trace_sha256", "recording_sha256s"}
        seal_path = source / "trace" / "prime-trace.seal.json"
        if original.get("sealed_trace") is True:
            expected_hashes.add("trace_seal_sha256")
            seal_path = _private_path(source, "trace", "prime-trace.seal.json")
            if sha256(seal_path.read_bytes()).hexdigest() != hashes.get("trace_seal_sha256"):
                return None
        elif original.get("sealed_trace") is not False or seal_path.exists() or seal_path.is_symlink():
            return None
        if set(hashes) != expected_hashes:
            return None
        recording_hashes = []
        for group in ("recordings", "replay-recordings"):
            recordings = _private_path(source, group)
            sessions = tuple(recordings.iterdir())
            if len(sessions) != 1:
                return None
            session = _private_path(source, group, sessions[0].name)
            files = tuple(session.glob("*.jsonl"))
            if len(files) != 1:
                return None
            recording = _private_path(source, group, session.name, files[0].name)
            recording_hashes.append(sha256(recording.read_bytes()).hexdigest())
        if sorted(recording_hashes) != hashes.get("recording_sha256s"):
            return None
        entries = read_trace_entries(_private_path(run, "trace"))
        identities = trace_identities_for(experiment["model"])
        if any(dict(entry.identities) != identities for entry in entries):
            return None
        markers = [entry.payload for entry in entries if entry.kind == "arc.recovery.source"]
        if len(markers) != 1 or _plain(markers[0]) != {"source_run_id": source_id, "recovery_kind": "terminal-game-win", **hashes}:
            return None
        previous = None
        original_actions = []
        for sequence, line in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), 1):
            row = json.loads(line)
            if (set(row) != {"sequence", "kind", "identities", "payload", "previous_sha256", "sha256"}
                    or type(row["sequence"]) is not int or row["sequence"] != sequence
                    or row["identities"] != identities or row["previous_sha256"] != previous
                    or row["sha256"] != _entry_digest(sequence, row["kind"], identities, row["payload"], previous)):
                return None
            previous = row["sha256"]
            if row["kind"] == "arc.action":
                original_actions.append(row["payload"])
        if not original_actions or original_actions != [dict(entry.payload) for entry in entries if entry.kind == "arc.action"]:
            return None
        return source, original
    except (OSError, ValueError, TypeError, KeyError):
        return None


def source_experiment(run: Path, summary: Mapping[str, object]) -> dict | None:
    """Return the checked solver experiment, including explicit replay lineage."""
    experiment = summary.get("experiment")
    if type(experiment) is not dict:
        return None
    diagnostics = summary.get("diagnostics")
    if isinstance(diagnostics, Mapping) and diagnostics.get("recovery_kind") == "saved-route-composition":
        from .route_composition import composition_sources
        sources = composition_sources(run, summary)
        return None if sources is None else sources[0][2]["experiment"]
    is_recovery = isinstance(diagnostics, Mapping) and diagnostics.get("recovery_kind") in {"terminal-game-win", "animation-replay"}
    if experiment.get("prediction_variant") != "offline-replay" and not is_recovery:
        return experiment
    recovered = recovery_source(run, summary)
    return None if recovered is None else recovered[1]["experiment"]


def load_resume_worldmap(run: Path, prefix: VerifiedPrefix) -> dict | None:
    """Read one exact revision as prose prior, without restoring its authority."""

    try:
        if (run / "summary.json").exists() or (run / "summary.json").is_symlink():
            summary_path = _private_path(run, "summary.json")
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            diagnostics = summary.get("diagnostics", {})
            if isinstance(diagnostics, Mapping) and diagnostics.get("recovery_kind") == "saved-route-composition":
                from .route_composition import composition_sources
                sources = composition_sources(run, summary)
                if sources is None or type(prefix) is not VerifiedPrefix or run.name != prefix.source_run_id:
                    return None
                _, source, _ = sources[-1]
                prior = _load_direct_resume_worldmap(source, replace(prefix, source_run_id=source.name))
                if prior is not None:
                    prior.update(recovered_run_id=run.name, route_sources=diagnostics["route_sources"])
                return prior
            if isinstance(diagnostics, Mapping) and diagnostics.get("recovery_kind") in {"terminal-game-win", "animation-replay"}:
                recovered = recovery_source(run, summary)
                if recovered is None or type(prefix) is not VerifiedPrefix or run.name != prefix.source_run_id:
                    return None
                source, _ = recovered
                prior = _load_direct_resume_worldmap(source, replace(prefix, source_run_id=source.name))
                if prior is not None:
                    prior["recovered_run_id"] = run.name
                return prior
        return _load_direct_resume_worldmap(run, prefix)
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _load_direct_resume_worldmap(run: Path, prefix: VerifiedPrefix) -> dict | None:
    from .research import worldmap
    from .score import digest

    try:
        if type(prefix) is not VerifiedPrefix or run.name != prefix.source_run_id:
            return None
        scope = {
            "game_id": prefix.game_id, "seed": prefix.seed,
            "win_levels": prefix.win_levels, "run_id": prefix.source_run_id,
            "attempt_id": prefix.source_run_id,
        }
        scope_id = digest(scope)[7:]
        current_path = _private_path(run, "research", scope_id, "current.json")
        if not current_path.is_file() or current_path.stat().st_size > 1024 * 1024:
            return None
        current = json.loads(current_path.read_text(encoding="utf-8"))
        if type(current) is not dict or set(current) != {"scope", "revision"} or current["scope"] != scope:
            return None
        revision = current["revision"]
        if type(revision) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", revision) is None:
            return None
        revision_path = _private_path(run, "research", scope_id, "revisions", revision[7:] + ".json")
        if not revision_path.is_file() or revision_path.stat().st_size > 1024 * 1024:
            return None
        snapshot = json.loads(revision_path.read_text(encoding="utf-8"))
        if type(snapshot) is not dict or snapshot.get("scope") != scope or digest(snapshot) != revision:
            return None
        return {
            "source_run_id": prefix.source_run_id, "source_revision": revision,
            "advisory_only": True, "requires_current_evidence": True,
            "worldmap": worldmap(snapshot["worldmap"]),
        }
    except (OSError, ValueError, TypeError, KeyError):
        return None


def list_verified_prefixes(
    arc_root: Path,
    runs_root: Path,
    game_ids: tuple[str, ...],
    seed: int,
    *,
    expected_model_id: str | None = None,
) -> tuple[VerifiedPrefix, ...]:
    """List one best verified prefix per selected exact game ID."""

    if type(game_ids) is not tuple or len(set(game_ids)) != len(game_ids):
        return ()
    return tuple(
        sorted(
            (
                prefix
                for game_id in game_ids
                if (
                    prefix := load_best_prefix(
                        arc_root,
                        runs_root,
                        game_id,
                        seed,
                        expected_model_id=expected_model_id,
                    )
                )
                is not None
            ),
            key=lambda value: value.game_id,
        )
    )


def _load_one(
    arc_root: Path, run: Path, expected_game_id: str, seed: int,
    max_level: int | None, expected_model_id: str | None = None, *, strict_model: bool = False,
) -> VerifiedPrefix | None:
    evidence = _read_one(arc_root, run, expected_game_id, seed, max_level,
                         expected_model_id, strict_model=strict_model)
    if evidence is None:
        return None
    prefix, receipt, game = evidence
    try:
        with tempfile.TemporaryDirectory(prefix="asterion-p7-prefix-") as directory:
            replay_arc_run(prefix.transitions, receipt,
                           lambda: _fresh_engine(arc_root, game, Path(directory)),
                           game=game, observations=prefix.observations)
        return prefix
    except Exception:
        return None


def _read_one(
    arc_root: Path,
    run: Path,
    expected_game_id: str,
    seed: int,
    max_level: int | None,
    expected_model_id: str | None = None,
    *,
    strict_model: bool = False,
) -> tuple[VerifiedPrefix, ArcRunReceipt, P7GameSelection] | None:
    """Read static admitted evidence; this alone grants no replay certification."""
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
        if not entries or not _known_trace_identities(
            entries[0].identities, expected_model_id
        ):
            return None
        if strict_model and expected_model_id is not None and dict(entries[0].identities) != trace_identities_for(expected_model_id):
            return None
        if any(entry.identities != entries[0].identities for entry in entries):
            return None
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
        observations = recorded_observations(run, transitions, recorded_game_id, win_levels)
        return (VerifiedPrefix(recorded_game_id, seed, win_levels, levels, transitions, run_id,
                               recorded_digest, observations), receipt, game)
    except Exception:
        return None


def prefix_rank(prefix: VerifiedPrefix, metadata: dict) -> tuple:
    """Keep official level/RHAE/action/source ordering independent of replay."""
    from .score import partial_game_score
    counts, previous = [], 0
    for level in range(1, prefix.levels_completed + 1):
        end = next(item.sequence for item in prefix.transitions if item.levels_completed == level)
        counts.append(end - previous)
        previous = end
    selection = P7GameSelection(prefix.game_id, prefix.seed, prefix.levels_completed,
                                tuple(metadata['baseline_actions']), metadata['win_levels'])
    return (-prefix.levels_completed, -Decimal(partial_game_score(tuple(counts), selection)),
            len(prefix.transitions), prefix.source_run_id)


def collect_roster_candidates(arc_root: Path, runs_root: Path, catalog: tuple[dict, ...],
                              *, expected_model_id: str) -> dict[str, list[VerifiedPrefix]]:
    """Bounded static native-WorldMap admission, with no SDK execution."""
    if runs_root.is_symlink() or not runs_root.is_dir():
        raise ValueError('solution registry unavailable')
    children = sorted(runs_root.iterdir(), key=lambda path: path.name)
    if len(children) > 4096:
        raise ValueError('solution registry unavailable')
    metadata = {game['game_id']: game for game in catalog}
    candidates = {game: [] for game in metadata}
    for run in children:
        try:
            path = run / 'summary.json'
            if (run.is_symlink() or not run.is_dir() or path.is_symlink()
                    or not path.is_file() or path.stat().st_size > 1024 * 1024):
                continue
            summary = json.loads(path.read_text())
            experiment = source_experiment(run, summary) if type(summary) is dict else None
            if (type(experiment) is not dict or summary.get('run_id') != run.name
                    or experiment.get('model') != expected_model_id
                    or type(experiment.get('seed')) is not int or experiment['seed'] != 0
                    or experiment.get('prediction_variant') != 'verified'):
                continue
            game_id = experiment.get('game_id')
            if type(game_id) is not str or game_id not in metadata:
                continue
            scope = VerifiedPrefix(game_id, 0, metadata[game_id]['win_levels'], 0, (), run.name, '')
            if load_resume_worldmap(run, scope) is None:
                continue
            evidence = _read_one(arc_root, run, game_id, 0, None, expected_model_id, strict_model=True)
            if evidence is not None:
                candidates[game_id].append(evidence[0])
        except (OSError, ValueError, TypeError, KeyError):
            continue
    for game_id, values in candidates.items():
        values.sort(key=lambda prefix: prefix_rank(prefix, metadata[game_id]))
    return candidates


def _load_attempt_one(
    arc_root: Path,
    run: Path,
    expected_game_id: str,
    seed: int,
    expected_model_id: str | None = None,
) -> VerifiedAttempt | None:
    """Validate a complete failed trace without promoting its progress."""

    try:
        summary_path = _private_path(run, "summary.json")
        trace_root = _private_path(run, "trace")
        trace_path = _private_path(run, "trace", "prime-trace.jsonl")
        seal_path = _private_path(run, "trace", "prime-trace.seal.json")
        if not all(path.is_file() for path in (summary_path, trace_path, seal_path)):
            return None
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if (
            type(summary) is not dict
            or summary.get("schema") != "asterion.prime.p7-live-private-summary/v1"
            or summary.get("replay_verified") is not True
            or summary.get("sealed_trace") is not True
            or summary.get("cleanup_complete") is not True
            or summary.get("run_id") != run.name
        ):
            return None
        entries = read_trace_entries(trace_root)
        if not entries or not _known_trace_identities(
            entries[0].identities, expected_model_id
        ):
            return None
        if any(entry.identities != entries[0].identities for entry in entries):
            return None
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        if (
            type(seal) is not dict
            or set(seal) != {"entry_count", "final_sha256", "sealed_at"}
            or seal.get("entry_count") != len(entries)
            or seal.get("final_sha256") != entries[-1].sha256
            or type(seal.get("sealed_at")) is not str
        ):
            return None
        failed = tuple(entry.payload for entry in entries if entry.kind == "arc.run.failed")
        partial = tuple(entry.payload for entry in entries if entry.kind == "arc.run.partial")
        if len(failed) + len(partial) != 1 or any(
            entry.kind == "arc.run.completed" for entry in entries
        ):
            return None
        is_partial = bool(partial)
        evidence = failed[0] if failed else partial[0]
        if not isinstance(evidence, Mapping):
            return None
        required = {
            "game_id", "seed", "win_levels", "levels_completed",
            "primitive_actions", "replay_sha256", "terminal_reason",
        }
        if is_partial:
            values = _prefix_values(
                evidence, expected_game_id, seed, evidence.get("win_levels"), is_partial=True
            ) if type(evidence.get("win_levels")) is int else None
            if values is None or not _partial_summary_matches(summary, evidence):
                return None
            # A partial marker describes the completed prefix.  The complete
            # failed route's terminal receipt is carried by diagnostics.
            diagnostics = summary.get("diagnostics")
            broker_status = diagnostics.get("broker_status") if type(diagnostics) is dict else None
            terminal = (
                broker_status.get("terminal_reason")
                if type(broker_status) is dict else summary.get("terminal_reason")
            )
            if type(terminal) is not str or terminal not in {"action-cap", "game-over", "human-baseline", "interrupted"}:
                return None
        elif set(evidence) != required:
            return None
        if (
            evidence.get("game_id") != expected_game_id
            or evidence.get("seed") != seed
            or type(evidence.get("win_levels")) is not int
        ):
            return None
        win_levels = evidence["win_levels"]
        levels = evidence["levels_completed"]
        actions = evidence["primitive_actions"]
        if not is_partial:
            terminal = evidence["terminal_reason"]
            digest = evidence["replay_sha256"]
        else:
            digest = ""
        if (
            type(levels) is not int
            or not 0 <= levels < win_levels
            or type(actions) is not int
            or actions < 1
            or type(terminal) is not str
            or terminal not in {"action-cap", "game-over", "human-baseline", "interrupted"}
            or (not is_partial and type(digest) is not str)
        ):
            return None
        transitions = _transitions(entries)
        if is_partial:
            actions = len(transitions)
            levels = max(item.levels_completed for item in transitions)
            digest = replay_sha256(transitions, terminal_reason=terminal)
            if levels >= win_levels:
                return None
        if len(transitions) != actions:
            return None
        if any(item.levels_completed > levels for item in transitions):
            return None
        identity = _recording_identity(run, transitions)
        if identity != (expected_game_id, win_levels):
            return None
        if replay_sha256(transitions, terminal_reason=terminal) != digest:
            return None
        game = resolve_game_selection(
            {
                GAME_ID_ENV: expected_game_id,
                SEED_ENV: str(seed),
                TARGET_LEVEL_ENV: str(win_levels),
            },
            arc_root,
        )
        if game.win_levels != win_levels or game.target_level != win_levels:
            return None
        if terminal == "human-baseline":
            game = replace(game, action_cap_override=actions)
        receipt = ArcRunReceipt(
            expected_game_id, seed, actions, levels, terminal, digest
        )
        with tempfile.TemporaryDirectory(prefix="asterion-p7-attempt-") as directory:
            replay_arc_run(
                transitions,
                receipt,
                lambda: _fresh_engine(arc_root, game, Path(directory)),
                game=game,
                observations=recorded_observations(run, transitions, expected_game_id, win_levels),
            )
        return VerifiedAttempt(
            expected_game_id,
            seed,
            win_levels,
            levels,
            transitions,
            run.name,
            terminal,
            digest,
        )
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


def recorded_observations(
    run: Path, transitions: tuple[ArcTransition, ...], game_id: str, win_levels: int,
) -> tuple[ArcObservation, ...] | None:
    """Authenticate SDK animation witnesses; absent legacy frames stay strict."""
    root = _private_path(run, "recordings")
    sessions = tuple(root.iterdir())
    if len(sessions) != 1:
        raise ValueError
    session = _private_path(run, "recordings", sessions[0].name)
    paths = tuple(session.glob("*.jsonl"))
    if len(paths) != 1:
        raise ValueError
    path = _private_path(run, "recordings", session.name, paths[0].name)
    rows = [json.loads(line)["data"] for line in path.read_text(encoding="utf-8").splitlines()]
    # Some historical fixtures/recordings retained action identities only.
    # They cannot authorize animation equivalence and use strict replay.
    if not any("frame" in row for row in rows):
        return None
    start = 0
    while start < len(rows) and rows[start]["action_input"]["id"] == "RESET":
        start += 1
    if start == 0 or len(rows) - start < len(transitions):
        raise ValueError
    selected = rows[start - 1:start + len(transitions)]
    values = []
    for index, row in enumerate(selected):
        if row.get("game_id") != game_id or row.get("win_levels") != win_levels:
            raise ValueError
        if index:
            action = row["action_input"]
            expected = transitions[index - 1]
            if action["id"] != expected.action or action["data"] != dict(expected.data):
                raise ValueError
        values.append(_snapshot_observation(row, win_levels=win_levels))
    return authenticate_observations(transitions, tuple(values))


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


__all__ = (
    "VerifiedAttempt",
    "VerifiedPrefix",
    "list_verified_prefixes",
    "load_best_prefix",
    "load_exact_prefix",
    "load_resume_worldmap",
    "load_verified_attempt",
)
