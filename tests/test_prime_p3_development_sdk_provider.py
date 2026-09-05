from __future__ import annotations
import unittest


class TestPrimeP3DevelopmentSdkProvider(unittest.TestCase):
    def test_role_partition_is_exact(self) -> None:
        from asterion.applications.prime_agent.operator.p3_development_sdk_provider import (
            PrimeP3DevelopmentSdkProvider,
        )

        provider = PrimeP3DevelopmentSdkProvider()
        for role, count in (("root", 4), ("implementation", 2), ("review", 4)):
            for _ in range(count):
                provider.admit(role, b"{}")
        self.assertTrue(provider.terminal())
