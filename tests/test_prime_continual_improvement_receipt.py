"""Bounded-only receipt tests for Prime continual improvement."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from asterion.applications.prime_agent.continual_improvement_receipt import (
    ContinualImprovementObservation,
    ContinualImprovementReceiptError,
    continual_improvement_observation_from_receipt,
    verify_continual_improvement_receipt,
)
from asterion.applications.prime_agent.evidence import PrimeEvidenceLevel


def _receipt(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "format": "asterion.prime-continual-harness-bounded/v1",
        "status": "PASS",
        "model_selector_digest": "a" * 64,
        "provider_operations": 1,
        "model_credential_reads": 1,
        "evidence_input_count": 7,
        "proposal_grounded": True,
        "host_admitted": True,
        "snapshot_activated": True,
        "limits": {
            "aggregate_tokens": 150_000,
            "cost_micros": 500_000,
            "deadline_ms": 600_000,
        },
        "usage": {"aggregate_tokens": 8_203, "cost_micros": 0},
    }
    result.update(changes)
    return result


class TestContinualImprovementReceipt(unittest.TestCase):
    def test_exact_bounded_refinement_emits_bounded_evidence_only(self) -> None:
        observation = continual_improvement_observation_from_receipt(_receipt())
        receipt = verify_continual_improvement_receipt(observation)

        self.assertEqual(receipt.scenario_id, "prime.continual-improvement/v1")
        self.assertIs(receipt.level, PrimeEvidenceLevel.BOUNDED_SANDBOXED)

    def test_rejects_unbounded_ungrounded_or_nonactivated_refinement(self) -> None:
        for changes in (
            {"provider_operations": 0},
            {"model_credential_reads": 0},
            {"evidence_input_count": 6},
            {"proposal_grounded": False},
            {"host_admitted": False},
            {"snapshot_activated": False},
            {"raw_output": "PRIVATE_REFINEMENT_BODY"},
        ):
            with self.subTest(changes=changes), self.assertRaises(
                ContinualImprovementReceiptError
            ):
                continual_improvement_observation_from_receipt(_receipt(**changes))

    def test_rejects_evidence_upgrade_and_redacts_observation(self) -> None:
        observation = ContinualImprovementObservation(
            grounded_proposal=True,
            host_admitted=True,
            snapshot_activated=True,
            provider_operation_count=1,
            model_credential_read_count=1,
        )

        with self.assertRaises(ContinualImprovementReceiptError):
            verify_continual_improvement_receipt(
                observation, PrimeEvidenceLevel.FULL_AUTHORIZED
            )
        self.assertNotIn("PRIVATE_REFINEMENT_BODY", repr(observation))
        with self.assertRaises(FrozenInstanceError):
            observation.snapshot_activated = False  # type: ignore[misc]
