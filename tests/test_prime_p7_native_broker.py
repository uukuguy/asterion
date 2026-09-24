"""Native P7 broker boundary tests; no legacy gateway is involved."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest


class _Engine:
    def __init__(
        self,
        *,
        level_after: int | None = None,
        raises_on: int | None = None,
        game_id: str = "ls20-9607627b",
        seed: int = 0,
        win_levels: int = 7,
        remove_second_after_first: bool = False,
        game_over_after: int | None = None,
    ) -> None:
        self.level_after = level_after
        self.raises_on = raises_on
        self.game_id = game_id
        self.seed = seed
        self.win_levels = win_levels
        self.remove_second_after_first = remove_second_after_first
        self.game_over_after = game_over_after
        self.calls: list[str] = []
        self.levels_completed = 0
        self.observe_calls = 0

    def observe(self) -> dict[str, object]:
        self.observe_calls += 1
        available = ["ACTION1", "ACTION2", "ACTION3"]
        if self.remove_second_after_first and self.calls:
            available.remove("ACTION2")
        return {
            "available_actions": available,
            "frame": [[[len(self.calls) % 10, 1]]],
            "levels_completed": self.levels_completed,
            "state": "GAME_OVER" if self.game_over_after == len(self.calls) else "NOT_FINISHED",
            "win_levels": self.win_levels,
        }

    def step(self, action: str) -> dict[str, object]:
        self.calls.append(action)
        if self.raises_on == len(self.calls):
            raise RuntimeError("engine interrupted after dispatch")
        if self.level_after == len(self.calls):
            self.levels_completed += 1
        return self.observe()


def _broker(*, level_after: int | None = None, raises_on: int | None = None):
    from asterion.applications.prime.p7.broker import ArcBroker

    engine = _Engine(level_after=level_after, raises_on=raises_on)
    return ArcBroker(engine=engine), engine


class TestNativeP7Broker(unittest.TestCase):
    def test_batch_stops_at_first_level_transition(self) -> None:
        broker, engine = _broker(level_after=2)

        result = broker.act(("ACTION1", "ACTION2", "ACTION3"))

        self.assertEqual(result.applied_count, 2)
        self.assertEqual(result.levels_completed, 1)
        self.assertEqual(engine.calls, ["ACTION1", "ACTION2"])
        self.assertEqual(tuple(item.sequence for item in result.transitions), (1, 2))

    def test_action_observe_and_status_after_transition_are_rejected(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBrokerError

        broker, _ = _broker(level_after=1)
        broker.act(("ACTION1",))
        for call in (lambda: broker.act(("ACTION1",)), broker.observe, broker.status):
            with self.subTest(call=call), self.assertRaisesRegex(ArcBrokerError, "closed"):
                call()

    def test_game_over_records_the_action_then_closes_with_terminal_snapshot(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBrokerError

        engine = _Engine(game_over_after=2)
        from asterion.applications.prime.p7.broker import ArcBroker

        broker = ArcBroker(engine=engine)
        result = broker.act(("ACTION1", "ACTION2", "ACTION3"))

        self.assertEqual(result.applied_count, 2)
        self.assertEqual(engine.calls, ["ACTION1", "ACTION2"])
        self.assertEqual(broker.seal().terminal_reason, "game-over")
        snapshot = broker.terminal_snapshot()
        self.assertEqual(snapshot.observation.state, "GAME_OVER")
        self.assertEqual(snapshot.status.primitive_actions, 2)
        self.assertEqual(snapshot.status.levels_completed, 0)
        self.assertEqual(snapshot.status.actions_remaining, 498)
        self.assertEqual(snapshot.status.terminal_reason, "game-over")
        for call in (broker.observe, broker.status, lambda: broker.act(("ACTION1",))):
            with self.subTest(call=call), self.assertRaisesRegex(ArcBrokerError, "closed"):
                call()

    def test_terminal_snapshot_is_rejected_while_active(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBrokerError

        broker, _ = _broker()
        with self.assertRaisesRegex(ArcBrokerError, "unavailable"):
            broker.terminal_snapshot()

    def test_malformed_unavailable_or_oversized_batch_never_dispatches(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBrokerError, P7_ACTION_CAP

        for actions in (("ACTION8",), ("ACTION1", 1), ("ACTION1",) * (P7_ACTION_CAP + 1)):
            with self.subTest(actions=actions):
                broker, engine = _broker()
                with self.assertRaises(ArcBrokerError):
                    broker.act(actions)  # type: ignore[arg-type]
                self.assertEqual(engine.calls, [])

    def test_action_cap_closes_at_500_and_receipt_has_no_frame_content(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBrokerError, P7_ACTION_CAP

        broker, engine = _broker()
        result = broker.act(("ACTION1",) * P7_ACTION_CAP)
        receipt = broker.seal()
        self.assertEqual(result.applied_count, P7_ACTION_CAP)
        self.assertEqual(len(engine.calls), P7_ACTION_CAP)
        self.assertEqual(receipt.primitive_actions, P7_ACTION_CAP)
        self.assertEqual(receipt.terminal_reason, "action-cap")
        self.assertNotIn("frame", repr(receipt))
        with self.assertRaisesRegex(ArcBrokerError, "closed"):
            broker.act(("ACTION1",))

    def test_engine_exception_after_dispatch_closes_as_uncertain(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBrokerError

        broker, engine = _broker(raises_on=1)
        with self.assertRaisesRegex(ArcBrokerError, "uncertain"):
            broker.act(("ACTION1",))
        self.assertEqual(engine.calls, ["ACTION1"])
        self.assertEqual(broker.seal().terminal_reason, "engine-uncertain")

    def test_observation_is_an_immutable_snapshot(self) -> None:
        broker, engine = _broker()
        observed = broker.observe()
        with self.assertRaises(FrozenInstanceError):
            observed.state = "FORGED"  # type: ignore[misc]
        engine.step("ACTION1")
        self.assertEqual(observed.frame, (((0, 1),),))

    def test_identity_mismatch_is_rejected_before_observation(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError

        engine = _Engine(game_id="other-game")
        with self.assertRaises(ArcBrokerError):
            ArcBroker(engine=engine)
        self.assertEqual(engine.observe_calls, 0)

    def test_tu93_selection_seals_exact_identity_and_nine_level_count(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection

        game = P7GameSelection("tu93-0768757b", 0)
        engine = _Engine(game_id=game.game_id, seed=game.seed, win_levels=9, level_after=1)
        broker = ArcBroker(engine=engine, game=game)
        broker.act(("ACTION1",))
        receipt = broker.seal()
        self.assertEqual((receipt.game_id, receipt.seed), (game.game_id, game.seed))
        self.assertEqual(
            broker.replay(
                lambda: _Engine(
                    game_id=game.game_id, seed=game.seed, win_levels=9, level_after=1
                )
            ),
            receipt,
        )

    def test_tu93_rejects_wrong_level_count_before_action(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection

        engine = _Engine(game_id="tu93-0768757b", win_levels=7)
        with self.assertRaises(ArcBrokerError):
            ArcBroker(engine=engine, game=P7GameSelection("tu93-0768757b", 0))
        self.assertEqual(engine.calls, [])

    def test_later_action_loses_authority_when_first_changes_availability(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBrokerError

        broker, engine = _broker()
        engine.remove_second_after_first = True
        with self.assertRaisesRegex(ArcBrokerError, "unavailable"):
            broker.act(("ACTION1", "ACTION2"))
        self.assertEqual(engine.calls, ["ACTION1"])
        self.assertEqual(broker.seal().terminal_reason, "action-unavailable")
        with self.assertRaisesRegex(ArcBrokerError, "closed"):
            broker.status()
