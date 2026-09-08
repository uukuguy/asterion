from __future__ import annotations

from pathlib import Path
import unittest

from asterion.agents.prime.detachment import assert_asterion_prime_source_detached


class TestAsterionPrimeArchitecture(unittest.TestCase):
    def test_release_path_has_no_prime_agent_dependency(self):
        assert_asterion_prime_source_detached(Path.cwd())

    def test_architecture_declares_peer_agents_and_application_boundary(self):
        body = Path("docs/architecture/agent-framework.md").read_text(encoding="utf-8")
        self.assertIn("asterion-prime", body)
        self.assertIn("asterion-native", body)
        self.assertIn("P1 through P7 are applications", body)
