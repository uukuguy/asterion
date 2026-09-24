"""Replay evidence for the source-independent native P7 broker."""

from __future__ import annotations

from pathlib import Path
import unittest

from tests.test_prime_p7_native_broker import _Engine


class TestNativeP7Replay(unittest.TestCase):
    def test_action_cap_replays_without_being_mistaken_for_game_over(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.score import P7_ACTION_CAP

        broker = ArcBroker(engine=_Engine())
        broker.act(("ACTION1",) * P7_ACTION_CAP)

        self.assertEqual(broker.seal().terminal_reason, "action-cap")
        self.assertEqual(broker.replay(lambda: _Engine()), broker.seal())

    def test_game_over_on_last_allowed_action_replays_as_game_over(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.score import P7_ACTION_CAP

        broker = ArcBroker(engine=_Engine(game_over_after=P7_ACTION_CAP))
        broker.act(("ACTION1",) * P7_ACTION_CAP)

        self.assertEqual(broker.seal().terminal_reason, "game-over")
        self.assertEqual(
            broker.replay(lambda: _Engine(game_over_after=P7_ACTION_CAP)), broker.seal()
        )

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
