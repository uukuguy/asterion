from __future__ import annotations

import hashlib
import unittest

from asterion.applications.dci_agent_lite.native_small_verification import (
    NativeSmallVerificationApplicationError,
    NativeSmallVerificationOperatorResolver,
)
from asterion.control.providers.native.bounded import NativeBoundedReservation


class _Host:
    async def execute(self, reservation: object, request: object) -> object:
        raise AssertionError("host must not execute during configuration tests")


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


if __name__ == "__main__":
    unittest.main()
