from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class TestPrimeP7PiModelConfig(unittest.TestCase):
    def test_runtime_selects_model_from_operator_pi_profile(self) -> None:
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import resolve_p7_runtime

        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            (profile / "auth.json").write_text(
                '{"openai-codex": {"type": "oauth", "access": "profile-token"}}'
            )
            (profile / "models-store.json").write_text(
                '{"openai-codex": {"models": [{"id": "gpt-6-sol"}]}}'
            )
            selection = resolve_p7_runtime(
                {"ASTERION_PRIME_PI_AGENT_DIR": str(profile), "ASTERION_PRIME_PROVIDER": "openai-codex", "ASTERION_PRIME_MODEL": "gpt-6-sol"},
                P7GameSelection("ls20-9607627b", 0, 1),
            )
        self.assertEqual(selection.provider, "openai-codex")
        self.assertEqual(selection.model, "gpt-6-sol")

    def test_provider_and_model_are_selected_from_operator_environment(self) -> None:
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import resolve_p7_runtime

        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            (profile / "auth.json").write_text("{}")
            (profile / "models-store.json").write_text('{"deepseek": {"models": []}}')
            selection = resolve_p7_runtime(
                {
                    "ASTERION_PRIME_PI_AGENT_DIR": str(profile),
                    "ASTERION_PRIME_PROVIDER": "deepseek",
                    "ASTERION_PRIME_MODEL": "deepseek-v4-flash",
                    "DEEPSEEK_API_KEY": "test-operator-credential",
                },
                P7GameSelection("ls20-9607627b", 0, 1),
            )
        self.assertEqual((selection.provider, selection.model), ("deepseek", "deepseek-v4-flash"))

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

    def test_pi_base_command_isolated_and_medium_reasoning(self) -> None:
        from asterion.applications.prime.p7.live import pi_base_command

        command = pi_base_command(
            node=Path("/usr/bin/node"),
            pi_entry=Path("/opt/pi/rpc-entry.js"),
        )
        self.assertIn("--no-extensions", command)
        self.assertIn("--no-context-files", command)
        tools = command[command.index("--tools") + 1].split(",")
        self.assertEqual(tools, ["ipython", "p7_execute_plan", "p7_workspace"])
        self.assertEqual(command[command.index("--thinking") + 1], "medium")

    def test_pi_base_command_uses_prime_effort_and_rejects_invalid_configuration(self) -> None:
        from asterion.applications.prime.p7.live import P7LiveSolveError, pi_base_command

        for effort in ("off", "low", "high", "max"):
            with self.subTest(effort=effort):
                command = pi_base_command(node=Path("/usr/bin/node"), pi_entry=Path("/opt/pi/rpc-entry.js"),
                                          environment={"ASTERION_PRIME_EFFORT": effort})
                self.assertEqual(command.count("--thinking"), 1)
                self.assertEqual(command[command.index("--thinking") + 1], effort)
        with self.assertRaisesRegex(P7LiveSolveError, "^Prime reasoning effort is invalid$"):
            pi_base_command(node=Path("/usr/bin/node"), pi_entry=Path("/opt/pi/rpc-entry.js"),
                            environment={"ASTERION_PRIME_EFFORT": "SENTINELSECRET"})

    def test_invalid_effort_rejects_operator_resources_before_service_preflight(self) -> None:
        from unittest.mock import patch
        from asterion.applications.prime.p7 import operator

        with patch.object(operator, "resolve_p7_runtime") as resolve, \
             patch.object(operator.socket, "socketpair") as sockets, \
             self.assertRaises(operator.P7OperatorError) as raised:
            operator.build_p7_operator_resources(
                environment={"ASTERION_PRIME_EFFORT": "SENTINELSECRET"},
                pi_base_command=("node", "pi", "--thinking", "medium"),
                extension_path=Path("/unused"), working_directory=Path("/unused"),
                worker=None, engine=None, private_trace_root=Path("/unused"),
            )
        self.assertNotIn("SENTINELSECRET", str(raised.exception))
        resolve.assert_not_called()
        sockets.assert_not_called()


if __name__ == "__main__":
    unittest.main()
