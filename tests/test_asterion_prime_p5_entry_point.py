"""Tests for the prime.bounded-autonomy host-service entry point registration."""

from __future__ import annotations

import unittest
from importlib.metadata import entry_points

from asterion.applications.prime.services import (
    BoundedAutonomyLoop,
    create_bounded_autonomy_host_service,
)
from asterion.services.registry import HOST_SERVICE_ENTRY_POINT_GROUP


class TestPrimeBoundedAutonomyEntryPoint(unittest.TestCase):
    def test_entry_point_factory_resolves_to_bounded_autonomy_factory(self) -> None:
        eps = entry_points(group=HOST_SERVICE_ENTRY_POINT_GROUP)
        names = {ep.name for ep in eps}
        self.assertIn("prime.bounded-autonomy", names)
        ep = next(
            ep
            for ep in eps
            if ep.name == "prime.bounded-autonomy"
        )
        self.assertTrue(callable(ep.load))
        target = ep.load()
        self.assertIs(target, create_bounded_autonomy_host_service)
        self.assertEqual(target.__module__, "asterion.applications.prime.services")
        self.assertEqual(target.__name__, "create_bounded_autonomy_host_service")

    def test_service_is_public_safe(self) -> None:
        # Basic shape check: the loop exposes a redacted public_identity.
        self.assertTrue(hasattr(BoundedAutonomyLoop, "public_identity"))


if __name__ == "__main__":
    unittest.main()