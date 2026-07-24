from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.runtime.factory import RuntimeFactoryContext
from asterion.runtime.factory import RuntimeFactoryError
from asterion.runtime.defaults import _claude_provider_environment


class DefaultRuntimeFactoryTests(unittest.TestCase):
    def test_claude_subscription_injects_no_provider_credentials(self) -> None:
        child, mode = _claude_provider_environment(
            {}, provider=None, model="claude-sonnet-4-6"
        )
        self.assertEqual(mode, "subscription")
        self.assertNotIn("ANTHROPIC_API_KEY", child)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", child)
        self.assertNotIn("ANTHROPIC_BASE_URL", child)

    def test_claude_factory_transports_exact_profile_options(self) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                patch.dict(
                    os.environ,
                    {
                        "ASTERION_CLAUDE_EXECUTABLE": "claude",
                        "ASTERION_RUNTIME_CWD": str(root),
                        "DCI_MAX_TURNS": "100",
                    },
                    clear=True,
                ),
                patch("asterion.runtime.defaults.shutil.which", return_value="/tool/claude"),
            ):
                runtime = default_runtime_factory_registry().select(
                    "claude-code.reference"
                ).factory(
                    self._context(
                        root,
                        model="claude-sonnet-4-6",
                        tools="read,grep",
                        thinking_level="medium",
                        context_profile="level3",
                    )
                )
        self.assertEqual(runtime._agent_model, "claude-sonnet-4-6")
        self.assertEqual(runtime._tools, ("Read", "Grep"))
        self.assertEqual(runtime._reasoning, "medium")
        self.assertEqual(runtime._context_profile, "level3")

    def test_claude_rejects_pi_default_pair(self) -> None:
        with self.assertRaisesRegex(RuntimeFactoryError, "unsupported"):
            _claude_provider_environment(
                {}, provider="openai-codex", model="gpt-5.6-luna"
            )

    def test_claude_rejects_mixed_subscription_and_minimax_signals(self) -> None:
        with self.assertRaisesRegex(RuntimeFactoryError, "ambiguous"):
            _claude_provider_environment(
                {
                    "CLAUDE_CODE_OAUTH_TOKEN": "subscription-token",
                    "MINIMAX_API_KEY": "coding-plan-key",
                },
                provider="minimax",
                model="MiniMax-M3",
            )

    def test_claude_factory_is_exact_and_constructs_without_starting_a_process(self) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                patch.dict(
                    os.environ,
                    {
                        "ASTERION_CLAUDE_EXECUTABLE": "claude",
                        "ASTERION_RUNTIME_CWD": str(root),
                        "DCI_PROVIDER": "minimax",
                        "DCI_MODEL": "MiniMax-M2.7",
                        "MINIMAX_API_KEY": "test-minimax-key",
                        "DCI_RPC_TIMEOUT_SECONDS": "3600",
                        "DCI_MAX_TURNS": "100",
                    },
                    clear=True,
                ),
                patch("asterion.runtime.defaults.shutil.which", return_value="/tool/claude"),
            ):
                binding = default_runtime_factory_registry().select(
                    "claude-code.reference"
                )
                runtime = binding.factory(
                    self._context(root)
                )

        self.assertEqual(
            binding.capabilities,
            ("claude.tool.glob", "claude.tool.grep", "filesystem.read"),
        )
        self.assertEqual(runtime.manifest.runtime_id, "claude-code.reference")
        self.assertEqual(runtime.manifest.capabilities, binding.capabilities)
        self.assertEqual(runtime._default_timeout_seconds, 3600.0)
        self.assertEqual(runtime._max_turns, 100)

    def test_claude_factory_derives_minimax_environment_from_shared_config(self) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry

        cases = (
            (
                "minimax",
                "MINIMAX_API_KEY",
                "sk-cp-international-secret",
                "https://api.minimax.io/anthropic",
            ),
            (
                "minimax-cn",
                "MINIMAX_CN_API_KEY",
                "sk-cp-china-secret",
                "https://api.minimaxi.com/anthropic",
            ),
        )
        for provider, key_name, secret, expected_base_url in cases:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                environment = {
                    "ASTERION_CLAUDE_EXECUTABLE": "claude",
                    "ASTERION_RUNTIME_CWD": str(root),
                    "DCI_PROVIDER": provider,
                    "DCI_MODEL": "MiniMax-M2.7",
                    key_name: secret,
                    "ANTHROPIC_API_KEY": "stale-api-key",
                    "ANTHROPIC_AUTH_TOKEN": "stale-auth-token",
                    "ANTHROPIC_BASE_URL": "https://stale.invalid",
                        "ANTHROPIC_MODEL": "stale-model",
                        "DEEPSEEK_API_KEY": "judge-secret",
                        "UNRELATED_SECRET": "unrelated-secret",
                        "PATH": "/safe/bin",
                }
                with (
                    patch.dict(os.environ, environment, clear=True),
                    patch(
                        "asterion.runtime.defaults.shutil.which",
                        return_value="/tool/claude",
                    ),
                ):
                    binding = default_runtime_factory_registry().select(
                        "claude-code.reference"
                    )
                    runtime = binding.factory(self._context(root))

                native_environment = runtime._environment
                self.assertEqual(runtime._agent_provider, provider)
                self.assertEqual(runtime._agent_model, "MiniMax-M2.7")
                self.assertEqual(
                    native_environment["ANTHROPIC_BASE_URL"], expected_base_url
                )
                self.assertEqual(native_environment["ANTHROPIC_AUTH_TOKEN"], secret)
                self.assertNotIn("ANTHROPIC_API_KEY", native_environment)
                for name in (
                    "ANTHROPIC_MODEL",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                ):
                    self.assertEqual(native_environment[name], "MiniMax-M2.7")
                self.assertEqual(native_environment["API_TIMEOUT_MS"], "3000000")
                self.assertEqual(
                    native_environment["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"],
                    "1",
                )
                self.assertEqual(native_environment["PATH"], "/safe/bin")
                self.assertNotIn("DEEPSEEK_API_KEY", native_environment)
                self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", native_environment)
                self.assertNotIn("UNRELATED_SECRET", native_environment)

    def test_claude_factory_maps_ordinary_minimax_key_to_api_key_auth(self) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            environment = {
                "ASTERION_CLAUDE_EXECUTABLE": "claude",
                "ASTERION_RUNTIME_CWD": str(root),
                "DCI_PROVIDER": "minimax",
                "DCI_MODEL": "MiniMax-M3",
                "MINIMAX_API_KEY": "ordinary-api-key",
                "ANTHROPIC_API_KEY": "stale-api-key",
                "ANTHROPIC_AUTH_TOKEN": "stale-auth-token",
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("asterion.runtime.defaults.shutil.which", return_value="/tool/claude"),
            ):
                binding = default_runtime_factory_registry().select(
                    "claude-code.reference"
                )
                runtime = binding.factory(self._context(root))

        native_environment = runtime._environment
        self.assertEqual(native_environment["ANTHROPIC_API_KEY"], "ordinary-api-key")
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", native_environment)

    def test_claude_factory_rejects_unsupported_provider_without_constructing_client(
        self,
    ) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry
        from asterion.runtime.factory import RuntimeFactoryError

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            environment = {
                "ASTERION_CLAUDE_EXECUTABLE": "claude",
                "ASTERION_RUNTIME_CWD": str(root),
                "DCI_PROVIDER": "SECRET-unsupported-provider",
                "DCI_MODEL": "SECRET-model",
                "OPENAI_API_KEY": "SECRET-key",
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("asterion.runtime.defaults.shutil.which", return_value="/tool/claude"),
                patch("asterion.runtime.defaults.ClaudeCodeRuntimeClient") as client,
            ):
                binding = default_runtime_factory_registry().select(
                    "claude-code.reference"
                )
                with self.assertRaises(RuntimeFactoryError) as caught:
                    binding.factory(self._context(root))

        client.assert_not_called()
        self.assertNotIn("SECRET", str(caught.exception))

    def test_claude_factory_rejects_unsupported_anthropic_api_mode(self) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            environment = {
                "ASTERION_CLAUDE_EXECUTABLE": "claude",
                "ASTERION_RUNTIME_CWD": str(root),
                "DCI_PROVIDER": "anthropic",
                "DCI_MODEL": "claude-test-model",
                "ANTHROPIC_API_KEY": "anthropic-secret",
                "ANTHROPIC_AUTH_TOKEN": "stale-auth-token",
                "ANTHROPIC_BASE_URL": "https://stale.invalid",
                "DCI_RPC_TIMEOUT_SECONDS": "0",
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("asterion.runtime.defaults.shutil.which", return_value="/tool/claude"),
            ):
                binding = default_runtime_factory_registry().select(
                    "claude-code.reference"
                )
                with self.assertRaisesRegex(RuntimeFactoryError, "unsupported"):
                    binding.factory(self._context(root))

    def test_claude_factory_rejects_invalid_shared_timeout_without_secret_echo(self) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry
        from asterion.runtime.factory import RuntimeFactoryError

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            environment = {
                "ASTERION_CLAUDE_EXECUTABLE": "claude",
                "ASTERION_RUNTIME_CWD": str(root),
                "DCI_PROVIDER": "minimax",
                "DCI_MODEL": "MiniMax-M3",
                "MINIMAX_API_KEY": "SECRET-key",
                "DCI_RPC_TIMEOUT_SECONDS": "SECRET-invalid",
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("asterion.runtime.defaults.shutil.which", return_value="/tool/claude"),
            ):
                binding = default_runtime_factory_registry().select(
                    "claude-code.reference"
                )
                with self.assertRaises(RuntimeFactoryError) as caught:
                    binding.factory(self._context(root))

        self.assertNotIn("SECRET", str(caught.exception))

    def test_claude_factory_rejects_missing_provider_key_without_exposing_config(
        self,
    ) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry
        from asterion.runtime.factory import RuntimeFactoryError

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            environment = {
                "ASTERION_CLAUDE_EXECUTABLE": "claude",
                "ASTERION_RUNTIME_CWD": str(root),
                "DCI_PROVIDER": "minimax",
                "DCI_MODEL": "SECRET-model",
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("asterion.runtime.defaults.shutil.which", return_value="/tool/claude"),
            ):
                binding = default_runtime_factory_registry().select(
                    "claude-code.reference"
                )
                with self.assertRaises(RuntimeFactoryError) as caught:
                    binding.factory(self._context(root))

        self.assertNotIn("SECRET", str(caught.exception))

    def test_missing_claude_executable_fails_without_echoing_the_path(self) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry
        from asterion.runtime.factory import RuntimeFactoryError

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.dict(
                os.environ,
                {
                    "ASTERION_CLAUDE_EXECUTABLE": "/SECRET/missing",
                    "ASTERION_RUNTIME_CWD": str(root),
                },
                clear=False,
            ):
                binding = default_runtime_factory_registry().select(
                    "claude-code.reference"
                )
                with self.assertRaises(RuntimeFactoryError) as caught:
                    binding.factory(
                        RuntimeFactoryContext(
                            provider_id="dci-agent-lite",
                            application_id="dci.research-capability",
                            application_version="1.0.0",
                            runtime_id="claude-code.reference",
                            assembly_path=root / "assembly.json",
                            options={},
                        )
                    )
        self.assertNotIn("SECRET", str(caught.exception))

    def test_pi_reference_factory_uses_explicit_environment_paths(self) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "pi/packages/coding-agent"
            agent = root / "agent"
            corpus = root / "corpus"
            (package / "dist").mkdir(parents=True)
            (package / "dist/cli.js").write_text("")
            agent.mkdir()
            corpus.mkdir()
            environment = {
                "DCI_PI_PACKAGE_DIR": str(package),
                "DCI_PI_AGENT_DIR": str(agent),
                "ASTERION_RUNTIME_CWD": str(corpus),
                "DCI_PROVIDER": "fixture-provider",
                "DCI_MODEL": "fixture-model",
            }
            with patch.dict(os.environ, environment, clear=False):
                binding = default_runtime_factory_registry().select("pi.reference")
                runtime = binding.factory(
                    RuntimeFactoryContext(
                        provider_id="dci-agent-lite",
                        application_id="dci.research-capability",
                        application_version="1.0.0",
                        runtime_id="pi.reference",
                        assembly_path=root / "assembly.json",
                        options={
                            "provider": "fixture-provider",
                            "model": "fixture-model",
                            "tools": "read,bash",
                            "timeout_seconds": 3600.0,
                            "authentication_mode": "saved-auth",
                        },
                    )
                )

        self.assertEqual(binding.capabilities, ("filesystem.read", "shell"))
        self.assertEqual(runtime.manifest.runtime_id, "pi.reference")
        self.assertEqual(runtime.manifest.capabilities, binding.capabilities)

    def test_missing_pi_cli_fails_without_exposing_the_path(self) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry
        from asterion.runtime.factory import RuntimeFactoryError

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.dict(
                os.environ,
                {
                    "DCI_PI_PACKAGE_DIR": str(root / "SECRET-PACKAGE"),
                    "DCI_PI_AGENT_DIR": str(root),
                    "ASTERION_RUNTIME_CWD": str(root),
                },
                clear=False,
            ):
                binding = default_runtime_factory_registry().select("pi.reference")
                with self.assertRaises(RuntimeFactoryError) as caught:
                    binding.factory(
                        RuntimeFactoryContext(
                            provider_id="dci-agent-lite",
                            application_id="dci.research-capability",
                            application_version="1.0.0",
                            runtime_id="pi.reference",
                            assembly_path=root / "assembly.json",
                            options={},
                        )
                    )
        self.assertNotIn("SECRET-PACKAGE", str(caught.exception))

    @staticmethod
    def _context(root: Path, **options: object) -> RuntimeFactoryContext:
        provider = os.environ.get("DCI_PROVIDER") or None
        model = os.environ.get("DCI_MODEL") or None
        mode = {
            "minimax": "minimax-coding-plan",
            "minimax-cn": "minimax-cn-coding-plan",
        }.get(provider, "subscription" if provider is None else "unsupported")
        return RuntimeFactoryContext(
            provider_id="dci-agent-lite",
            application_id="dci.research-capability",
            application_version="1.0.0",
            runtime_id="claude-code.reference",
            assembly_path=root / "assembly.json",
            options={
                "provider": provider,
                "model": model,
                "tools": "read,grep,glob",
                "timeout_seconds": os.environ.get("DCI_RPC_TIMEOUT_SECONDS", "3600"),
                "authentication_mode": mode,
                **options,
            },
        )


if __name__ == "__main__":
    unittest.main()
