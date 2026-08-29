from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from dataclasses import dataclass
from pathlib import Path

from asterion.control.parity_testing import ParityScenarioRegistry
from asterion.control.long_running import LongRunningIntent, LongRunningReceipt
from asterion.control.providers.prime.client import (
    PrimeControlPlaneClient,
    PrimeLongRunningIpcReceipt,
)
from asterion.control.providers.prime.long_running import (
    PrimeLongRunningCommand,
    PrimeLongRunningError,
    PrimeLongRunningService,
)
from asterion.control.providers.prime.parity_testing import (
    PHASE1_PRIME_SCENARIO_IDS,
    PRIME_LONG_RUNNING_BOUNDED_PASS_CHECK_IDS,
    PRIME_LONG_RUNNING_BOUNDED_VERIFICATION_COMMAND_ID,
    PRIME_LONG_RUNNING_BOUNDED_SCENARIO_IDS,
    PRIME_LONG_RUNNING_PROVIDER_FREE_VERIFICATION_COMMAND_ID,
    PRIME_LONG_RUNNING_PROVIDER_FREE_SCENARIO_IDS,
    PRIME_LONG_RUNNING_REQUIRED_CHECK_IDS,
    PRIME_LONG_RUNNING_SCENARIO_MATRIX,
    PROVEN_PHASE1_PARITY_SCENARIO_IDS,
    build_prime_long_running_bounded_observation,
    build_prime_long_running_observation,
    register_prime_long_running_scenarios,
)


ROOT = Path(__file__).resolve().parents[1]
LEDGER = (
    ROOT / "tests" / "fixtures" / "prime-parity" / "v1" /
    "prime-agent-0.7.1.json"
)


@dataclass(frozen=True)
class _Phase1Result:
    scenario_id: str
    evidence_id: str
    status: str = "PASS"
    outcome: str = "proven-effect-succeeded"
    provider_operations: int = 0
    pathlight_control_events: tuple[str, ...] = ()
    pathlight_gaps: tuple[str, ...] = ()
    serialized_observations: str = "public-safe"


class _PrivateContent:
    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        raise AssertionError("long-running IPC must not resolve public input refs")


class _LongRunningProcess:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    async def request(self, envelope):
        self.requests.append(dict(envelope))
        command_id = envelope["command_id"]
        return {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": envelope["id"],
            "type": "long-running.receipt",
            "receipt": {
                "commandId": command_id,
                "commandDigest": "a" * 64,
                "status": "succeeded",
            },
        }

    async def close(self) -> None:
        return None


class _ServiceClient:
    def __init__(self, *, receipt_command_id: str = "effect-1") -> None:
        self.receipt_command_id = receipt_command_id
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute_long_running(self, command_id, command):
        self.calls.append((command_id, dict(command)))
        return PrimeLongRunningIpcReceipt(
            self.receipt_command_id,
            "b" * 64,
            "succeeded",
        )


def _phase1_results() -> tuple[_Phase1Result, ...]:
    events = {
        "prime-loop-application": (
            "goal.updated",
            "session.completed",
            "session.created",
        ),
        "prime-loop-detach-attach": (
            "session.created",
            "session.recovery-required",
            "session.running",
        ),
    }
    return tuple(
        _Phase1Result(
            scenario_id=scenario_id,
            evidence_id="evidence.phase1."
            + hashlib.sha256(f"public-safe-{scenario_id}".encode()).hexdigest(),
            pathlight_control_events=events.get(scenario_id, ()),
            serialized_observations=f"public-safe-{scenario_id}",
        )
        for scenario_id in PHASE1_PRIME_SCENARIO_IDS
    )


class TestPrimeLongRunningParity(unittest.TestCase):
    def test_bounded_observation_is_bound_to_one_finite_safe_receipt(self) -> None:
        receipt = {
            "format": "asterion.prime-long-running-bounded-receipt/v1",
            "status": "PASS",
            "terminal": "completed",
            "checks": list(PRIME_LONG_RUNNING_BOUNDED_PASS_CHECK_IDS),
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

        observation = build_prime_long_running_bounded_observation(receipt)

        self.assertEqual(observation.provider_operations, 1)
        serialized = json.loads(observation.serialized_observations)
        self.assertEqual(
            serialized["bounded_receipt_sha256"],
            hashlib.sha256(
                json.dumps(
                    receipt,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
        )
        self.assertNotIn("model_selector_digest", serialized)

    def test_bounded_observation_rejects_unbounded_or_content_bearing_receipt(
        self,
    ) -> None:
        base = {
            "format": "asterion.prime-long-running-bounded-receipt/v1",
            "status": "PASS",
            "terminal": "completed",
            "checks": list(PRIME_LONG_RUNNING_BOUNDED_PASS_CHECK_IDS),
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
        invalid = (
            {**base, "provider_operations": 2},
            {**base, "usage": {"aggregate_tokens": 150_001, "cost_micros": 0}},
            {**base, "raw_output": "SENTINEL_PRIVATE_OUTPUT"},
        )

        for receipt in invalid:
            with self.subTest(receipt=receipt), self.assertRaisesRegex(
                Exception, "observation is invalid"
            ):
                build_prime_long_running_bounded_observation(receipt)

    def test_long_running_matrix_matches_the_ten_ledger_scenarios(self) -> None:
        expected = (
            "prime-parity.operation.autonomous-quality",
            "prime-parity.operation.detach-attach-replay",
            "prime-parity.operation.goals",
            "prime-parity.operation.heartbeat-agent",
            "prime-parity.operation.heartbeat-user",
            "prime-parity.operation.orphan-cleanup",
            "prime-parity.operation.resident-workers",
            "prime-parity.operation.restart-update-recovery",
            "prime-parity.operation.schedule-once-cron",
            "prime-parity.operation.worker-residency-eviction",
        )

        self.assertEqual(PRIME_LONG_RUNNING_SCENARIO_MATRIX, expected)
        self.assertEqual(
            PRIME_LONG_RUNNING_BOUNDED_SCENARIO_IDS,
            ("prime-parity.operation.autonomous-quality",),
        )
        self.assertEqual(
            PRIME_LONG_RUNNING_PROVIDER_FREE_SCENARIO_IDS,
            tuple(item for item in expected if item not in {
                "prime-parity.operation.autonomous-quality"
            }),
        )

    def test_phase1_promotes_only_detach_attach_and_goals(self) -> None:
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        registry = ParityScenarioRegistry(
            ledger,
            provider_id="asterion.prime-gateway",
        )

        register_prime_long_running_scenarios(
            registry,
            _phase1_results(),
            provider_factory=lambda: object(),
        )
        report = asyncio.run(registry.run(PRIME_LONG_RUNNING_SCENARIO_MATRIX))

        self.assertEqual(
            report.passed_scenario_ids,
            PROVEN_PHASE1_PARITY_SCENARIO_IDS,
        )
        self.assertEqual(
            report.blocking_scenario_ids,
            tuple(
                scenario_id
                for scenario_id in PRIME_LONG_RUNNING_SCENARIO_MATRIX
                if scenario_id not in PROVEN_PHASE1_PARITY_SCENARIO_IDS
            ),
        )
        self.assertEqual(
            registry.registered_scenario_ids,
            PROVEN_PHASE1_PARITY_SCENARIO_IDS,
        )

    def test_exact_provider_free_and_bounded_receipts_close_the_matrix(
        self,
    ) -> None:
        bounded_receipt = {
            "format": "asterion.prime-long-running-bounded-receipt/v1",
            "status": "PASS",
            "terminal": "completed",
            "checks": list(PRIME_LONG_RUNNING_BOUNDED_PASS_CHECK_IDS),
            "provider_operations": 1,
            "model_credential_reads": 1,
            "model_selector_digest": "a" * 64,
            "usage": {"aggregate_tokens": 8_203, "cost_micros": 0},
            "limits": {
                "aggregate_tokens": 150_000,
                "cost_micros": 500_000,
                "deadline_ms": 600_000,
            },
        }
        observations = tuple(
            build_prime_long_running_bounded_observation(bounded_receipt)
            if scenario_id in PRIME_LONG_RUNNING_BOUNDED_SCENARIO_IDS
            else build_prime_long_running_observation(
                scenario_id=scenario_id,
                status="PASS",
                checks=PRIME_LONG_RUNNING_REQUIRED_CHECK_IDS[scenario_id],
                real_prime_runtime=True,
                fake_daemon=False,
                provider_operations=0,
                model_credential_reads=0,
            )
            for scenario_id in PRIME_LONG_RUNNING_SCENARIO_MATRIX
            if scenario_id not in PROVEN_PHASE1_PARITY_SCENARIO_IDS
        )
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        registry = ParityScenarioRegistry(
            ledger,
            provider_id="asterion.prime-gateway",
        )

        register_prime_long_running_scenarios(
            registry,
            _phase1_results(),
            observations=observations,
            bounded_receipt=bounded_receipt,
            provider_factory=lambda: object(),
        )
        report = asyncio.run(registry.run(PRIME_LONG_RUNNING_SCENARIO_MATRIX))

        self.assertEqual(report.passed_scenario_ids, PRIME_LONG_RUNNING_SCENARIO_MATRIX)
        self.assertEqual(report.blocking_scenario_ids, ())

    def test_selected_client_uses_private_ipc_and_returns_a_body_free_receipt(
        self,
    ) -> None:
        process = _LongRunningProcess()
        client = PrimeControlPlaneClient(
            process=process,
            private_content=_PrivateContent(),
        )
        command = PrimeLongRunningCommand.heartbeat_set(
            LongRunningIntent("effect-1", "heartbeat-user", "heartbeat", 60_000),
            active_session_id="prime-root",
            schedule="0 * * * *",
            prompt="SENTINEL_PRIVATE_HEARTBEAT_BODY",
            delivery_mode="followUp",
        )

        receipt = asyncio.run(
            client.execute_long_running(command.command_id, command.to_mapping())
        )

        self.assertEqual(receipt.command_id, "effect-1")
        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(process.requests[0]["type"], "long-running.execute")
        self.assertNotIn("SENTINEL_PRIVATE_HEARTBEAT_BODY", repr(receipt))

    def test_selected_service_preserves_host_effect_identity(self) -> None:
        client = _ServiceClient()
        command = PrimeLongRunningCommand.heartbeat_set(
            LongRunningIntent("effect-1", "heartbeat-user", "heartbeat", 60_000),
            active_session_id="prime-root",
            schedule="0 * * * *",
            prompt="SENTINEL_PRIVATE_HEARTBEAT_BODY",
        )

        receipt = asyncio.run(PrimeLongRunningService(client).apply(command))

        self.assertEqual(
            receipt,
            LongRunningReceipt(
                "effect-1",
                "heartbeat-user",
                "heartbeat",
                60_000,
                "succeeded",
            ),
        )
        self.assertEqual(client.calls[0][0], "effect-1")
        self.assertNotIn("SENTINEL_PRIVATE_HEARTBEAT_BODY", repr(command))
        self.assertNotIn("SENTINEL_PRIVATE_HEARTBEAT_BODY", repr(receipt))

    def test_selected_command_adapter_exposes_only_the_five_pinned_shapes(self) -> None:
        intent = LongRunningIntent(
            "effect-1", "heartbeat-user", "heartbeat", 60_000
        )
        commands = (
            PrimeLongRunningCommand.heartbeats_list(intent),
            PrimeLongRunningCommand.heartbeat_get(intent, "prime-root"),
            PrimeLongRunningCommand.heartbeat_set(
                intent,
                active_session_id="prime-root",
                schedule="0 * * * *",
                prompt="private",
            ),
            PrimeLongRunningCommand.heartbeat_update(
                intent, "prime-root", "pause"
            ),
            PrimeLongRunningCommand.heartbeat_manage(
                intent, "prime-root", "job-1", "cancel"
            ),
        )

        self.assertEqual(
            tuple(command.to_mapping()["type"] for command in commands),
            (
                "heartbeats_list",
                "heartbeat_get",
                "heartbeat_set",
                "heartbeat_update",
                "heartbeat_manage",
            ),
        )
        with self.assertRaises(PrimeLongRunningError):
            PrimeLongRunningCommand.heartbeat_update(
                intent, "prime-root", "restart"
            )

    def test_selected_service_fails_closed_on_receipt_identity_drift(self) -> None:
        command = PrimeLongRunningCommand.heartbeat_set(
            LongRunningIntent("effect-1", "heartbeat-user", "heartbeat", 60_000),
            active_session_id="prime-root",
            schedule="0 * * * *",
            prompt="private",
        )

        with self.assertRaises(PrimeLongRunningError):
            asyncio.run(
                PrimeLongRunningService(
                    _ServiceClient(receipt_command_id="effect-other")
                ).apply(command)
            )

    def test_autonomous_quality_requires_one_real_bounded_provider_operation(
        self,
    ) -> None:
        scenario_id = "prime-parity.operation.autonomous-quality"
        checks = PRIME_LONG_RUNNING_BOUNDED_PASS_CHECK_IDS

        with self.assertRaisesRegex(Exception, "observation is invalid"):
            build_prime_long_running_observation(
                scenario_id=scenario_id,
                status="PASS",
                checks=checks,
                real_prime_runtime=True,
                fake_daemon=False,
                provider_operations=0,
                model_credential_reads=0,
            )

        observation = build_prime_long_running_observation(
            scenario_id=scenario_id,
            status="PASS",
            checks=checks,
            real_prime_runtime=True,
            fake_daemon=False,
            provider_operations=1,
            model_credential_reads=1,
        )
        self.assertEqual(
            observation.command_id,
            PRIME_LONG_RUNNING_BOUNDED_VERIFICATION_COMMAND_ID,
        )
        self.assertIsNotNone(observation.evidence_id)

    def test_provider_free_receipt_never_promotes_autonomous_quality(self) -> None:
        with self.assertRaisesRegex(Exception, "observation is invalid"):
            build_prime_long_running_observation(
                scenario_id="prime-parity.operation.autonomous-quality",
                status="PASS",
                checks=PRIME_LONG_RUNNING_BOUNDED_PASS_CHECK_IDS,
                real_prime_runtime=True,
                fake_daemon=False,
                provider_operations=0,
                model_credential_reads=0,
            )
        self.assertNotEqual(
            PRIME_LONG_RUNNING_PROVIDER_FREE_VERIFICATION_COMMAND_ID,
            PRIME_LONG_RUNNING_BOUNDED_VERIFICATION_COMMAND_ID,
        )


if __name__ == "__main__":
    unittest.main()
