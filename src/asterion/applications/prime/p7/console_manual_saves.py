"""Bounded, operator-private HUMAN journals; never a P7 prefix store."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

SCHEMA = 'asterion.p7-human-save/v1'
SDK = {'arc-agi': '0.9.9', 'arcengine': '0.9.3'}
MAX_STEPS = 10000
MAX_BYTES = 32 * 1024 * 1024
# One normalized observation has at most 64x64 two-digit pixels.  This
# reservation also covers every closed observation/action field and JSON
# punctuation, so a settled step cannot overflow the writable journal cap.
MAX_STEP_BYTES = 16 * 1024
_GAME = re.compile(r'[A-Za-z0-9]+-[A-Za-z0-9]+\Z')
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')


class ManualSaveError(ValueError):
    """Closed save failure code, with no private diagnostics."""


def digest(observation: dict) -> str:
    return hashlib.sha256(json.dumps(observation, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def game_identity(arc_root: Path, game_id: str) -> str:
    try:
        if not _GAME.fullmatch(game_id):
            raise ValueError
        stem, version = game_id.split('-')
        directory = Path(arc_root) / 'environment_files' / stem / version
        identity = hashlib.sha256()
        for name in ('metadata.json', f'{stem}.py'):
            path = directory / name
            if any(part.is_symlink() for part in (path, *path.parents)):
                raise ValueError
            with path.open('rb') as source:
                raw = source.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError
            identity.update(name.encode() + b'\0' + raw + b'\0')
        return identity.hexdigest()
    except (OSError, ValueError):
        raise ManualSaveError('manual-save-invalid') from None


def new_record(observation: dict, identity: str) -> dict:
    return {'schema': SCHEMA, 'sdk': dict(SDK), 'seed': 0,
            'game_id': observation['game_id'], 'win_levels': observation['win_levels'],
            'origin_level': observation['current_level'], 'game_identity': identity, 'initial': deepcopy(observation),
            'initial_digest': digest(observation), 'steps': []}


def append_step(record: dict, action: str, data: dict, observation: dict) -> None:
    if len(record['steps']) >= MAX_STEPS:
        raise ManualSaveError('manual-save-limit')
    record['steps'].append({'action': action, 'data': deepcopy(data),
                            'observation': deepcopy(observation), 'digest': digest(observation)})


class ManualSaveStore:
    def __init__(self, root: Path):
        self.root = Path(root).absolute()

    def _directory(self, create=False):
        # Operator-owned location, with no symlink traversal at any component.
        for part in (self.root, *self.root.parents):
            if part.is_symlink():
                raise ManualSaveError('manual-save-invalid')
        if create:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.exists() and not self.root.is_dir():
            raise ManualSaveError('manual-save-invalid')

    def _path(self, game_id, level):
        if (type(game_id) is not str or not _GAME.fullmatch(game_id)
                or type(level) is not int or not 1 <= level <= 100):
            raise ManualSaveError('manual-save-invalid')
        path = self.root / f'{game_id}--{level}.json'
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ManualSaveError('manual-save-invalid')
        return path

    def levels(self, game_id: str) -> list[int]:
        try:
            self._directory()
            if not self.root.exists():
                return []
            values = []
            for level in range(1, 101):
                if self._path(game_id, level).exists():
                    values.append(level)
            return values
        except OSError:
            raise ManualSaveError('manual-save-failed') from None

    def load(self, game_id: str, wins: int, level: int, observation_validator, identity: str) -> dict | None:
        try:
            self._directory()
            path = self._path(game_id, level)
            if not path.exists():
                return None
            with path.open('rb') as source:
                raw = source.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError
            record = json.loads(raw)
            if (type(record) is not dict or set(record) != {'schema', 'sdk', 'seed', 'game_id',
                    'win_levels', 'origin_level', 'game_identity', 'initial', 'initial_digest', 'steps'}
                    or record['game_identity'] != identity or record['schema'] != SCHEMA or record['sdk'] != SDK
                    or type(record['seed']) is not int or record['seed'] != 0
                    or record['game_id'] != game_id or type(record['win_levels']) is not int
                    or record['win_levels'] != wins or type(record['origin_level']) is not int
                    or not 1 <= record['origin_level'] <= wins or type(record['steps']) is not list
                    or len(record['steps']) > MAX_STEPS):
                raise ValueError
            value = observation_validator(record['initial'], game_id, wins)
            if (value != record['initial'] or value['current_level'] != record['origin_level']
                    or value['state'] != 'NOT_FINISHED' or value['levels_completed'] != 0
                    or record['initial_digest'] != digest(value)):
                raise ValueError
            for step in record['steps']:
                if (type(step) is not dict or set(step) != {'action', 'data', 'observation', 'digest'}
                        or step['action'] not in ('RESET', *(f'ACTION{i}' for i in range(1, 8)))
                        or type(step['data']) is not dict or type(step['digest']) is not str
                        or not _DIGEST.fullmatch(step['digest'])):
                    raise ValueError
                actions = [] if value['state'] == 'WIN' else ['RESET']
                if value['state'] == 'NOT_FINISHED':
                    actions.extend(f'ACTION{i}' for i in value['available_actions'])
                if step['action'] not in actions:
                    raise ValueError
                data = step['data']
                if step['action'] == 'ACTION6':
                    if (set(data) != {'x', 'y'} or any(type(v) is not int for v in data.values())
                            or not 0 <= data['y'] < len(value['frame'])
                            or not 0 <= data['x'] < len(value['frame'][0])):
                        raise ValueError
                elif data:
                    raise ValueError
                value = observation_validator(step['observation'], game_id, wins)
                if value != step['observation'] or step['digest'] != digest(value):
                    raise ValueError
            if value['current_level'] != level:
                raise ValueError
            return record
        except ManualSaveError:
            raise
        except (OSError, ValueError, TypeError, KeyError, IndexError, RecursionError):
            raise ManualSaveError('manual-save-invalid') from None

    def write(self, record: dict, *, retain_previous: bool = False) -> None:
        temporary = backup = None
        replaced = committed = False
        try:
            self._directory(create=True)
            value = record['steps'][-1]['observation'] if record['steps'] else record['initial']
            path = self._path(record['game_id'], value['current_level'])
            raw = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
            if len(record['steps']) > MAX_STEPS or len(raw) > MAX_BYTES:
                raise ManualSaveError('manual-save-limit')
            fd, temporary = tempfile.mkstemp(prefix='.human-', dir=self.root)
            with os.fdopen(fd, 'wb') as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            if retain_previous and path.exists():
                backup_fd, backup = tempfile.mkstemp(prefix='.human-', dir=self.root)
                os.close(backup_fd)
                os.unlink(backup)
                os.link(path, backup)
            os.replace(temporary, path)
            replaced = True
            temporary = None
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            committed = True
        except ManualSaveError:
            raise
        except (OSError, ValueError, TypeError, KeyError):
            raise ManualSaveError('manual-save-failed') from None
        finally:
            if retain_previous and replaced and not committed:
                # A restart does not publish a replacement until directory
                # fsync succeeds. Restore the old inode on any earlier failure.
                try:
                    if backup is None:
                        os.unlink(path)
                    else:
                        os.rename(backup, path)
                        backup = None
                except OSError:
                    raise ManualSaveError('manual-save-failed') from None
            if backup is not None:
                try:
                    os.unlink(backup)
                except OSError:
                    pass
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def ensure_room(self, record: dict) -> None:
        raw = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        if len(record['steps']) >= MAX_STEPS or len(raw) + MAX_STEP_BYTES > MAX_BYTES:
            raise ManualSaveError('manual-save-limit')
