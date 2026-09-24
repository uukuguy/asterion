"""Fresh-engine verification of native P7 broker evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

from .broker import (
    ArcBrokerError,
    ArcRunReceipt,
    ArcTransition,
    _engine_identity,
    _observation_digest,
    _snapshot_observation,
)
from .game import DEFAULT_GAME, P7GameSelection
from .score import P7_ACTION_CAP, replay_sha256


class _ArcEngine(Protocol):
    def observe(self) -> object: ...


def _step(engine: object, action: str) -> object:
    step = getattr(engine, "step", None)
    if callable(step):
        return step(action)
    act = getattr(engine, "act", None)
    if not callable(act):
        raise ValueError
    return act({"name": action, "data": {}})


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
        or receipt.levels_completed not in (0, 1)
        or receipt.terminal_reason not in {"level-completed", "action-cap", "game-over"}
        or (receipt.terminal_reason == "level-completed") != (receipt.levels_completed == 1)
        or (
            receipt.terminal_reason == "action-cap"
            and not (receipt.primitive_actions == P7_ACTION_CAP and receipt.levels_completed == 0)
        )
        or (
            receipt.terminal_reason == "game-over"
            and not (1 <= receipt.primitive_actions <= P7_ACTION_CAP and receipt.levels_completed == 0)
        )
        or len(journal) != receipt.primitive_actions
    ):
        raise ArcBrokerError("unavailable")
    engine = None
    try:
        engine = cast(_ArcEngine, engine_factory())
        _engine_identity(engine, game)
        current = _snapshot_observation(engine.observe(), win_levels=game.win_levels)
        if current.levels_completed != 0:
            raise ValueError
        for sequence, transition in enumerate(journal, 1):
            if type(transition) is not ArcTransition or transition.sequence != sequence:
                raise ValueError
            if _observation_digest(current) != transition.before_sha256:
                raise ValueError
            after = _snapshot_observation(
                _step(engine, transition.action), win_levels=game.win_levels
            )
            if (
                _observation_digest(after) != transition.after_sha256
                or after.levels_completed != transition.levels_completed
                or after.levels_completed < current.levels_completed
                or after.levels_completed > current.levels_completed + 1
            ):
                raise ValueError
            current = after
            if current.levels_completed > 0 and sequence != len(journal):
                raise ValueError
            if current.state == "GAME_OVER" and sequence != len(journal):
                raise ValueError
        if (
            current.levels_completed != receipt.levels_completed
            or (receipt.terminal_reason == "game-over") != (
                current.state == "GAME_OVER" and current.levels_completed == 0
            )
            or replay_sha256(journal, terminal_reason=receipt.terminal_reason) != receipt.replay_sha256
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
