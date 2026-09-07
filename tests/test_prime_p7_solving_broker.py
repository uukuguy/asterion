from __future__ import annotations

import unittest
from unittest.mock import patch


class FakeEngine:
    def __init__(self, *, complete_on: int | None = 2) -> None:
        self.complete_on = complete_on
        self.calls: list[dict[str, object]] = []
        self.completed = 0

    def observe(self) -> dict[str, object]:
        return {
            "available_actions": [1, 2, 3, 4, 5, 6, 7],
            "frame": [[[0, 1], [2, 3]]],
            "levels_completed": self.completed,
            "state": "NOT_FINISHED",
            "win_levels": 7,
        }

    def act(self, action: dict[str, object]) -> dict[str, object]:
        self.calls.append(action)
        if self.complete_on == len(self.calls):
            self.completed += 1
        value = self.observe()
        value["frame"] = [[[len(self.calls) % 10, 1], [2, 3]]]
        return value

    def close(self) -> None:
        pass


def request(token: str, sequence: int, method: str, data: object) -> dict[str, object]:
    return {"data": data, "method": method, "sequence": sequence, "token": token}


class TestP7SolvingBroker(unittest.TestCase):
    def test_read_only_calls_do_not_consume_action_authority(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_broker import (
            P7SolvingBroker,
        )

        engine = FakeEngine(complete_on=None)
        broker = P7SolvingBroker(engine=engine, token="secret")
        for sequence, method in enumerate(
            ("observe", "observe", "status", "status"), 1
        ):
            result = broker.request(request("secret", sequence, method, {}))
            self.assertEqual(result["actions_taken"], 0)
            self.assertEqual(result["terminal"], "ACTIVE")
        self.assertEqual(engine.calls, [])

    def test_batch_stops_at_first_level_transition(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_broker import (
            P7SolvingBroker,
            P7SolvingBrokerError,
        )

        engine = FakeEngine()
        broker = P7SolvingBroker(engine=engine, token="secret")
        actions = [{"data": {}, "name": f"ACTION{i}"} for i in (1, 2, 3)]
        result = broker.request(request("secret", 1, "act", {"actions": actions}))
        self.assertEqual(result["actions_taken"], 2)
        self.assertEqual(result["levels_completed"], 1)
        self.assertEqual(result["terminal"], "LEVEL_SOLVED")
        self.assertEqual(
            [item["name"] for item in engine.calls], ["ACTION1", "ACTION2"]
        )
        with self.assertRaisesRegex(P7SolvingBrokerError, "unavailable"):
            broker.request(request("secret", 2, "act", {"actions": [actions[0]]}))

    def test_action_shapes_and_envelope_fail_closed(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_broker import (
            P7SolvingBroker,
            P7SolvingBrokerError,
        )

        good = {"actions": [{"data": {}, "name": "ACTION1"}]}
        cases = {
            "bad-auth": request("wrong", 1, "act", good),
            "skipped-sequence": request("secret", 2, "act", good),
            "empty-batch": request("secret", 1, "act", {"actions": []}),
            "large-batch": request(
                "secret", 1, "act", {"actions": good["actions"] * 21}
            ),
            "unknown-action": request(
                "secret", 1, "act", {"actions": [{"name": "ACTION8", "data": {}}]}
            ),
            "malformed-data": request(
                "secret", 1, "act", {"actions": [{"name": "ACTION1", "data": {"x": 1}}]}
            ),
            "extra-envelope-field": {**request("secret", 1, "act", good), "other": 1},
        }
        for name, value in cases.items():
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(P7SolvingBrokerError, "unavailable"),
            ):
                P7SolvingBroker(
                    engine=FakeEngine(complete_on=None), token="secret"
                ).request(value)

    def test_action6_requires_exact_bounded_integer_coordinates(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_broker import (
            P7SolvingBroker,
            P7SolvingBrokerError,
        )

        for data in (
            {},
            {"x": -1, "y": 0},
            {"x": 64, "y": 0},
            {"x": True, "y": 1},
            {"x": 1, "y": 1, "z": 1},
        ):
            with self.subTest(data=data), self.assertRaises(P7SolvingBrokerError):
                broker = P7SolvingBroker(
                    engine=FakeEngine(complete_on=None), token="secret"
                )
                broker.request(
                    request(
                        "secret",
                        1,
                        "act",
                        {"actions": [{"name": "ACTION6", "data": data}]},
                    )
                )
        broker = P7SolvingBroker(engine=FakeEngine(complete_on=None), token="secret")
        result = broker.request(
            request(
                "secret",
                1,
                "act",
                {"actions": [{"name": "ACTION6", "data": {"x": 0, "y": 63}}]},
            )
        )
        self.assertEqual(result["actions_taken"], 1)

    def test_action_cap_closes_before_action_501(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_broker import (
            P7SolvingBroker,
            P7SolvingBrokerError,
        )

        engine = FakeEngine(complete_on=None)
        broker = P7SolvingBroker(engine=engine, token="secret")
        sequence = 0
        for _ in range(25):
            sequence += 1
            result = broker.request(
                request(
                    "secret",
                    sequence,
                    "act",
                    {"actions": [{"name": "ACTION1", "data": {}}] * 20},
                )
            )
        self.assertEqual(result["terminal"], "ACTION_CAP")
        self.assertEqual(len(engine.calls), 500)
        with self.assertRaises(P7SolvingBrokerError):
            broker.request(
                request(
                    "secret",
                    sequence + 1,
                    "act",
                    {"actions": [{"name": "ACTION1", "data": {}}]},
                )
            )
        self.assertEqual(len(engine.calls), 500)

    def test_noncanonical_engine_observation_is_rejected(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_broker import (
            P7SolvingBroker,
            P7SolvingBrokerError,
        )

        for frame in (([[0]],), [[0]], [[[[0]]]], [[[False]]], [[[0.5]]], [[0, [1]]]):

            class Bad(FakeEngine):
                def observe(self) -> dict[str, object]:
                    value = super().observe()
                    value["frame"] = frame
                    return value

            with self.subTest(frame=frame), self.assertRaises(P7SolvingBrokerError):
                P7SolvingBroker(engine=Bad(), token="secret")

    def test_score_projection_and_game_shape_changes_fail_closed(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_broker import (
            P7SolvingBroker,
            P7SolvingBrokerError,
        )

        class ChangedGame(FakeEngine):
            def act(self, action: dict[str, object]) -> dict[str, object]:
                value = super().act(action)
                value["win_levels"] = 8
                return value

        broker = P7SolvingBroker(engine=ChangedGame(), token="secret")
        with self.assertRaises(P7SolvingBrokerError):
            broker.request(
                request(
                    "secret",
                    1,
                    "act",
                    {
                        "actions": [
                            {"name": "ACTION1", "data": {}},
                            {"name": "ACTION2", "data": {}},
                        ]
                    },
                )
            )

        broker = P7SolvingBroker(engine=FakeEngine(complete_on=1), token="secret")
        broker.request(
            request("secret", 1, "act", {"actions": [{"name": "ACTION1", "data": {}}]})
        )
        with patch(
            "asterion.applications.prime_agent.operator.p7_solving_broker.official_p7_partial_score",
            return_value="/private/sentinel",
        ):
            with self.assertRaises(P7SolvingBrokerError):
                broker.seal()

    def test_replay_binds_every_observation_transition_score_and_identity(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_broker import (
            P7SolvingBroker,
            P7SolvingBrokerError,
        )

        broker = P7SolvingBroker(engine=FakeEngine(), token="secret")
        broker.request(
            request(
                "secret",
                1,
                "act",
                {
                    "actions": [
                        {"name": "ACTION1", "data": {}},
                        {"name": "ACTION2", "data": {}},
                    ]
                },
            )
        )
        with patch(
            "asterion.applications.prime_agent.operator.p7_solving_broker.official_p7_partial_score",
            return_value="3.571429",
        ):
            seal = broker.seal()
            self.assertEqual(seal.score, "3.571429")
            replay = broker.replay(lambda: FakeEngine())
            presentation = broker.presentation()
        self.assertEqual(replay["score"], seal.score)
        self.assertNotEqual(replay["score_sha256"], seal.score)
        self.assertEqual(
            set(presentation),
            {
                "action_count",
                "applied_actions",
                "completion_grid",
                "initial_grid",
                "levels_completed",
                "score",
                "terminal_reason",
            },
        )
        with self.assertRaises(P7SolvingBrokerError):
            broker.replay(lambda: FakeEngine(), resource_sha256="sha256:" + "0" * 64)
        with self.assertRaises(P7SolvingBrokerError):
            broker.replay(lambda: FakeEngine(complete_on=1))

    def test_duplicate_sequence_does_not_advance_authority(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_broker import (
            P7SolvingBroker,
            P7SolvingBrokerError,
        )

        broker = P7SolvingBroker(engine=FakeEngine(complete_on=None), token="secret")
        broker.request(request("secret", 1, "observe", {}))
        with self.assertRaises(P7SolvingBrokerError):
            broker.request(request("secret", 1, "status", {}))
        self.assertEqual(
            broker.request(request("secret", 2, "status", {}))["actions_taken"], 0
        )

    def test_first_level_identity_and_ambiguous_engine_failure_fail_closed(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_broker import (
            P7SolvingBroker,
            P7SolvingBrokerError,
        )

        class LaterLevel(FakeEngine):
            def observe(self) -> dict[str, object]:
                value = super().observe()
                value["levels_completed"] = 1
                return value

        with self.assertRaises(P7SolvingBrokerError):
            P7SolvingBroker(engine=LaterLevel(), token="secret")

        class Ambiguous(FakeEngine):
            def act(self, action: dict[str, object]) -> dict[str, object]:
                self.calls.append(action)
                return {"malformed": True}

        engine = Ambiguous(complete_on=None)
        broker = P7SolvingBroker(engine=engine, token="secret")
        with self.assertRaises(P7SolvingBrokerError):
            broker.request(
                request(
                    "secret", 1, "act", {"actions": [{"name": "ACTION1", "data": {}}]}
                )
            )
        with self.assertRaises(P7SolvingBrokerError):
            broker.request(
                request(
                    "secret", 1, "act", {"actions": [{"name": "ACTION2", "data": {}}]}
                )
            )
        self.assertEqual(len(engine.calls), 1)
        self.assertEqual(broker.seal().action_count, 1)
        self.assertEqual(
            broker.presentation()["applied_actions"], [{"name": "ACTION1", "data": {}}]
        )


if __name__ == "__main__":
    unittest.main()
