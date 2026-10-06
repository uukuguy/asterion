"""Operator-prepared initial views; ready requests never construct game engines.

The closed normalized observation contains no history, score, cognition, or
provider data. SHA detects incomplete/corrupt derivatives under existing
operator ownership; source game identity binds freshness, not authority.
"""
from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import re
import stat

from .console_manual import _observation
from .console_manual_saves import SDK, digest, game_identity
from .console_preview import (ConsolePreviewError, _PreviewWorker,
                              build_preview_observation, preview_snapshot)
from .game import public_game_catalog
from .run_story.storage import write_atomic_file


_SCHEMA = 'asterion.p7-console-initial-preview/v1'
_PROJECTOR = 'asterion.p7-console-initial-projector/v1'
_GAME = re.compile(r'[A-Za-z0-9]+-[A-Za-z0-9]+\Z')
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_MAX_BYTES = 64 * 1024
_FIELDS = {'schema', 'projector', 'sdk', 'game_id', 'game_identity', 'seed', 'level',
           'win_levels', 'observation', 'observation_sha256'}


def _safe(path):
    return not any(part.is_symlink() for part in (path, *path.parents))


def _path(operator_root, game, level):
    if (type(game) is not dict or type(game.get('game_id')) is not str
            or not _GAME.fullmatch(game['game_id']) or type(game.get('win_levels')) is not int
            or not 1 <= game['win_levels'] <= 100 or type(level) is not int
            or not 1 <= level <= game['win_levels']):
        raise ConsolePreviewError('preview-unavailable')
    path = (Path(operator_root).absolute() / '.asterion-private' / 'prime-p7-live'
            / 'console-previews' / f"{game['game_id']}--{level}.json")
    if not _safe(path):
        raise ConsolePreviewError('preview-unavailable')
    return path


def _read(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_BYTES:
            raise ValueError
        raw = source.read(_MAX_BYTES + 1)
        after = os.fstat(source.fileno())
    def stamp(value):
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns
    if (len(raw) > _MAX_BYTES or stamp(before) != stamp(after) or not _safe(path)
            or stamp(after) != stamp(path.stat())):
        raise ValueError
    return json.loads(raw)


def _validated(record, game, level, identity):
    if (type(record) is not dict or set(record) != _FIELDS
            or record['schema'] != _SCHEMA or record['projector'] != _PROJECTOR or record['sdk'] != SDK
            or type(record['seed']) is not int or record['seed'] != 0
            or record['game_id'] != game['game_id'] or record['game_identity'] != identity
            or type(record['level']) is not int or record['level'] != level
            or type(record['win_levels']) is not int or record['win_levels'] != game['win_levels']
            or type(record['observation_sha256']) is not str or not _HEX.fullmatch(record['observation_sha256'])):
        raise ValueError
    observation = _observation(record['observation'], game['game_id'], game['win_levels'])
    if (observation != record['observation'] or observation['current_level'] != level
            or observation['levels_completed'] != 0 or observation['state'] != 'NOT_FINISHED'
            or digest(observation) != record['observation_sha256']):
        raise ValueError
    return observation


def read_prepared_preview(operator_root: Path, arc_root: Path, game: dict, level: int = 1) -> dict:
    """Read only the requested ready artifact, validating source/content afresh."""
    try:
        path = _path(operator_root, game, level)
        identity = game_identity(arc_root, game['game_id'])
        observation = _validated(_read(path), game, level, identity)
        if game_identity(arc_root, game['game_id']) != identity:
            raise ValueError
        return preview_snapshot(observation, level)
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise ConsolePreviewError('preview-unavailable') from None


def prepare_preview(operator_root: Path, arc_root: Path, game: dict, level: int = 1,
                    *, worker_factory=_PreviewWorker) -> bool:
    """Explicit batch-only operation; return True when an existing view was reused."""
    try:
        path = _path(operator_root, game, level)
        try:
            read_prepared_preview(operator_root, arc_root, game, level)
            return True
        except ConsolePreviewError:
            pass
        identity = game_identity(arc_root, game['game_id'])
        # The finite offline worker checks actual SDK versions before its one
        # initial observation. It never receives activation or action commands.
        observation = build_preview_observation(arc_root, game, level, worker_factory=worker_factory)
        record = {'schema': _SCHEMA, 'projector': _PROJECTOR, 'sdk': dict(SDK),
                  'game_id': game['game_id'], 'game_identity': identity, 'seed': 0,
                  'level': level, 'win_levels': game['win_levels'], 'observation': observation,
                  'observation_sha256': digest(observation)}
        _validated(record, game, level, identity)
        raw = json.dumps(record, ensure_ascii=False, allow_nan=False,
                         sort_keys=True, separators=(',', ':')).encode()
        if len(raw) > _MAX_BYTES or not _safe(path) or game_identity(arc_root, game['game_id']) != identity:
            raise ValueError
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_atomic_file(path, raw)
        read_prepared_preview(operator_root, arc_root, game, level)
        return False
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise ConsolePreviewError('preview-unavailable') from None


def prepare_preview_catalog(operator_root: Path, arc_root: Path, *, catalog=None,
                            worker_factory=_PreviewWorker, progress: Callable | None = None) -> dict:
    """Sequential resumable preparation for an explicit bounded catalog, no models."""
    games = tuple(public_game_catalog(arc_root) if catalog is None else catalog)
    if not 1 <= len(games) <= 100:
        raise ConsolePreviewError('preview-unavailable')
    seen = set()
    for game in games:
        _path(operator_root, game, 1)
        if game['game_id'] in seen:
            raise ConsolePreviewError('preview-unavailable')
        seen.add(game['game_id'])
    if sum(game['win_levels'] for game in games) > 2500:
        raise ConsolePreviewError('preview-unavailable')
    results = []
    for game in games:
        for level in range(1, game['win_levels'] + 1):
            row = {'game_id': game['game_id'], 'level': level, 'state': 'ready', 'cached': False}
            try:
                row['cached'] = prepare_preview(operator_root, arc_root, game, level, worker_factory=worker_factory)
            except ConsolePreviewError:
                row['state'] = 'unavailable'
            results.append(row)
            if progress is not None:
                progress(dict(row))
    return {'ready': sum(row['state'] == 'ready' for row in results),
            'failed': sum(row['state'] != 'ready' for row in results),
            'cached': sum(row['cached'] for row in results), 'levels': results}
