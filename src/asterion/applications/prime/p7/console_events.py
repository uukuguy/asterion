"""Bounded application-owned public process events, independent of execution authority."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from threading import Lock

from .observation_state import ObservationState
from .score import digest

SCHEMA = 'asterion.prime.p7-console-event/v1'
SCHEMA_V2 = 'asterion.prime.p7-console-event/v2'
RESEARCH_KINDS = frozenset({'compute_task', 'model_revision', 'plan', 'feedback', 'run_control'})
_MAX_ROW_BYTES = 1100 * 1024
_MAX_FILE_BYTES = 32 * 1024 * 1024
_MAX_ROWS = 16384
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,159}\Z')
_HASH = re.compile(r'sha256:[0-9a-f]{64}\Z')
_PRIVATE = re.compile(r'(?:https?://|(?<![A-Za-z0-9])/[A-Za-z0-9_.~+-]+(?:/|(?=\s|[。；，]|$))|[A-Za-z]:\\|\b(?:Bearer\s+|sk-[A-Za-z0-9]|(?:[A-Za-z0-9]+[_ -])*api[_ -]?key\s*[:=]|(?:[A-Za-z0-9]+[_ -])*(?:password|authorization|token|secret)\s*[:=]))', re.I)


def public_text(value: object, limit: int = 600) -> str:
    if type(value) is not str or _PRIVATE.search(value):
        return ''
    return ' '.join(''.join(c for c in value if c >= ' ' and c != '\x7f').split())[:limit]


def public_narrative(value: object, limit: int = 8000) -> str:
    """Preserve readable cognition sections with the same redaction boundary."""
    if type(value) is not str or _PRIVATE.search(value):
        return ''
    lines = [' '.join(''.join(c for c in line if c >= ' ' and c != '\x7f').split())
             for line in value.splitlines()]
    return '\n'.join(lines).strip()[:limit].rstrip()


def _id(value: object) -> bool:
    return type(value) is str and _ID.fullmatch(value) is not None


def _int(value: object) -> bool:
    return type(value) is int and 0 <= value <= 10**9


def _hash(value: object) -> bool:
    return type(value) is str and _HASH.fullmatch(value) is not None


def _observation(value: object) -> bool:
    """Only actual bounded pixels and public game-state fields may be persisted."""
    if (type(value) is not dict
        or set(value) != {'frame', 'available_actions', 'state', 'levels_completed', 'win_levels'}
        or value['state'] not in ('NOT_STARTED', 'NOT_FINISHED', 'WIN', 'GAME_OVER')
        or not _int(value['win_levels']) or not 1 <= value['win_levels'] <= 100
        or not _int(value['levels_completed']) or value['levels_completed'] > value['win_levels']):
        return False
    actions, layers = value['available_actions'], value['frame']
    if (type(actions) is not list or len(actions) > 7
        or any(type(a) is not str or a not in {f'ACTION{i}' for i in range(1, 8)} for a in actions)
        or actions != sorted(set(actions)) or type(layers) is not list or not 1 <= len(layers) <= 64):
        return False
    shape = None
    for grid in layers:
        if type(grid) is not list or not 1 <= len(grid) <= 64:
            return False
        width = len(grid[0]) if type(grid[0]) is list else 0
        if not 1 <= width <= 64 or (shape is not None and shape != (len(grid), width)):
            return False
        shape = (len(grid), width)
        if any(type(row) is not list or len(row) != width
               or any(type(c) is not int or not 0 <= c <= 255 for c in row) for row in grid):
            return False
    return True


def _texts(value: object, *, count: int = 32, limit: int = 600) -> bool:
    return (type(value) is list and len(value) <= count
            and all(type(v) is str and len(v) <= limit and public_text(v, limit) == v for v in value))


def _optional_id(value: object) -> bool:
    return value is None or _id(value)


def _public_prose(value: object, limit: int = 600) -> bool:
    return type(value) is str and len(value) <= limit and public_narrative(value, limit) == value


def public_action_labels(value: object, *, latest: int) -> list[dict]:
    """Copy exact actor-authored labels with the public event privacy boundary."""
    from .research import action_labels
    result = action_labels(value, latest=latest)
    for item in result:
        if (not _public_prose(item['purpose'])
                or (item['label'] is not None and public_text(item['label'], 24) != item['label'])):
            raise ValueError('console event unavailable')
    return result


def _research_payload(kind: str, value: dict) -> bool:
    common = {'source_action_sequence', 'observation_sha256', 'level', 'workspace_revision', 'task_id', 'origin'}
    fields = {
        'compute_task': {'status', 'operation', 'goal', 'obstacles', 'question', 'summary', 'elapsed_ms', 'completed_units'},
        'model_revision': {'revision', 'parent_revision', 'description_zh', 'state_summary', 'rule_summaries', 'unknowns',
                           'coverage_summary', 'validation_summary', 'correction_summary', 'evidence_sequences'},
        'plan': {'plan_id', 'status', 'goal', 'assumptions', 'actions', 'applied_count', 'stop_reason'},
        'feedback': {'plan_id', 'expected_summary', 'actual_summary', 'mismatch_kind', 'unexecuted_count', 'counterexample_sequence'},
        'run_control': {'state', 'command_id', 'request_sequence', 'reason'},
    }
    optional = {'action_labels'} if kind == 'model_revision' else set()
    if (set(value) - optional != common | fields[kind] or not _int(value['source_action_sequence'])
        or not _hash(value['observation_sha256']) or not _int(value['level']) or value['level'] < 1
        or not _optional_id(value['workspace_revision']) or not _optional_id(value['task_id'])
        or value['origin'] not in {'actor', 'calculation', 'environment', 'operator'}):
        return False
    if kind == 'compute_task':
        return (value['status'] in {'declared', 'started', 'completed', 'failed', 'interrupted'}
                and value['operation'] in {'analyze', 'model', 'validate', 'search', 'probe', 'execute'}
                and all(_public_prose(value[k]) for k in ('goal', 'question', 'summary'))
                and _texts(value['obstacles']) and all(value[k] is None or _int(value[k]) for k in ('elapsed_ms', 'completed_units')))
    if kind == 'model_revision':
        if 'action_labels' in value:
            public_action_labels(value['action_labels'], latest=value['source_action_sequence'])
        return (_id(value['revision']) and _optional_id(value['parent_revision'])
                and _public_prose(value['description_zh'], 8000)
                and all(_public_prose(value[k]) for k in ('state_summary', 'coverage_summary', 'validation_summary', 'correction_summary'))
                and _texts(value['rule_summaries']) and _texts(value['unknowns'])
                and type(value['evidence_sequences']) is list and len(value['evidence_sequences']) <= 128
                and all(_int(v) and v <= value['source_action_sequence'] for v in value['evidence_sequences'])
                and value['evidence_sequences'] == sorted(set(value['evidence_sequences'])))
    if kind == 'plan':
        actions = value['actions']
        valid_actions = type(actions) is list and 1 <= len(actions) <= 20
        if valid_actions:
            for action in actions:
                if type(action) is not dict or set(action) != {'name', 'data'} or action['name'] not in {'RESET', *(f'ACTION{i}' for i in range(1, 8))}:
                    valid_actions = False
                    break
                data = action['data']
                if type(data) is not dict or not ((action['name'] != 'ACTION6' and data == {}) or (action['name'] == 'ACTION6' and set(data) == {'x', 'y'} and all(type(v) is int and 0 <= v <= 63 for v in data.values()))):
                    valid_actions = False
                    break
        return (_id(value['plan_id']) and value['status'] in {'proposed', 'executing', 'completed', 'stopped'}
                and _public_prose(value['goal']) and _texts(value['assumptions']) and valid_actions
                and _int(value['applied_count']) and value['applied_count'] <= len(actions)
                and (value['stop_reason'] is None or _public_prose(value['stop_reason'])))
    if kind == 'feedback':
        return (_id(value['plan_id']) and _public_prose(value['expected_summary']) and _public_prose(value['actual_summary'])
                and value['mismatch_kind'] in {'none', 'state', 'dynamics', 'goal', 'implementation', 'unknown'}
                and _int(value['unexecuted_count']) and value['unexecuted_count'] <= 20
                and (value['counterexample_sequence'] is None or (_int(value['counterexample_sequence']) and value['counterexample_sequence'] <= value['source_action_sequence'])))
    return (value['state'] in {'running', 'pause_requested', 'paused', 'stop_requested', 'stopping', 'stopped', 'cleanup_failed'}
            and _optional_id(value['command_id']) and _int(value['request_sequence'])
            and (value['reason'] is None or _public_prose(value['reason'])))


def _payload(kind: str, payload: Mapping[str, object]) -> dict:
    if not isinstance(payload, Mapping):
        raise ValueError('console event unavailable')
    value = dict(payload)
    if kind in RESEARCH_KINDS:
        try:
            valid = _research_payload(kind, value)
        except (TypeError, KeyError, ValueError):
            valid = False
    elif kind == 'decision':
        valid = (set(value) == {'decision_id', 'source_action_sequence', 'observation_sha256', 'goal', 'basis', 'expected'}
                 and _id(value.get('decision_id')) and _int(value.get('source_action_sequence'))
                 and _hash(value.get('observation_sha256')))
        for key in ('goal', 'basis', 'expected'):
            prose = value.get(key)
            valid = valid and type(prose) is str and bool(prose.strip()) and len(prose) <= 600 and public_text(prose) == prose
    elif kind == 'observation':
        valid = (set(value) == {'source_action_sequence', 'observation_sha256', 'observation'}
                 and _int(value.get('source_action_sequence')) and _hash(value.get('observation_sha256'))
                 and _observation(value.get('observation'))
                 and digest(ObservationState.from_observation(value['observation']).to_projection()) == value['observation_sha256'])
    elif kind == 'action':
        valid = (set(value) <= {'action', 'sequence', 'before_sha256', 'after_sha256', 'levels_completed', 'data', 'decision_id'}
                 and {'action', 'sequence', 'before_sha256', 'after_sha256', 'levels_completed', 'decision_id'} <= set(value)
                 and value.get('action') in {'RESET', *(f'ACTION{i}' for i in range(1, 8))}
                 and _int(value.get('sequence')) and value['sequence'] > 0
                 and _int(value.get('levels_completed')) and _hash(value.get('before_sha256')) and _hash(value.get('after_sha256'))
                 and (value.get('decision_id') is None or _id(value.get('decision_id'))))
        data = value.get('data', {})
        valid = valid and type(data) is dict and (data == {} or (value.get('action') == 'ACTION6' and set(data) == {'x', 'y'} and all(type(c) is int and 0 <= c <= 63 for c in data.values())))
    elif kind == 'cognition':
        valid = (set(value) == {'cognition_revision', 'source_action_sequence', 'observation_sha256', 'stable_description', 'cognition_narrative_zh', 'session'}
                 and _int(value.get('cognition_revision')) and _int(value.get('source_action_sequence')) and _hash(value.get('observation_sha256')))
        for key in ('stable_description', 'cognition_narrative_zh'):
            prose = value.get(key)
            valid = valid and type(prose) is str and len(prose) <= 8000 and public_narrative(prose, 8000) == prose
        session = value.get('session')
        valid = valid and type(session) is dict and set(session) <= {'state', 'episode', 'episode_actions'}
        if type(session) is dict:
            valid = valid and all((_id(v) if k == 'state' else _int(v)) for k, v in session.items())
    else:
        valid = False
    if not valid:
        raise ValueError('console event unavailable')
    return value


def read_console_events(run_root: Path, run_id: str, game_id: str | None, *, warnings: list[str] | None = None) -> list[dict]:
    """Read only complete, contiguous rows; reject identity disagreement."""
    if run_root.is_symlink():
        raise ValueError('console event unavailable')
    path = run_root.resolve() / 'console-events.jsonl'
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        return []
    rows = []

    def invalid() -> None:
        if warnings is not None:
            warnings.append('console-events-invalid')

    total_bytes = 0
    with path.open('rb') as stream:
        for _ in range(_MAX_ROWS):
            line = stream.readline(_MAX_ROW_BYTES + 1)
            total_bytes += len(line)
            if len(line) > _MAX_ROW_BYTES or total_bytes > _MAX_FILE_BYTES:
                invalid()
                break
            if not line or not line.endswith(b'\n'):
                break
            try:
                row = json.loads(line)
                if type(row) is not dict or set(row) != {'schema', 'run_id', 'game_id', 'sequence', 'kind', 'payload'}:
                    invalid()
                    break
                if row['run_id'] != run_id or (game_id is not None and row['game_id'] != game_id):
                    raise ValueError('console identity unavailable')
                if rows and row['game_id'] != rows[0]['game_id']:
                    raise ValueError('console identity unavailable')
                if row['schema'] not in {SCHEMA, SCHEMA_V2} or (row['schema'] == SCHEMA and row['kind'] in RESEARCH_KINDS) or not _id(row['game_id']) or type(row['sequence']) is not int or row['sequence'] != len(rows) + 1:
                    invalid()
                    break
                if type(row['payload']) is not dict:
                    invalid()
                    break
                row['payload'] = _payload(row['kind'], row['payload'])
            except (TypeError, KeyError, UnicodeError, RecursionError, json.JSONDecodeError):
                invalid()
                break
            except ValueError as error:
                if str(error) == 'console identity unavailable':
                    raise
                invalid()
                break
            rows.append(row)
    return rows


class ConsoleEventWriter:
    def __init__(self, run_root: Path, run_id: str, game_id: str):
        if not isinstance(run_root, Path) or not _id(run_id) or not _id(game_id) or run_root.name != run_id:
            raise ValueError('console event unavailable')
        self._root = run_root.resolve()
        self._run_id, self._game_id = run_id, game_id
        self._lock = Lock()
        path = self._root / 'console-events.jsonl'
        if path.exists() or path.is_symlink():
            raise ValueError('console event unavailable')
        self._sequence = 0
        self._bytes = 0

    def append(self, kind: str, payload: Mapping[str, object]) -> None:
        safe = _payload(kind, payload)
        with self._lock:
            row = {'schema': SCHEMA_V2 if kind in RESEARCH_KINDS else SCHEMA, 'run_id': self._run_id, 'game_id': self._game_id,
                   'sequence': self._sequence + 1, 'kind': kind, 'payload': safe}
            line = (json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode()
            if len(line) > _MAX_ROW_BYTES or self._sequence >= _MAX_ROWS or self._bytes + len(line) > _MAX_FILE_BYTES:
                raise ValueError('console event unavailable')
            path = self._root / 'console-events.jsonl'
            if path.is_symlink():
                raise ValueError('console event unavailable')
            with path.open('ab') as stream:
                stream.write(line)
                stream.flush()
            self._sequence += 1
            self._bytes += len(line)
