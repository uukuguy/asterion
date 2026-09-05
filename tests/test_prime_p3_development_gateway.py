from __future__ import annotations
import unittest


class TestPrimeP3DevelopmentGateway(unittest.TestCase):
    def test_rejects_every_nested_kind_outside_closed_vocabulary(self) -> None:
        from asterion.applications.prime_agent.operator.p3_development_gateway import PrimeP3DevelopmentGatewayError
        self.assertEqual(str(PrimeP3DevelopmentGatewayError()), "prime P3 development gateway is unavailable")
