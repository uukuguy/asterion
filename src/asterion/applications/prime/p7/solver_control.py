"""Cooperative P7 admission and atomic operator/console control handshake."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time

SCHEMA = 'asterion.prime.p7-run-control/v1'
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,159}\Z')
_HASH = re.compile(r'sha256:[0-9a-f]{64}\Z')
_REQUEST_KEYS = {'schema', 'run_id', 'command_id', 'request_sequence', 'operation'}
_ACK_KEYS = {'schema', 'run_id', 'command_id', 'request_sequence', 'state', 'reason',
             'source_action_sequence', 'observation_sha256'}
_STATES = {'running', 'pause_requested', 'paused', 'stop_requested', 'rejected'}
_REASONS = {None, 'deadline_expired', 'request_invalid', 'control_stale', 'command_conflict', 'stop_requested'}


def _root(path: Path, run_id: str) -> Path:
    path = Path(path)
    if not _ID.fullmatch(run_id) or path.name != run_id or path.is_symlink():
        raise ValueError('solver control unavailable')
    root = path.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('solver control unavailable')
    return root


def _valid(value: object, *, run_id: str, ack: bool = False) -> bool:
    if not isinstance(value, dict) or set(value) != (_ACK_KEYS if ack else _REQUEST_KEYS):
        return False
    if value['schema'] != SCHEMA or value['run_id'] != run_id:
        return False
    command = value['command_id']
    seq = value['request_sequence']
    if (type(seq) is not int or not 0 <= seq <= 10**9
        or (command is None and (not ack or seq != 0))
        or (command is not None and (type(command) is not str or not _ID.fullmatch(command)))):
        return False
    if not ack:
        return seq > 0 and type(value['operation']) is str and value['operation'] in {'pause', 'resume'}
    return (type(value['state']) is str and value['state'] in _STATES
            and (value['reason'] is None or type(value['reason']) is str) and value['reason'] in _REASONS
            and type(value['source_action_sequence']) is int and 0 <= value['source_action_sequence'] <= 10**9
            and (value['observation_sha256'] is None or
                 (type(value['observation_sha256']) is str and _HASH.fullmatch(value['observation_sha256']))))


def _read(root: Path, name: str) -> dict | None:
    path = root / name
    if path.is_symlink():
        raise ValueError('solver control unavailable')
    try:
        with path.open('rb') as stream:
            raw = stream.read(4097)
    except FileNotFoundError:
        return None
    if len(raw) > 4096:
        raise ValueError('solver control unavailable')
    def pairs(items):
        value = dict(items)
        if len(value) != len(items):
            raise ValueError('solver control unavailable')
        return value
    return json.loads(raw, object_pairs_hook=pairs)


def _write(root: Path, name: str, value: dict) -> None:
    target = root / name
    if target.is_symlink():
        raise ValueError('solver control unavailable')
    raw = json.dumps(value, allow_nan=False, separators=(',', ':')).encode()
    if len(raw) > 4096:
        raise ValueError('solver control unavailable')
    fd, temporary = tempfile.mkstemp(prefix='.control-', dir=root)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_control_request(run_root: Path, *, run_id: str, command_id: str,
                          request_sequence: int, operation: str) -> dict:
    value = dict(schema=SCHEMA, run_id=run_id, command_id=command_id,
                 request_sequence=request_sequence, operation=operation)
    if not _valid(value, run_id=run_id):
        raise ValueError('solver control unavailable')
    root = _root(run_root, run_id)
    prior = _read(root, 'control-request.json')
    if prior is not None:
        if not _valid(prior, run_id=run_id):
            raise ValueError('solver control unavailable')
        if prior == value:
            return dict(value)
        if prior['request_sequence'] >= request_sequence or prior['command_id'] == command_id:
            raise ValueError('solver control unavailable')
    _write(root, 'control-request.json', value)
    return dict(value)


def read_control_ack(run_root: Path, *, run_id: str) -> dict | None:
    value = _read(_root(run_root, run_id), 'control-ack.json')
    if value is not None and not _valid(value, run_id=run_id, ack=True):
        raise ValueError('solver control unavailable')
    return value


class SolverControl:
    """Admission gate; it neither dispatches work nor claims process cleanup."""
    def __init__(self, run_root: Path, run_id: str, deadline: float, *, clock=time.monotonic):
        self._root = _root(run_root, run_id)
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError('solver control unavailable')
        self._run_id, self._deadline, self._clock = run_id, deadline, clock
        self._lock = threading.RLock()
        self._active = {'cell': 0, 'action': 0, 'model_round': 0}
        self._commands = {}
        self._request_sequence = 0
        self._command_id = None
        self._state, self._reason = 'running', None
        self._position, self._hash = 0, None

    def _settle(self):
        if self._clock() >= self._deadline:
            self._state, self._reason = 'stop_requested', 'deadline_expired'
        elif self._state == 'pause_requested' and not any(self._active.values()):
            self._state = 'paused'

    def _snapshot(self):
        self._settle()
        return dict(schema=SCHEMA, run_id=self._run_id, command_id=self._command_id,
                    request_sequence=self._request_sequence, state=self._state, reason=self._reason,
                    source_action_sequence=self._position, observation_sha256=self._hash)

    def snapshot(self) -> dict:
        with self._lock:
            return self._snapshot()

    def request(self, operation: str, command_id: str) -> dict:
        with self._lock:
            if type(operation) is not str or operation not in {'pause', 'resume', 'stop'} or type(command_id) is not str or not _ID.fullmatch(command_id):
                raise ValueError('solver control unavailable')
            prior = self._commands.get(command_id)
            if prior is not None:
                if prior != operation:
                    raise ValueError('solver control unavailable')
                return self._snapshot()
            if len(self._commands) >= 256:
                raise ValueError('solver control unavailable')
            self._commands[command_id] = operation
            self._command_id = command_id
            self._settle()
            if self._state != 'stop_requested':
                self._reason = None
                self._state = 'pause_requested' if operation == 'pause' else 'running' if operation == 'resume' else 'stop_requested'
            value = self._snapshot()
            _write(self._root, 'control-ack.json', value)
            return value

    def poll(self, source_action_sequence: int, observation_sha256: str) -> dict:
        with self._lock:
            if type(source_action_sequence) is not int or source_action_sequence < 0 or type(observation_sha256) is not str or not _HASH.fullmatch(observation_sha256):
                raise ValueError('solver control unavailable')
            self._position, self._hash = source_action_sequence, observation_sha256
            value = _read(self._root, 'control-request.json')
            if value is not None:
                if not _valid(value, run_id=self._run_id):
                    raise ValueError('solver control unavailable')
                sequence = value['request_sequence']
                if sequence > self._request_sequence:
                    if value['command_id'] in self._commands:
                        raise ValueError('solver control unavailable')
                    self._request_sequence = sequence
                    self.request(value['operation'], value['command_id'])
                elif sequence == self._request_sequence and (value['command_id'] != self._command_id or self._commands.get(value['command_id']) != value['operation']):
                    raise ValueError('solver control unavailable')
            result = self._snapshot()
            _write(self._root, 'control-ack.json', result)
            return result

    def enter(self, operation: str) -> bool:
        with self._lock:
            if type(operation) is not str or operation not in self._active:
                raise ValueError('solver control unavailable')
            self._settle()
            if self._state != 'running':
                return False
            self._active[operation] += 1
            return True

    def leave(self, operation: str) -> None:
        with self._lock:
            if type(operation) is not str or operation not in self._active or self._active[operation] < 1:
                raise ValueError('solver control unavailable')
            self._active[operation] -= 1
            _write(self._root, 'control-ack.json', self._snapshot())

    def action_allowed(self) -> bool:
        with self._lock:
            return self._snapshot()['state'] == 'running'
