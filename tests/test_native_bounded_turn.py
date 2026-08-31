from __future__ import annotations

import asyncio
import unittest

from asterion.control.authority import BudgetUsage, RemainingBudget
from asterion.control.providers.native.bounded import (
    BoundedNativeTurnAdapter,
    NativeBoundedReservation,
    NativeBoundedTurnError,
    run_bounded_native_turn,
)
from asterion.control.providers.native.model import NativeTurnRequest
from asterion.control.providers.native.model import NativeTurnResult


REQUEST = NativeTurnRequest(
    turn_id="turn-1",
    session_id="session-1",
    generation=1,
    authority_revision=1,
    causal_command_ids=(),
    inputs=(),
    action_results=(),
    budget=RemainingBudget(100, 0, 0, 100, 1000, 1000),
)


class RecordingBoundedHost:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, reservation: object, request: object) -> object:
        self.calls += 1
        raise AssertionError("host must not be called")


class ReturningBoundedHost:
    def __init__(self, *, cost_micros: int = 0) -> None:
        self.calls = 0
        self._cost_micros = cost_micros

    async def execute(self, reservation: object, request: NativeTurnRequest) -> NativeTurnResult:
        self.calls += 1
        return NativeTurnResult(
            request.turn_id,
            (),
            BudgetUsage(0, 0, 0, 0, self._cost_micros),
        )


class FailingBoundedHost:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, reservation: object, request: object) -> object:
        self.calls += 1
        raise RuntimeError("SENTINEL_SECRET")


class TestNativeBoundedTurn(unittest.TestCase):
    def test_missing_reservation_never_calls_host(self) -> None:
        host = RecordingBoundedHost()

        with self.assertRaises(NativeBoundedTurnError):
            asyncio.run(run_bounded_native_turn(None, host, REQUEST))

        self.assertEqual(host.calls, 0)

    def test_invalid_reservation_never_calls_host(self) -> None:
        host = RecordingBoundedHost()
        reservation = NativeBoundedReservation(
            reservation_id="reservation-1",
            provider_digest="not-a-digest",
            model_digest="2" * 64,
            max_turns=1,
            max_cost_micros=1000,
            deadline_ms=1000,
        )

        with self.assertRaises(NativeBoundedTurnError):
            asyncio.run(run_bounded_native_turn(reservation, host, REQUEST))

        self.assertEqual(host.calls, 0)

    def test_exact_reservation_allows_one_validated_turn(self) -> None:
        host = ReturningBoundedHost()
        reservation = NativeBoundedReservation(
            reservation_id="reservation-1",
            provider_digest="1" * 64,
            model_digest="2" * 64,
            max_turns=1,
            max_cost_micros=1000,
            deadline_ms=1000,
        )

        result = asyncio.run(run_bounded_native_turn(reservation, host, REQUEST))

        self.assertEqual(result.turn_id, REQUEST.turn_id)
        self.assertEqual(host.calls, 1)

        with self.assertRaises(NativeBoundedTurnError):
            asyncio.run(run_bounded_native_turn(reservation, host, REQUEST))

        self.assertEqual(host.calls, 1)

    def test_over_budget_receipt_is_rejected_after_one_host_call(self) -> None:
        host = ReturningBoundedHost(cost_micros=1001)
        reservation = NativeBoundedReservation(
            reservation_id="reservation-over-budget",
            provider_digest="1" * 64,
            model_digest="2" * 64,
            max_turns=1,
            max_cost_micros=1000,
            deadline_ms=1000,
        )

        with self.assertRaises(NativeBoundedTurnError):
            asyncio.run(run_bounded_native_turn(reservation, host, REQUEST))

        self.assertEqual(host.calls, 1)

    def test_bound_adapter_hides_reservation_from_controller_callers(self) -> None:
        host = ReturningBoundedHost()
        adapter = BoundedNativeTurnAdapter(
            NativeBoundedReservation(
                reservation_id="reservation-adapter",
                provider_digest="1" * 64,
                model_digest="2" * 64,
                max_turns=1,
                max_cost_micros=1000,
                deadline_ms=1000,
            ),
            host,
        )

        result = asyncio.run(adapter.execute(REQUEST))

        self.assertEqual(adapter.adapter_id, "native.bounded-turn/v1")
        self.assertEqual(result.turn_id, REQUEST.turn_id)
        self.assertEqual(host.calls, 1)

    def test_host_failure_is_redacted_and_consumes_reservation(self) -> None:
        host = FailingBoundedHost()
        reservation = NativeBoundedReservation(
            reservation_id="reservation-failure",
            provider_digest="1" * 64,
            model_digest="2" * 64,
            max_turns=1,
            max_cost_micros=1000,
            deadline_ms=1000,
        )

        with self.assertRaises(NativeBoundedTurnError) as caught:
            asyncio.run(run_bounded_native_turn(reservation, host, REQUEST))

        self.assertNotIn("SENTINEL_SECRET", str(caught.exception))
        self.assertEqual(host.calls, 1)

if __name__ == "__main__":
    unittest.main()
