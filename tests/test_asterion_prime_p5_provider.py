"""Native P5 provider factory tests.

The witness-gated publication in :func:`create_provider` (Phase 8, Task 16)
is asserted in :func:`test_create_provider_does_not_include_p5_until_witness_passes`;
P5 returns to the public selector once ``make asterion-prime-p5-run`` exits 0
with a sealed ``receipt_sha256``.
"""

from __future__ import annotations

import unittest

from asterion.applications.prime import (
    create_prime_bounded_autonomy_provider,
    create_provider,
    prime_bounded_autonomy_application,
)


class TestAsterionPrimeP5Provider(unittest.TestCase):
    def test_provider_factory_exists_and_returns_p5_application(self) -> None:
        record = prime_bounded_autonomy_application()
        self.assertEqual(record.application_id, "prime.bounded-autonomy")
        self.assertEqual(record.version, "1.0.0")
        self.assertEqual(record.runtime_ids, ("asterion.prime",))

    def test_create_provider_does_not_include_p5_until_witness_passes(self) -> None:
        """Phase 8, Task 16: published together with its installed-route
        bounded-autonomy witness (exit 0 from ``make asterion-prime-p5-run``
        with a sealed ``receipt_sha256``).

        Until that witness passes, P5 stays unpublished in the public
        selector — ``create_provider()`` returns P7 + P1 + P2 + P3 + P4
        (5 apps) only. The P5 operator composes itself from
        :func:`create_prime_bounded_autonomy_provider` instead, so the
        application is reachable without depending on publication.
        """

        p5_provider = create_prime_bounded_autonomy_provider()
        self.assertEqual(p5_provider.provider_id, "prime-applications")
        self.assertEqual(len(p5_provider.applications), 1)
        self.assertEqual(
            p5_provider.applications[0].application_id, "prime.bounded-autonomy"
        )

        # Before the witness passes, P5 stays unpublished: the public
        # selector returns 5 apps (P7 + P1 + P2 + P3 + P4), not 6.
        public_provider = create_provider()
        published_ids = tuple(
            application.application_id for application in public_provider.applications
        )
        self.assertNotIn("prime.bounded-autonomy", published_ids)
        self.assertEqual(len(published_ids), 5)


if __name__ == "__main__":
    unittest.main()