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

    def test_distribution_and_commands_have_no_p7_sdk_wrapper(self):
        forbidden_files = (
            "packages/typescript/prime-gateway/src/p7-solving-session.ts",
            "packages/typescript/prime-gateway/src/p7-solving-bridge.ts",
            "packages/typescript/prime-gateway/src/p7-solving-main.ts",
            "src/asterion/applications/prime_agent/operator/p7_solving_sdk_provider.py",
            "src/asterion/applications/prime_agent/operator/p7_solving_gateway.py",
            "src/asterion/applications/prime_agent/operator/p7_solving_cli_host.py",
            "src/asterion/applications/prime_agent/operator/p7_solving_preparation.py",
            "tools/run_prime_p7_seeded.py",
        )
        for relative in forbidden_files:
            with self.subTest(path=relative):
                self.assertFalse(Path(relative).exists())

        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
        makefile = Path("Makefile").read_text(encoding="utf-8")
        provider = Path(
            "src/asterion/applications/prime_agent/provider.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("prime-gateway/dist/src/p7-solving", pyproject)
        self.assertNotIn("p7_solving_cli_host", pyproject)
        self.assertNotRegex(makefile, r"(?m)^prime-p7-solve:")
        self.assertNotRegex(makefile, r"(?m)^prime-p7-seeded-run:")
        self.assertNotIn('application_id="prime.arc-agi-3-solving"', provider)
