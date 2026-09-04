"""Provider-free truth-table tests for the fixed Prime coding fixture."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import unittest

from asterion.applications.prime_agent.coding_fixture_receipt import (
    CodingFixtureObservation,
    CodingFixtureReceiptError,
    CodingFixtureWitness,
    verify_prime_coding_fixture_receipt,
)
from asterion.applications.prime_agent.evidence import PrimeEvidenceLevel
from asterion.applications.prime_agent.operator.model_broker import PrimeModelBrokerReceipt
from asterion.applications.prime_agent.worker_gate import PrimeWorkerBoundaryReceipt
from asterion.services.bounded_model_session import BoundedModelSessionRequest


_CHALLENGE = "sha256:" + "a" * 64
_IMAGE = "sha256:" + "b" * 64
_WORKLOAD = "sha256:" + "c" * 64
_RESULT = "sha256:" + "d" * 64


def _session(**changes: object) -> BoundedModelSessionRequest:
    values: dict[str, object] = {
        "run_id": "run-1", "max_requests": 2, "max_input_tokens": 32,
        "max_output_tokens": 32, "max_input_bytes": 32, "max_output_bytes": 32,
        "max_cost_microunits": 32, "deadline_seconds": 30,
    }
    values.update(changes)
    return BoundedModelSessionRequest(**values)  # type: ignore[arg-type]


def _broker(**changes: object) -> PrimeModelBrokerReceipt:
    values: dict[str, object] = {
        "session_id": "session-1", "run_id": "run-1", "worker_id": "worker-1",
        "challenge_digest": _CHALLENGE, "request_count": 2, "input_bytes": 16,
        "output_bytes": 24, "status": "revoked",
    }
    values.update(changes)
    return PrimeModelBrokerReceipt(**values)  # type: ignore[arg-type]


def _worker(**changes: object) -> PrimeWorkerBoundaryReceipt:
    values: dict[str, object] = {
        "scenario_id": "prime.ipython-coding/v1", "role_id": "prime.ipython-coding",
        "worker_id": "worker-1", "run_id": "run-1", "challenge_digest": _CHALLENGE,
        "workload_digest": _WORKLOAD, "result_digest": _RESULT,
        "image_digest": _IMAGE,
    }
    values.update(changes)
    return PrimeWorkerBoundaryReceipt._admit(**values)  # type: ignore[arg-type]


def _observation(**changes: object) -> CodingFixtureObservation:
    values: dict[str, object] = {
        "built_in_tools": ("ipython",), "model_tool_calls": ("ipython", "ipython"),
        "turn_count": 2, "compaction_turn": 1, "session_id": "session-1",
        "kernel_generation": "kernel-1", "image_digest": _IMAGE, "witnesses": (
            CodingFixtureWitness("session-1", "kernel-1", 2, "cwd"),
            CodingFixtureWitness("session-1", "kernel-1", 2, "function"),
            CodingFixtureWitness("session-1", "kernel-1", 2, "import"),
            CodingFixtureWitness("session-1", "kernel-1", 2, "namespace"),
            CodingFixtureWitness("session-1", "kernel-1", 2, "workspace-file"),
        ),
        "child_session_opened": False, "other_action_taken": False,
        "oracle_initially_failed": True, "oracle_eventually_passed": True,
        "session_limits": _session(), "broker_receipt": _broker(), "worker_receipt": _worker(),
    }
    values.update(changes)
    return CodingFixtureObservation(**values)  # type: ignore[arg-type]


class TestPrimeCodingFixtureReceipt(unittest.TestCase):
    def test_emits_only_the_fixed_provider_free_receipt(self) -> None:
        receipt = verify_prime_coding_fixture_receipt(_observation())
        self.assertEqual(receipt.scenario_id, "prime.ipython-coding/v1")
        self.assertIs(receipt.level, PrimeEvidenceLevel.PROVIDER_FREE)
        self.assertEqual(receipt.status, "PASS")
        self.assertEqual(tuple(receipt.__dataclass_fields__), (
            "scenario_id", "level", "status", "receipt_scenario_id"))

    def test_rejects_each_missing_or_mutated_truth_table_fact(self) -> None:
        witness = _observation().witnesses
        cases = (
            ("tools", {"built_in_tools": ()}),
            ("extra-tool", {"built_in_tools": ("ipython", "other")}),
            ("tool-call", {"model_tool_calls": ("ipython", "other")}),
            ("no-tool-calls", {"model_tool_calls": ()}),
            ("turns", {"turn_count": 1}),
            ("no-compaction", {"compaction_turn": 0}),
            ("late-compaction", {"compaction_turn": 2}),
            ("session", {"session_id": "session-2"}),
            ("kernel", {"kernel_generation": "kernel-2"}),
            ("image", {"image_digest": "sha256:" + "c" * 64}),
            ("witness-session", {"witnesses": (replace(witness[0], session_id="session-2"), *witness[1:])}),
            ("witness-kernel", {"witnesses": (replace(witness[0], kernel_generation="kernel-2"), *witness[1:])}),
            ("pre-compaction-witness", {"witnesses": (replace(witness[0], turn=1), *witness[1:])}),
            ("missing-post-kind", {"witnesses": witness[:-1]}),
            ("unexpected-post-kind", {"witnesses": (*witness, CodingFixtureWitness("session-1", "kernel-1", 2, "namespace"))}),
            ("child-session", {"child_session_opened": True}),
            ("other-action", {"other_action_taken": True}),
            ("oracle-not-initially-failed", {"oracle_initially_failed": False}),
            ("oracle-not-passed", {"oracle_eventually_passed": False}),
            ("broker-not-terminal", {"broker_receipt": _broker(status="active")}),
            ("broker-over-requests", {"broker_receipt": _broker(request_count=3)}),
            ("broker-unbound-requests", {"broker_receipt": _broker(request_count=1)}),
            ("broker-over-input", {"broker_receipt": _broker(input_bytes=33)}),
            ("broker-over-output", {"broker_receipt": _broker(output_bytes=33)}),
            ("broker-session", {"broker_receipt": _broker(session_id="session-2")}),
            ("broker-run", {"broker_receipt": _broker(run_id="run-2")}),
            ("broker-worker", {"broker_receipt": _broker(worker_id="worker-2")}),
            ("broker-challenge", {"broker_receipt": _broker(challenge_digest="sha256:" + "c" * 64)}),
            ("worker-run", {"worker_receipt": _worker(run_id="run-2")}),
            ("worker-id", {"worker_receipt": _worker(worker_id="worker-2")}),
            ("worker-challenge", {"worker_receipt": _worker(challenge_digest="sha256:" + "c" * 64)}),
            ("worker-scenario", {"worker_receipt": _worker(scenario_id="prime.arc-agi-3/v1")}),
            ("worker-role", {"worker_receipt": _worker(role_id="prime.arc-agi-3")}),
            ("worker-image", {"worker_receipt": _worker(image_digest="sha256:" + "c" * 64)}),
        )
        for name, changes in cases:
            with self.subTest(name=name), self.assertRaises(CodingFixtureReceiptError):
                verify_prime_coding_fixture_receipt(_observation(**changes))

    def test_rejects_upgrade_requests_and_private_sentinels_are_not_exposed(self) -> None:
        observation = _observation()
        with self.assertRaises(CodingFixtureReceiptError):
            verify_prime_coding_fixture_receipt(observation, PrimeEvidenceLevel.BOUNDED_SANDBOXED)
        self.assertNotIn("SECRET-PROMPT", repr(observation))
        self.assertNotIn("SECRET-PROMPT", repr(_broker()))
        with self.assertRaises(FrozenInstanceError):
            observation.turn_count = 3  # type: ignore[misc]
