"""Tests for Prime capability evidence boundaries."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from asterion.applications.prime_agent.evidence import (
    PRIME_CAPABILITY_SCENARIO_IDS,
    PrimeCapabilityEvidenceError,
    PrimeEvidenceLevel,
    PrimeEvidenceReceipt,
    can_promote,
    validate_prime_evidence_receipt,
)


class TestPrimeCapabilityEvidence(unittest.TestCase):
    def test_scenarios_are_the_closed_sorted_program_set(self) -> None:
        self.assertEqual(PRIME_CAPABILITY_SCENARIO_IDS, tuple(sorted(PRIME_CAPABILITY_SCENARIO_IDS)))
        self.assertEqual(len(PRIME_CAPABILITY_SCENARIO_IDS), 7)
        self.assertIn("prime.arc-agi-3/v1", PRIME_CAPABILITY_SCENARIO_IDS)

    def test_levels_are_immutable_closed_values(self) -> None:
        self.assertEqual(PrimeEvidenceLevel.PROVIDER_FREE.value, "provider-free")
        with self.assertRaises(AttributeError):
            PrimeEvidenceLevel.PROVIDER_FREE.value = "unsafe"  # type: ignore[misc]

    def test_pass_receipt_requires_a_known_matching_scenario(self) -> None:
        receipt = PrimeEvidenceReceipt(
            scenario_id="prime.ipython-coding/v1",
            level=PrimeEvidenceLevel.PROVIDER_FREE,
            status="PASS",
        )
        self.assertEqual(validate_prime_evidence_receipt(receipt), receipt)

        for scenario_id in ("prime.unknown/v1", "prime.arc-agi-3/v1"):
            with self.subTest(scenario_id=scenario_id), self.assertRaises(
                PrimeCapabilityEvidenceError
            ):
                validate_prime_evidence_receipt(
                    PrimeEvidenceReceipt(
                        scenario_id=scenario_id,
                        level=PrimeEvidenceLevel.PROVIDER_FREE,
                        status="PASS",
                        receipt_scenario_id="prime.ipython-coding/v1",
                    )
                )

    def test_receipts_are_frozen_and_reject_public_unsafe_values(self) -> None:
        receipt = PrimeEvidenceReceipt(
            scenario_id="prime.ipython-coding/v1",
            level=PrimeEvidenceLevel.PROVIDER_FREE,
            status="PASS",
        )
        with self.assertRaises(FrozenInstanceError):
            receipt.status = "FAIL"  # type: ignore[misc]

        with self.assertRaises(PrimeCapabilityEvidenceError):
            validate_prime_evidence_receipt({})  # type: ignore[arg-type]

    def test_evidence_never_promotes_to_a_broader_level(self) -> None:
        self.assertTrue(can_promote("prime.arc-agi-3/v1", "bounded-sandboxed", "bounded-sandboxed"))
        self.assertFalse(can_promote("prime.arc-agi-3/v1", "provider-free", "bounded-sandboxed"))
        self.assertFalse(can_promote("prime.arc-agi-3/v1", "bounded-sandboxed", "full-authorized"))
        self.assertFalse(can_promote("prime.unknown/v1", "provider-free", "provider-free"))
