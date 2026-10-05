"""Replay evidence for the source-independent native P7 broker."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import unittest

from tests.test_prime_p7_native_broker import _Engine, _ResetEngine


class TestNativeP7Replay(unittest.TestCase):
    def test_operator_interruption_replays_acknowledged_actions_without_progress(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError

        broker = ArcBroker(engine=_Engine())
        broker.act(("ACTION1", "ACTION2"))
        broker.interrupt()
        receipt = broker.seal()
        self.assertEqual(receipt.terminal_reason, "interrupted")
        self.assertEqual(receipt.levels_completed, 0)
        self.assertEqual(broker.replay(_Engine), receipt)
        with self.assertRaises(ArcBrokerError):
            broker.act(("ACTION1",))
        for state in ("empty", "inflight", "uncertain", "terminal"):
            with self.subTest(state=state):
                candidate = ArcBroker(engine=_Engine(level_after=1 if state == "terminal" else None))
                if state != "empty":
                    candidate.act(("ACTION1",))
                if state == "inflight":
                    candidate._actions_dispatched += 1
                elif state == "uncertain":
                    candidate._failed_action = "ACTION1"
                with self.assertRaises(ArcBrokerError):
                    candidate.interrupt()

    def test_human_baseline_replays_only_with_exact_sweep_cap(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.replay import replay_arc_run
        from asterion.applications.prime.p7.score import replay_sha256

        game = P7GameSelection("ls20-9607627b", 0, 1, action_cap_override=3)
        broker = ArcBroker(engine=_Engine(), game=game)
        broker.act(("ACTION1", "ACTION1", "ACTION1"))
        receipt = broker.seal()
        self.assertEqual(receipt.terminal_reason, "human-baseline")
        self.assertEqual(broker.replay(_Engine), receipt)
        forged = replace(
            receipt,
            primitive_actions=2,
            replay_sha256=replay_sha256(broker.journal, terminal_reason="human-baseline"),
        )
        with self.assertRaises(ArcBrokerError):
            replay_arc_run(broker.journal, forged, _Engine, game=game)

    def test_full_game_terminal_and_budget_replay(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.replay import replay_arc_run
        from asterion.applications.prime.p7.score import replay_sha256
        from tests.test_prime_p7_native_broker import _FullGameEngine

        game = P7GameSelection("ls20-9607627b", 0, 7)
        for state in ("WIN", "NOT_FINISHED"):
            with self.subTest(state=state):
                def factory() -> _FullGameEngine:
                    return _FullGameEngine(final_state=state, actions_per_level=100)
                broker = ArcBroker(engine=factory(), game=game)
                for _ in range(7):
                    broker.act(("ACTION1",) * 100)
                self.assertEqual(broker.replay(factory), broker.seal())
                forged = replace(broker.seal(), terminal_reason="game-won", replay_sha256=replay_sha256(broker.journal, terminal_reason="game-won"))
                if state != "WIN":
                    with self.assertRaises(ArcBrokerError):
                        replay_arc_run(broker.journal, forged, factory, game=game)
        broker = ArcBroker(engine=_Engine(), game=game)
        broker.act(("ACTION1",) * 1552)
        self.assertEqual(broker.seal().terminal_reason, "action-cap")
        self.assertEqual(broker.replay(_Engine), broker.seal())

    def test_unified_observation_partial_journal_digest_is_pinned(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker

        broker = ArcBroker(engine=_Engine(level_after=2))
        broker.act(("ACTION1", "ACTION2"))
        self.assertEqual(broker.seal().replay_sha256, "sha256:003ab3856f737693c177e2ce2db25fd601c0c9ed07b724b28f55502df381b440")
        self.assertEqual(broker.replay(lambda: _Engine(level_after=2)), broker.seal())

    def test_second_level_replays_full_cross_level_journal(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection

        game = P7GameSelection("ls20-9607627b", 0, 2)
        broker = ArcBroker(engine=_Engine(level_after=2, second_level_after=4), game=game)
        broker.act(("ACTION1", "ACTION1", "ACTION1"))
        broker.act(("ACTION1", "ACTION1"))

        self.assertEqual(broker.seal().levels_completed, 2)
        self.assertEqual(
            broker.replay(lambda: _Engine(level_after=2, second_level_after=4)),
            broker.seal(),
        )

    def test_action_cap_replays_without_being_mistaken_for_game_over(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.score import P7_ACTION_CAP

        broker = ArcBroker(engine=_Engine())
        broker.act(("ACTION1",) * P7_ACTION_CAP)

        self.assertEqual(broker.seal().terminal_reason, "action-cap")
        self.assertEqual(broker.replay(lambda: _Engine()), broker.seal())

    def test_game_over_on_last_allowed_action_replays_as_action_cap(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.score import P7_ACTION_CAP

        broker = ArcBroker(engine=_Engine(game_over_after=P7_ACTION_CAP))
        broker.act(("ACTION1",) * P7_ACTION_CAP)

        self.assertEqual(broker.seal().terminal_reason, "action-cap")
        self.assertEqual(
            broker.replay(lambda: _Engine(game_over_after=P7_ACTION_CAP)), broker.seal()
        )

    def test_replay_reproduces_reset_and_click_data(self) -> None:
        from asterion.applications.prime.p7.broker import ArcAction, ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.replay import replay_arc_run

        game = P7GameSelection("ls20-9607627b", 0, 2)
        broker = ArcBroker(engine=_ResetEngine(), game=game)
        broker.act(("ACTION1",))
        broker.act(("ACTION1",))
        broker.act(("RESET",))
        broker.act((ArcAction("ACTION6", (("x", 12), ("y", 34))),))
        broker.act(("ACTION1",))
        self.assertEqual(broker.replay(lambda: _ResetEngine()), broker.seal())
        self.assertEqual([item.action for item in broker.journal], ["ACTION1", "ACTION1", "RESET", "ACTION6", "ACTION1"])
        forged = list(broker.journal)
        forged[3] = replace(forged[3], data=(("x", 13), ("y", 34)))
        with self.assertRaises(ArcBrokerError):
            replay_arc_run(tuple(forged), broker.seal(), lambda: _ResetEngine(), game=game)

    def test_replay_rejects_reset_that_loses_completed_level(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection

        game = P7GameSelection("ls20-9607627b", 0, 2)
        broker = ArcBroker(engine=_ResetEngine(), game=game)
        broker.act(("ACTION1",))
        broker.act(("ACTION1",))
        broker.act(("RESET",))
        broker.act(("ACTION1",))
        with self.assertRaises(ArcBrokerError):
            broker.replay(lambda: _ResetEngine(reset_loses_level=True))

    def test_level_completion_takes_precedence_over_simultaneous_game_over(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker

        broker = ArcBroker(engine=_Engine(level_after=1, game_over_after=1))
        broker.act(("ACTION1",))

        self.assertEqual(broker.seal().terminal_reason, "level-completed")
        self.assertEqual(
            broker.replay(lambda: _Engine(level_after=1, game_over_after=1)),
            broker.seal(),
        )

    def test_seal_replays_journal_against_a_fresh_engine(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.replay import replay_arc_run

        broker = ArcBroker(engine=_Engine(level_after=2))
        broker.act(("ACTION1", "ACTION2", "ACTION3"))
        receipt = broker.seal()

        self.assertEqual(replay_arc_run(broker.journal, receipt, lambda: _Engine(level_after=2)), receipt)

    def test_replay_rejects_before_after_or_terminal_mismatches(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.replay import replay_arc_run

        broker = ArcBroker(engine=_Engine(level_after=2))
        broker.act(("ACTION1", "ACTION2"))
        with self.assertRaises(ArcBrokerError):
            replay_arc_run(broker.journal, broker.seal(), lambda: _Engine(level_after=1))

    def test_game_over_replays_against_a_fresh_engine_and_requires_terminal_state(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.replay import replay_arc_run

        broker = ArcBroker(engine=_Engine(game_over_after=2))
        broker.act(("ACTION1", "ACTION2", "ACTION3"))
        receipt = broker.seal()

        self.assertEqual(
            replay_arc_run(broker.journal, receipt, lambda: _Engine(game_over_after=2)), receipt
        )
        with self.assertRaises(ArcBrokerError):
            replay_arc_run(broker.journal, receipt, lambda: _Engine())

    def test_replay_rejects_identity_mismatch_before_observation(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.replay import replay_arc_run

        broker = ArcBroker(engine=_Engine(level_after=1))
        broker.act(("ACTION1",))
        replay_engine = _Engine(level_after=1, seed=1)
        with self.assertRaises(ArcBrokerError):
            replay_arc_run(broker.journal, broker.seal(), lambda: replay_engine)
        self.assertEqual(replay_engine.observe_calls, 0)

    def test_replay_rejects_other_supported_game_before_observation(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection

        game = P7GameSelection("tu93-0768757b", 0)
        broker = ArcBroker(
            engine=_Engine(game_id=game.game_id, win_levels=9, level_after=1), game=game
        )
        broker.act(("ACTION1",))
        replay_engine = _Engine(level_after=1)
        with self.assertRaises(ArcBrokerError):
            broker.replay(lambda: replay_engine)
        self.assertEqual(replay_engine.observe_calls, 0)

    def test_native_sources_are_detached_from_legacy_provider_stack(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/asterion/applications/prime/p7"
        source = "\n".join((root / name).read_text() for name in ("broker.py", "replay.py", "score.py"))
        for forbidden in ("prime_agent", "p7_solving", "gateway", "sdk", ".env", "seeded"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source.lower())
