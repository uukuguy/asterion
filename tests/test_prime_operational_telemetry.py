from __future__ import annotations

import unittest

from tests.test_operation_telemetry import _telemetry_request, _telemetry_service, _telemetry_transaction


class TestPrimeOperationalTelemetry(unittest.IsolatedAsyncioTestCase):
    async def test_offline_usage_observation_has_no_provider_network_or_delivery_effect(self) -> None:
        service, sink = _telemetry_service()

        receipt = await service.execute(
            _telemetry_transaction("telemetry-prime-1"), _telemetry_request()
        )

        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(service.effects.injected_sink_calls, 1)
        self.assertEqual(len(sink.calls), 1)
        for counter in (
            "provider_model_requests",
            "network_operations",
            "external_telemetry_deliveries",
            "uploads",
        ):
            with self.subTest(counter=counter):
                self.assertEqual(receipt.effect_counts[counter], 0)
