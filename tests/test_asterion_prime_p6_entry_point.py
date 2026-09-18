"""Tests for the prime.candidate-store host-service entry point registration."""

from __future__ import annotations

import unittest
from importlib.metadata import entry_points

from asterion.services.registry import HOST_SERVICE_ENTRY_POINT_GROUP


class TestPrimeCandidateStoreEntryPoint(unittest.TestCase):
    def test_prime_candidate_store_entry_point_resolves(self) -> None:
        eps = entry_points(group=HOST_SERVICE_ENTRY_POINT_GROUP)
        names = {ep.name for ep in eps}
        self.assertIn("prime.candidate-store", names)
        ep = next(
            ep
            for ep in eps
            if ep.name == "prime.candidate-store"
        )
        self.assertTrue(callable(ep.load))
        target = ep.load()
        self.assertTrue(callable(target))


if __name__ == "__main__":
    unittest.main()