"""Bounded-only receipt tests for Prime continual improvement."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import json
import unittest

from asterion.applications.prime_agent.continual_improvement_receipt import (
    ContinualImprovementTrace,
    ContinualImprovementObservation,
    ContinualImprovementReceiptError,
    continual_improvement_observation_from_receipt,
    verify_continual_improvement_receipt,
    validate_continual_improvement_trace,
)
from asterion.applications.prime_agent.evidence import PrimeEvidenceLevel
from asterion.applications.prime_agent.operator.continual_improvement_workload import (
    P6_CONTINUAL_IMPROVEMENT_MODEL_SHA256,
    P6_CONTINUAL_IMPROVEMENT_ORACLE_SHA256,
    P6_CONTINUAL_IMPROVEMENT_SCHEMA_SHA256,
    P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST,
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _trace(*, outcome: str = "preserved", rollback_count: int = 0) -> ContinualImprovementTrace:
    return ContinualImprovementTrace(
        P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST, _digest("a"), _digest("b"),
        _digest("c"), _digest("d"), _digest("e"), P6_CONTINUAL_IMPROVEMENT_ORACLE_SHA256,
        P6_CONTINUAL_IMPROVEMENT_MODEL_SHA256, P6_CONTINUAL_IMPROVEMENT_SCHEMA_SHA256,
        ("ipython",), 3, 10, 1, 1, rollback_count, outcome, True, True, True,
    )


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
    def test_trace_binds_fixed_workload_and_exact_outcome_branch(self) -> None:
        validate_continual_improvement_trace(_trace())
        validate_continual_improvement_trace(_trace(outcome="rolled-back", rollback_count=1))
        for trace in (
            _trace(outcome="preserved", rollback_count=1),
            _trace(outcome="rolled-back", rollback_count=0),
            ContinualImprovementTrace(
                _digest("0"), _digest("a"), _digest("b"), _digest("c"), _digest("d"), _digest("e"),
                P6_CONTINUAL_IMPROVEMENT_ORACLE_SHA256, P6_CONTINUAL_IMPROVEMENT_MODEL_SHA256,
                P6_CONTINUAL_IMPROVEMENT_SCHEMA_SHA256, ("ipython",), 3, 10, 1, 1, 0,
                "preserved", True, True, True,
            ),
        ):
            with self.subTest(trace=trace), self.assertRaises(ContinualImprovementReceiptError):
                validate_continual_improvement_trace(trace)

    def test_trusted_local_receipt_cannot_emit_bounded_evidence(self) -> None:
        source = _receipt()
        observation = continual_improvement_observation_from_receipt(source)

        with self.assertRaises(ContinualImprovementReceiptError):
            verify_continual_improvement_receipt(observation)
        self.assertEqual(
            observation.source_receipt_digest,
            "sha256:" + hashlib.sha256(json.dumps(
                source, ensure_ascii=True, separators=(",", ":"), sort_keys=True,
            ).encode()).hexdigest(),
        )

    def test_no_worker_receipt_can_promote_until_the_role_has_a_real_launcher(self) -> None:
        observation = continual_improvement_observation_from_receipt(_receipt())
        with self.assertRaises(ContinualImprovementReceiptError):
            verify_continual_improvement_receipt(observation, object())

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
            source_receipt_digest="sha256:" + "a" * 64,
        )

        with self.assertRaises(ContinualImprovementReceiptError):
            verify_continual_improvement_receipt(
                observation, PrimeEvidenceLevel.FULL_AUTHORIZED
            )
        self.assertNotIn("PRIVATE_REFINEMENT_BODY", repr(observation))
        with self.assertRaises(FrozenInstanceError):
            observation.snapshot_activated = False  # type: ignore[misc]
