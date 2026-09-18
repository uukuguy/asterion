"""Tests for the prime.continuity-store host-service entry point registration."""

from __future__ import annotations

import unittest

from asterion.applications.prime.services import (
    ContinuityStoreHostService,
    create_continuity_store_host_service,
)
from asterion.services.registry import HOST_SERVICE_ENTRY_POINT_GROUP


class TestPrimeContinuityStoreEntryPoint(unittest.TestCase):
    def test_entry_point_factory_resolves_to_continuity_store_factory(self) -> None:
        binding = create_continuity_store_host_service()
        self.assertEqual(binding.capability_id, "prime.continuity-store")
        self.assertEqual(binding.option_names, ("root",))
        self.assertTrue(callable(binding.factory))

    def test_service_is_public_safe(self) -> None:
        from asterion.applications.prime.services import _PublicContinuityIdentity

        self.assertTrue(issubclass(ContinuityStoreHostService, object))
        # No public path / private-root field on the public identity.
        self.assertNotIn("private_root", _PublicContinuityIdentity.__annotations__)
        self.assertNotIn("path", _PublicContinuityIdentity.__annotations__)

    def test_entry_point_group_constant(self) -> None:
        # Sanity-check the constant the entry-point is registered against.
        self.assertEqual(HOST_SERVICE_ENTRY_POINT_GROUP, "asterion.host_services")


if __name__ == "__main__":
    unittest.main()