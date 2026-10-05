"""Bounded application-owned public process events, independent of execution authority."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from threading import Lock

SCHEMA = 'asterion.prime.p7-console-event/v1'
_MAX_ROW_BYTES = 48 * 1024
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


def _payload(kind: str, payload: Mapping[str, object]) -> dict:
    if not isinstance(payload, Mapping):
        raise ValueError('console event unavailable')
    value = dict(payload)
    if kind == 'decision':
        valid = (set(value) == {'decision_id', 'source_action_sequence', 'observation_sha256', 'goal', 'basis', 'expected'}
                 and _id(value.get('decision_id')) and _int(value.get('source_action_sequence'))
                 and _hash(value.get('observation_sha256')))
        for key in ('goal', 'basis', 'expected'):
            prose = value.get(key)
            valid = valid and type(prose) is str and bool(prose.strip()) and len(prose) <= 600 and public_text(prose) == prose
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

    with path.open('rb') as stream:
        for _ in range(_MAX_ROWS):
            line = stream.readline(_MAX_ROW_BYTES + 1)
            if len(line) > _MAX_ROW_BYTES:
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
                if row['schema'] != SCHEMA or not _id(row['game_id']) or type(row['sequence']) is not int or row['sequence'] != len(rows) + 1:
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

    def append(self, kind: str, payload: Mapping[str, object]) -> None:
        safe = _payload(kind, payload)
        with self._lock:
            row = {'schema': SCHEMA, 'run_id': self._run_id, 'game_id': self._game_id,
                   'sequence': self._sequence + 1, 'kind': kind, 'payload': safe}
            line = (json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode()
            if len(line) > _MAX_ROW_BYTES or self._sequence >= _MAX_ROWS:
                raise ValueError('console event unavailable')
            path = self._root / 'console-events.jsonl'
            if path.is_symlink():
                raise ValueError('console event unavailable')
            with path.open('ab') as stream:
                stream.write(line)
                stream.flush()
            self._sequence += 1
