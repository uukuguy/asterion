from __future__ import annotations

import unittest

from asterion.applications.prime_agent.arc_agi_3_broker import (
    ArcAgi3BrokerCall,
    ArcAgi3BrokerError,
    arc_agi_3_action_chain_sha256,
    validate_arc_agi_3_broker_calls,
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _calls() -> tuple[ArcAgi3BrokerCall, ...]:
    return (
        ArcAgi3BrokerCall("observe", 1, None, _digest("a"), False),
        ArcAgi3BrokerCall("act", 2, _digest("b"), _digest("c"), False),
        ArcAgi3BrokerCall("act", 3, _digest("d"), _digest("e"), False),
        ArcAgi3BrokerCall("status", 4, None, _digest("f"), True),
    )


class TestArcAgi3Broker(unittest.TestCase):
    def test_admits_one_contiguous_terminal_single_game_transcript(self) -> None:
        calls = _calls()
        validate_arc_agi_3_broker_calls(calls)
        self.assertRegex(arc_agi_3_action_chain_sha256(calls), r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("SECRET_BOARD", repr(calls[0]))

    def test_rejects_unknown_duplicate_skipped_and_post_terminal_calls(self) -> None:
        invalid = (
            _calls()[:-1] + (ArcAgi3BrokerCall("shell", 4, None, _digest("f"), True),),  # type: ignore[arg-type]
            _calls()[:-1] + (ArcAgi3BrokerCall("status", 5, None, _digest("f"), True),),
            _calls() + (ArcAgi3BrokerCall("act", 5, _digest("0"), _digest("1"), True),),
        )
        for calls in invalid:
            with self.subTest(calls=calls), self.assertRaises(ArcAgi3BrokerError):
                validate_arc_agi_3_broker_calls(calls)
