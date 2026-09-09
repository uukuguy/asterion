"""Replay evidence for the source-independent native P7 broker."""

from __future__ import annotations

from pathlib import Path
import unittest

from tests.test_prime_p7_native_broker import _Engine


class TestNativeP7Replay(unittest.TestCase):
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

    def test_replay_rejects_identity_mismatch_before_observation(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.replay import replay_arc_run

        broker = ArcBroker(engine=_Engine(level_after=1))
        broker.act(("ACTION1",))
        replay_engine = _Engine(level_after=1, seed=1)
        with self.assertRaises(ArcBrokerError):
            replay_arc_run(broker.journal, broker.seal(), lambda: replay_engine)
        self.assertEqual(replay_engine.observe_calls, 0)

    def test_native_sources_are_detached_from_legacy_provider_stack(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/asterion/applications/prime/p7"
        source = "\n".join((root / name).read_text() for name in ("broker.py", "replay.py", "score.py"))
        for forbidden in ("prime_agent", "p7_solving", "gateway", "sdk", ".env", "seeded"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source.lower())
