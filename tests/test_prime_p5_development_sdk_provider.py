from __future__ import annotations

import unittest


class TestP5DevelopmentSdkProvider(unittest.TestCase):
    def test_exposes_the_fixed_finite_budget(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p5_development_sdk_provider as subject,
        )

        self.assertEqual(
            (
                subject.P5_PROVIDER_CALLBACK_LIMIT,
                subject.P5_PROVIDER_INPUT_LIMIT,
                subject.P5_PROVIDER_OUTPUT_LIMIT,
                subject.P5_PROVIDER_COST_LIMIT,
                subject.P5_PROVIDER_DEADLINE_SECONDS,
            ),
            (4, 32768, 2304, 20000, 180),
        )
