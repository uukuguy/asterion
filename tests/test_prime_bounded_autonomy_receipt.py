from __future__ import annotations

import unittest

from asterion.applications.prime_agent.bounded_autonomy_receipt import (
    BoundedAutonomyTrace,
    BoundedAutonomyReceiptError,
    validate_bounded_autonomy_trace,
)
from asterion.applications.prime_agent.operator.bounded_autonomy_workload import (
    P5_BOUNDED_AUTONOMY_MODEL_SHA256,
    P5_BOUNDED_AUTONOMY_ORACLE_SHA256,
    P5_BOUNDED_AUTONOMY_SCHEMA_SHA256,
    P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST,
)


def _digest(letter: str) -> str:
    return "sha256:" + letter * 64


class TestBoundedAutonomyReceipt(unittest.TestCase):
    def test_requires_changed_workspace_and_exact_two_gate_sequence(self) -> None:
        trace = BoundedAutonomyTrace(
            P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST, _digest("b"), _digest("c"), _digest("d"),
            _digest("e"), P5_BOUNDED_AUTONOMY_ORACLE_SHA256, P5_BOUNDED_AUTONOMY_MODEL_SHA256, P5_BOUNDED_AUTONOMY_SCHEMA_SHA256,
            ("ipython",), 2, 2, 2, 1, True, True, True, True, True, True,
        )
        validate_bounded_autonomy_trace(trace)
        with self.assertRaises(BoundedAutonomyReceiptError):
            validate_bounded_autonomy_trace(
                BoundedAutonomyTrace(
                    P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST, _digest("b"), _digest("b"), _digest("d"),
                    _digest("e"), P5_BOUNDED_AUTONOMY_ORACLE_SHA256, P5_BOUNDED_AUTONOMY_MODEL_SHA256, P5_BOUNDED_AUTONOMY_SCHEMA_SHA256,
                    ("ipython",), 2, 2, 2, 1, True, True, True, True, True, True,
                )
            )

        with self.assertRaises(BoundedAutonomyReceiptError):
            validate_bounded_autonomy_trace(
                BoundedAutonomyTrace(
                    _digest("a"), _digest("b"), _digest("c"), _digest("d"),
                    _digest("e"), P5_BOUNDED_AUTONOMY_ORACLE_SHA256, P5_BOUNDED_AUTONOMY_MODEL_SHA256, P5_BOUNDED_AUTONOMY_SCHEMA_SHA256,
                    ("ipython",), 2, 2, 2, 1, True, True, True, True, True, True,
                )
            )
