"""Fresh offline ARC replay adapter for generic route optimization."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

from .broker import ArcAction, _canonical_action, _engine_identity, _snapshot_observation
from .game import P7GameSelection
from .optimizer import PlannerAction, RouteResult, RouteCandidate, optimize_route
from .replay import _step


class ArcReplayOracle:
    """Replay each candidate in a newly created engine, closing it on failure."""

    def __init__(self, *, game: P7GameSelection, engine_factory: Callable[[], object]) -> None:
        if type(game) is not P7GameSelection or not callable(engine_factory):
            raise ValueError("offline replay is unavailable")
        self.game = game
        self.engine_factory = engine_factory

    def replay(self, actions: tuple[PlannerAction, ...]) -> RouteResult:
        identity = (self.game.game_id, self.game.seed)
        count = 0
        state = "UNAVAILABLE"
        engine = None
        try:
            if type(actions) is not tuple or len(actions) > self.game.action_cap:
                raise ValueError
            engine = self.engine_factory()
            _engine_identity(engine, self.game)
            current = _snapshot_observation(engine.observe(), win_levels=self.game.win_levels)
            state = current.state
            if current.levels_completed != 0 or state != "NOT_FINISHED":
                raise ValueError
            for action in actions:
                if type(action) is not PlannerAction:
                    raise ValueError
                canonical = _canonical_action(ArcAction(action.name, action.data))
                if canonical.name == "RESET" or canonical.name not in current.available_actions:
                    raise ValueError
                previous = current
                current = _snapshot_observation(
                    _step(engine, canonical), win_levels=self.game.win_levels
                )
                count += 1
                state = current.state
                if not previous.levels_completed <= current.levels_completed <= previous.levels_completed + 1:
                    raise ValueError
                if state == "WIN" and current.levels_completed != self.game.win_levels:
                    raise ValueError
                if count != len(actions) and (
                    current.levels_completed >= self.game.target_level
                    or state in {"WIN", "GAME_OVER"}
                ):
                    raise ValueError
            success = (
                count == len(actions)
                and current.levels_completed == self.game.target_level
                and state != "GAME_OVER"
                and (not self.game.is_full_game or state == "WIN")
            )
            return RouteResult(success, count, state, identity)
        except BaseException:
            return RouteResult(False, count, state, identity)
        finally:
            if engine is not None:
                try:
                    close = getattr(engine, "close", None)
                    if callable(close):
                        close()
                except BaseException:
                    pass


def optimize_arc_route(
    *,
    game: P7GameSelection,
    arc_root: Path,
    route: tuple[PlannerAction, ...],
    candidate_budget: int = 128,
    max_removed: int = 3,
    replacements: tuple[PlannerAction, ...] = (),
) -> RouteCandidate:
    """Explicit offline entry point; each candidate receives a fresh ARC SDK game."""

    from .live import ArcadeEngine

    with TemporaryDirectory(prefix="asterion-p7-route-") as directory:
        def create_engine() -> ArcadeEngine:
            return ArcadeEngine(
                arc_root=arc_root,
                recordings_dir=Path(directory),
                game=game,
            )

        return optimize_route(
            route,
            ArcReplayOracle(game=game, engine_factory=create_engine),
            identity=(game.game_id, game.seed),
            candidate_budget=candidate_budget,
            max_removed=max_removed,
            replacements=replacements,
        )


__all__ = ("ArcReplayOracle", "optimize_arc_route")
