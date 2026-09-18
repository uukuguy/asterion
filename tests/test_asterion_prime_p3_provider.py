"""Native P3 provider factory tests.

The witness-gated publication in :func:`create_provider` (Phase 7, Task 16)
is intentionally NOT asserted here; P3 stays unpublished in the public
selector until ``make asterion-prime-p3-run`` and
``make asterion-prime-p3-run-limits`` both exit 0.
"""

from __future__ import annotations

import unittest

from asterion.applications.prime import (
    create_prime_recursive_workflow_provider,
    create_provider,
    prime_recursive_workflow_application,
)


class TestAsterionPrimeP3Provider(unittest.TestCase):
    def test_provider_factory_exists_and_returns_p3_application(self) -> None:
        record = prime_recursive_workflow_application()
        self.assertEqual(record.application_id, "prime.recursive-workflow")
        self.assertEqual(record.version, "1.0.0")
        self.assertEqual(record.runtime_ids, ("asterion.prime",))

    def test_create_provider_does_not_include_p3_until_witness_passes(self) -> None:
        provider = create_prime_recursive_workflow_provider()
        self.assertEqual(provider.provider_id, "prime-applications")
        self.assertEqual(len(provider.applications), 1)
        self.assertEqual(
            provider.applications[0].application_id, "prime.recursive-workflow"
        )

        # The P3 selector stays unpublished until its installed-route witness
        # passes (Phase 7, Task 16). create_provider() currently publishes
        # P7 + P1 + P2 + P4 (4 apps); P3 must not be among them yet.
        public_provider = create_provider()
        published_ids = tuple(
            application.application_id for application in public_provider.applications
        )
        self.assertNotIn("prime.recursive-workflow", published_ids)


if __name__ == "__main__":
    unittest.main()
