from __future__ import annotations

import unittest

from asterion.applications.prime_agent.arc_agi_3_acceptance import (
    ArcAgi3AcceptanceError,
    accept_arc_agi_3,
)
from asterion.applications.prime_agent.arc_agi_3_broker import (
    ArcAgi3BrokerCall,
    arc_agi_3_action_chain_sha256,
)
from asterion.applications.prime_agent.arc_agi_3_receipt import ArcAgi3Trace
from asterion.applications.prime_agent.operator.arc_agi_3_workload import (
    P7_ARC_AGI_3_MODEL_SHA256, P7_ARC_AGI_3_ORACLE_SHA256,
    P7_ARC_AGI_3_SCHEMA_SHA256, P7_ARC_AGI_3_WORKLOAD_DIGEST,
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _calls() -> tuple[ArcAgi3BrokerCall, ...]:
    return (ArcAgi3BrokerCall("observe", 1, None, _digest("a"), False), ArcAgi3BrokerCall("act", 2, _digest("b"), _digest("c"), False), ArcAgi3BrokerCall("act", 3, _digest("d"), _digest("e"), False), ArcAgi3BrokerCall("status", 4, None, _digest("f"), True))


def _trace(calls: tuple[ArcAgi3BrokerCall, ...]) -> ArcAgi3Trace:
    return ArcAgi3Trace(P7_ARC_AGI_3_WORKLOAD_DIGEST, _digest("a"), arc_agi_3_action_chain_sha256(calls), _digest("f"), _digest("9"), P7_ARC_AGI_3_ORACLE_SHA256, P7_ARC_AGI_3_MODEL_SHA256, P7_ARC_AGI_3_SCHEMA_SHA256, ("ipython",), 1, 1, 4, 4, 1, 2, 1, 12, True, True, True, True)


class TestArcAgi3Acceptance(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_exact_broker_transcript_and_host_score_replay(self) -> None:
        calls = _calls()
        trace = _trace(calls)

        class Broker:
            async def calls(self) -> tuple[ArcAgi3BrokerCall, ...]: return calls
            async def replay_score(self, action_chain: str) -> str: return trace.score_sha256

        receipt = await accept_arc_agi_3(broker=Broker(), trace=trace, disposed=True, reaped=True)
        self.assertEqual(receipt.level.value, "provider-free")

    async def test_rejects_mismatched_replay_or_cleanup(self) -> None:
        calls = _calls()
        class Broker:
            async def calls(self) -> tuple[ArcAgi3BrokerCall, ...]: return calls
            async def replay_score(self, action_chain: str) -> str: return _digest("0")
        with self.assertRaises(ArcAgi3AcceptanceError):
            await accept_arc_agi_3(broker=Broker(), trace=_trace(calls), disposed=False, reaped=True)
        with self.assertRaises(ArcAgi3AcceptanceError):
            await accept_arc_agi_3(broker=Broker(), trace=_trace(calls), disposed=True, reaped=True)
