"""Bounded observation witnesses emitted by fresh ARC replay."""

from __future__ import annotations

import unittest

from asterion.applications.prime.p7.game import P7GameSelection
from asterion.applications.prime.p7.optimizer import PlannerAction
from asterion.applications.prime.p7.optimizer_arc import ArcReplayOracle


GAME = P7GameSelection("aa11-bb22", 0, 1, (5,), 1)
A = PlannerAction("ACTION1")
B = PlannerAction("ACTION2")


class WitnessEngine:
    game_id = GAME.game_id
    seed = GAME.seed

    def __init__(self) -> None:
        self.actions: list[str] = []
        self.closed = False

    def observe(self) -> dict[str, object]:
        won = self.actions == ["ACTION1", "ACTION2"]
        return {
            "available_actions": [1, 2],
            "frame": [[[len(self.actions)]]],
            "levels_completed": int(won),
            "state": "WIN" if won else "NOT_FINISHED",
            "win_levels": 1,
        }

    def step(self, name: str) -> dict[str, object]:
        self.actions.append(name)
        return self.observe()

    def close(self) -> None:
        self.closed = True


class TestArcReplayWitness(unittest.TestCase):
    def test_incomplete_replay_is_marked_complete_only_after_all_actions(self) -> None:
        oracle = ArcReplayOracle(game=GAME, engine_factory=WitnessEngine)
        result = oracle.replay((A,))
        self.assertFalse(result.success)
        self.assertTrue(result.replay_complete)
        self.assertEqual(len(result.expectations), 1)
        self.assertEqual(result.expectations[0].action, "ACTION1")
        self.assertEqual(result.action_count, 1)

    def test_witness_contains_initial_warmup_boundary_and_each_candidate_step(self) -> None:
        engines: list[WitnessEngine] = []

        def make() -> WitnessEngine:
            engine = WitnessEngine()
            engines.append(engine)
            return engine

        oracle = ArcReplayOracle(game=GAME, engine_factory=make, warmup=(A,))
        result = oracle.replay((B,))

        self.assertTrue(result.success)
        witness = result.observation_witness
        self.assertEqual([item.kind for item in witness], ["initial", "warmup-boundary", "candidate"])
        self.assertEqual([item.action_index for item in witness], [0, 0, 1])
        self.assertEqual([item.levels_completed for item in witness], [0, 0, 1])
        self.assertEqual([item.state for item in witness], ["NOT_FINISHED", "NOT_FINISHED", "WIN"])
        self.assertEqual(len(result.expectations), 1)
        for item in witness:
            self.assertRegex(item.observation_sha256, r"^sha256:[0-9a-f]{64}$")
            self.assertNotIn("frame", repr(item))
            self.assertNotIn("path", repr(item).lower())
        self.assertTrue(engines[0].closed)

    def test_witness_is_bounded_and_excludes_observation_payload(self) -> None:
        oracle = ArcReplayOracle(game=GAME, engine_factory=WitnessEngine)
        result = oracle.replay((A, B))
        replayed = oracle.replay((A, B))

        self.assertEqual(result.observation_witness, replayed.observation_witness)
        self.assertEqual(len(result.observation_witness), 3)
        self.assertEqual(len(result.expectations), 2)
        for item in result.observation_witness:
            self.assertEqual(set(item.__dataclass_fields__), {
                "kind", "action_index", "observation_sha256", "levels_completed", "state",
            })
            self.assertIsInstance(item.action_index, int)
            self.assertIsInstance(item.levels_completed, int)
            self.assertIsInstance(item.state, str)
            self.assertNotIn("/", repr(item))


if __name__ == "__main__":
    unittest.main()
