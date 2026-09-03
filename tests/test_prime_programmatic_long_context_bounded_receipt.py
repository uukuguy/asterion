"""Closed bounded-receipt tests for Prime programmatic long context."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from asterion.applications.prime_agent.evidence import PrimeEvidenceLevel
from asterion.applications.prime_agent.operator.model_broker import PrimeModelBrokerReceipt
from asterion.applications.prime_agent.programmatic_long_context_bounded_receipt import (
    PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_SHA256,
    PROGRAMMATIC_LONG_CONTEXT_P2_ORACLE_SHA256,
    PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_SHA256,
    ProgrammaticLongContextBoundedObservation,
    ProgrammaticLongContextBoundedReceiptError,
    verify_programmatic_long_context_bounded_receipt,
)
from asterion.applications.prime_agent.worker_gate import PrimeWorkerBoundaryReceipt


def _digest(value: str) -> str:
    return "sha256:" + value * 64


_IMAGE = _digest("a")
_CHALLENGE = _digest("b")
_RESULT = _digest("c")


def _broker(**changes: object) -> PrimeModelBrokerReceipt:
    values: dict[str, object] = {
        "session_id": "session-1",
        "run_id": "run-1",
        "worker_id": "worker-1",
        "challenge_digest": _CHALLENGE,
        "request_count": 1,
        "input_bytes": 16,
        "output_bytes": 16,
        "status": "revoked",
    }
    values.update(changes)
    return PrimeModelBrokerReceipt(**values)  # type: ignore[arg-type]


def _worker(**changes: object) -> PrimeWorkerBoundaryReceipt:
    values: dict[str, object] = {
        "scenario_id": "prime.programmatic-long-context/v1",
        "role_id": "prime.programmatic-long-context",
        "worker_id": "worker-1",
        "run_id": "run-1",
        "challenge_digest": _CHALLENGE,
        "workload_digest": PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_SHA256,
        "result_digest": _RESULT,
        "image_digest": _IMAGE,
    }
    values.update(changes)
    return PrimeWorkerBoundaryReceipt._admit(**values)  # type: ignore[arg-type]


def _observation(**changes: object) -> ProgrammaticLongContextBoundedObservation:
    values: dict[str, object] = {
        "built_in_tools": ("ipython",),
        "active_tool_names": ("ipython",),
        "corpus_sha256": PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_SHA256,
        "program_sha256": _RESULT,
        "response_sha256": _RESULT,
        "aggregate_sha256": _RESULT,
        "oracle_sha256": PROGRAMMATIC_LONG_CONTEXT_P2_ORACLE_SHA256,
        "ipython_cell_executed": True,
        "oracle_passed": True,
        "broker_receipt": _broker(),
        "worker_receipt": _worker(),
    }
    values.update(changes)
    return ProgrammaticLongContextBoundedObservation(**values)  # type: ignore[arg-type]


class TestProgrammaticLongContextBoundedReceipt(unittest.TestCase):
    def test_emits_only_the_worker_bound_bounded_receipt(self) -> None:
        receipt = verify_programmatic_long_context_bounded_receipt(_observation())

        self.assertEqual(receipt.scenario_id, "prime.programmatic-long-context/v1")
        self.assertIs(receipt.level, PrimeEvidenceLevel.BOUNDED_SANDBOXED)
        self.assertEqual(receipt.status, "PASS")

    def test_rejects_mutated_or_missing_bounded_truth_table_facts(self) -> None:
        cases = (
            ("tools", {"built_in_tools": ()}),
            ("active-tools", {"active_tool_names": ("shell",)}),
            ("corpus", {"corpus_sha256": _digest("d")}),
            ("response-program", {"response_sha256": _digest("d")}),
            ("aggregate", {"aggregate_sha256": _digest("d")}),
            ("oracle", {"oracle_sha256": _digest("d")}),
            ("executed", {"ipython_cell_executed": False}),
            ("oracle-passed", {"oracle_passed": False}),
            ("broker-cleanup", {"broker_receipt": _broker(status="active")}),
            ("broker-no-requests", {"broker_receipt": _broker(request_count=0)}),
            ("broker-no-output", {"broker_receipt": _broker(output_bytes=0)}),
            ("broker-run", {"broker_receipt": _broker(run_id="run-2")}),
            ("broker-worker", {"broker_receipt": _broker(worker_id="worker-2")}),
            ("broker-challenge", {"broker_receipt": _broker(challenge_digest=_digest("d"))}),
            ("worker-scenario", {"worker_receipt": _worker(scenario_id="prime.ipython-coding/v1")}),
            ("worker-role", {"worker_receipt": _worker(role_id="prime.ipython-coding")}),
            ("worker-workload", {"worker_receipt": _worker(workload_digest=_digest("d"))}),
            ("worker-result", {"worker_receipt": _worker(result_digest=_digest("d"))}),
        )
        for name, changes in cases:
            with self.subTest(name=name), self.assertRaises(
                ProgrammaticLongContextBoundedReceiptError
            ):
                verify_programmatic_long_context_bounded_receipt(_observation(**changes))

    def test_rejects_evidence_downgrade_or_upgrade_and_redacts_private_facts(self) -> None:
        observation = _observation()

        for level in (PrimeEvidenceLevel.PROVIDER_FREE,):
            with self.subTest(level=level), self.assertRaises(
                ProgrammaticLongContextBoundedReceiptError
            ):
                verify_programmatic_long_context_bounded_receipt(observation, level)
        self.assertNotIn("SECRET-PROGRAM", repr(observation))
        self.assertNotIn("SECRET-RESPONSE", str(observation))
        with self.assertRaises(FrozenInstanceError):
            observation.program_sha256 = _digest("d")  # type: ignore[misc]

    def test_redacts_invalid_private_sentinels_from_observation_and_error(self) -> None:
        observation = _observation(
            program_sha256="SECRET-PROGRAM",
            response_sha256="SECRET-PROGRAM",
        )

        self.assertNotIn("SECRET-PROGRAM", repr(observation))
        self.assertNotIn("SECRET-PROGRAM", str(observation))
        with self.assertRaises(ProgrammaticLongContextBoundedReceiptError) as raised:
            verify_programmatic_long_context_bounded_receipt(observation)
        self.assertNotIn("SECRET-PROGRAM", str(raised.exception))
