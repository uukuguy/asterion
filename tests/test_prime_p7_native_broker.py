"""Native P7 broker boundary tests; no legacy gateway is involved."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest


class _Engine:
    def __init__(self, *, level_after: int | None = None, raises_on: int | None = None) -> None:
        self.level_after = level_after
        self.raises_on = raises_on
        self.calls: list[str] = []
        self.levels_completed = 0

    def observe(self) -> dict[str, object]:
        return {
            "available_actions": ["ACTION1", "ACTION2", "ACTION3"],
            "frame": [[[len(self.calls) % 10, 1]]],
            "levels_completed": self.levels_completed,
            "state": "NOT_FINISHED",
            "win_levels": 7,
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
