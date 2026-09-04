from __future__ import annotations

import unittest

from asterion.applications.prime_agent.arc_agi_3_receipt import ArcAgi3Trace
from asterion.applications.prime_agent.operator.arc_agi_3_completion import (
    ArcAgi3Completion,
    ArcAgi3CompletionError,
    canonical_arc_agi_3_completion_bytes,
)
from asterion.applications.prime_agent.operator.arc_agi_3_worker import (
    P7_ARC_AGI_3_ADAPTER,
)
from asterion.applications.prime_agent.operator.arc_agi_3_workload import (
    P7_ARC_AGI_3_MODEL_SHA256,
    P7_ARC_AGI_3_ORACLE_SHA256,
    P7_ARC_AGI_3_SCHEMA_SHA256,
    P7_ARC_AGI_3_WORKLOAD_DIGEST,
)


def _digest(letter: str) -> str:
    return "sha256:" + letter * 64


class TestArcAgi3Worker(unittest.TestCase):
    def test_completion_encoder_rejects_forged_private_trace(self) -> None:
        class ForgedTrace:
            private = "PRIVATE_BOARD"

        with self.assertRaises(ArcAgi3CompletionError):
            canonical_arc_agi_3_completion_bytes(
                ArcAgi3Completion(ForgedTrace())  # type: ignore[arg-type]
            )

    def test_p7_adapter_rejects_multiple_games(self) -> None:
        trace = ArcAgi3Trace(
            P7_ARC_AGI_3_WORKLOAD_DIGEST, _digest("a"), _digest("b"),
            _digest("c"), _digest("d"), P7_ARC_AGI_3_ORACLE_SHA256,
            P7_ARC_AGI_3_MODEL_SHA256, P7_ARC_AGI_3_SCHEMA_SHA256, ("ipython",),
            1, 1, 4, 4, 1, 2, 1, 12, True, True, True, True,
        )
        self.assertTrue(
            P7_ARC_AGI_3_ADAPTER.parse_completion(
                canonical_arc_agi_3_completion_bytes(ArcAgi3Completion(trace))
            )
        )
        two_games = ArcAgi3Trace(
            P7_ARC_AGI_3_WORKLOAD_DIGEST, _digest("a"), _digest("b"),
            _digest("c"), _digest("d"), P7_ARC_AGI_3_ORACLE_SHA256,
            P7_ARC_AGI_3_MODEL_SHA256, P7_ARC_AGI_3_SCHEMA_SHA256, ("ipython",),
            2, 1, 4, 4, 1, 2, 1, 12, True, True, True, True,
        )
        raw = canonical_arc_agi_3_completion_bytes_unchecked(two_games)
        self.assertFalse(P7_ARC_AGI_3_ADAPTER.parse_completion(raw))


def canonical_arc_agi_3_completion_bytes_unchecked(trace: ArcAgi3Trace) -> bytes:
    import json

    payload: dict[str, object] = {"format": "asterion.prime-arc-agi-3/v1"}
    payload.update(vars(trace))
    payload["tool_names"] = list(trace.tool_names)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
