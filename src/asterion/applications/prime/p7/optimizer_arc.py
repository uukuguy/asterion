"""Fresh offline ARC replay adapter for generic route optimization."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

from .broker import (
    ArcAction,
    _canonical_action,
    _engine_identity,
    _observation_digest,
    _snapshot_observation,
)
from .game import P7GameSelection
from .optimizer import (
    ObservationWitness,
    PlannerAction,
    RouteCandidate,
    RouteResult,
    _route_digest,
    optimize_partial_route,
    optimize_route,
)
from .replay import _step
from .score import digest
from .transition_model import ActionExpectation
from .verified_history import stable_changed_cells


class ArcReplayOracle:
    """Replay each candidate in a newly created engine, closing it on failure."""

    def __init__(
        self,
        *,
        game: P7GameSelection,
        engine_factory: Callable[[], object],
        warmup: tuple[PlannerAction, ...] = (),
    ) -> None:
        if (
            type(game) is not P7GameSelection
            or not callable(engine_factory)
            or type(warmup) is not tuple
            or any(type(action) is not PlannerAction for action in warmup)
        ):
            raise ValueError("offline replay is unavailable")
        self.game = game
        self.engine_factory = engine_factory
        self.warmup = warmup

    def replay(self, actions: tuple[PlannerAction, ...]) -> RouteResult:
        identity = (self.game.game_id, self.game.seed)
        count = 0
        state = "UNAVAILABLE"
        observation_witness: list[ObservationWitness] = []
        expectations: list[ActionExpectation] = []
        engine = None
        try:
            if (
                type(actions) is not tuple
                or len(self.warmup) + len(actions) > self.game.action_cap
            ):
                raise ValueError
            engine = self.engine_factory()
            _engine_identity(engine, self.game)
            observe = getattr(engine, "observe", None)
            if not callable(observe):
                raise ValueError
            current = _snapshot_observation(observe(), win_levels=self.game.win_levels)
            state = current.state
            observation_witness.append(
                ObservationWitness(
                    "initial", 0, _observation_digest(current),
                    current.levels_completed, current.state,
                )
            )
            if current.levels_completed != 0 or state != "NOT_FINISHED":
                raise ValueError
            level_actions = 0

            def apply(action: PlannerAction, *, count_action: bool) -> None:
                nonlocal current, count, state, level_actions
                if type(action) is not PlannerAction:
                    raise ValueError
                canonical = _canonical_action(ArcAction(action.name, action.data))
                if canonical.name != "RESET" and canonical.name not in current.available_actions:
                    raise ValueError
                previous = current
                current = _snapshot_observation(
                    _step(engine, canonical), win_levels=self.game.win_levels
                )
                _total_changed, changed_cells, _omitted = stable_changed_cells(
                    previous.frame[-1], current.frame[-1]
                )
                if count_action:
                    count += 1
                    observation_witness.append(
                        ObservationWitness(
                            "candidate", count, _observation_digest(current),
                            current.levels_completed, current.state,
                        )
                    )
                    expectations.append(
                        ActionExpectation(
                            action=canonical.name,
                            data=canonical.data,
                            prior_state_sha256=_observation_digest(previous),
                            after_state_sha256=_observation_digest(current),
                            after_frame_sha256=digest(current.frame[-1]),
                            changed_cells=changed_cells,
                            levels_completed=current.levels_completed,
                            state=current.state,
                        )
                    )
                state = current.state
                if canonical.name == "RESET":
                    if level_actions == 0 or current.levels_completed != previous.levels_completed or state != "NOT_FINISHED":
                        raise ValueError
                    level_actions = 0
                    return
                if not previous.levels_completed <= current.levels_completed <= previous.levels_completed + 1:
                    raise ValueError
                level_actions += 1
                if current.levels_completed > previous.levels_completed:
                    level_actions = 0
                if state == "WIN" and current.levels_completed != self.game.win_levels:
                    raise ValueError

            for action in self.warmup:
                apply(action, count_action=False)
            if self.warmup:
                observation_witness.append(
                    ObservationWitness(
                        "warmup-boundary", 0, _observation_digest(current),
                        current.levels_completed, current.state,
                    )
                )
            if (
                self.warmup
                and current.levels_completed != self.game.target_level - 1
            ):
                raise ValueError
            for action in actions:
                apply(action, count_action=True)
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
            return RouteResult(
                success, count, state, identity, tuple(observation_witness), True,
                tuple(expectations),
            )
        except BaseException:
            return RouteResult(
                False, count, state, identity, tuple(observation_witness), False,
                tuple(expectations),
            )
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
    warmup: tuple[PlannerAction, ...] = (),
    time_budget_seconds: float | None = None,
    preserve_terminal_observation: bool = False,
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

        optimizer = optimize_partial_route if preserve_terminal_observation else optimize_route
        kwargs = {
            "identity": (game.game_id, game.seed),
            "candidate_budget": candidate_budget,
            "max_removed": max_removed,
            "replacements": replacements,
            "time_budget_seconds": time_budget_seconds,
            "target_level": game.target_level,
            "warmup_digest": _route_digest(warmup),
        }
        if not preserve_terminal_observation:
            return optimizer(route, ArcReplayOracle(game=game, engine_factory=create_engine, warmup=warmup), **kwargs)
        return optimizer(
            route,
            ArcReplayOracle(game=game, engine_factory=create_engine, warmup=warmup),
            **kwargs,
        )


__all__ = ("ArcReplayOracle", "optimize_arc_route")
