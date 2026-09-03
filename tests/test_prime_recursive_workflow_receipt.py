"""Provider-free receipt tests for Prime recursive workflow."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from asterion.applications.prime_agent.evidence import PrimeEvidenceLevel
from asterion.applications.prime_agent.recursive_workflow_receipt import (
    RecursiveWorkflowObservation,
    RecursiveWorkflowReceiptError,
    recursive_workflow_observation_from_public_report,
    verify_recursive_workflow_receipt,
)


def _digest(value: str) -> str:
    return "sha256:" + value * 64


def _observation(**changes: object) -> RecursiveWorkflowObservation:
    values: dict[str, object] = {
        "built_in_tools": ("ipython",),
        "active_tool_names": ("ipython",),
        "admitted_child_count": 2,
        "bound_child_count": 2,
        "root_to_child_message_count": 2,
        "child_to_root_result_count": 2,
        "terminal_child_count": 2,
        "deleted_child_count": 2,
        "workflow_sha256": _digest("a"),
        "aggregation_sha256": _digest("b"),
        "oracle_sha256": _digest("c"),
        "root_continued_locally": True,
        "aggregation_passed": True,
    }
    values.update(changes)
    return RecursiveWorkflowObservation(**values)  # type: ignore[arg-type]


class TestRecursiveWorkflowReceipt(unittest.TestCase):
    def test_emits_only_matching_provider_free_receipt(self) -> None:
        receipt = verify_recursive_workflow_receipt(_observation())

        self.assertEqual(receipt.scenario_id, "prime.recursive-workflow/v1")
        self.assertIs(receipt.level, PrimeEvidenceLevel.PROVIDER_FREE)
        self.assertEqual(receipt.status, "PASS")
        self.assertIsNone(receipt.receipt_scenario_id)

    def test_rejects_incomplete_child_message_and_lifecycle_truth_table(self) -> None:
        for field in (
            "admitted_child_count",
            "bound_child_count",
            "root_to_child_message_count",
            "child_to_root_result_count",
            "terminal_child_count",
            "deleted_child_count",
        ):
            with self.subTest(field=field), self.assertRaises(
                RecursiveWorkflowReceiptError
            ):
                verify_recursive_workflow_receipt(_observation(**{field: 1}))

    def test_rejects_invalid_surface_facts_and_evidence_upgrade(self) -> None:
        cases: tuple[dict[str, object], ...] = (
            {"built_in_tools": ()},
            {"built_in_tools": ("ipython", "shell")},
            {"active_tool_names": ("shell",)},
            {"admitted_child_count": True},
            {"workflow_sha256": _digest("A")},
            {"aggregation_sha256": "sha256:" + "b" * 63},
            {"oracle_sha256": "digest"},
            {"root_continued_locally": False},
            {"aggregation_passed": False},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(
                RecursiveWorkflowReceiptError
            ):
                verify_recursive_workflow_receipt(_observation(**changes))
        with self.assertRaises(RecursiveWorkflowReceiptError):
            verify_recursive_workflow_receipt(
                _observation(), PrimeEvidenceLevel.BOUNDED_SANDBOXED
            )

    def test_private_observation_is_immutable_and_redacted(self) -> None:
        observation = _observation()

        self.assertNotIn("PRIVATE-RLM-GOAL", repr(observation))
        self.assertNotIn("PRIVATE-RLM-MESSAGE", str(observation))
        with self.assertRaises(FrozenInstanceError):
            observation.deleted_child_count = 1  # type: ignore[misc]

    def test_public_compatibility_report_only_converts_exact_supported_pass(self) -> None:
        report = {
            "format": "asterion.prime-recursive-workflow-compat/v1",
            "status": "PASS",
            "reason": "supported",
            "real_prime_runtime": True,
            "allowed_tool_names": ["ipython"],
            "active_tool_names": ["ipython"],
            "admitted_child_count": 2,
            "bound_child_count": 2,
            "root_to_child_message_count": 2,
            "child_to_root_result_count": 2,
            "terminal_child_count": 2,
            "deleted_child_count": 2,
            "workflow_sha256": _digest("a"),
            "aggregation_sha256": _digest("b"),
            "oracle_sha256": _digest("c"),
            "root_continued_locally": True,
            "aggregation_passed": True,
            "disposed": True,
            "reaped": True,
        }

        observation = recursive_workflow_observation_from_public_report(report)
        self.assertEqual(
            verify_recursive_workflow_receipt(observation).scenario_id,
            "prime.recursive-workflow/v1",
        )
        for changes in (
            {"status": "External-limited", "reason": "missing-prerequisite"},
            {"bound_child_count": 1},
            {"deleted_child_count": 1},
            {"disposed": False},
            {"reaped": False},
            {"unexpected": "value"},
        ):
            with self.subTest(changes=changes), self.assertRaises(
                RecursiveWorkflowReceiptError
            ):
                recursive_workflow_observation_from_public_report(
                    {**report, **changes}
                )
