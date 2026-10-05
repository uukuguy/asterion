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


_OUTPUT_CAP = 1100 * 1024
_COMMAND_SECONDS = 20
_IDLE_SECONDS = 300
_TOTAL_SECONDS = 1800
_ACTION_CAP = 1000
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

    def _read(self) -> dict:
        deadline, buffer = time.monotonic() + _COMMAND_SECONDS, bytearray()
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

    def __init__(self, arc_root: Path, *, worker_factory=None, clock=time.monotonic):
        self._arc_root, self._factory, self._clock = Path(arc_root), worker_factory or _Worker, clock
        self._gate, self._lock = threading.Lock(), threading.Lock()
        self._worker, self._observation, self._closed = None, None, False
        self._commands: dict[str, tuple[str, dict]] = {}
        self._created = self._last_action = 0.0
        self._view = {'session_id': None, 'game_id': None, 'level': None, 'state': 'idle', 'observation_version': 0,
                      'episode_id': 0, 'action_count': 0, 'snapshot': None, 'last_action': None}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._monitor, daemon=True, name='manual-console-expiry')
        self._thread.start()

    def view(self) -> dict:
        with self._lock:
            return deepcopy(self._view)

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

    def _remember(self, command_id, signature):
        value = self.view()
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
                return prior
            if self._closed:
                raise ManualConsoleError('session-busy')
            self._close_worker()
            self._change(state='closed')
            try:
                self._worker = self._factory(self._arc_root, game_id, level)
                value = _observation(self._worker.observe(), game_id, win_levels)
                if (value['levels_completed'] != 0 or value['state'] != 'NOT_FINISHED'
                        or value['current_level'] != level):
                    raise ManualConsoleError('manual-unavailable')
            except Exception:
                self._close_worker()
                raise ManualConsoleError('manual-unavailable') from None
            self._observation = value
            self._created = self._last_action = self._clock()
            self._change(session_id='manual-' + secrets.token_hex(16), game_id=game_id, level=level, state='ready',
                         observation_version=0, episode_id=1, action_count=0,
                         snapshot=_snapshot(value, 0, 0), last_action=None)
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
                return prior
            if session_id != self._view['session_id']:
                raise ManualConsoleError('session-mismatch')
            if self._closed or self._view['state'] != 'ready':
                raise ManualConsoleError('session-busy')
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
            try:
                value = _observation(self._worker.step(action, data), self._view['game_id'], self._observation['win_levels'])
            except Exception:
                self._change(state='uncertain')
                self._close_worker()
                raise ManualConsoleError('manual-uncertain') from None
            self._observation = value
            version, count = observation_version + 1, self._view['action_count'] + 1
            self._last_action = self._clock()
            self._change(observation_version=version, action_count=count, level=value['current_level'],
                         episode_id=self._view['episode_id'] + int(action == 'RESET'),
                         snapshot=_snapshot(value, version, count),
                         last_action={'action': action, 'data': deepcopy(data), 'observation_version': version})
            return self._remember(command_id, signature)
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
            self._close_worker()
            if self._view['state'] != 'idle':
                self._change(state='closed')
            return self._remember(command_id, signature) if command_id is not None else self.view()
        finally:
            self._gate.release()

    def _expired(self):
        now = self._clock()
        return (now - self._created >= _TOTAL_SECONDS or now - self._last_action >= _IDLE_SECONDS
                or self._view['action_count'] >= _ACTION_CAP)

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
        signal.setitimer(signal.ITIMER_REAL, _TOTAL_SECONDS)
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
        deadline, count = time.monotonic() + _TOTAL_SECONDS, 0
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
            if type(command) is not dict or set(command) != {'action', 'data'}:
                raise ValueError
            value = manual.step(command['action'], command['data'])
            count += 1
        return 0
    except Exception:
        return 1
    finally:
        if engine is not None:
            engine.close()
        os.close(output_fd)


if __name__ == '__main__':
    raise SystemExit(main())
