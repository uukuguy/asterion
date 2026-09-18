"""Native P5 provider factory tests.

The witness-gated publication in :func:`create_provider` (Phase 8, Task 16)
is asserted in :func:`test_p5_is_published_to_public_selector`; P5 returns
to the public selector once ``make asterion-prime-p5-run`` and
``make asterion-prime-p5-run-limits`` both exit 0.
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

    def test_p5_is_published_to_public_selector(self) -> None:
        """Phase 8, Task 16: published together with its installed-route
        bounded-autonomy propose/verify/repair + limits witness (exit 0
        from both ``make asterion-prime-p5-run`` and
        ``make asterion-prime-p5-run-limits``; the limits witness asserts
        iteration-cap-exceeded / duration-cap-exceeded / no-progress
        refusals, each with a sealed ``receipt_sha256``).
        """
        p5_provider = create_prime_bounded_autonomy_provider()
        self.assertEqual(p5_provider.provider_id, "prime-applications")
        self.assertEqual(len(p5_provider.applications), 1)
        self.assertEqual(
            p5_provider.applications[0].application_id, "prime.bounded-autonomy"
        )

        # After the witness passes (Phase 8, Task 16), P5 returns to the
        # public selector. create_provider() now publishes P7 + P1 + P2 + P3
        # + P4 + P5 (6 apps); P5 must be among them.
        public_provider = create_provider()
        published_ids = tuple(
            application.application_id for application in public_provider.applications
        )
        self.assertIn("prime.bounded-autonomy", published_ids)


if __name__ == "__main__":
    unittest.main()