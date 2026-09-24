"""Fresh-engine verification of native P7 broker evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

from .broker import (
    ArcAction,
    ArcBrokerError,
    ArcRunReceipt,
    ArcTransition,
    _engine_identity,
    _canonical_action,
    _observation_digest,
    _snapshot_observation,
)
from .game import DEFAULT_GAME, P7GameSelection
from .score import P7_ACTION_CAP, replay_sha256


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


def replay_arc_run(
    journal: object,
    receipt: object,
    engine_factory: Callable[[], object],
    *,
    game: P7GameSelection = DEFAULT_GAME,
) -> ArcRunReceipt:
    """Require a fresh adapter to reproduce every state digest and terminal count."""

    if (
        type(receipt) is not ArcRunReceipt
        or type(journal) is not tuple
        or not callable(engine_factory)
        or type(game) is not P7GameSelection
        or receipt.game_id != game.game_id
        or receipt.seed != game.seed
        or not 0 <= receipt.primitive_actions <= P7_ACTION_CAP
        or not 0 <= receipt.levels_completed <= game.target_level
        or receipt.terminal_reason not in {"level-completed", "action-cap", "game-over"}
        or (receipt.terminal_reason == "level-completed") != (
            receipt.levels_completed == game.target_level
        )
        or (
            receipt.terminal_reason == "action-cap"
            and not (
                receipt.primitive_actions == P7_ACTION_CAP
                and receipt.levels_completed < game.target_level
            )
        )
        or (
            receipt.terminal_reason == "game-over"
            and not (
                1 <= receipt.primitive_actions < P7_ACTION_CAP
                and receipt.levels_completed < game.target_level
            )
        )
        or len(journal) != receipt.primitive_actions
    ):
        raise ArcBrokerError("unavailable")
    engine = None
    try:
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
            if _observation_digest(current) != transition.before_sha256:
                raise ValueError
            after = _snapshot_observation(
                _step(engine, action), win_levels=game.win_levels
            )
            if (
                _observation_digest(after) != transition.after_sha256
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
            or (receipt.terminal_reason == "level-completed" and current.levels_completed != game.target_level)
            or replay_sha256(journal, terminal_reason=receipt.terminal_reason) != receipt.replay_sha256
            or (receipt.terminal_reason == "action-cap" and receipt.primitive_actions != P7_ACTION_CAP)
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
