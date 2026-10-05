"""Independent, finite human game sessions with no P7 broker or learning path."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import secrets
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time

from .console_manual_saves import (MAX_STEPS, ManualSaveError, ManualSaveStore,
                                  append_step, digest, game_identity, new_record)

_OUTPUT_CAP = 1100 * 1024
_COMMAND_SECONDS = 20
_IDLE_SECONDS = 300
_TOTAL_SECONDS = 1800
_ACTION_CAP = 1000
_RESTORE_SECONDS = 60
_COMMAND_ID = re.compile(r'[A-Za-z0-9_-]{1,80}\Z')
_GAME_ID = re.compile(r'[A-Za-z0-9]+-[A-Za-z0-9]+\Z')


class ManualConsoleError(ValueError):
    """Fixed public-safe manual console failure."""


def _observation(value: object, game_id: str, win_levels: int) -> dict:
    try:
        if (type(value) is not dict
                or set(value) != {'game_id', 'win_levels', 'levels_completed', 'current_level',
                                  'state', 'available_actions', 'frame'}
                or value['game_id'] != game_id or type(value['win_levels']) is not int
                or value['win_levels'] != win_levels or type(value['levels_completed']) is not int
                or not 0 <= value['levels_completed'] <= win_levels
                or type(value['current_level']) is not int or not 1 <= value['current_level'] <= win_levels
                or value['state'] not in ('NOT_FINISHED', 'WIN', 'GAME_OVER')):
            raise ValueError
        actions, frame = value['available_actions'], value['frame']
        if (type(actions) is not list or len(actions) > 7
                or any(type(a) is not int or not 1 <= a <= 7 for a in actions)
                or actions != sorted(set(actions)) or type(frame) is not list or not frame
                or type(frame[0]) is not list or not frame[0]):
            raise ValueError
        layers = frame if type(frame[0][0]) is list else [frame]
        if len(layers) > 64:
            raise ValueError
        for grid in layers:
            if type(grid) is not list or not 1 <= len(grid) <= 64 or type(grid[0]) is not list:
                raise ValueError
            width = len(grid[0])
            if not 1 <= width <= 64 or any(type(row) is not list or len(row) != width
                    or any(type(c) is not int or not 0 <= c <= 15 for c in row) for row in grid):
                raise ValueError
        return {**deepcopy(value), 'frame': deepcopy(layers[-1])}
    except (ValueError, TypeError, KeyError, IndexError, RecursionError):
        raise ManualConsoleError('manual-unavailable') from None


def _snapshot(observation: dict, version: int, action_count: int) -> dict:
    completed = observation['levels_completed']
    wins = observation['win_levels']
    actions = [] if observation['state'] == 'WIN' else ['RESET']
    if observation['state'] == 'NOT_FINISHED':
        actions.extend(f'ACTION{a}' for a in observation['available_actions'])
    frame = {'id': f'manual-{version}', 'grid': deepcopy(observation['frame']), 'timestamp': None,
             'available_actions': actions, 'state': observation['state'], 'levels_completed': completed}
    return {'schema': 'asterion.arc-agi3-p7-console/v1', 'generated_at': None,
            'run': {'run_id': None, 'game_id': observation['game_id'], 'status': 'manual',
                    'completed_level_count': completed, 'win_levels': wins, 'target_level': wins,
                    'primitive_action_count': action_count, 'replay_verified': False,
                    'sealed_trace': False, 'model': None},
            'levels': [{'level': observation['current_level'], 'status': 'manual', 'frames': [frame],
                        'actions': [], 'decisions': [], 'cognition_timeline': [],
                        'cognition': {'scope': 'unavailable', 'stable_description': '独立人工验证，不生成 P7 认知。',
                                      'updates': [], 'world_map_facts': {}}, 'receipt': None}],
            'decisions': [], 'warnings': []}


class _ManualEngine:
    """HUMAN-only direct level adapter for arc-agi 0.9.9 / arcengine 0.9.3.

    The pinned local wrapper has no public game accessor. Its typed ``_game``
    is the sole SDK-private seam; all level selection, reset, rendering and
    actions then use public SDK APIs. No game source or score is inspected or
    modified. P7 continues to use its unchanged fresh-L1 ArcadeEngine.
    """

    def __init__(self, engine, level: int):
        from importlib.metadata import version
        from arc_agi.local_wrapper import LocalEnvironmentWrapper
        from arcengine import ARCBaseGame

        if (version('arc-agi'), version('arcengine')) != ('0.9.9', '0.9.3'):
            raise ManualConsoleError('manual-unavailable')
        environment = engine._environment
        if not isinstance(environment, LocalEnvironmentWrapper) or not isinstance(environment._game, ARCBaseGame):
            raise ManualConsoleError('manual-unavailable')
        self._engine, self._game = engine, environment._game
        self._latest = dict(engine.observe())
        if (type(level) is not int or not 1 <= level <= self._latest['win_levels']
                or self._latest['levels_completed'] != 0 or self._latest['state'] != 'NOT_FINISHED'):
            raise ManualConsoleError('manual-unavailable')
        self._game.set_level(level - 1)
        self._render()

    def _render(self):
        # set_level / level_reset do not refresh the wrapper's last FrameData.
        # Render the actual sprites without issuing an action (RESET at action
        # count zero would otherwise perform a full reset and return to L1).
        self._latest['frame'] = self._game.camera.render(self._game.current_level.get_sprites()).tolist()

    def observe(self) -> dict:
        return {'game_id': self._engine.game_id, **deepcopy(self._latest),
                'current_level': self._game.level_index + 1}

    def step(self, action: str, data: dict) -> dict:
        if action == 'RESET':
            self._game.level_reset()
            # Public level_reset preserves the SDK score and sets NOT_FINISHED.
            self._latest['state'] = 'NOT_FINISHED'
            self._render()
        else:
            # The SDK owns the complete action/animation and real score change.
            self._latest = dict(self._engine.step(action, data))
        return self.observe()


class _Worker:
    """Private JSON pipe to exactly one installed, isolated offline engine."""

    def __init__(self, arc_root: Path, game_id: str, level: int = 1):
        self._directory = tempfile.TemporaryDirectory(prefix='asterion-manual-')
        self._process = None
        try:
            self._process = subprocess.Popen(
                [sys.executable, '-I', '-m', __name__, '--arc-root', str(arc_root),
                 '--game-id', game_id, '--level', str(level), '--recordings', self._directory.name],
                cwd=self._directory.name, env={'OPERATION_MODE': 'offline'},
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                start_new_session=True, bufsize=0,
            )
        except Exception:
            self.close()
            raise ManualConsoleError('manual-unavailable') from None

    def _read(self, seconds=_COMMAND_SECONDS) -> dict:
        deadline, buffer = time.monotonic() + seconds, bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self._process.stdout], [], [], remaining)[0]:
                raise ManualConsoleError('manual-unavailable')
            chunk = os.read(self._process.stdout.fileno(), 8192)
            if not chunk:
                raise ManualConsoleError('manual-unavailable')
            buffer.extend(chunk)
            if len(buffer) > _OUTPUT_CAP:
                raise ManualConsoleError('manual-unavailable')
            if b'\n' in buffer:
                if not buffer.endswith(b'\n') or buffer.count(b'\n') != 1:
                    raise ManualConsoleError('manual-unavailable')
                value = json.loads(buffer)
                if type(value) is not dict:
                    raise ManualConsoleError('manual-unavailable')
                return value

    def observe(self) -> dict:
        # Read only after the controller has retained ownership of this worker.
        # A failed read must never strand a process during construction.
        return self._read()

    def step(self, action: str, data: dict) -> dict:
        raw = json.dumps({'action': action, 'data': data}, separators=(',', ':')).encode() + b'\n'
        self._process.stdin.write(raw)
        self._process.stdin.flush()
        return self._read()

    def replay_step(self, action: str, data: dict, seconds: float) -> dict:
        raw = json.dumps({'action': action, 'data': data, 'replay': True}, separators=(',', ':')).encode() + b'\n'
        self._process.stdin.write(raw)
        self._process.stdin.flush()
        return self._read(min(_COMMAND_SECONDS, seconds))

    def activate(self) -> dict:
        self._process.stdin.write(b'{"activate":true}\n')
        self._process.stdin.flush()
        return self._read()

    def close(self) -> None:
        process = self._process
        if process is not None:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            # All descendants share this owned group, even if the worker exited.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        stream.close()
                deadline = time.monotonic() + 5
                while True:
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        break
                    if time.monotonic() >= deadline:
                        raise ManualConsoleError('manual-cleanup-unconfirmed')
                    time.sleep(0.02)
            except Exception:
                raise ManualConsoleError('manual-cleanup-unconfirmed')
            self._process = None
        self._directory.cleanup()


class ManualConsole:
    """One independent session. Commands never queue behind another action."""

    def __init__(self, arc_root: Path, *, worker_factory=None, clock=time.monotonic, save_root: Path | None = None):
        self._arc_root, self._factory, self._clock = Path(arc_root), worker_factory or _Worker, clock
        self._gate, self._lock = threading.Lock(), threading.RLock()
        self._worker, self._observation, self._closed = None, None, False
        self._commands: dict[str, tuple[str, dict]] = {}
        self._created = self._last_action = 0.0
        self._store = ManualSaveStore(save_root) if save_root is not None else None
        self._record = None
        self._history = []
        self._live_start_count = 0
        self._view = {'session_id': None, 'game_id': None, 'level': None, 'state': 'idle', 'observation_version': 0,
                      'episode_id': 0, 'action_count': 0, 'snapshot': None, 'last_action': None,
                      'saved_levels': [], 'save_status': 'disabled' if self._store is None else 'saved',
                      'restored': False}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._monitor, daemon=True, name='manual-console-expiry')
        self._thread.start()

    def view(self, *, history=True) -> dict:
        with self._lock:
            value = deepcopy(self._view)
            if history:
                value['history'] = deepcopy(self._history)
            return value

    def _history_entry(self):
        value = self._view
        return {key: deepcopy(value[key]) for key in
                ('observation_version', 'episode_id', 'action_count', 'level', 'last_action')} | {
                    'frame': deepcopy(value['snapshot']['levels'][0]['frames'][0])}

    def _save(self):
        if self._store is None or self._record is None:
            return
        try:
            self._store.write(self._record)
            self._change(save_status='saved', saved_levels=self._store.levels(self._record['game_id']))
        except ManualSaveError as error:
            self._change(save_status='failed')
            raise ManualConsoleError(str(error)) from None

    def _flush_unsaved(self):
        if self._view['save_status'] == 'failed':
            self._save()

    def _retry_save(self, command_id, signature, prior):
        if (self._view['save_status'] == 'failed'
                and prior['session_id'] == self._view['session_id']
                and prior['observation_version'] == self._view['observation_version']):
            try:
                self._save()
            except ManualConsoleError:
                pass
            prior['save_status'] = self._view['save_status']
            prior['saved_levels'] = deepcopy(self._view['saved_levels'])
            self._commands[command_id] = (signature, deepcopy(prior))
        return prior

    def _change(self, **values):
        with self._lock:
            self._view.update(values)

    def _prior(self, command_id, signature):
        if type(command_id) is not str or not _COMMAND_ID.fullmatch(command_id):
            raise ManualConsoleError('command-invalid')
        prior = self._commands.get(command_id)
        if prior is not None:
            if prior[0] != signature:
                raise ManualConsoleError('command-conflict')
            return deepcopy(prior[1])
        if len(self._commands) >= 2048:
            raise ManualConsoleError('command-limit')
        return None

    def _remember(self, command_id, signature, *, history=True):
        value = self.view(history=history)
        self._commands[command_id] = (signature, value)
        return deepcopy(value)

    def _close_worker(self):
        if self._worker is not None:
            try:
                self._worker.close()
            except Exception:
                self._change(state='uncertain')
                raise ManualConsoleError('manual-cleanup-unconfirmed') from None
            self._worker = None

    def open(self, game_id: str, win_levels: int, command_id: str, level: int = 1) -> dict:
        if not self._gate.acquire(blocking=False):
            raise ManualConsoleError('session-busy')
        try:
            if (type(game_id) is not str or len(game_id) > 80 or not _GAME_ID.fullmatch(game_id)
                    or type(win_levels) is not int or not 1 <= win_levels <= 100):
                raise ManualConsoleError('game-unavailable')
            if type(level) is not int or not 1 <= level <= win_levels:
                raise ManualConsoleError('level-unavailable')
            signature = json.dumps(['open', game_id, win_levels, level])
            prior = self._prior(command_id, signature)
            if prior is not None:
                return self._retry_save(command_id, signature, prior)
            if self._closed:
                raise ManualConsoleError('session-busy')
            self._flush_unsaved()
            record = None
            identity = None
            if self._store is not None:
                try:
                    identity = game_identity(self._arc_root, game_id)
                    record = self._store.load(game_id, win_levels, level, _observation, identity)
                except ManualSaveError as error:
                    raise ManualConsoleError(str(error)) from None
            self._close_worker()
            self._change(state='closed')
            replay_deadline = time.monotonic() + _RESTORE_SECONDS
            try:
                self._worker = self._factory(self._arc_root, game_id, record['origin_level'] if record else level)
                value = _observation(self._worker.observe(), game_id, win_levels)
                if (value['levels_completed'] != 0 or value['state'] != 'NOT_FINISHED'
                        or value['current_level'] != (record['origin_level'] if record else level)):
                    raise ManualConsoleError('manual-unavailable')
                history_values = [(value, None)]
                if record is not None:
                    if digest(value) != record['initial_digest']:
                        raise ManualConsoleError('manual-restore-failed')
                    for step in record['steps']:
                        remaining = replay_deadline - time.monotonic()
                        if remaining <= 0:
                            raise ManualConsoleError('manual-restore-failed')
                        replay = getattr(self._worker, 'replay_step', None)
                        raw = (replay(step['action'], step['data'], remaining) if replay is not None
                               else self._worker.step(step['action'], step['data']))
                        value = _observation(raw, game_id, win_levels)
                        if digest(value) != step['digest']:
                            raise ManualConsoleError('manual-restore-failed')
                        history_values.append((value, step))
                    if time.monotonic() >= replay_deadline:
                        raise ManualConsoleError('manual-restore-failed')
                activate = getattr(self._worker, 'activate', None)
                if activate is not None and _observation(activate(), game_id, win_levels) != value:
                    raise ManualConsoleError('manual-restore-failed')
            except Exception:
                self._close_worker()
                raise ManualConsoleError('manual-restore-failed' if record else 'manual-unavailable') from None
            self._observation = value
            self._record = record if record is not None else new_record(value, identity)
            self._created = self._last_action = self._clock()
            episode = 1
            history = []
            for version, (observed, step) in enumerate(history_values):
                episode += int(step is not None and step['action'] == 'RESET')
                last_action = None if step is None else {'action': step['action'],
                              'data': deepcopy(step['data']), 'observation_version': version}
                if version >= len(history_values) - 1001:
                    snapshot = _snapshot(observed, version, version)
                    history.append({'level': observed['current_level'], 'observation_version': version,
                                    'episode_id': episode, 'action_count': version, 'last_action': last_action,
                                    'frame': snapshot['levels'][0]['frames'][0]})
            with self._lock:
                self._change(session_id='manual-' + secrets.token_hex(16), game_id=game_id, state='ready',
                             restored=record is not None, save_status='disabled' if self._store is None else 'saved',
                             level=value['current_level'], observation_version=version, episode_id=episode,
                             action_count=version, snapshot=snapshot, last_action=last_action)
                self._history = history
                self._live_start_count = self._view['action_count']
                try:
                    self._save()
                except ManualConsoleError:
                    # The actual initial/restored pose remains usable and visible.
                    # A subsequent switch must first retry this save successfully.
                    pass
            return self._remember(command_id, signature)
        finally:
            self._gate.release()

    def restart(self, session_id, command_id, observation_version) -> dict:
        """Replace only the confirmed current HUMAN slot with a fresh SDK pose."""
        if not self._gate.acquire(blocking=False):
            raise ManualConsoleError('session-busy')
        try:
            if (type(session_id) is not str or type(observation_version) is not int
                    or observation_version < 0):
                raise ManualConsoleError('action-invalid')
            signature = json.dumps(['restart', session_id, observation_version])
            prior = self._prior(command_id, signature)
            if prior is not None:
                return prior
            if session_id != self._view['session_id']:
                raise ManualConsoleError('session-mismatch')
            if self._closed or self._view['state'] not in {'ready', 'uncertain'}:
                raise ManualConsoleError('session-busy')
            if observation_version != self._view['observation_version']:
                raise ManualConsoleError('observation-stale')
            game_id, level = self._view['game_id'], self._view['level']
            wins = self._observation['win_levels']
            identity = None
            if self._store is not None:
                try:
                    identity = game_identity(self._arc_root, game_id)
                    if identity != self._record['game_identity']:
                        raise ManualSaveError('manual-save-invalid')
                    # Inspect storage boundaries before stopping the live game.
                    saved_levels = self._store.levels(game_id)
                except ManualSaveError as error:
                    raise ManualConsoleError(str(error)) from None
            else:
                saved_levels = []
            # Explicit restart may discard an unsaved pose. It must not retry
            # the old journal or ever overlap the old and replacement workers.
            self._close_worker()
            self._change(state='uncertain')
            try:
                self._worker = self._factory(self._arc_root, game_id, level)
                value = _observation(self._worker.observe(), game_id, wins)
                if (value['current_level'] != level or value['levels_completed'] != 0
                        or value['state'] != 'NOT_FINISHED'):
                    raise ManualConsoleError('manual-unavailable')
                activate = getattr(self._worker, 'activate', None)
                if activate is not None and _observation(activate(), game_id, wins) != value:
                    raise ManualConsoleError('manual-unavailable')
                record = new_record(value, identity)
                if self._store is not None:
                    self._store.write(record, retain_previous=True)
                    saved_levels = sorted(set(saved_levels) | {level})
            except Exception as error:
                self._close_worker()
                code = str(error) if isinstance(error, ManualSaveError) else 'manual-unavailable'
                raise ManualConsoleError(code) from None
            self._observation, self._record = value, record
            self._created = self._last_action = self._clock()
            with self._lock:
                self._change(session_id='manual-' + secrets.token_hex(16), state='ready', level=level,
                             observation_version=0, action_count=0, episode_id=1, last_action=None,
                             snapshot=_snapshot(value, 0, 0), restored=False, saved_levels=saved_levels,
                             save_status='disabled' if self._store is None else 'saved')
                self._history = [self._history_entry()]
                self._live_start_count = 0
            return self._remember(command_id, signature)
        finally:
            self._gate.release()

    def act(self, session_id, command_id, observation_version, action, data) -> dict:
        if not self._gate.acquire(blocking=False):
            raise ManualConsoleError('session-busy')
        try:
            if (type(session_id) is not str or type(observation_version) is not int
                    or observation_version < 0 or type(action) is not str or type(data) is not dict
                    or (action == 'ACTION6' and (set(data) != {'x', 'y'}
                        or any(type(v) is not int or not 0 <= v <= 63 for v in data.values())))
                    or (action != 'ACTION6' and data)):
                raise ManualConsoleError('action-invalid')
            signature = json.dumps(['act', session_id, observation_version, action, data], sort_keys=True)
            prior = self._prior(command_id, signature)
            if prior is not None:
                return self._retry_save(command_id, signature, prior)
            if session_id != self._view['session_id']:
                raise ManualConsoleError('session-mismatch')
            if self._closed or self._view['state'] != 'ready':
                raise ManualConsoleError('session-busy')
            self._flush_unsaved()
            if self._expired():
                self._close_worker()
                self._change(state='expired')
                raise ManualConsoleError('manual-expired')
            if observation_version != self._view['observation_version']:
                raise ManualConsoleError('observation-stale')
            frame = self._view['snapshot']['levels'][0]['frames'][0]
            if action not in frame['available_actions']:
                raise ManualConsoleError('action-unavailable')
            if action == 'ACTION6' and (data['y'] >= len(frame['grid']) or data['x'] >= len(frame['grid'][0])):
                raise ManualConsoleError('action-invalid')
            if len(self._record['steps']) >= MAX_STEPS:
                raise ManualConsoleError('manual-save-limit')
            if self._store is not None:
                try:
                    self._store.ensure_room(self._record)
                except ManualSaveError as error:
                    raise ManualConsoleError(str(error)) from None
            try:
                value = _observation(self._worker.step(action, data), self._view['game_id'], self._observation['win_levels'])
            except Exception:
                self._change(state='uncertain')
                self._close_worker()
                raise ManualConsoleError('manual-uncertain') from None
            self._observation = value
            version, count = observation_version + 1, self._view['action_count'] + 1
            self._last_action = self._clock()
            previous_level = self._view['level']
            append_step(self._record, action, data, value)
            with self._lock:
                self._change(observation_version=version, action_count=count, level=value['current_level'],
                             episode_id=self._view['episode_id'] + int(action == 'RESET'),
                             snapshot=_snapshot(value, version, count),
                             last_action={'action': action, 'data': deepcopy(data), 'observation_version': version})
                self._history.append(self._history_entry())
                self._history = self._history[-1001:]
                try:
                    collision = (self._store is not None and previous_level != value['current_level']
                                 and value['current_level'] in self._store.levels(value['game_id']))
                    if collision:
                        self._change(save_status='pending', saved_levels=self._store.levels(value['game_id']))
                    else:
                        self._save()
                except (ManualConsoleError, ManualSaveError):
                    self._change(save_status='failed')
            return self._remember(command_id, signature, history=False)
        finally:
            self._gate.release()

    def close(self, session_id=None, command_id=None) -> dict:
        if not self._gate.acquire(blocking=False):
            raise ManualConsoleError('session-busy')
        try:
            signature = json.dumps(['close', session_id])
            if command_id is not None:
                prior = self._prior(command_id, signature)
                if prior is not None:
                    return prior
                if type(session_id) is not str or session_id != self._view['session_id']:
                    raise ManualConsoleError('session-mismatch')
            self._flush_unsaved()
            self._close_worker()
            if self._view['state'] != 'idle':
                self._change(state='closed')
            return self._remember(command_id, signature) if command_id is not None else self.view()
        finally:
            self._gate.release()

    def _expired(self):
        now = self._clock()
        return (now - self._created >= _TOTAL_SECONDS or now - self._last_action >= _IDLE_SECONDS
                or self._view['action_count'] - self._live_start_count >= _ACTION_CAP)

    def reap_idle(self):
        if self._gate.acquire(blocking=False):
            try:
                if self._worker is not None and self._expired():
                    self._close_worker()
                    self._change(state='expired')
            finally:
                self._gate.release()

    def _monitor(self):
        while not self._stop.wait(1):
            try:
                self.reap_idle()
            except ManualConsoleError:
                pass

    def shutdown(self):
        self._stop.set()
        self._thread.join(timeout=6)
        with self._gate:
            self._closed = True
            self._close_worker()
            self._change(state='closed')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--arc-root', type=Path, required=True)
    parser.add_argument('--game-id', required=True)
    parser.add_argument('--level', type=int, default=1)
    parser.add_argument('--recordings', type=Path, required=True)
    args = parser.parse_args()
    output_fd = os.dup(sys.stdout.fileno())
    engine = None
    try:
        # Remain finite even if the host disappears during a blocked SDK call.
        signal.setitimer(signal.ITIMER_REAL, _RESTORE_SECONDS)
        with open(os.devnull, 'w') as silent:
            os.dup2(silent.fileno(), sys.stdout.fileno())
            os.dup2(silent.fileno(), sys.stderr.fileno())
        from .game import GAME_ID_ENV, SEED_ENV, TARGET_LEVEL_ENV, resolve_game_selection
        from .live import ArcadeEngine
        game = resolve_game_selection({GAME_ID_ENV: args.game_id, SEED_ENV: '0', TARGET_LEVEL_ENV: '1'}, args.arc_root)
        if game.game_id != args.game_id:
            raise ValueError
        engine = ArcadeEngine(arc_root=args.arc_root, recordings_dir=args.recordings, game=game)
        manual = _ManualEngine(engine, args.level)
        deadline, count, replay_count, active = time.monotonic() + _RESTORE_SECONDS, 0, 0, False
        value = manual.observe()
        while True:
            _observation(value, game.game_id, game.win_levels)
            body = json.dumps(value, separators=(',', ':'), allow_nan=False).encode() + b'\n'
            if len(body) > _OUTPUT_CAP:
                raise ValueError
            with os.fdopen(os.dup(output_fd), 'wb') as output:
                output.write(body)
            remaining = min(_IDLE_SECONDS, deadline - time.monotonic())
            if count >= _ACTION_CAP or remaining <= 0 or not select.select([sys.stdin], [], [], remaining)[0]:
                break
            raw = sys.stdin.buffer.readline(4097)
            if not raw:
                break
            if len(raw) > 4096 or not raw.endswith(b'\n'):
                raise ValueError
            command = json.loads(raw)
            if type(command) is not dict:
                raise ValueError
            if command == {'activate': True} and not active:
                active = True
                deadline = time.monotonic() + _TOTAL_SECONDS
                signal.setitimer(signal.ITIMER_REAL, _TOTAL_SECONDS)
            elif (not active and set(command) == {'action', 'data', 'replay'}
                  and command['replay'] is True and replay_count < MAX_STEPS):
                value = manual.step(command['action'], command['data'])
                replay_count += 1
            elif active and set(command) == {'action', 'data'}:
                value = manual.step(command['action'], command['data'])
                count += 1
            else:
                raise ValueError
        return 0
    except Exception:
        return 1
    finally:
        if engine is not None:
            engine.close()
        os.close(output_fd)


if __name__ == '__main__':
    raise SystemExit(main())
