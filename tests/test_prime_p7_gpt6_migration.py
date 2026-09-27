from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class TestPrimeP7Gpt6Migration(unittest.TestCase):
    def test_runtime_selects_codex_from_operator_pi_profile(self) -> None:
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import resolve_p7_runtime

        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            (profile / "auth.json").write_text('{"openai-codex": {}}')
            (profile / "models-store.json").write_text('{"openai-codex": {}}')
            selection = resolve_p7_runtime(
                {"ASTERION_PRIME_PI_AGENT_DIR": str(profile)},
                P7GameSelection("ls20-9607627b", 0, 1),
            )
        self.assertEqual(selection.provider, "openai-codex")
        self.assertEqual(selection.model, "gpt-6-sol")

    def test_pi_profile_root_must_not_be_a_symlink(self) -> None:
        from asterion.applications.prime.p7.live import P7LiveSolveError, resolve_pi_agent_dir

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "profile"
            profile.mkdir()
            (profile / "auth.json").write_text("{}")
            (profile / "models-store.json").write_text("{}")
            alias = root / "alias"
            alias.symlink_to(profile, target_is_directory=True)
            with self.assertRaisesRegex(P7LiveSolveError, "unavailable"):
                resolve_pi_agent_dir({"ASTERION_PRIME_PI_AGENT_DIR": str(alias)})

    def test_pi_base_command_isolated_and_high_reasoning(self) -> None:
        from asterion.applications.prime.p7.live import pi_base_command

        command = pi_base_command(
            node=Path("/usr/bin/node"),
            pi_entry=Path("/opt/pi/rpc-entry.js"),
        )
        self.assertIn("--no-extensions", command)
        self.assertIn("--no-context-files", command)
        self.assertEqual(command[command.index("--thinking") + 1], "high")


if __name__ == "__main__":
    unittest.main()
