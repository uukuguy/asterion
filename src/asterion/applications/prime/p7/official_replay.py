"""One-shot replay of an already verified local prefix on an official engine."""

from __future__ import annotations

from typing import Any

from .broker import ArcAction, ArcTransition, _canonical_action, _observation_digest, _snapshot_observation
from .solutions import VerifiedPrefix


class OfficialReplayError(RuntimeError):
    """A fixed, public-safe failure while dispatching saved official actions."""


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


def execute_saved_prefix(engine: object, prefix: VerifiedPrefix) -> None:
    """Dispatch a verified prefix once, failing closed on every observation mismatch.

    ``engine`` is already created by ``CompetitionSession.make``.  This function
    deliberately never calls reset, make, close, or any model-facing service.
    """
    try:
        verified = _validate_prefix(engine, prefix)
        current = _snapshot(engine.observe(), win_levels=verified.win_levels)
        if current.levels_completed != 0 or current.state != "NOT_FINISHED":
            raise ValueError
        for sequence, transition in enumerate(verified.transitions, 1):
            if type(transition) is not ArcTransition or transition.sequence != sequence:
                raise ValueError
            action = _canonical_action(ArcAction(transition.action, transition.data))
            if action.name == "RESET" or action.name not in current.available_actions:
                raise ValueError
            if _observation_digest(current) != transition.before_sha256:
                raise ValueError
            after_raw = engine.step(action.name, dict(action.data) if action.data else None)
            after = _snapshot(after_raw, win_levels=verified.win_levels)
            if (
                _observation_digest(after) != transition.after_sha256
                or after.levels_completed != transition.levels_completed
                or after.levels_completed < current.levels_completed
                or after.levels_completed > current.levels_completed + 1
                or (after.levels_completed >= verified.levels_completed and sequence != len(verified.transitions))
            ):
                raise ValueError
            current = after
        if current.levels_completed != verified.levels_completed:
            raise ValueError
    except Exception:
        raise OfficialReplayError("official saved replay unavailable") from None


__all__ = ("OfficialReplayError", "execute_saved_prefix")
