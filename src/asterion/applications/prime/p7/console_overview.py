"""Read-only fixed-roster scores from saved P7 evidence.

The small cache is a display optimization. It never authorizes execution or
imports game source; the operator replays an explicitly selected source.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import re
import threading
from asterion.agents.prime.trace import PrimeTraceEntry, PrimeTraceError, _entry_digest

from .game import P7GameSelection
from .live import read_trace_entries
from .private_trace import trace_identities_for
from .score import digest, partial_game_score, replay_sha256
from .solutions import (VerifiedPrefix, _partial_summary_matches, _prefix_values,
                        _summary_matches, _transitions, _truncate, load_resume_worldmap, source_experiment)

MODEL_ID = 'gpt-6.1-sol'
SEED = 0
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,159}\Z')
_MAX_FILE = 32 * 1024 * 1024


def _safe(path: Path) -> bool:
    return not any(part.is_symlink() for part in (path, *path.parents))


def _json(path: Path) -> dict:
    if not _safe(path) or not path.is_file() or path.stat().st_size > _MAX_FILE:
        raise ValueError
    value = json.loads(path.read_text(encoding='utf-8'))
    if type(value) is not dict:
        raise ValueError
    return value


def _count(value: object) -> int:
    return value if type(value) is int and 0 <= value <= 10**9 else 0


def _fingerprint(run: Path) -> tuple:
    paths = [run / 'summary.json', run / 'trace' / 'prime-trace.jsonl',
             run / 'trace' / 'prime-trace.seal.json']
    research = run / 'research'
    if _safe(research) and research.is_dir():
        for scope in sorted(research.iterdir()):
            if not _safe(scope) or not scope.is_dir():
                continue
            paths.append(scope / 'current.json')
            revisions = scope / 'revisions'
            if _safe(revisions) and revisions.is_dir():
                paths.extend(sorted(revisions.glob('*.json')))
    values = []
    for path in paths:
        try:
            if not _safe(path):
                values.append((str(path.relative_to(run)), 'symlink'))
                continue
            stat = path.stat()
            values.append((str(path.relative_to(run)), stat.st_size, stat.st_mtime_ns,
                           stat.st_ctime_ns, stat.st_ino))
        except OSError:
            values.append((str(path.relative_to(run)), None))
    return tuple(values)


def _recorded_entries(path: Path, *, strict: bool = False) -> tuple:
    """Read an intact journal prefix; strict mode rejects any corrupt complete row."""
    if not _safe(path) or path.stat().st_size > _MAX_FILE:
        return ()
    entries = []
    previous = None
    with path.open(encoding='utf-8') as handle:
        for _ in range(16384):
            raw = handle.readline(65537)
            if len(raw) > 65536:
                return () if strict else tuple(entries)
            if not raw or not raw.endswith('\n'):
                break
            try:
                row = json.loads(raw)
                if (set(row) != {'sequence', 'kind', 'identities', 'payload', 'previous_sha256', 'sha256'}
                        or type(row['sequence']) is not int or row['sequence'] != len(entries) + 1
                        or row['identities'] != trace_identities_for(MODEL_ID)
                        or row['previous_sha256'] != previous
                        or _entry_digest(row['sequence'], row['kind'], row['identities'],
                                         row['payload'], previous) != row['sha256']):
                    return () if strict else tuple(entries)
                entries.append(PrimeTraceEntry(**row))
                previous = row['sha256']
            except (TypeError, ValueError, KeyError, PrimeTraceError):
                return () if strict else tuple(entries)
        else:
            return () if strict else tuple(entries)
    return tuple(entries)


def _recorded_actions(path: Path) -> int:
    try:
        return len(_transitions(_recorded_entries(path)))
    except (TypeError, ValueError):
        return 0


def _observed_completed_levels(run: Path, game: dict) -> int:
    """Provisional game progress, never a saved route, score or resume grant."""
    try:
        entries = _recorded_entries(run / 'trace' / 'prime-trace.jsonl', strict=True)
        contexts = [entry for entry in entries if entry.kind == 'arc.run.context']
        if len(contexts) != 1 or not entries:
            return 0
        context = contexts[0].payload
        if (set(context) != {'run_id', 'game_id', 'model_id', 'seed', 'win_levels',
                             'target_level', 'restoration_actions', 'source_run_id'}
                or context['run_id'] != run.name or context['game_id'] != game['game_id']
                or context['model_id'] != MODEL_ID or type(context['seed']) is not int
                or context['seed'] != SEED or context['win_levels'] != game['win_levels']
                or type(context['win_levels']) is not int
                or type(context['target_level']) is not int
                or not 1 <= context['target_level'] <= game['win_levels']
                or type(context['restoration_actions']) is not int or context['restoration_actions'] < 0
                or not (context['source_run_id'] is None or
                        type(context['source_run_id']) is str and _ID.fullmatch(context['source_run_id']))):
            return 0
        before_context = entries[:entries.index(contexts[0])]
        restored = context['restoration_actions']
        source = context['source_run_id']
        if (len(before_context) != restored or any(entry.kind != 'arc.action' for entry in before_context)
                or restored == 0 and source is not None
                or restored > 0 and (source is None or source == run.name)):
            return 0
        transitions = _transitions(entries)
        if restored and not 0 < transitions[restored - 1].levels_completed < context['target_level']:
            return 0
        previous_hash, previous_level, completed = None, 0, 0
        for item in transitions:
            if (type(item.sequence) is not int or type(item.levels_completed) is not int
                    or not 0 <= item.levels_completed <= game['win_levels']
                    or item.levels_completed > previous_level + 1
                    or item.levels_completed < previous_level and item.action != 'RESET'
                    or item.action not in {'RESET', *(f'ACTION{i}' for i in range(1, 8))}
                    or any(type(value) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', value)
                           for value in (item.before_sha256, item.after_sha256))
                    or previous_hash is not None and item.before_sha256 != previous_hash):
                return 0
            if item.action == 'ACTION6':
                if (dict(item.data).keys() != {'x', 'y'} or
                        any(type(value) is not int or not 0 <= value <= 63 for _, value in item.data)):
                    return 0
            elif item.data:
                return 0
            previous_hash, previous_level = item.after_sha256, item.levels_completed
            completed = max(completed, item.levels_completed)
        return completed
    except (OSError, ValueError, TypeError, KeyError):
        return 0


class ConsoleOverview:
    def __init__(self, runs_root: Path, catalog: tuple[dict, ...]):
        self._runs = Path(runs_root)
        self._catalog = deepcopy(catalog)
        self._catalog_id = digest(self._catalog)
        self._cache: dict[str, tuple[tuple, dict | None]] = {}
        self._lock = threading.RLock()

    def _read_run(self, run: Path, games: dict[str, dict]) -> dict | None:
        try:
            summary = _json(run / 'summary.json')
            experiment = source_experiment(run, summary)
            if (summary.get('schema') != 'asterion.prime.p7-live-private-summary/v1'
                    or summary.get('run_id') != run.name or type(experiment) is not dict
                    or experiment.get('model') != MODEL_ID or type(experiment.get('seed')) is not int
                    or experiment['seed'] != SEED or experiment.get('prediction_variant') != 'verified'):
                return None
            game_id = experiment.get('game_id')
            if game_id not in games:
                return None
            game = games[game_id]
            if not self._has_current_worldmap(run, game):
                return None
            diagnostics = summary.get('diagnostics')
            diagnostics = diagnostics if type(diagnostics) is dict else {}
            broker = summary.get('broker')
            status = diagnostics.get('broker_status')
            status = status if type(status) is dict else broker if type(broker) is dict else {}
            # A partial summary's broker is None: count the whole diagnostic
            # journal, including unsuccessful actions after the saved prefix.
            actions = _count(status.get('primitive_actions'))
            restored = min(actions, _count(diagnostics.get('restoration_actions')))
            result = {'game_id': game_id, 'run_id': run.name, 'status': 'unverified',
                      'completed_levels': 0, 'primitive_actions': actions,
                      'restoration_actions': restored, 'new_solver_actions': actions - restored,
                      'verified': False, 'sealed_trace': False, 'route_actions': 0,
                      'score': '0.000000', 'resume_eligible': False,
                      'observed_completed_levels': _observed_completed_levels(run, game)}
            if diagnostics.get('recovery_kind') == 'terminal-game-win':
                result.update(recovery_kind='terminal-game-win',
                              recovered_from=diagnostics['recovered_from'],
                              execution_mode='offline-replay', source_runtime_status='failed')
            elif diagnostics.get('recovery_kind') == 'saved-route-composition':
                result.update(recovery_kind='saved-route-composition', execution_mode='offline-replay',
                              source_runtime_status='mixed',
                              route_sources=[{key: segment[key] for key in
                                              ('source_run_id', 'source_start_sequence', 'source_end_sequence',
                                               'destination_start_sequence', 'destination_end_sequence')}
                                             for segment in diagnostics['route_sources']])
            try:
                prefix = self._display_prefix(run, summary, game)
                if prefix is None:
                    return result
                result.update(verified=True, sealed_trace=True, completed_levels=prefix.levels_completed,
                              route_actions=len(prefix.transitions),
                              status='completed' if prefix.levels_completed == game['win_levels'] else 'partial')
                counts, previous = [], 0
                for level in range(1, prefix.levels_completed + 1):
                    end = next(item.sequence for item in prefix.transitions if item.levels_completed == level)
                    counts.append(end - previous)
                    previous = end
                # partial_game_score uses target_level to validate the supplied
                # counts; its denominator remains the entire catalog's win_levels.
                selection = P7GameSelection(game_id, SEED, game['win_levels'],
                                            tuple(game['baseline_actions']), game['win_levels'])
                result['score'] = partial_game_score(tuple(counts), replace(selection, target_level=len(counts)))
                result['resume_eligible'] = (prefix.levels_completed < game['win_levels']
                                             and load_resume_worldmap(run, prefix) is not None)
                return result
            except Exception:
                return result
        except (OSError, ValueError, TypeError, KeyError):
            return self._pending_run(run, games)

    def _pending_run(self, run: Path, games: dict[str, dict]) -> dict | None:
        # A missing summary is recording evidence, not proof that a process is
        # alive. Expose it separately without granting progress or resume.
        try:
            trace = run / 'trace' / 'prime-trace.jsonl'
            if not _safe(trace) or not trace.is_file():
                return None
            with trace.open(encoding='utf-8') as handle:
                first = json.loads(handle.readline(65537))
            if first.get('identities') != trace_identities_for(MODEL_ID):
                return None
            research = run / 'research'
            if not _safe(research):
                return None
            scopes = []
            for path in research.glob('*/current.json'):
                scope = _json(path).get('scope')
                if (type(scope) is dict and scope.get('run_id') == run.name
                        and scope.get('attempt_id') == run.name and type(scope.get('seed')) is int
                        and scope['seed'] == SEED and scope.get('game_id') in games
                        and scope.get('win_levels') == games[scope['game_id']]['win_levels']):
                    scopes.append(scope)
            if len(scopes) != 1 or not self._has_current_worldmap(run, games[scopes[0]['game_id']]):
                return None
            actions = _recorded_actions(trace)
            return {'game_id': scopes[0]['game_id'], 'run_id': run.name,
                    'status': 'unverified', 'recording': True, 'completed_levels': 0,
                    'primitive_actions': actions, 'restoration_actions': 0, 'new_solver_actions': 0,
                    'counts_pending': True,
                    'verified': False, 'sealed_trace': False, 'route_actions': 0,
                    'score': '0.000000', 'resume_eligible': False,
                    'observed_completed_levels': _observed_completed_levels(run, games[scopes[0]['game_id']])}
        except (OSError, ValueError, TypeError, KeyError):
            return None

    @staticmethod
    def _has_current_worldmap(run: Path, game: dict) -> bool:
        # This nominal identity is only a read-only scope key. Its empty route
        # grants no replay or progress authority. Current revision content,
        # digest and exact scope are validated by the existing prior reader.
        scope = VerifiedPrefix(game['game_id'], SEED, game['win_levels'], 0,
                               (), run.name, '')
        return load_resume_worldmap(run, scope) is not None

    @staticmethod
    def _display_prefix(run: Path, summary: dict, game: dict) -> VerifiedPrefix | None:
        if any(summary.get(key) is not True for key in ('replay_verified', 'sealed_trace', 'cleanup_complete')):
            return None
        trace = run / 'trace' / 'prime-trace.jsonl'
        if not _safe(trace) or not trace.is_file() or trace.stat().st_size > _MAX_FILE:
            return None
        entries = read_trace_entries(run / 'trace')
        if any(dict(entry.identities) != trace_identities_for(MODEL_ID) for entry in entries):
            return None
        seal = _json(run / 'trace' / 'prime-trace.seal.json')
        if (set(seal) != {'entry_count', 'final_sha256', 'sealed_at'}
                or seal['entry_count'] != len(entries) or seal['final_sha256'] != entries[-1].sha256
                or type(seal['sealed_at']) is not str):
            return None
        full = _transitions(entries)
        markers = [item for item in entries if item.kind in {'arc.run.completed', 'arc.run.partial'}]
        if len(markers) != 1:
            return None
        marker = markers[0]
        partial = marker.kind == 'arc.run.partial'
        evidence = marker.payload
        # Require explicit identity even for the historical completed format.
        if not {'game_id', 'seed', 'win_levels'} <= set(evidence):
            return None
        if (type(evidence.get('seed')) is not int or type(evidence.get('win_levels')) is not int):
            return None
        values = _prefix_values(evidence, game['game_id'], SEED, game['win_levels'], is_partial=partial)
        if values is None:
            return None
        levels, actions, terminal, recorded_digest = values
        if partial:
            if not _partial_summary_matches(summary, evidence):
                return None
            transitions = _truncate(full, levels)
        else:
            if not _summary_matches(summary, game['game_id'], SEED, game['win_levels'],
                                    levels, actions, terminal, recorded_digest):
                return None
            transitions = full
        if (len(transitions) != actions or not transitions
                or transitions[-1].levels_completed != levels
                or replay_sha256(transitions, terminal_reason=terminal) != recorded_digest):
            return None
        return VerifiedPrefix(game['game_id'], SEED, game['win_levels'], levels,
                              transitions, run.name, recorded_digest)

    def build(self, *, active_run_id: str | None = None) -> dict:
        with self._lock:
            return self._build(active_run_id)

    def _build(self, active_run_id: str | None) -> dict:
        games = {game['game_id']: game for game in self._catalog}
        grouped: dict[str, list[dict]] = {key: [] for key in games}
        seen = set()
        if _safe(self._runs) and self._runs.is_dir():
            for run in sorted(self._runs.iterdir(), key=lambda p: p.name, reverse=True):
                if not _ID.fullmatch(run.name) or not _safe(run) or not run.is_dir():
                    continue
                seen.add(run.name)
                key = _fingerprint(run)
                cached = self._cache.get(run.name)
                if cached is None or cached[0] != key:
                    cached = (key, self._read_run(run, games))
                    self._cache[run.name] = cached
                if cached[1] is not None:
                    item = deepcopy(cached[1])
                    if item['run_id'] == active_run_id:
                        item['status'] = 'running'
                    grouped[item.pop('game_id')].append(item)
        self._cache = {key: value for key, value in self._cache.items() if key in seen}
        output = []
        for game in self._catalog:
            attempts = grouped[game['game_id']]
            verified = sorted((item for item in attempts if item['verified']),
                              key=lambda item: (-item['completed_levels'], -Decimal(item['score']),
                                                item['route_actions'], item['run_id']))
            best = verified[0] if verified else None
            eligible = next((item for item in verified if item['resume_eligible']), None)
            active = next((item['run_id'] for item in attempts if item['status'] == 'running'), None)
            recording = next((item['run_id'] for item in attempts if item.get('recording') is True), None)
            def display_recency(item):
                # Opaque run IDs can use different time zones. Exporting an
                # old replay must not make it the latest attempt either.
                root = self._runs / item['run_id']
                path = root / 'summary.json'
                if not path.is_file():
                    path = root / 'trace' / 'prime-trace.jsonl'
                try:
                    updated = path.stat().st_mtime_ns if _safe(path) else 0
                except OSError:
                    updated = 0
                return updated, item['run_id']
            latest = max(attempts, key=display_recency)['run_id'] if attempts else None
            saved_levels = best['completed_levels'] if best else 0
            displayed_levels = max(saved_levels, *(item.get('observed_completed_levels', 0) for item in attempts), 0)
            output.append({'game_id': game['game_id'], 'alias': game['alias'], 'win_levels': game['win_levels'],
                           'completed_levels': saved_levels, 'display_completed_levels': displayed_levels,
                           'progress_pending': displayed_levels > saved_levels,
                           'score': best['score'] if best else '0.000000',
                           'status': 'running' if active else best['status'] if best else 'unverified' if attempts else 'unplayed',
                           'best_run_id': best['run_id'] if best else None,
                           'resume_run_id': eligible['run_id'] if eligible else None,
                           'active_run_id': active, 'recording_run_id': recording,
                           'latest_run_id': latest,
                           'route_actions': best['route_actions'] if best else 0,
                           'runs': attempts})
        total_score = sum((Decimal(game['score']) for game in output), Decimal(0)) / max(1, len(output))
        totals = {'score': format(total_score.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP), '.6f'),
                  'completed_games': sum(game['completed_levels'] == game['win_levels'] for game in output),
                  'total_games': len(output), 'completed_levels': sum(game['completed_levels'] for game in output),
                  'total_levels': sum(game['win_levels'] for game in output),
                  'display_completed_levels': sum(game['display_completed_levels'] for game in output),
                  'display_completed_games': sum(game['display_completed_levels'] == game['win_levels'] for game in output),
                  'saved_route_actions': sum(game['route_actions'] for game in output)}
        for key in ('primitive_actions', 'restoration_actions', 'new_solver_actions'):
            totals[key] = sum(run[key] for game in output for run in game['runs'])
        totals['actions_pending'] = sum(run['primitive_actions'] for game in output
                                         for run in game['runs'] if run.get('counts_pending'))
        return {'scope': {'model_id': MODEL_ID, 'seed': SEED, 'score_kind': 'saved-route-rhae',
                          'catalog_id': self._catalog_id, 'history_scope': 'worldmap-p7'}, 'totals': totals, 'games': output}
