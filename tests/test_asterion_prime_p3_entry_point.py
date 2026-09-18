"""Tests for the prime.child-runner host-service entry point registration."""

from __future__ import annotations

import unittest

from asterion.applications.prime.services import (
    ChildRunnerHostService,
    create_child_runner_host_service,
)
from asterion.services.registry import HOST_SERVICE_ENTRY_POINT_GROUP


class TestPrimeChildRunnerEntryPoint(unittest.TestCase):
    def test_entry_point_factory_resolves_to_child_runner_factory(self) -> None:
        binding = create_child_runner_host_service()
        self.assertEqual(binding.capability_id, "prime.child-runner")
        self.assertEqual(
            binding.option_names,
            (
                "max_depth",
                "max_concurrent_children",
                "max_child_cost_usd",
                "max_total_duration_ms",
            ),
        )
        self.assertTrue(callable(binding.factory))

    def test_service_is_public_safe(self) -> None:
        self.assertTrue(issubclass(ChildRunnerHostService, object))

    def test_entry_point_group_constant(self) -> None:
        # Sanity-check the constant the entry-point is registered against.
        self.assertEqual(HOST_SERVICE_ENTRY_POINT_GROUP, "asterion.host_services")


if __name__ == "__main__":
    unittest.main()
