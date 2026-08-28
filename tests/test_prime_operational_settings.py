from __future__ import annotations

import unittest

from asterion.operation.protocol import EFFECT_COUNTERS
from tests.test_operation_settings import _settings_request, _settings_service, _settings_transaction
from tests.test_prime_operational_auth import (
    _FAILURE_MATRICES,
    _base_scenario_counts,
    _real_prime_receipt,
    _zero_effect_counts,
)


class TestPrimeOperationalSettings(unittest.IsolatedAsyncioTestCase):
    async def test_settings_and_keybindings_are_provider_free_preference_writes(self) -> None:
        service, store = _settings_service()

        receipts = []
        for operation_id, name, value in (
            ("settings-theme", "theme", "dark"),
            ("settings-telemetry", "telemetry.enabled", False),
            ("settings-new", "app.session.new", "Ctrl+N"),
            ("settings-clear", "app.input.clear", "Ctrl+L"),
            ("settings-interrupt", "app.interrupt", "Ctrl+C"),
        ):
            receipts.append(
                await service.execute(
                    _settings_transaction(operation_id),
                    _settings_request("global", name, value),
                )
            )

        self.assertEqual(len(store.records), 5)
        self.assertTrue(all(receipt.status == "succeeded" for receipt in receipts))
        self.assertTrue(
            all(receipt.effect_counts == {counter: 0 for counter in EFFECT_COUNTERS} for receipt in receipts)
        )
        self.assertEqual(store.provider_requests, 0)
        self.assertEqual(store.network_operations, 0)
        self.assertEqual(store.runtime_mutations, 0)

    async def test_real_prime_settings_receipt_has_only_five_allowed_names_and_rejects_aliases(self) -> None:
        receipt = _real_prime_receipt("settings-keybindings")

        self.assertEqual(receipt["scenario_counts"], _base_scenario_counts())
        self.assertEqual(receipt["effect_counts"], _zero_effect_counts())
        self.assertEqual(receipt["status"], "pass")
        self.assertEqual(
            receipt["settings"],
            [
                ["global", "theme", "enum"],
                ["global", "telemetry.enabled", "boolean"],
                ["global", "app.session.new", "key-chord"],
                ["global", "app.input.clear", "key-chord"],
                ["global", "app.interrupt", "key-chord"],
            ],
        )
        self.assertEqual(
            receipt["key_chords"],
            {
                "app.input.clear": "Ctrl+L",
                "app.interrupt": "Ctrl+C",
                "app.session.new": "Ctrl+N",
            },
        )
        self.assertEqual(receipt["failure_matrix"], _FAILURE_MATRICES["settings-keybindings"])


if __name__ == "__main__":
    unittest.main()
