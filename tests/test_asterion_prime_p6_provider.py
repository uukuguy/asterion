"""Native P6 provider factory tests.

The witness-gated publication in :func:`create_provider` (Phase 9, Task 16)
is asserted in :func:`test_create_provider_does_not_include_p6_until_witness_passes`;
P6 returns to the public selector once ``make asterion-prime-p6-run`` and
``make asterion-prime-p6-run-limits`` both exit 0.
"""

from __future__ import annotations

import unittest

from asterion.applications.prime import (
    create_prime_continual_improvement_provider,
    create_provider,
    prime_continual_improvement_application,
)


class TestAsterionPrimeP6Provider(unittest.TestCase):
    def test_prime_continual_improvement_application_returns_expected_tuple(self) -> None:
        record = prime_continual_improvement_application()
        self.assertEqual(record.application_id, "prime.continual-improvement")
        self.assertEqual(record.version, "1.0.0")
        self.assertEqual(record.runtime_ids, ("asterion.prime",))

    def test_create_prime_continual_improvement_provider_emits_one_application(self) -> None:
        """P6 stays unpublished in :func:`create_provider` until the witness
        passes (Phase 9, Task 16). The dedicated
        :func:`create_prime_continual_improvement_provider` emits exactly one
        application — P6's own record — so the operator can compose itself
        without depending on the public selector.
        """
        p6_provider = create_prime_continual_improvement_provider()
        self.assertEqual(p6_provider.provider_id, "prime-applications")
        self.assertEqual(len(p6_provider.applications), 1)
        self.assertEqual(
            p6_provider.applications[0].application_id,
            "prime.continual-improvement",
        )

        # P6 stays out of the public selector until the witness passes
        # (Phase 9, Task 16). create_provider() still publishes the six
        # Phase 8 apps (P7 + P1 + P2 + P3 + P4 + P5); P6 must NOT be
        # among them.
        public_provider = create_provider()
        published_ids = tuple(
            application.application_id for application in public_provider.applications
        )
        self.assertNotIn("prime.continual-improvement", published_ids)


if __name__ == "__main__":
    unittest.main()