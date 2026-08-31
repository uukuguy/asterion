from __future__ import annotations

import hashlib
import unittest

from asterion.applications.dci_agent_lite.native_small_verification import (
    NativeSmallVerificationApplicationError,
    NativeSmallVerificationOperatorResolver,
    PrimeNativeSmallVerificationHost,
)
from asterion.control.authority import RemainingBudget
from asterion.control.providers.native.bounded import NativeBoundedReservation
from asterion.control.providers.native.model import NativeTurnRequest


class _Host:
    async def execute(self, reservation: object, request: object) -> object:
        raise AssertionError("host must not execute during configuration tests")


_REQUEST = NativeTurnRequest(
    turn_id="native-small-turn",
    session_id="native-small-session",
    generation=1,
    authority_revision=1,
    causal_command_ids=(),
    inputs=(),
    action_results=(),
    budget=RemainingBudget(1, 0, 0, 1, 1, 1),
)


class TestNativeSmallVerificationOperatorResolver(unittest.TestCase):
    def test_resolves_fixed_one_turn_reservation_from_private_environment(self) -> None:
        secret = "SENTINEL_PRIVATE_DEEPSEEK_KEY"
        resolver = NativeSmallVerificationOperatorResolver(
            environment_loader=lambda: {
                "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash",
                "DEEPSEEK_API_KEY": secret,
            },
            host=_Host(),
        )

        reservation, host = resolver.resolve()

        self.assertIsInstance(reservation, NativeBoundedReservation)
        self.assertEqual(reservation.max_turns, 1)
        self.assertEqual(reservation.max_cost_micros, 500_000)
        self.assertEqual(reservation.deadline_ms, 600_000)
        self.assertEqual(
            reservation.provider_digest,
            hashlib.sha256(b"deepseek").hexdigest(),
        )
        self.assertEqual(
            reservation.model_digest,
            hashlib.sha256(b"deepseek-v4-flash").hexdigest(),
        )
        self.assertIsInstance(host, _Host)
        self.assertNotIn(secret, repr(resolver))
        self.assertNotIn(secret, repr(reservation))

    def test_missing_private_configuration_fails_without_exposing_values(self) -> None:
        resolver = NativeSmallVerificationOperatorResolver(
            environment_loader=lambda: {
                "ASTERION_PRIME_EXPERIMENT_MODEL": "unsupported-private-model",
                "DEEPSEEK_API_KEY": "SENTINEL_PRIVATE_DEEPSEEK_KEY",
            },
            host=_Host(),
        )

        with self.assertRaises(NativeSmallVerificationApplicationError) as caught:
            resolver.resolve()

        self.assertNotIn("SENTINEL_PRIVATE_DEEPSEEK_KEY", str(caught.exception))

    def test_host_projects_only_bounded_public_usage_from_controlled_runner(self) -> None:
        calls = 0

        def run_once() -> dict[str, object]:
            nonlocal calls
            calls += 1
            return {
                "status": "PASS",
                "level": "native-rlm-bounded",
                "terminal": "completed",
                "child_started": True,
                "message_delivered": True,
                "child_deleted": True,
                "checkpoint_recovered": True,
                "detach_attached": True,
                "cancelled": True,
                "budget_limited": True,
                "child_model_selected": True,
                "generated_program_admitted": True,
                "recursion_depth_limited": True,
                "application_operations": 1,
                "provider_operations": 1,
                "usage": {"aggregate_tokens": 9, "cost_micros": 17},
                "full_dataset_ran": False,
            }

        host = PrimeNativeSmallVerificationHost(runner=run_once)
        reservation = NativeBoundedReservation(
            reservation_id="native-small-host",
            provider_digest="1" * 64,
            model_digest="2" * 64,
            max_turns=1,
            max_cost_micros=20,
            deadline_ms=600_000,
        )

        result = __import__("asyncio").run(host.execute(reservation, _REQUEST))

        self.assertEqual(calls, 1)
        self.assertEqual(result.turn_id, _REQUEST.turn_id)
        self.assertEqual(result.usage.aggregate_tokens, 9)
        self.assertEqual(result.usage.cost_micros, 17)

    def test_host_rejects_unredacted_runner_result(self) -> None:
        host = PrimeNativeSmallVerificationHost(
            runner=lambda: {"private_raw_output": "SENTINEL_PRIVATE_RAW_OUTPUT"}
        )
        reservation = NativeBoundedReservation(
            reservation_id="native-small-host-redaction",
            provider_digest="1" * 64,
            model_digest="2" * 64,
            max_turns=1,
            max_cost_micros=20,
            deadline_ms=600_000,
        )

        with self.assertRaises(NativeSmallVerificationApplicationError) as caught:
            __import__("asyncio").run(host.execute(reservation, _REQUEST))

        self.assertNotIn("SENTINEL_PRIVATE_RAW_OUTPUT", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
