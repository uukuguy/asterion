from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from asterion.agents.prime.detachment import assert_asterion_prime_source_detached


class TestAsterionPrimeArchitecture(unittest.TestCase):
    def test_release_path_has_no_prime_agent_dependency(self):
        assert_asterion_prime_source_detached(Path.cwd())

    def test_source_detachment_rejects_forbidden_owned_file(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            forbidden_file = root / "src/asterion/agents/prime/dependency.py"
            forbidden_file.parent.mkdir(parents=True)
            forbidden_file.write_text("primeSourceRoot = None\n", encoding="utf-8")

            with self.assertRaisesRegex(
                AssertionError,
                "^Asterion-prime source dependency is forbidden$",
            ):
                assert_asterion_prime_source_detached(root)

    def test_architecture_declares_peer_agents_and_application_boundary(self):
        body = Path("docs/architecture/agent-framework.md").read_text(encoding="utf-8")
        self.assertIn("asterion-prime", body)
        self.assertIn("asterion-native", body)
        self.assertIn("P1 through P7 are applications", body)
