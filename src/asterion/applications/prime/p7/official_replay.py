"""One-shot replay of an already verified local prefix on an official engine."""

from __future__ import annotations

from typing import Any
from collections.abc import Callable

from .broker import ArcAction, ArcTransition, _canonical_action, _snapshot_observation
from .solutions import VerifiedPrefix
from .replay import authenticate_observations, observation_matches_digest


class OfficialReplayError(RuntimeError):
    """A fixed, public-safe failure while dispatching saved official actions."""

    def __init__(self, message='official saved replay unavailable', *, reason='unknown',
                 action_sequence=0, attempted_actions=0, confirmed_actions=0):
        super().__init__(message)
        self.reason = reason
        self.action_sequence = action_sequence
        self.attempted_actions = attempted_actions
        self.confirmed_actions = confirmed_actions


class _CheckpointError(RuntimeError):
    pass


def _snapshot(value: object, *, win_levels: int) -> Any:
    return _snapshot_observation(value, win_levels=win_levels)


def _validate_prefix(engine: object, prefix: object) -> VerifiedPrefix:
    if type(prefix) is not VerifiedPrefix:
        raise ValueError
    if (
        type(prefix.game_id) is not str
        or type(prefix.seed) is not int
        or type(prefix.win_levels) is not int
        or type(prefix.levels_completed) is not int
        or prefix.seed != 0
        or prefix.win_levels < 1
        or not 1 <= prefix.levels_completed <= prefix.win_levels
        or type(prefix.transitions) is not tuple
        or not prefix.transitions
        or type(getattr(engine, "game_id", None)) is not str
        or type(getattr(engine, "seed", None)) is not int
        or type(getattr(engine, "win_levels", None)) is not int
        or getattr(engine, "game_id") != prefix.game_id
        or getattr(engine, "seed") != prefix.seed
        or getattr(engine, "win_levels") != prefix.win_levels
        or not callable(getattr(engine, "observe", None))
        or not callable(getattr(engine, "step", None))
    ):
        raise ValueError
    return prefix


def execute_saved_prefix(engine: object, prefix: VerifiedPrefix, *,
                         progress: Callable[[dict[str, object]], None] | None = None) -> None:
    """Dispatch a verified prefix once, failing closed on every observation mismatch.

    ``engine`` is already created by ``CompetitionSession.make``.  This function
    deliberately never calls reset, make, close, or any model-facing service.
    """
    reason, sequence, attempted, confirmed, current = 'invalid-prefix', 0, 0, 0, None
    observed = None
    def checkpoint(phase, failure=None):
        if progress is not None:
            try:
                progress({'phase': phase, 'reason': failure, 'action_sequence': sequence,
                      'attempted_actions': attempted, 'confirmed_actions': confirmed,
                      'levels_completed': None if observed is None else observed.levels_completed,
                          'state': None if observed is None else observed.state})
            except Exception:
                raise _CheckpointError from None
    try:
        verified = _validate_prefix(engine, prefix)
        observations = verified.observations
        if observations is not None:
            authenticate_observations(verified.transitions, observations)
        reason = 'initial-observation'
        current = _snapshot(engine.observe(), win_levels=verified.win_levels)
        observed = current
        reason = 'initial-state'
        if current.levels_completed != 0 or current.state != "NOT_FINISHED":
            raise ValueError
        checkpoint('replay-started')
        level_gameplay_actions = 0
        for sequence, transition in enumerate(verified.transitions, 1):
            reason = 'transition-invalid'
            if type(transition) is not ArcTransition or transition.sequence != sequence:
                raise ValueError
            reason = 'action-invalid'
            action = _canonical_action(ArcAction(transition.action, transition.data))
            if action.name == "RESET":
                if level_gameplay_actions == 0:
                    raise ValueError
            elif current.state == "GAME_OVER" or action.name not in current.available_actions:
                raise ValueError
            reason = 'before-mismatch'
            if not observation_matches_digest(current, transition.before_sha256,
                    None if observations is None else observations[sequence - 1]):
                raise ValueError
            reason = 'sdk-action-failed'
            checkpoint('action-pending')
            attempted += 1
            after_raw = engine.step(action.name, dict(action.data) if action.data else None)
            reason = 'after-observation'
            after = _snapshot(after_raw, win_levels=verified.win_levels)
            observed = after
            reason = 'after-mismatch'
            if not observation_matches_digest(after, transition.after_sha256,
                    None if observations is None else observations[sequence]):
                raise ValueError
            reason = 'levels-mismatch'
            if (
                after.levels_completed != transition.levels_completed
                or after.levels_completed < current.levels_completed
                or after.levels_completed > current.levels_completed + 1
                or (after.levels_completed >= verified.levels_completed and sequence != len(verified.transitions))
            ):
                raise ValueError
            if action.name == "RESET":
                reason = 'reset-mismatch'
                if after.levels_completed != current.levels_completed or after.state != "NOT_FINISHED":
                    raise ValueError
                level_gameplay_actions = 0
            elif after.levels_completed > current.levels_completed:
                level_gameplay_actions = 0
            else:
                level_gameplay_actions += 1
            current = after
            confirmed += 1
            checkpoint('action-confirmed')
        reason = 'terminal-mismatch'
        if current.levels_completed != verified.levels_completed:
            raise ValueError
        checkpoint('replay-completed')
    except Exception as error:
        # Adapter categories are fixed enums, never the native exception text.
        if isinstance(error, _CheckpointError):
            reason = 'progress-unavailable'
        elif reason in ('initial-observation', 'sdk-action-failed') and getattr(error, 'reason', None) in {
                'sdk-action-failed', 'identity-mismatch', 'observation-invalid', 'levels-regressed', 'action-invalid'}:
            reason = error.reason
        try:
            checkpoint('replay-failed', reason)
        except Exception:
            pass
        raise OfficialReplayError(reason=reason, action_sequence=sequence,
                                  attempted_actions=attempted, confirmed_actions=confirmed) from None


__all__ = ("OfficialReplayError", "execute_saved_prefix")
