"""Small private write-ahead record for one sequential P7 effect at a time.

A pending record is evidence of possible execution, never retry authority.
No recovery, engine invocation, or replay is performed here.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
import os
from pathlib import Path
from threading import RLock
import uuid

from .run_story.storage import write_atomic_file

_SCHEMA = 'asterion.prime.p7-action-transaction/v1'
_TERMINAL = {'committed', 'not-dispatched'}
_PHASES = _TERMINAL | {'prepared', 'entered', 'reply-received', 'unresolved'}
_STAGES = {'not-dispatched', 'dispatched-no-reply', 'reply-received-invalid',
           'reply-received-unvalidated', 'validated-not-durable', 'derived-failed'}


def _copy(value):
    if not isinstance(value, Mapping):
        raise ValueError('action journal unavailable')
    raw = json.dumps(dict(value), ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    if len(raw) > 32768:
        raise ValueError('action journal unavailable')
    return json.loads(raw)


def _action(value):
    result = _copy(value)
    if (set(result) != {'name', 'data'} or result['name'] not in {'RESET', *(f'ACTION{i}' for i in range(1, 8))}
            or type(result['data']) is not dict
            or any(type(key) is not str or type(item) is not int for key, item in result['data'].items())):
        raise ValueError('action journal unavailable')
    return result


class ActionJournal:
    def __init__(self, root: Path, scope: Mapping):
        root = Path(root).absolute()
        if any(path.is_symlink() for path in (root, *root.parents)):
            raise ValueError('action journal unavailable')
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._root, self._scope = root, _copy(scope)
        self._path = root / 'current.json'
        self._lock = RLock()
        self._current = None
        if self._path.is_symlink():
            raise ValueError('action journal unavailable')
        if self._path.exists():
            if self._path.stat().st_size > 65536:
                raise ValueError('action journal unavailable')
            value = json.loads(self._path.read_text())
            if (type(value) is not dict or value.get('schema') != _SCHEMA or value.get('scope') != self._scope
                    or value.get('phase') not in _PHASES or type(value.get('sequence')) is not int
                    or value['sequence'] < 1 or type(value.get('outcome_known')) is not bool
                    or type(value.get('transaction_id')) is not str
                    or len(value['transaction_id']) != 32
                    or any(c not in '0123456789abcdef' for c in value['transaction_id'])):
                raise ValueError('action journal unavailable')
            _action(value.get('action'))
            self._current = value

    @property
    def has_unresolved(self) -> bool:
        with self._lock:
            return self._current is not None and self._current['phase'] not in _TERMINAL

    def snapshot(self) -> dict | None:
        with self._lock:
            return deepcopy(self._current)

    def _save(self, value):
        if self._path.is_symlink() or any(path.is_symlink() for path in (self._root, *self._root.parents)):
            raise ValueError('action journal unavailable')
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()
        if len(raw) > 65536:
            raise ValueError('action journal unavailable')
        if value['phase'] in _TERMINAL:
            archive = self._root / (value['transaction_id'] + '.json')
            if archive.is_symlink():
                raise ValueError('action journal unavailable')
            write_atomic_file(archive, raw)
        write_atomic_file(self._path, raw)
        # A published pending/reply record must remain blocking even if the
        # following directory durability check fails. Do not lose its metadata.
        if value['phase'] not in _TERMINAL:
            self._current = value
        descriptor = os.open(self._root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._current = value

    def prepare(self, *, sequence: int, action: Mapping, before: Mapping) -> None:
        with self._lock:
            if (self.has_unresolved or type(sequence) is not int or sequence < 1
                    or (self._current is not None and self._current['phase'] == 'committed'
                        and sequence <= self._current['sequence'])):
                raise ValueError('action journal unavailable')
            self._save({'schema': _SCHEMA, 'scope': self._scope, 'transaction_id': uuid.uuid4().hex,
                        'sequence': sequence, 'action': _action(action), 'before': _copy(before),
                        'phase': 'prepared', 'outcome_known': False})

    def _change(self, allowed, **fields):
        if self._current is None or self._current['phase'] not in allowed:
            raise ValueError('action journal unavailable')
        self._save({**self._current, **fields})

    def dispatch_entered(self, action: Mapping) -> None:
        with self._lock:
            if self._current is None or self._current['action'] != _action(action):
                raise ValueError('action journal unavailable')
            self._change({'prepared'}, phase='entered')

    def response_received(self, metadata: Mapping) -> None:
        with self._lock:
            self._change({'entered'}, phase='reply-received', response=_copy(metadata), outcome_known=False)

    def commit(self, *, sequence: int, observation_ref: Mapping) -> None:
        with self._lock:
            if self._current is None or sequence != self._current['sequence']:
                raise ValueError('action journal unavailable')
            reference = _copy(observation_ref)
            if self._current['phase'] == 'committed' and self._current.get('observation_ref') == reference:
                return
            self._change({'prepared', 'entered', 'reply-received'}, phase='committed',
                         observation_ref=reference, outcome_known=True)

    def not_dispatched(self, reason: str) -> None:
        with self._lock:
            if type(reason) is not str or not reason or len(reason) > 80:
                raise ValueError('action journal unavailable')
            if self._current is not None and self._current['phase'] == 'not-dispatched':
                return
            self._change({'prepared', 'entered'}, phase='not-dispatched', reason=reason, outcome_known=True)

    def unresolved(self, stage: str, outcome_known: bool = False) -> None:
        with self._lock:
            if stage not in _STAGES or type(outcome_known) is not bool:
                raise ValueError('action journal unavailable')
            self._change({'prepared', 'entered', 'reply-received', 'unresolved'},
                         phase='unresolved', stage=stage,
                         outcome_known=outcome_known or self._current['outcome_known'])
