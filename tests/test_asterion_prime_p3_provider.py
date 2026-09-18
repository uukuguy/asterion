"""Native P3 provider factory tests.

The witness-gated publication in :func:`create_provider` (Phase 7, Task 16)
is asserted in :func:`test_p3_is_published_to_public_selector`; P3 returns
to the public selector once ``make asterion-prime-p3-run`` and
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

    def test_p3_is_published_to_public_selector(self) -> None:
        """Phase 7, Task 16: published together with its installed-route
        recursive-workflow depth + limits witness (exit 0 from both
        ``make asterion-prime-p3-run`` and
        ``make asterion-prime-p3-run-limits``; the limits witness asserts
        depth-exceeded / concurrency-exceeded / budget-exceeded / cancelled
        refusals, each with a sealed ``receipt_sha256``).
        """
        provider = create_prime_recursive_workflow_provider()
        self.assertEqual(provider.provider_id, "prime-applications")
        self.assertEqual(len(provider.applications), 1)
        self.assertEqual(
            provider.applications[0].application_id, "prime.recursive-workflow"
        )

        # After the witness passes (Phase 7, Task 16), P3 returns to the
        # public selector. create_provider() now publishes P7 + P1 + P2 + P3
        # + P4 (5 apps); P3 must be among them.
        public_provider = create_provider()
        published_ids = tuple(
            application.application_id for application in public_provider.applications
        )
        self.assertIn("prime.recursive-workflow", published_ids)


if __name__ == "__main__":
    unittest.main()
