from __future__ import annotations
import unittest
class TestPrimeP3CliHost(unittest.TestCase):
    def test_projection_is_digest_only(self) -> None:
        from asterion.applications.prime_agent.operator.p3_cli_host import project_p3_development_trace
        from asterion.applications.prime_agent.operator.p3_development_host import PrimeP3DevelopmentTrace
        self.assertEqual(set(project_p3_development_trace(PrimeP3DevelopmentTrace("sha256:" + "0" * 64))), {"scope", "promotion", "trace_sha256"})
