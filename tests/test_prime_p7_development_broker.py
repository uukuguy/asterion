from __future__ import annotations
import unittest
from asterion.applications.prime_agent.operator.p7_development_broker import (
    P7DevelopmentBroker,
    P7DevelopmentBrokerError,
)


class _Engine:
    def __init__(self):
        self.actions = []

    def observe(self):
        return {
            "state": "play",
            "levels_completed": 0,
            "win_levels": 0,
            "available_actions": [1, 2],
            "frame": [[0]],
        }

    def act(self, action):
        self.actions.append(action)
        return {
            "state": "play",
            "levels_completed": 0,
            "win_levels": 0,
            "available_actions": [1, 2],
            "frame": [[action]],
        }

    def status(self):
        return len(self.actions) >= 4


class TestP7DevelopmentBroker(unittest.TestCase):
    def test_fences_one_authenticated_episode_and_replays_it(self):
        broker = P7DevelopmentBroker(engine=_Engine(), token="t")
        broker.request({"token": "t", "sequence": 1, "method": "observe", "data": {}})
        for sequence in range(2, 6):
            broker.request(
                {
                    "token": "t",
                    "sequence": sequence,
                    "method": "act",
                    "data": {"action_id": 1, "data": {}},
                }
            )
        status = broker.request({"token": "t", "sequence": 6, "method": "status", "data": {}})
        self.assertEqual(status["terminal_reason"], "engine-terminal")
        seal = broker.seal()
        self.assertEqual(seal.terminal_reason, "engine-terminal")
        self.assertRegex(seal.score_sha256, r"\Asha256:[0-9a-f]{64}\Z")
        replay = broker.replay(_Engine)
        self.assertEqual(replay["action_count"], 4)
        self.assertEqual(replay["score_sha256"], seal.score_sha256)
        with self.assertRaises(P7DevelopmentBrokerError):
            broker.request(
                {"token": "t", "sequence": 7, "method": "status", "data": {}}
            )

    def test_rejects_auth_sequence_reset_and_extra_fields(self):
        broker = P7DevelopmentBroker(engine=_Engine(), token="t")
        for request in (
            {"token": "x", "sequence": 1, "method": "observe", "data": {}},
            {"token": "t", "sequence": 2, "method": "observe", "data": {}},
            {
                "token": "t",
                "sequence": 1,
                "method": "act",
                "data": {"action_id": 7, "data": {}},
            },
            {
                "token": "t",
                "sequence": 1,
                "method": "observe",
                "data": {},
                "private": "x",
            },
        ):
            with (
                self.subTest(request=request),
                self.assertRaises(P7DevelopmentBrokerError),
            ):
                broker.request(request)
