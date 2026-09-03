"""Bounded-only receipt tests for Prime autonomous goal completion."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import unittest

from asterion.applications.prime_agent.bounded_autonomy_receipt import (
    BoundedAutonomyObservation,
    BoundedAutonomyReceiptError,
    bounded_autonomy_observation_from_receipt,
    verify_bounded_autonomy_receipt,
)
from asterion.applications.prime_agent.evidence import PrimeEvidenceLevel
from asterion.applications.prime_agent.worker_gate import PrimeWorkerBoundaryReceipt


def _receipt(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "format": "asterion.prime-long-running-bounded-receipt/v1",
        "status": "PASS",
        "terminal": "completed",
        "checks": [
            "bounded-autonomous-goal-completed-passed",
            "bounded-heartbeat-schedule-quiescence-passed",
            "bounded-orphan-audit-passed",
        ],
        "provider_operations": 1,
        "model_credential_reads": 1,
        "model_selector_digest": "a" * 64,
        "usage": {"aggregate_tokens": 9_000, "cost_micros": 0},
        "limits": {
            "aggregate_tokens": 150_000,
            "cost_micros": 500_000,
            "deadline_ms": 600_000,
        },
    }
    value.update(changes)
    return value


class TestBoundedAutonomyReceipt(unittest.TestCase):
    def test_trusted_local_receipt_cannot_emit_bounded_evidence(self) -> None:
        source = _receipt()
        observation = bounded_autonomy_observation_from_receipt(source)

        with self.assertRaises(BoundedAutonomyReceiptError):
            verify_bounded_autonomy_receipt(observation)
        self.assertEqual(
            observation.source_receipt_digest,
            "sha256:" + hashlib.sha256(json.dumps(
                source, ensure_ascii=True, separators=(",", ":"), sort_keys=True,
            ).encode()).hexdigest(),
        )

    def test_matching_worker_result_emits_bounded_evidence(self) -> None:
        observation = bounded_autonomy_observation_from_receipt(_receipt())
        worker = PrimeWorkerBoundaryReceipt(
            "prime.bounded-autonomy/v1", "prime.bounded-autonomy", "worker-1",
            "run-1", "sha256:" + "b" * 64, "sha256:" + "c" * 64,
            observation.source_receipt_digest, "sha256:" + "d" * 64,
        )
        receipt = verify_bounded_autonomy_receipt(observation, worker)

        self.assertEqual(receipt.scenario_id, "prime.bounded-autonomy/v1")
        self.assertIs(receipt.level, PrimeEvidenceLevel.BOUNDED_SANDBOXED)

        for worker_receipt in (
            replace(worker, scenario_id="prime.continual-improvement/v1"),
            replace(worker, result_digest="sha256:" + "e" * 64),
        ):
            with self.subTest(worker_receipt=worker_receipt), self.assertRaises(
                BoundedAutonomyReceiptError
            ):
                verify_bounded_autonomy_receipt(observation, worker_receipt)

    def test_rejects_missing_model_or_finite_autonomy_facts(self) -> None:
        for changes in (
            {"provider_operations": 0},
            {"model_credential_reads": 0},
            {"terminal": "failed"},
            {"checks": []},
            {"usage": {"aggregate_tokens": 150_001, "cost_micros": 0}},
            {"raw_output": "PRIVATE_MODEL_OUTPUT"},
        ):
            with self.subTest(changes=changes), self.assertRaises(
                BoundedAutonomyReceiptError
            ):
                bounded_autonomy_observation_from_receipt(_receipt(**changes))

    def test_rejects_evidence_upgrade_and_redacts_observation(self) -> None:
        observation = BoundedAutonomyObservation(
            goal_completed=True,
            host_quiescent=True,
            orphan_audit_clean=True,
            provider_operation_count=1,
            model_credential_read_count=1,
            source_receipt_digest="sha256:" + "a" * 64,
        )

        with self.assertRaises(BoundedAutonomyReceiptError):
            verify_bounded_autonomy_receipt(
                observation, PrimeEvidenceLevel.PROVIDER_FREE
            )
        self.assertNotIn("PRIVATE_MODEL_OUTPUT", repr(observation))
        with self.assertRaises(FrozenInstanceError):
            observation.goal_completed = False  # type: ignore[misc]
