"""Closed bounded-evidence tests for a real Prime recursive workflow."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from asterion.applications.prime_agent.evidence import PrimeEvidenceLevel
from asterion.applications.prime_agent.recursive_workflow_receipt import (
    RecursiveWorkflowReceiptError,
    RecursiveWorkflowTrace,
    verify_real_recursive_workflow_trace,
)


def _digest(value: str) -> str:
    return "sha256:" + value * 64


def _trace(**changes: object) -> RecursiveWorkflowTrace:
    values: dict[str, object] = {
        "workload_sha256": _digest("a"),
        "root_artifact_sha256": _digest("b"),
        "first_child_role_digests": (_digest("c"), _digest("d")),
        "first_child_result_digests": (_digest("e"), _digest("f")),
        "first_child_usage_digests": (_digest("0"), _digest("1")),
        "follow_up_digest": _digest("2"),
        "aggregation_sha256": _digest("3"),
        "oracle_sha256": _digest("4"),
        "model_sha256": _digest("5"),
        "usage_sha256": _digest("6"),
        "root_to_child_message_count": 2,
        "child_to_root_result_count": 3,
        "follow_up_count": 1,
        "root_deleted_child_count": 2,
        "root_continued_locally": True,
        "root_work_before_children": True,
        "child_tool_names": (("ipython",), ("ipython",)),
        "child_ipython_action_counts": (1, 1),
        "revoked": True,
        "disposed": True,
        "reaped": True,
    }
    values.update(changes)
    return RecursiveWorkflowTrace(**values)  # type: ignore[arg-type]


class TestRecursiveWorkflowTrace(unittest.TestCase):
    def test_emits_only_matching_bounded_receipt(self) -> None:
        receipt = verify_real_recursive_workflow_trace(
            _trace(), PrimeEvidenceLevel.BOUNDED
        )

        self.assertEqual(receipt.scenario_id, "prime.recursive-workflow/v1")
        self.assertIs(receipt.level, PrimeEvidenceLevel.BOUNDED)
        self.assertEqual(receipt.status, "PASS")
        self.assertIsNone(receipt.receipt_scenario_id)

    def test_rejects_absent_real_workflow_facts(self) -> None:
        cases: tuple[dict[str, object], ...] = (
            {"root_continued_locally": False},
            {"root_work_before_children": False},
            {"child_tool_names": (("ipython",), ("shell",))},
            {"child_ipython_action_counts": (0, 1)},
            {"first_child_result_digests": (_digest("e"),)},
            {"follow_up_count": 0},
            {"root_deleted_child_count": 1},
            {"usage_sha256": ""},
            {"revoked": False},
            {"disposed": False},
            {"reaped": False},
            {"model_sha256": _digest("A")},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(
                RecursiveWorkflowReceiptError
            ):
                verify_real_recursive_workflow_trace(_trace(**changes))

    def test_rejects_every_p1_p2_identity(self) -> None:
        for level in (
            PrimeEvidenceLevel.PROVIDER_FREE,
            PrimeEvidenceLevel.BOUNDED_SANDBOXED,
            PrimeEvidenceLevel.FULL_AUTHORIZED,
        ):
            with self.subTest(level=level), self.assertRaises(
                RecursiveWorkflowReceiptError
            ):
                verify_real_recursive_workflow_trace(_trace(), level)

    def test_trace_is_immutable_and_redacts_private_values(self) -> None:
        trace = _trace(workload_sha256="PRIVATE-RLM-WORKLOAD")

        self.assertNotIn("PRIVATE-RLM-WORKLOAD", repr(trace))
        with self.assertRaises(FrozenInstanceError):
            trace.revoked = False  # type: ignore[misc]

    def test_rejects_unrecognized_private_trace_field_without_disclosure(self) -> None:
        trace = _trace()
        sentinel = "PRIVATE_RLM_SECRET"
        object.__setattr__(trace, "private_field", sentinel)

        with self.assertRaises(RecursiveWorkflowReceiptError) as raised:
            verify_real_recursive_workflow_trace(trace)
        self.assertNotIn(sentinel, repr(trace))
        self.assertNotIn(sentinel, str(trace))
        self.assertNotIn(sentinel, str(raised.exception))
