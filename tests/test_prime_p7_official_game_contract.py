"""Official broker contracts do not acquire local replay or score authority."""

from dataclasses import FrozenInstanceError
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from asterion.applications.prime.p7 import game as game_module
from asterion.applications.prime.p7.broker import ArcAction, ArcBroker, ArcBrokerError
from tests.test_prime_p7_native_broker import _Engine


class _OfficialEngine:
    game_id = "unknown-v99"
    seed = 0
    baseline_actions = None

    def __init__(self, final_state="WIN", stall=False):
        self.calls = []
        self.levels_completed = 0
        self.state = "NOT_FINISHED"
        self.final_state = final_state
        self.stall = stall

    def observe(self):
        return {
            "available_actions": ["ACTION1", "ACTION6"],
            "frame": [[[len(self.calls) % 10]]],
            "levels_completed": self.levels_completed,
            "state": self.state,
            "win_levels": 1,
        }

    def step(self, action, data=None):
        self.calls.append((action, data))
        if action == "RESET":
            self.state = "NOT_FINISHED"
        elif action == "ACTION6":
            self.state = "GAME_OVER"
        elif not self.stall:
            self.levels_completed = 1
            self.state = self.final_state
        return self.observe()


class TestOfficialGameContract(unittest.TestCase):
    def contract(self, **kwargs):
        self.assertTrue(hasattr(game_module, "ArcGameContract"), "official contract is missing")
        return game_module.ArcGameContract(**{"game_id": "unknown-v99", "win_levels": 1, **kwargs})

    def test_contract_is_immutable_and_has_no_local_baseline(self):
        contract = self.contract()
        self.assertEqual((contract.seed, contract.target_level, contract.action_cap, contract.mode), (0, 1, 1000, "official"))
        self.assertTrue(contract.is_full_game)
        self.assertFalse(hasattr(contract, "baseline_actions"))
        with self.assertRaises(FrozenInstanceError):
            contract.action_cap = 2000

    def test_invalid_contracts_fail_closed(self):
        for kwargs in (
            {"game_id": "../secret"}, {"game_id": "unknown"}, {"game_id": None},
            {"win_levels": 0}, {"win_levels": True}, {"win_levels": 1.5},
            {"seed": 1}, {"seed": False}, {"action_cap": 999},
            {"action_cap": 5001}, {"action_cap": True}, {"mode": "local"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(game_module.P7GameSelectionError):
                self.contract(**kwargs)
        self.assertEqual(self.contract(action_cap=5000).action_cap, 5000)

    def test_unknown_game_click_reset_and_win_without_baseline(self):
        engine = _OfficialEngine()
        initial = engine.observe()
        broker = ArcBroker(engine=engine, game=self.contract(win_levels=initial["win_levels"]))
        with self.assertRaises(ArcBrokerError):
            broker.act(("RESET",))
        broker.act((ArcAction("ACTION6", (("x", 4), ("y", 5))),))
        broker.act(("RESET",))
        broker.act(("ACTION1",))
        self.assertEqual(engine.calls[0], ("ACTION6", {"x": 4, "y": 5}))
        self.assertEqual(broker.seal().terminal_reason, "game-won")
        self.assertEqual(broker.seal().primitive_actions, 3)

    def test_full_completion_requires_win_and_enforces_cap(self):
        broker = ArcBroker(engine=_OfficialEngine(final_state="NOT_FINISHED"), game=self.contract())
        broker.act(("ACTION1",))
        self.assertEqual(broker.seal().terminal_reason, "game-incomplete")
        broker = ArcBroker(engine=_OfficialEngine(stall=True), game=self.contract())
        broker.act(("ACTION1",) * 1000)
        self.assertEqual(broker.seal().terminal_reason, "action-cap")
        self.assertEqual(broker.seal().primitive_actions, 1000)

    def test_official_replay_rejected_without_calling_factory(self):
        from asterion.applications.prime.p7.replay import replay_arc_run

        broker = ArcBroker(engine=_OfficialEngine(), game=self.contract())
        broker.act(("ACTION1",))
        factory = Mock()
        with self.assertRaises(ArcBrokerError):
            broker.replay(factory)
        with self.assertRaises(ArcBrokerError):
            replay_arc_run(broker.journal, broker.seal(), factory, game=broker.game)
        factory.assert_not_called()

    def test_official_local_receipt_rejected_without_trace_artifact(self):
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt, P7PrivateTraceReceiptError

        broker = ArcBroker(engine=_OfficialEngine(), game=self.contract())
        broker.act(("ACTION1",))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recorder = PrimeTraceRecorder(root)
            before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            try:
                with self.assertRaises(P7PrivateTraceReceiptError):
                    P7PrivateTraceReceipt(broker, recorder)
                self.assertEqual(before, {p: p.read_bytes() for p in root.rglob("*") if p.is_file()})
            finally:
                recorder.close()

    def test_local_unified_observation_replay_digest_is_pinned(self):
        broker = ArcBroker(engine=_Engine(level_after=2))
        broker.act(("ACTION1", "ACTION1"))
        self.assertEqual(broker.seal().replay_sha256, "sha256:97c8997fd8e82cbbf256e86307cf30bcc32b341c9c0fbd83b20ae09e7fdb38ac")
        self.assertEqual(broker.replay(lambda: _Engine(level_after=2)), broker.seal())
