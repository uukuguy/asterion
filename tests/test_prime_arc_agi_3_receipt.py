"""Closed redacted trace tests for Prime P7 ARC-AGI-3."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from asterion.applications.prime_agent.arc_agi_3_receipt import (
    ArcAgi3ReceiptError,
    ArcAgi3Trace,
    validate_arc_agi_3_trace,
)
from asterion.applications.prime_agent.operator.arc_agi_3_workload import (
    P7_ARC_AGI_3_MODEL_SHA256,
    P7_ARC_AGI_3_ORACLE_SHA256,
    P7_ARC_AGI_3_SCHEMA_SHA256,
    P7_ARC_AGI_3_WORKLOAD_DIGEST,
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _trace(**changes: object) -> ArcAgi3Trace:
    values: dict[str, object] = {
        "workload_sha256": P7_ARC_AGI_3_WORKLOAD_DIGEST,
        "initial_observation_sha256": _digest("a"),
        "action_chain_sha256": _digest("b"),
        "terminal_status_sha256": _digest("c"),
        "score_sha256": _digest("d"),
        "oracle_sha256": P7_ARC_AGI_3_ORACLE_SHA256,
        "model_sha256": P7_ARC_AGI_3_MODEL_SHA256,
        "schema_sha256": P7_ARC_AGI_3_SCHEMA_SHA256,
        "tool_names": ("ipython",),
        "game_count": 1,
        "first_broker_sequence": 1,
        "last_broker_sequence": 4,
        "broker_call_count": 4,
        "observation_count": 1,
        "action_count": 2,
        "status_count": 1,
        "usage_count": 12,
        "terminal": True,
        "score_replayed": True,
        "disposed": True,
        "reaped": True,
    }
    values.update(changes)
    return ArcAgi3Trace(**values)  # type: ignore[arg-type]


class TestArcAgi3Receipt(unittest.TestCase):
    def test_trace_binds_one_game_contiguous_broker_calls_and_score_replay(self) -> None:
        trace = _trace()
        validate_arc_agi_3_trace(trace)
        self.assertEqual(repr(trace), "ArcAgi3Trace(redacted)")
        with self.assertRaises(FrozenInstanceError):
            trace.terminal = False  # type: ignore[misc]

    def test_rejects_identity_tool_sequence_and_terminal_substitutions(self) -> None:
        for changes in (
            {"workload_sha256": _digest("0")},
            {"model_sha256": _digest("0")},
            {"oracle_sha256": _digest("0")},
            {"schema_sha256": _digest("0")},
            {"tool_names": ("shell",)},
            {"game_count": 2},
            {"last_broker_sequence": 5},
            {"broker_call_count": True},
            {"action_count": 0},
            {"terminal": False},
            {"score_replayed": False},
            {"disposed": False},
        ):
            with self.subTest(changes=changes), self.assertRaises(ArcAgi3ReceiptError):
                validate_arc_agi_3_trace(_trace(**changes))

    def test_rejects_extra_fields_and_private_repr_content(self) -> None:
        trace = _trace()
        object.__setattr__(trace, "private_game", "SECRET_BOARD_CELLS")

        with self.assertRaises(ArcAgi3ReceiptError):
            validate_arc_agi_3_trace(trace)
        self.assertNotIn("SECRET_BOARD_CELLS", repr(trace))
