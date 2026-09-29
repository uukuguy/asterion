"""Bounded route search and fresh offline P7 replay."""

from __future__ import annotations

import unittest
from unittest import mock

from asterion.applications.prime.p7.game import P7GameSelection
from asterion.applications.prime.p7.optimizer import (
    PlannerAction,
    RouteResult,
    optimize_route,
)
from asterion.applications.prime.p7.optimizer_arc import ArcReplayOracle


GAME = P7GameSelection("aa11-bb22", 0, 1, (5,), 1)
A = PlannerAction("ACTION1")
B = PlannerAction("ACTION2")
C = PlannerAction("ACTION3")


class TableOracle:
    def __init__(self, winners: set[tuple[PlannerAction, ...]]) -> None:
        self.winners = winners
        self.calls: list[tuple[PlannerAction, ...]] = []

    def replay(self, route: tuple[PlannerAction, ...]) -> RouteResult:
        self.calls.append(route)
        return RouteResult(route in self.winners, len(route), "WIN" if route in self.winners else "NOT_FINISHED", (GAME.game_id, GAME.seed))


class FakeEngine:
    def __init__(self, *, game_id: str = GAME.game_id, seed: int = GAME.seed) -> None:
        self.game_id = game_id
        self.seed = seed
        self.actions: list[str] = []
        self.closed = False

    def observe(self) -> dict[str, object]:
        won = self.actions in (["ACTION1", "ACTION2"], ["ACTION1", "ACTION3", "ACTION2"])
        return {
            "available_actions": [1, 2, 3],
            "frame": [[[len(self.actions)]]],
            "levels_completed": 1 if won else 0,
            "state": "WIN" if won else "NOT_FINISHED",
            "win_levels": 1,
        }

    def step(self, name: str) -> dict[str, object]:
        self.actions.append(name)
        return self.observe()

    def close(self) -> None:
        self.closed = True


class MultiLevelFakeEngine:
    def __init__(self) -> None:
        self.game_id = "aa11-bb22"
        self.seed = 0
        self.level = 0
        self.actions: list[str] = []
        self.closed = False

    def observe(self) -> dict[str, object]:
        return {
            "available_actions": [1, 2],
            "frame": [[[self.level, len(self.actions)]]],
            "levels_completed": self.level,
            "state": "WIN" if self.level == 2 else "NOT_FINISHED",
            "win_levels": 2,
        }

    def step(self, name: str) -> dict[str, object]:
        self.actions.append(name)
        if (self.level, name) in {(0, "ACTION1"), (1, "ACTION2")}:
            self.level += 1
        return self.observe()

    def close(self) -> None:
        self.closed = True


class TestRouteOptimizer(unittest.TestCase):
    def test_finds_shorter_route_after_fresh_verification(self) -> None:
        route = (A, C, B)
        oracle = TableOracle({route, (A, B)})
        result = optimize_route(route, oracle, identity=(GAME.game_id, GAME.seed), candidate_budget=8)
        self.assertEqual(result.actions, (A, B))
        self.assertEqual(result.replay.action_count, 2)
        self.assertEqual(route, (A, C, B))

    def test_rejects_shorter_route_without_terminal_success(self) -> None:
        route = (A, B)
        oracle = TableOracle({route})
        result = optimize_route(route, oracle, identity=(GAME.game_id, GAME.seed), candidate_budget=8)
        self.assertEqual(result.actions, route)

    def test_accepts_an_empty_verified_route(self) -> None:
        oracle = TableOracle({()})
        result = optimize_route((), oracle, identity=(GAME.game_id, GAME.seed))
        self.assertEqual(result.actions, ())
        self.assertEqual(result.replay.action_count, 0)

    def test_rejects_mismatched_identity_and_action_count(self) -> None:
        class BadOracle:
            def replay(self, route: tuple[PlannerAction, ...]) -> RouteResult:
                return RouteResult(True, len(route) + 1, "WIN", (GAME.game_id, GAME.seed))

        with self.assertRaises(ValueError):
            optimize_route((A, B), BadOracle(), identity=(GAME.game_id, GAME.seed))

    def test_candidate_budget_includes_baseline(self) -> None:
        route = (A, C, B)
        oracle = TableOracle({route, (A, B)})
        result = optimize_route(route, oracle, identity=(GAME.game_id, GAME.seed), candidate_budget=1)
        self.assertEqual(result.actions, route)
        self.assertEqual(oracle.calls, [route])

    def test_exhausting_candidate_budget_is_not_reported_as_timeout(self) -> None:
        route = (A, C, B)
        oracle = TableOracle({route})
        with mock.patch(
            "asterion.applications.prime.p7.optimizer.time.monotonic",
            side_effect=(0.0, 2.0),
        ):
            result = optimize_route(
                route,
                oracle,
                identity=(GAME.game_id, GAME.seed),
                candidate_budget=1,
                time_budget_seconds=1.0,
            )
        self.assertFalse(result.timed_out)
        self.assertEqual(result.candidates_replayed, 1)

    def test_stops_candidate_search_when_time_budget_expires(self) -> None:
        route = (A, C, B)
        oracle = TableOracle({route, (A, B)})
        with mock.patch(
            "asterion.applications.prime.p7.optimizer.time.monotonic",
            side_effect=(0.0, 0.0, 2.0),
        ):
            result = optimize_route(
                route,
                oracle,
                identity=(GAME.game_id, GAME.seed),
                candidate_budget=8,
                time_budget_seconds=1.0,
            )
        self.assertEqual(result.actions, route)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.candidates_replayed, 1)

    def test_replacement_can_combine_with_deletion_to_shorten_route(self) -> None:
        replacement = PlannerAction("ACTION4")
        route = (A, C, B)
        oracle = TableOracle({route, (A, replacement)})
        result = optimize_route(
            route, oracle, identity=(GAME.game_id, GAME.seed),
            candidate_budget=32, max_removed=1, replacements=(replacement,),
        )
        self.assertEqual(result.actions, (A, replacement))

    def test_arc_oracle_fresh_engine_per_replay_and_closes(self) -> None:
        engines: list[FakeEngine] = []

        def make() -> FakeEngine:
            engine = FakeEngine()
            engines.append(engine)
            return engine

        oracle = ArcReplayOracle(game=GAME, engine_factory=make)
        result = optimize_route((A, C, B), oracle, identity=(GAME.game_id, GAME.seed), candidate_budget=8)
        self.assertEqual(result.actions, (A, B))
        self.assertGreater(len(engines), 1)
        self.assertTrue(all(engine.closed for engine in engines))

    def test_arc_oracle_rejects_wrong_identity_and_closes(self) -> None:
        engine = FakeEngine(game_id="xx11-yy22")
        oracle = ArcReplayOracle(game=GAME, engine_factory=lambda: engine)
        result = oracle.replay((A, B))
        self.assertFalse(result.success)
        self.assertTrue(engine.closed)

    def test_arc_oracle_rejects_reset_before_gameplay(self) -> None:
        engine = FakeEngine()
        oracle = ArcReplayOracle(game=GAME, engine_factory=lambda: engine)
        result = oracle.replay((PlannerAction("RESET"), A, B))
        self.assertFalse(result.success)
        self.assertTrue(engine.closed)

    def test_arc_oracle_warm_starts_target_level_from_verified_prefix(self) -> None:
        game = P7GameSelection("aa11-bb22", 0, 2, (5, 5), 2)
        engines: list[MultiLevelFakeEngine] = []

        def make() -> MultiLevelFakeEngine:
            engine = MultiLevelFakeEngine()
            engines.append(engine)
            return engine

        oracle = ArcReplayOracle(
            game=game,
            engine_factory=make,
            warmup=(PlannerAction("ACTION1"),),
        )
        result = oracle.replay((PlannerAction("ACTION2"),))
        self.assertEqual(result, RouteResult(True, 1, "WIN", (game.game_id, game.seed)))
        self.assertTrue(engines[0].closed)

    def test_arc_oracle_counts_warmup_against_total_action_cap(self) -> None:
        game = P7GameSelection("aa11-bb22", 0, 2, (5, 5), 2, 1)
        oracle = ArcReplayOracle(
            game=game,
            engine_factory=MultiLevelFakeEngine,
            warmup=(PlannerAction("ACTION1"),),
        )
        result = oracle.replay((PlannerAction("ACTION2"),))
        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
