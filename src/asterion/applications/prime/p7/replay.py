"""Fresh-engine verification of native P7 broker evidence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Protocol, cast

from .broker import (
    ArcAction,
    ArcObservation,
    ArcBrokerError,
    ArcRunReceipt,
    ArcTransition,
    _engine_identity,
    _canonical_action,
    _observation_digest,
    _snapshot_observation,
)
from .game import DEFAULT_GAME, P7GameSelection
from .score import replay_sha256


class _ArcEngine(Protocol):
    def observe(self) -> object: ...


def _step(engine: object, action: ArcAction) -> object:
    step = getattr(engine, "step", None)
    if callable(step):
        if action.data:
            return step(action.name, dict(action.data))
        return step(action.name)
    act = getattr(engine, "act", None)
    if not callable(act):
        raise ValueError
    return act({"name": action.name, "data": dict(action.data)})


def authenticate_observations(
    journal: tuple[ArcTransition, ...], observations: tuple[ArcObservation, ...],
) -> tuple[ArcObservation, ...]:
    """Bind complete recorded observations to every immutable transition digest."""
    if type(observations) is not tuple or len(observations) != len(journal) + 1:
        raise ValueError
    if any(type(value) is not ArcObservation for value in observations):
        raise ValueError
    hashes = tuple(_observation_digest(value) for value in observations)
    for index, transition in enumerate(journal):
        if (transition.sequence != index + 1
                or hashes[index] != transition.before_sha256
                or hashes[index + 1] != transition.after_sha256
                or observations[index + 1].levels_completed != transition.levels_completed):
            raise ValueError
    return observations


def observations_match(actual: ArcObservation, expected: ArcObservation) -> bool:
    """Compare settled state and all metadata, retaining animation dimensions.

    Callers must authenticate expected observations against their original full
    transition hashes first. Only intermediate pixel values may vary.
    """
    return (
        len(actual.frame) == len(expected.frame)
        and all(tuple(map(len, left)) == tuple(map(len, right))
                for left, right in zip(actual.frame, expected.frame))
        and replace(actual, frame=(actual.frame[-1],))
        == replace(expected, frame=(expected.frame[-1],))
    )


def observation_matches_digest(
    actual: ArcObservation, digest: str, expected: ArcObservation | None = None,
) -> bool:
    if expected is not None and _observation_digest(expected) != digest:
        return False
    return (_observation_digest(actual) == digest
            or (expected is not None and observations_match(actual, expected)))


def replay_arc_run(
    journal: object,
    receipt: object,
    engine_factory: Callable[[], object],
    *,
    game: P7GameSelection = DEFAULT_GAME,
    observations: tuple[ArcObservation, ...] | None = None,
) -> ArcRunReceipt:
    """Require a fresh adapter to reproduce every state digest and terminal count."""

    if (
        type(receipt) is not ArcRunReceipt
        or type(journal) is not tuple
        or not callable(engine_factory)
        or type(game) is not P7GameSelection
        or receipt.game_id != game.game_id
        or receipt.seed != game.seed
        or not 0 <= receipt.primitive_actions <= game.action_cap
        or not 0 <= receipt.levels_completed <= game.target_level
        or receipt.terminal_reason not in (
            ({"game-won", "game-incomplete", "action-cap", "game-over"}
             if game.is_full_game else {"level-completed", "action-cap", "game-over"})
            | ({"human-baseline"} if game.action_cap_override is not None else set())
            | {"interrupted"}
        )
        or (receipt.terminal_reason in {"level-completed", "game-won", "game-incomplete"}) != (
            receipt.levels_completed == game.target_level
        )
        or (
            receipt.terminal_reason in {"action-cap", "human-baseline"}
            and not (
                receipt.primitive_actions == game.action_cap
                and receipt.levels_completed < game.target_level
            )
        )
        or (
            receipt.terminal_reason == "game-over"
            and not (
                1 <= receipt.primitive_actions < game.action_cap
                and receipt.levels_completed < game.target_level
            )
        )
        or len(journal) != receipt.primitive_actions
        or (receipt.terminal_reason == "interrupted" and not (
            1 <= receipt.primitive_actions < game.action_cap
            and receipt.levels_completed < game.target_level
        ))
    ):
        raise ArcBrokerError("unavailable")
    engine = None
    try:
        if observations is not None:
            authenticate_observations(journal, observations)
        engine = cast(_ArcEngine, engine_factory())
        _engine_identity(engine, game)
        current = _snapshot_observation(engine.observe(), win_levels=game.win_levels)
        if current.levels_completed != 0 or current.state != "NOT_FINISHED":
            raise ValueError
        level_gameplay_actions = 0
        for sequence, transition in enumerate(journal, 1):
            if type(transition) is not ArcTransition or transition.sequence != sequence:
                raise ValueError
            action = _canonical_action(ArcAction(transition.action, transition.data))
            if action.name == "RESET":
                if level_gameplay_actions == 0:
                    raise ValueError
            elif current.state == "GAME_OVER" or action.name not in current.available_actions:
                raise ValueError
            if not observation_matches_digest(current, transition.before_sha256,
                    None if observations is None else observations[sequence - 1]):
                raise ValueError
            after = _snapshot_observation(
                _step(engine, action), win_levels=game.win_levels
            )
            if (
                not observation_matches_digest(after, transition.after_sha256,
                    None if observations is None else observations[sequence])
                or after.levels_completed != transition.levels_completed
                or (action.name == "RESET" and (after.levels_completed != current.levels_completed or after.state != "NOT_FINISHED"))
                or (action.name != "RESET" and (after.levels_completed < current.levels_completed or after.levels_completed > current.levels_completed + 1))
            ):
                raise ValueError
            if action.name == "RESET" or after.levels_completed > current.levels_completed:
                level_gameplay_actions = 0
            else:
                level_gameplay_actions += 1
            current = after
            if current.levels_completed >= game.target_level and sequence != len(journal):
                raise ValueError
        if (
            current.levels_completed != receipt.levels_completed
            or (receipt.terminal_reason == "game-over" and current.state != "GAME_OVER")
            or (receipt.terminal_reason == "game-won" and current.state != "WIN")
            or (receipt.terminal_reason == "game-incomplete" and current.state == "WIN")
            or (receipt.terminal_reason == "interrupted" and current.state != "NOT_FINISHED")
            or (receipt.terminal_reason in {"level-completed", "game-won", "game-incomplete"} and current.levels_completed != game.target_level)
            or replay_sha256(journal, terminal_reason=receipt.terminal_reason) != receipt.replay_sha256
            or (receipt.terminal_reason in {"action-cap", "human-baseline"} and receipt.primitive_actions != game.action_cap)
        ):
            raise ValueError
        return receipt
    except ArcBrokerError:
        raise
    except BaseException:
        raise ArcBrokerError("unavailable") from None
    finally:
        try:
            close = getattr(engine, "close", None)
            if callable(close):
                close()
        except BaseException:
            pass


__all__ = ("replay_arc_run",)
