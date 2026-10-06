"""One read-only initial observation from an isolated, finite offline engine."""

from copy import deepcopy
from pathlib import Path

from .console_manual import _observation, _snapshot, _Worker


class ConsolePreviewError(ValueError):
    """A fixed public-safe initial-preview error."""


class _PreviewWorker(_Worker):
    def observe(self) -> dict:
        return self._read(seconds=8)


def preview_snapshot(observation: dict, selected_level: int) -> dict:
    """Project one validated initial observation without constructing an engine."""
    value = _snapshot(observation, 0, 0)
    value['run'].update(status='preview', seed=0, target_level=selected_level)
    level = value['levels'][0]
    level['status'] = 'preview'
    level['frames'][0]['id'] = 'preview-initial'
    # Position context only; zero completed levels cannot establish a score.
    level['frames'][0]['levels_completed'] = selected_level - 1
    level['cognition'] = {'scope': 'unavailable', 'updates': []}
    return deepcopy(value)


def build_preview_observation(arc_root: Path, game: dict, selected_level: int = 1, *, worker_factory=_PreviewWorker) -> dict:
    # The existing worker clears the environment, bounds its initial read, and
    # owns an ephemeral recording directory. Never activate a HUMAN controller
    # or send a game action; close its engine and recordings after this one read.
    worker = None
    try:
        if type(selected_level) is not int or not 1 <= selected_level <= game['win_levels']:
            raise ValueError
        worker = worker_factory(arc_root, game['game_id'], selected_level)
        observation = _observation(worker.observe(), game['game_id'], game['win_levels'])
        if (observation['current_level'] != selected_level or observation['levels_completed'] != 0
                or observation['state'] != 'NOT_FINISHED'):
            raise ValueError
        return deepcopy(observation)
    except Exception:
        raise ConsolePreviewError('preview-unavailable') from None
    finally:
        if worker is not None:
            try:
                worker.close()
            except Exception:
                raise ConsolePreviewError('preview-unavailable') from None


def build_preview_snapshot(arc_root: Path, game: dict, selected_level: int = 1, *, worker_factory=_PreviewWorker) -> dict:
    return preview_snapshot(build_preview_observation(arc_root, game, selected_level,
                                                     worker_factory=worker_factory), selected_level)
