"""Provider-free receipt tests for Prime programmatic long context."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from asterion.applications.prime_agent.evidence import PrimeEvidenceLevel
from asterion.applications.prime_agent.programmatic_long_context_receipt import (
    ProgrammaticLongContextObservation,
    ProgrammaticLongContextReceiptError,
    programmatic_long_context_observation_from_public_report,
    verify_programmatic_long_context_receipt,
)


def _digest(value: str) -> str:
    return "sha256:" + value * 64


def _observation(**changes: object) -> ProgrammaticLongContextObservation:
    values: dict[str, object] = {
        "built_in_tools": ("ipython",),
        "active_tool_names": ("ipython",),
        "corpus_sha256": _digest("a"),
        "corpus_record_count": 8,
        "selected_record_count": 3,
        "program_sha256": _digest("b"),
        "aggregate_sha256": _digest("c"),
        "oracle_sha256": _digest("d"),
        "ipython_cell_executed": True,
        "oracle_passed": True,
    }
    values.update(changes)
    return ProgrammaticLongContextObservation(**values)  # type: ignore[arg-type]


class TestProgrammaticLongContextReceipt(unittest.TestCase):
    def test_emits_only_the_matching_provider_free_receipt(self) -> None:
        receipt = verify_programmatic_long_context_receipt(_observation())

        self.assertEqual(receipt.scenario_id, "prime.programmatic-long-context/v1")
        self.assertIs(receipt.level, PrimeEvidenceLevel.PROVIDER_FREE)
        self.assertEqual(receipt.status, "PASS")
        self.assertIsNone(receipt.receipt_scenario_id)

    def test_rejects_mutated_or_incomplete_truth_table_facts(self) -> None:
        cases: tuple[dict[str, object], ...] = (
            {"built_in_tools": ()},
            {"built_in_tools": ("ipython", "shell")},
            {"active_tool_names": ("shell",)},
            {"corpus_sha256": _digest("A")},
            {"corpus_record_count": 0},
            {"corpus_record_count": True},
            {"selected_record_count": 0},
            {"selected_record_count": 9},
            {"program_sha256": "sha256:" + "b" * 63},
            {"aggregate_sha256": "sha256:" + "C" * 64},
            {"oracle_sha256": "digest"},
            {"ipython_cell_executed": False},
            {"oracle_passed": False},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(
                ProgrammaticLongContextReceiptError
            ):
                verify_programmatic_long_context_receipt(_observation(**changes))

    def test_rejects_evidence_upgrade_and_redacts_private_observation_content(
        self,
    ) -> None:
        observation = _observation()

        with self.assertRaises(ProgrammaticLongContextReceiptError):
            verify_programmatic_long_context_receipt(
                observation, PrimeEvidenceLevel.BOUNDED_SANDBOXED
            )
        self.assertNotIn("CORPUS-SENTINEL", repr(observation))
        self.assertNotIn("PROGRAM-SENTINEL", str(observation))
        with self.assertRaises(FrozenInstanceError):
            observation.corpus_record_count = 9  # type: ignore[misc]

    def test_public_compatibility_report_only_converts_exact_supported_pass(
        self,
    ) -> None:
        report = {
            "format": "asterion.prime-programmatic-long-context-compat/v1",
            "status": "PASS",
            "reason": "supported",
            "real_prime_runtime": True,
            "allowed_tool_names": ["ipython"],
            "active_tool_names": ["ipython"],
            "corpus_sha256": _digest("a"),
            "corpus_record_count": 8,
            "selected_record_count": 3,
            "program_sha256": _digest("b"),
            "aggregate_sha256": _digest("c"),
            "oracle_sha256": _digest("d"),
            "ipython_cell_executed": True,
            "oracle_passed": True,
            "disposed": True,
            "reaped": True,
        }
        observation = programmatic_long_context_observation_from_public_report(report)

        self.assertEqual(
            verify_programmatic_long_context_receipt(observation).scenario_id,
            "prime.programmatic-long-context/v1",
        )
        for changes in (
            {"status": "External-limited", "reason": "missing-ipython"},
            {"allowed_tool_names": ["shell"]},
            {"disposed": False},
            {"reaped": False},
            {"unexpected": "value"},
        ):
            with self.subTest(changes=changes), self.assertRaises(
                ProgrammaticLongContextReceiptError
            ):
                programmatic_long_context_observation_from_public_report(
                    {**report, **changes}
                )
