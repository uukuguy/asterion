"""The Prime service facade preserves candidate-store import identities."""
from __future__ import annotations

import unittest

from asterion.applications.prime import services


class PrimeServiceImportsTests(unittest.TestCase):
    def test_candidate_store_reexports_preserve_class_and_factory_identity(self):
        from asterion.applications.prime.p6 import candidate_store

        for name in (
            "CandidateStoreLoop", "CandidateStoreServiceError",
            "CandidateStoreTerminalOutcome", "CandidateStoreVerdict",
            "HoldoutResult", "HoldoutCallable", "_CandidateStoreLimits",
            "_PublicCandidateStoreIdentity", "_error_digest",
            "create_candidate_store_host_service",
            "create_candidate_store_host_service_for_test",
            "MAX_CANDIDATE_REVISIONS_PER_RUN", "MAX_HOLDOUT_EVALUATIONS_PER_RUN",
            "MAX_ROLLBACK_INVOCATIONS_PER_RUN", "MAX_ACTIONS",
            "MAX_USAGE_PROVIDER_OPS", "MAX_DEADLINE_MS", "MAX_COST_USD",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(services, name), getattr(candidate_store, name))
        binding = services.create_candidate_store_host_service()
        self.assertEqual(binding.capability_id, "prime.candidate-store")
        self.assertIs(binding.factory, candidate_store._open_candidate_store_service)

    def test_candidate_store_exports_remain_available_through_facade(self):
        for name in services.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(services, name))
