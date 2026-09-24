"""Native P7 broker boundary tests; no legacy gateway is involved."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest


class _Engine:
    def __init__(
        self,
        *,
        level_after: int | None = None,
        second_level_after: int | None = None,
        raises_on: int | None = None,
        game_id: str = "ls20-9607627b",
        seed: int = 0,
        win_levels: int = 7,
        remove_second_after_first: bool = False,
        game_over_after: int | None = None,
    ) -> None:
        self.level_after = level_after
        self.second_level_after = second_level_after
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
        if self.level_after == len(self.calls) or self.second_level_after == len(self.calls):
            self.levels_completed += 1
        return self.observe()


class _ResetEngine:
    game_id = "ls20-9607627b"
    seed = 0

    def __init__(self, *, reset_loses_level: bool = False, reset_stays_dead: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, int]]] = []
        self.levels_completed = 0
        self.state = "NOT_FINISHED"
        self.reset_loses_level = reset_loses_level
        self.reset_stays_dead = reset_stays_dead

    def observe(self) -> dict[str, object]:
        return {
            "available_actions": ["ACTION1", "ACTION6"],
            "frame": [[[len(self.calls)]]],
            "levels_completed": self.levels_completed,
            "state": self.state,
            "win_levels": 7,
        }

    def step(self, action: str, data: dict[str, int] | None = None) -> dict[str, object]:
        self.calls.append((action, data or {}))
        if action == "RESET":
            self.state = "GAME_OVER" if self.reset_stays_dead else "NOT_FINISHED"
            if self.reset_loses_level:
                self.levels_completed = 0
        elif self.levels_completed == 0:
            self.levels_completed = 1
        elif action == "ACTION1" and len(self.calls) == 2:
            self.state = "GAME_OVER"
        elif action == "ACTION1":
            self.levels_completed = 2
        return self.observe()


class _FullGameEngine(_Engine):
    def __init__(self, *, final_state: str = "WIN", actions_per_level: int = 1) -> None:
        super().__init__()
        self.final_state = final_state
        self.actions_per_level = actions_per_level

    def observe(self) -> dict[str, object]:
        value = super().observe()
        if self.levels_completed == 7:
            value["state"] = self.final_state
        return value

    def step(self, action: str) -> dict[str, object]:
        self.calls.append(action)
        self.levels_completed = len(self.calls) // self.actions_per_level
        return self.observe()


def _broker(*, level_after: int | None = None, raises_on: int | None = None):
    from asterion.applications.prime.p7.broker import ArcBroker

    engine = _Engine(level_after=level_after, raises_on=raises_on)
    return ArcBroker(engine=engine), engine


class TestNativeP7Broker(unittest.TestCase):
    def test_full_game_requires_win_and_dynamic_cap(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection

        game = P7GameSelection("ls20-9607627b", 0, 7)
        self.assertEqual(sum(game.baseline_actions), 776)
        self.assertEqual(game.action_cap, 1552)
        for state, reason in (("WIN", "game-won"), ("NOT_FINISHED", "game-incomplete")):
            with self.subTest(state=state):
                broker = ArcBroker(engine=_FullGameEngine(final_state=state, actions_per_level=100), game=game)
                for _ in range(7):
                    broker.act(("ACTION1",) * 100)
                self.assertEqual(broker.seal().primitive_actions, 700)
                self.assertEqual(broker.seal().terminal_reason, reason)
                self.assertEqual(broker.terminal_snapshot().observation.state, state)

    def test_full_game_cap_bounds_and_legacy_partial_cap(self) -> None:
        from asterion.applications.prime.p7.game import P7GameSelection

        for baseline, cap in (((1,), 1000), ((3000,), 5000)):
            with self.subTest(baseline=baseline):
                game = P7GameSelection("new-v1", 0, 1, baseline, 1)
                self.assertEqual(game.action_cap, cap)
        self.assertEqual(P7GameSelection("ls20-9607627b", 0, 2).action_cap, 500)

    def test_initial_game_over_is_rejected_before_any_action(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError

        engine = _ResetEngine()
        engine.state = "GAME_OVER"
        with self.assertRaises(ArcBrokerError):
            ArcBroker(engine=engine)
        self.assertEqual(engine.calls, [])

    def test_level_advance_with_game_over_is_not_falsely_resettable(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection

        class Engine(_ResetEngine):
            def step(self, action: str, data: dict[str, int] | None = None) -> dict[str, object]:
                super().step(action, data)
                if self.levels_completed == 1:
                    self.state = "GAME_OVER"
                return self.observe()

        engine = Engine()
        game = P7GameSelection(engine.game_id, 0, 2)
        broker = ArcBroker(engine=engine, game=game)
        broker.act(("ACTION1",))
        self.assertEqual(broker.seal().terminal_reason, "game-over")
        with self.assertRaisesRegex(ArcBrokerError, "closed"):
            broker.act(("RESET",))
        self.assertEqual(broker.replay(Engine).levels_completed, 1)

    def test_target_second_level_keeps_broker_open_after_first_transition(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection

        game = P7GameSelection("ls20-9607627b", 0, 2)
        engine = _Engine(level_after=2, second_level_after=4)
        broker = ArcBroker(engine=engine, game=game)

        first = broker.act(("ACTION1", "ACTION1", "ACTION1"))
        self.assertEqual(first.applied_count, 2)
        self.assertEqual(broker.status().levels_completed, 1)
        self.assertEqual(broker.status().terminal_reason, "active")
        self.assertEqual(engine.calls, ["ACTION1", "ACTION1"])
        with self.assertRaises(ArcBrokerError):
            broker.seal()

        second = broker.act(("ACTION1", "ACTION1", "ACTION1"))
        self.assertEqual(second.applied_count, 2)
        self.assertEqual(broker.seal().levels_completed, 2)
        self.assertEqual(broker.seal().terminal_reason, "level-completed")
        self.assertEqual(engine.calls, ["ACTION1"] * 4)

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

    def test_game_over_records_the_action_and_requires_reset(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBrokerError

        engine = _Engine(game_over_after=2)
        from asterion.applications.prime.p7.broker import ArcBroker

        broker = ArcBroker(engine=engine)
        result = broker.act(("ACTION1", "ACTION2", "ACTION3"))

        self.assertEqual(result.applied_count, 2)
        self.assertEqual(engine.calls, ["ACTION1", "ACTION2"])
        self.assertEqual(broker.observe().state, "GAME_OVER")
        self.assertEqual(broker.status().primitive_actions, 2)
        self.assertEqual(broker.status().terminal_reason, "reset-required")
        with self.assertRaisesRegex(ArcBrokerError, "unavailable"):
            broker.act(("ACTION1",))

    def test_same_engine_resets_failed_second_level_and_counts_action(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection

        engine = _ResetEngine()
        broker = ArcBroker(engine=engine, game=P7GameSelection(engine.game_id, 0, 2))
        broker.act(("ACTION1",))
        broker.act(("ACTION1", "ACTION1"))
        self.assertEqual(broker.status().terminal_reason, "reset-required")
        result = broker.act(("RESET", "ACTION1"))
        self.assertEqual(result.applied_count, 1)
        self.assertEqual(broker.observe().state, "NOT_FINISHED")
        self.assertEqual(broker.status().levels_completed, 1)
        broker.act(("ACTION1",))
        self.assertEqual(broker.seal().primitive_actions, 4)
        self.assertEqual(broker.seal().levels_completed, 2)
        self.assertEqual([call[0] for call in engine.calls], ["ACTION1", "ACTION1", "RESET", "ACTION1"])

    def test_reset_requires_gameplay_in_current_level_and_preserves_progress(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection

        engine = _ResetEngine()
        broker = ArcBroker(engine=engine, game=P7GameSelection(engine.game_id, 0, 2))
        with self.assertRaises(ArcBrokerError):
            broker.act(("RESET",))
        broker.act(("ACTION1",))
        with self.assertRaises(ArcBrokerError):
            broker.act(("RESET",))
        broker.act(("ACTION1",))
        broker.act(("RESET",))
        with self.assertRaises(ArcBrokerError):
            broker.act(("RESET",))

        for kwargs in ({"reset_loses_level": True}, {"reset_stays_dead": True}):
            with self.subTest(kwargs=kwargs):
                bad = _ResetEngine(**kwargs)
                test_broker = ArcBroker(engine=bad, game=P7GameSelection(bad.game_id, 0, 2))
                test_broker.act(("ACTION1",))
                test_broker.act(("ACTION1",))
                with self.assertRaises(ArcBrokerError):
                    test_broker.act(("RESET",))

    def test_proactive_reset_stops_batch_and_keeps_level(self) -> None:
        from asterion.applications.prime.p7.broker import ArcAction, ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection

        engine = _ResetEngine()
        broker = ArcBroker(engine=engine, game=P7GameSelection(engine.game_id, 0, 2))
        broker.act(("ACTION1",))
        broker.act((ArcAction("ACTION6", (("x", 1), ("y", 2))),))
        result = broker.act(("RESET", "ACTION1"))
        self.assertEqual(result.applied_count, 1)
        self.assertEqual(broker.status().levels_completed, 1)
        self.assertEqual(broker.status().terminal_reason, "active")
        self.assertEqual(engine.calls[-1], ("RESET", {}))

    def test_action6_requires_exact_coordinates_and_journals_them(self) -> None:
        from asterion.applications.prime.p7.broker import ArcAction, ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection

        for data in ((), (("x", True), ("y", 1)), (("x", -1), ("y", 1)), (("x", 64), ("y", 1)), (("y", 1), ("x", 2)), (("x", 1), ("y", 2), ("z", 3))):
            with self.subTest(data=data):
                engine = _ResetEngine()
                broker = ArcBroker(engine=engine, game=P7GameSelection(engine.game_id, 0, 2))
                with self.assertRaises(ArcBrokerError):
                    broker.act((ArcAction("ACTION6", data),))
                self.assertEqual(engine.calls, [])
        engine = _ResetEngine()
        broker = ArcBroker(engine=engine, game=P7GameSelection(engine.game_id, 0, 2))
        action = ArcAction("ACTION6", (("x", 0), ("y", 63)))
        broker.act((action,))
        self.assertEqual(engine.calls, [("ACTION6", {"x": 0, "y": 63})])
        self.assertEqual(broker.journal[0].data, action.data)
        with self.assertRaises(FrozenInstanceError):
            action.name = "ACTION1"  # type: ignore[misc]

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
