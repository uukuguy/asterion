from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from asterion.runtime.factory import RuntimeFactoryContext
from asterion.runtime.factory import RuntimeFactoryError
from asterion.pathlight import NoopPathlightRecorder
from asterion.runtime.defaults import _claude_provider_environment
from asterion.runtime.host import RunRequest
from asterion.runtime.working_directory import ProcessWorkingDirectory
from asterion.capabilities.dci.implementation.services import create_local_corpus_service_factory
from asterion.services.registry import HostServiceFactoryContext


class DirectoryAuthority:
    def __init__(self, root: Path) -> None:
        self.directory_path = root

    @contextmanager
    def open_process_working_directory(self):
        yield ProcessWorkingDirectory(
            identity_path=self.directory_path,
            cwd=str(self.directory_path),
            pass_fds=(),
        )


class DefaultRuntimeFactoryTests(unittest.TestCase):
    def test_factory_context_defaults_to_noop_pathlight(self) -> None:
        context = RuntimeFactoryContext(
            provider_id="provider",
            application_id="application",
            application_version="1.0.0",
            runtime_id="pi.reference",
            assembly_path=Path("/assembly.json"),
            options={},
        )

        self.assertIsInstance(context.pathlight, NoopPathlightRecorder)

    def test_runtime_factory_context_repr_redacts_all_operator_values(self) -> None:
        class SecretService:
            def __repr__(self) -> str:
                return "<SECRET-SERVICE-VALUE>"

        context = RuntimeFactoryContext(
            provider_id="provider",
            application_id="application",
            application_version="1.0.0",
            runtime_id="pi.reference",
            assembly_path=Path("/SECRET-ASSEMBLY/assembly.json"),
            options={"token": "SECRET-OPTION-VALUE"},
            host_services={"service.secret": SecretService()},
        )

        for rendered in (
            repr(context),
            repr(context.options),
            repr(context.host_services),
        ):
            self.assertNotIn("SECRET-", rendered)

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

    def test_pi_reference_factory_uses_only_explicit_context_options(self) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            with (
                patch("asterion.runtime.defaults.Path.cwd", side_effect=AssertionError),
                patch(
                    "asterion.runtime.defaults.shutil.which",
                    side_effect=AssertionError,
                ),
            ):
                binding = default_runtime_factory_registry().select("pi.reference")
                runtime = binding.factory(
                    RuntimeFactoryContext(
                        provider_id="dci-agent-lite",
                        application_id="dci.research-capability",
                        application_version="1.0.0",
                        runtime_id="pi.reference",
                        assembly_path=root / "assembly.json",
                        options={
                            "command": json.dumps(
                                [
                                    str(Path(sys.executable).resolve()),
                                    "-u",
                                    "-c",
                                    "pass",
                                ],
                                separators=(",", ":"),
                            ),
                            "cwd": str(corpus),
                            "environment": json.dumps(
                                {"SENTINEL_RUNTIME_VALUE": "private"},
                                separators=(",", ":"),
                            ),
                            "evidence_root": str(root / "evidence"),
                            "provider": "fixture-provider",
                            "model": "fixture-model",
                            "tools": "read,grep",
                            "max_turns": "100",
                            "context_profile": "level3",
                        },
                    )
                )

        self.assertEqual(
            binding.capabilities, ("filesystem.read", "pi.tool.grep")
        )
        self.assertEqual(runtime.manifest.runtime_id, "pi.reference")
        self.assertEqual(runtime.manifest.capabilities, binding.capabilities)
        self.assertEqual(runtime._cwd, corpus.resolve())
        self.assertEqual(runtime._env, {"SENTINEL_RUNTIME_VALUE": "private"})
        self.assertEqual(runtime._max_turns, 100)
        self.assertEqual(runtime._provider, "fixture-provider")
        self.assertEqual(runtime._model, "fixture-model")
        self.assertEqual(runtime._tools, ("read", "grep"))
        self.assertEqual(runtime._context_profile, "level3")
        self.assertEqual(runtime._evidence_root, (root / "evidence").resolve())

    def test_pi_reference_factory_can_bind_cwd_to_one_exact_host_service(
        self,
    ) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            executable = Path(sys.executable).resolve()
            context = RuntimeFactoryContext(
                provider_id="dci-agent-lite",
                application_id="dci.research-capability",
                application_version="1.0.0",
                runtime_id="pi.reference",
                assembly_path=root / "assembly.json",
                options={
                    "command": json.dumps(
                        [str(executable), "-u", "-c", "pass"],
                        separators=(",", ":"),
                    ),
                    "cwd_host_capability": "corpus.local-root",
                    "environment": "{}",
                    "evidence_root": str(root / "evidence"),
                    "max_turns": "4",
                    "tools": "read,grep",
                },
                host_services={
                    "corpus.local-root": DirectoryAuthority(corpus)
                },
            )
            runtime = default_runtime_factory_registry().select(
                "pi.reference"
            ).factory(context)

        self.assertIsNone(runtime._cwd)
        self.assertIs(
            runtime._cwd_authority,
            context.host_services["corpus.local-root"],
        )
        with self.assertRaises(TypeError):
            context.host_services["service.other"] = object()

    def test_pi_host_bound_cwd_rejects_missing_ambiguous_or_invalid_service(
        self,
    ) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry
        from asterion.runtime.factory import RuntimeFactoryError

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            executable = Path(sys.executable).resolve()
            base = {
                "command": json.dumps(
                    [str(executable), "-u", "-c", "pass"],
                    separators=(",", ":"),
                ),
                "cwd_host_capability": "corpus.local-root",
                "environment": "{}",
                "evidence_root": str(root / "evidence"),
                "max_turns": "4",
                "tools": "read,grep",
            }
            cases = (
                ({}, {}),
                (
                    {**base, "cwd": str(corpus)},
                    {"corpus.local-root": DirectoryAuthority(corpus)},
                ),
                (base, {"corpus.local-root": object()}),
                (base, {"service.other": DirectoryAuthority(corpus)}),
                (
                    base,
                    {
                        "corpus.local-root": DirectoryAuthority(corpus),
                        "service.other": DirectoryAuthority(corpus),
                    },
                ),
            )
            binding = default_runtime_factory_registry().select("pi.reference")
            for options, services in cases:
                with (
                    self.subTest(options=tuple(options)),
                    self.assertRaises(RuntimeFactoryError) as raised,
                ):
                    binding.factory(
                        RuntimeFactoryContext(
                            provider_id="dci-agent-lite",
                            application_id="dci.research-capability",
                            application_version="1.0.0",
                            runtime_id="pi.reference",
                            assembly_path=root / "assembly.json",
                            options=options or base,
                            host_services=services,
                        )
                    )
                self.assertNotIn("SECRET", str(raised.exception))

    def test_runtime_factories_allow_unrelated_host_services(
        self,
    ) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            direct = root / "direct"
            direct.mkdir()
            authority = DirectoryAuthority(corpus)
            judge = object()
            executable = Path(sys.executable).resolve()
            pi_options = {
                "command": json.dumps(
                    [str(executable), "-u", "-c", "pass"],
                    separators=(",", ":"),
                ),
                "cwd_host_capability": "corpus.local-root",
                "environment": "{}",
                "evidence_root": str(root / "pi-evidence"),
                "max_turns": "4",
                "tools": "read,grep",
            }
            registry = default_runtime_factory_registry()
            pi = registry.select("pi.reference").factory(
                RuntimeFactoryContext(
                    provider_id="dci-agent-lite",
                    application_id="dci.complete-application",
                    application_version="1.0.0",
                    runtime_id="pi.reference",
                    assembly_path=root / "pi.json",
                    options=pi_options,
                    host_services={
                        "corpus.local-root": authority,
                        "evaluation.answer-judge": judge,
                    },
                )
            )
            direct_pi = registry.select("pi.reference").factory(
                RuntimeFactoryContext(
                    provider_id="provider",
                    application_id="application",
                    application_version="1.0.0",
                    runtime_id="pi.reference",
                    assembly_path=root / "standalone.json",
                    options={
                        **{
                            key: value
                            for key, value in pi_options.items()
                            if key != "cwd_host_capability"
                        },
                        "cwd": str(direct),
                    },
                    host_services={"evaluation.answer-judge": judge},
                )
            )
            with (
                patch.dict(
                    os.environ,
                    {"ASTERION_CLAUDE_EXECUTABLE": "claude"},
                    clear=True,
                ),
                patch(
                    "asterion.runtime.defaults.shutil.which",
                    return_value="/tool/claude",
                ),
            ):
                claude = registry.select("claude-code.reference").factory(
                    RuntimeFactoryContext(
                        provider_id="dci-agent-lite",
                        application_id="dci.complete-application",
                        application_version="1.0.0",
                        runtime_id="claude-code.reference",
                        assembly_path=root / "claude.json",
                        options={
                            "authentication_mode": "subscription",
                            "cwd_host_capability": "corpus.local-root",
                            "evidence_root": str(root / "claude-evidence"),
                            "provider": None,
                            "model": None,
                            "timeout_seconds": "10",
                            "tools": "read,grep,glob",
                        },
                        host_services={
                            "corpus.local-root": authority,
                            "evaluation.answer-judge": judge,
                        },
                    )
                )
            with (
                patch.dict(
                    os.environ,
                    {"ASTERION_CLAUDE_EXECUTABLE": "claude"},
                    clear=True,
                ),
                patch(
                    "asterion.runtime.defaults.shutil.which",
                    return_value="/tool/claude",
                ),
            ):
                direct_claude = registry.select(
                    "claude-code.reference"
                ).factory(
                    RuntimeFactoryContext(
                        provider_id="provider",
                        application_id="application",
                        application_version="1.0.0",
                        runtime_id="claude-code.reference",
                        assembly_path=root / "direct-claude.json",
                        options={
                            "authentication_mode": "subscription",
                            "cwd": str(direct),
                            "provider": None,
                            "model": None,
                            "timeout_seconds": "10",
                            "tools": "read,grep,glob",
                        },
                        host_services={
                            "evaluation.answer-judge": judge,
                        },
                    )
                )

        self.assertIs(pi._cwd_authority, authority)
        self.assertIs(claude._cwd_authority, authority)
        self.assertEqual(direct_pi._cwd, direct)
        self.assertEqual(direct_claude._cwd, direct)

    def test_claude_host_directory_is_exact_and_rejects_competing_cwd(
        self,
    ) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            authority = DirectoryAuthority(corpus)
            evidence = root / "evidence"
            base_options = {
                "authentication_mode": "subscription",
                "cwd_host_capability": "corpus.local-root",
                "evidence_root": str(evidence),
                "model": None,
                "provider": None,
                "timeout_seconds": "3600",
                "tools": "read,grep,glob",
            }
            registry = default_runtime_factory_registry()
            with (
                patch.dict(
                    os.environ,
                    {"ASTERION_CLAUDE_EXECUTABLE": "claude"},
                    clear=True,
                ),
                patch(
                    "asterion.runtime.defaults.shutil.which",
                    return_value="/tool/claude",
                ),
                patch.object(Path, "cwd", side_effect=AssertionError("cwd")),
            ):
                runtime = registry.select("claude-code.reference").factory(
                    RuntimeFactoryContext(
                        provider_id="dci-agent-lite",
                        application_id="dci.research-capability",
                        application_version="1.0.0",
                        runtime_id="claude-code.reference",
                        assembly_path=root / "assembly.json",
                        options=base_options,
                        host_services={"corpus.local-root": authority},
                    )
                )

        self.assertIsNone(runtime._cwd)
        self.assertIs(runtime._cwd_authority, authority)

        cases = (
            (
                {**base_options, "cwd": str(corpus)},
                {"ASTERION_CLAUDE_EXECUTABLE": "claude"},
                {"corpus.local-root": authority},
            ),
            (
                base_options,
                {
                    "ASTERION_CLAUDE_EXECUTABLE": "claude",
                    "ASTERION_RUNTIME_CWD": str(root / "other"),
                },
                {"corpus.local-root": authority},
            ),
            (
                {
                    key: value
                    for key, value in base_options.items()
                    if key != "cwd_host_capability"
                },
                {"ASTERION_CLAUDE_EXECUTABLE": "claude"},
                {"corpus.local-root": authority},
            ),
            (
                {
                    key: value
                    for key, value in base_options.items()
                    if key != "cwd_host_capability"
                },
                {
                    "ASTERION_CLAUDE_EXECUTABLE": "claude",
                    "ASTERION_RUNTIME_CWD": str(root / "other"),
                },
                {"corpus.local-root": authority},
            ),
            (
                base_options,
                {"ASTERION_CLAUDE_EXECUTABLE": "claude"},
                {
                    "corpus.local-root": authority,
                    "service.other": DirectoryAuthority(corpus),
                },
            ),
            (
                base_options,
                {"ASTERION_CLAUDE_EXECUTABLE": "claude"},
                {"service.other": authority},
            ),
            (
                base_options,
                {"ASTERION_CLAUDE_EXECUTABLE": "claude"},
                {"corpus.local-root": object()},
            ),
        )
        for options, environment, services in cases:
            with (
                self.subTest(options=tuple(options)),
                patch.dict(os.environ, environment, clear=True),
                patch(
                    "asterion.runtime.defaults.shutil.which",
                    return_value="/tool/claude",
                ),
                self.assertRaises(RuntimeFactoryError),
            ):
                registry.select("claude-code.reference").factory(
                    RuntimeFactoryContext(
                        provider_id="dci-agent-lite",
                        application_id="dci.research-capability",
                        application_version="1.0.0",
                        runtime_id="claude-code.reference",
                        assembly_path=root / "assembly.json",
                        options=options,
                        host_services=services,
                    )
                )

    def test_pi_factory_rejects_every_noncanonical_authority_value(self) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            cwd = root / "cwd"
            cwd.mkdir()
            executable = Path(sys.executable).resolve()
            base = {
                "command": json.dumps(
                    [str(executable), "-u", "-c", "pass"],
                    separators=(",", ":"),
                ),
                "cwd": str(cwd),
                "environment": '{"A":"1","B":"2"}',
                "evidence_root": str(root / "evidence"),
                "provider": "fixture-provider",
                "model": "fixture-model",
                "tools": "read,grep",
                "max_turns": "4",
                "context_profile": "level3",
            }
            non_executable = root / "SECRET-NON-EXECUTABLE"
            non_executable.write_text("#!/bin/sh\n")
            non_executable.chmod(0o600)
            symlink_target = root / "target"
            symlink_target.mkdir(mode=0o700)
            symlink_root = root / "SECRET-SYMLINK"
            symlink_root.symlink_to(symlink_target, target_is_directory=True)
            public_root = root / "SECRET-PUBLIC"
            public_root.mkdir(mode=0o755)
            cases = (
                {"tools": " read,grep"},
                {"provider": " fixture-provider"},
                {"model": "fixture-model "},
                {"context_profile": "level3 "},
                {"max_turns": "04"},
                {"cwd": str(cwd / ".." / "cwd")},
                {"evidence_root": str(symlink_root)},
                {"evidence_root": str(public_root)},
                {
                    "command": json.dumps(
                        [str(non_executable)],
                        separators=(",", ":"),
                    )
                },
                {
                    "command": json.dumps(
                        [str(executable), "-c", "pass"]
                    )
                },
                {"environment": '{"A":"1","A":"2"}'},
                {"environment": '{"B":"2", "A":"1"}'},
            )
            binding = default_runtime_factory_registry().select("pi.reference")
            for override in cases:
                with (
                    self.subTest(override=next(iter(override))),
                    self.assertRaises(RuntimeFactoryError) as raised,
                ):
                    binding.factory(
                        RuntimeFactoryContext(
                            provider_id="dci-agent-lite",
                            application_id="dci.research-capability",
                            application_version="1.0.0",
                            runtime_id="pi.reference",
                            assembly_path=root / "assembly.json",
                            options={**base, **override},
                        )
                    )
                self.assertNotIn("SECRET", str(raised.exception))

    def test_missing_pi_cli_fails_without_exposing_the_path(self) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry
        from asterion.runtime.factory import RuntimeFactoryError

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            binding = default_runtime_factory_registry().select("pi.reference")
            with self.assertRaises(RuntimeFactoryError) as caught:
                binding.factory(
                    RuntimeFactoryContext(
                        provider_id="dci-agent-lite",
                        application_id="dci.research-capability",
                        application_version="1.0.0",
                        runtime_id="pi.reference",
                        assembly_path=root / "assembly.json",
                        options={
                            "command": json.dumps(
                                [str(root / "SECRET-PACKAGE"), "--mode", "rpc"],
                                separators=(",", ":"),
                            ),
                            "cwd": str(root),
                            "environment": "{}",
                            "evidence_root": str(root / "evidence"),
                            "tools": "read,grep",
                            "max_turns": "4",
                        },
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


class DefaultRuntimeFactoryProcessAuthorityTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_pi_rejects_direct_cwd_when_real_corpus_is_injected(
        self,
    ) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            unrelated = root / "unrelated"
            unrelated.mkdir()
            service_context = HostServiceFactoryContext(
                provider_id="dci-agent-lite",
                application_id="dci.research-capability",
                application_version="1.0.0",
                capability_id="corpus.local-root",
                options={"root": str(corpus)},
            )
            async with create_local_corpus_service_factory().factory(
                service_context
            ) as service:
                with (
                    patch(
                        "asterion.runtime.defaults.PiRuntimeClient"
                    ) as client,
                    self.assertRaises(RuntimeFactoryError),
                ):
                    default_runtime_factory_registry().select(
                        "pi.reference"
                    ).factory(
                        RuntimeFactoryContext(
                            provider_id="dci-agent-lite",
                            application_id="dci.research-capability",
                            application_version="1.0.0",
                            runtime_id="pi.reference",
                            assembly_path=root / "assembly.json",
                            options={
                                "command": json.dumps(
                                    [
                                        str(Path(sys.executable).resolve()),
                                        "-u",
                                        "-c",
                                        "pass",
                                    ],
                                    separators=(",", ":"),
                                ),
                                "cwd": str(unrelated),
                                "environment": "{}",
                                "evidence_root": str(root / "evidence"),
                                "max_turns": "4",
                                "tools": "read,grep",
                            },
                            host_services={
                                "corpus.local-root": service,
                            },
                        )
                    )
                client.assert_not_called()

    async def test_pi_factory_starts_child_pinned_without_fd_leak(
        self,
    ) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry
        import asterion.runtimes.pi as pi_runtime

        script = (
            "import json,os,pathlib,sys;"
            "request=json.loads(sys.stdin.readline());"
            "fd_root='/proc/self/fd' if os.path.isdir('/proc/self/fd') "
            "else '/dev/fd';"
            "leaked=any('original-corpus' in os.path.realpath("
            "f'{fd_root}/{fd}') for fd in range(3,256) "
            "if os.path.exists(f'{fd_root}/{fd}'));"
            "answer=pathlib.Path('marker.txt').read_text()+"
            "(':LEAK' if leaked else ':CLEAN');"
            "print(json.dumps({'type':'response','id':request['id'],"
            "'success':True}),flush=True);"
            "print(json.dumps({'type':'agent_start'}),flush=True);"
            "print(json.dumps({'type':'turn_start'}),flush=True);"
            "print(json.dumps({'type':'message_end','message':{'role':"
            "'assistant','stopReason':'stop','usage':{'input':1,'output':1},"
            "'content':[{'type':'text','text':answer}]}}),flush=True);"
            "print(json.dumps({'type':'agent_end'}),flush=True)"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            (corpus / "marker.txt").write_text("ORIGINAL")
            context = HostServiceFactoryContext(
                provider_id="dci-agent-lite",
                application_id="dci.research-capability",
                application_version="1.0.0",
                capability_id="corpus.local-root",
                options={"root": str(corpus)},
            )
            async with create_local_corpus_service_factory().factory(
                context
            ) as service:
                runtime = default_runtime_factory_registry().select(
                    "pi.reference"
                ).factory(
                    RuntimeFactoryContext(
                        provider_id="dci-agent-lite",
                        application_id="dci.research-capability",
                        application_version="1.0.0",
                        runtime_id="pi.reference",
                        assembly_path=root / "assembly.json",
                        options={
                            "command": json.dumps(
                                [
                                    str(Path(sys.executable).resolve()),
                                    "-u",
                                    "-c",
                                    script,
                                ],
                                separators=(",", ":"),
                            ),
                            "cwd_host_capability": "corpus.local-root",
                            "environment": "{}",
                            "evidence_root": str(root / "pi-evidence"),
                            "max_turns": "4",
                            "tools": "read,grep",
                        },
                        host_services={"corpus.local-root": service},
                    )
                )
                original_start = pi_runtime.asyncio.create_subprocess_exec
                swapped = False

                async def swap_then_start(*args, **kwargs):
                    nonlocal swapped
                    if not swapped:
                        swapped = True
                        corpus.rename(root / "original-corpus")
                        corpus.mkdir()
                        (corpus / "marker.txt").write_text("REPLACEMENT")
                    return await original_start(*args, **kwargs)

                with patch.object(
                    pi_runtime.asyncio,
                    "create_subprocess_exec",
                    side_effect=swap_then_start,
                ):
                    events = [
                        event
                        async for event in runtime.run(
                            RunRequest(
                                "pinned-pi",
                                "question",
                                requested_capabilities=("filesystem.read",),
                            )
                        )
                    ]

            run_dir = runtime.completed_run_dir("pinned-pi")
            self.assertTrue(swapped)
            self.assertEqual(events[-1].type, "run.completed")
            assert run_dir is not None
            self.assertEqual(
                (run_dir / "final.txt").read_text(),
                "ORIGINAL:CLEAN",
            )

    async def test_claude_factory_starts_child_pinned_without_fd_leak(
        self,
    ) -> None:
        from asterion.runtime.defaults import default_runtime_factory_registry
        import asterion.runtimes.claude_code as claude_runtime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            (corpus / "marker.txt").write_text("ORIGINAL")
            executable = root / "fixture-claude"
            executable.write_text(
                f"#!{sys.executable}\n"
                "import json, os, pathlib\n"
                "fd_root = '/proc/self/fd' if "
                "os.path.isdir('/proc/self/fd') else '/dev/fd'\n"
                "leaked = any(\n"
                "    'original-corpus' in "
                "os.path.realpath(f'{fd_root}/{fd}')\n"
                "    for fd in range(3, 256)\n"
                "    if os.path.exists(f'{fd_root}/{fd}')\n"
                ")\n"
                "answer = pathlib.Path('marker.txt').read_text() + "
                "(':LEAK' if leaked else ':CLEAN')\n"
                "print(json.dumps({'type':'system','subtype':'init',"
                "'tools':['Read','Grep','Glob']}))\n"
                "print(json.dumps({'type':'assistant','message':{'role':"
                "'assistant','content':[{'type':'text','text':answer}],"
                "'usage':{'input_tokens':1,'output_tokens':1}}}))\n"
                "print(json.dumps({'type':'result','subtype':'success',"
                "'is_error':False,'result':answer,'usage':"
                "{'input_tokens':1,'output_tokens':1}}))\n"
            )
            executable.chmod(0o700)
            service_context = HostServiceFactoryContext(
                provider_id="dci-agent-lite",
                application_id="dci.research-capability",
                application_version="1.0.0",
                capability_id="corpus.local-root",
                options={"root": str(corpus)},
            )
            async with create_local_corpus_service_factory().factory(
                service_context
            ) as service:
                with patch.dict(
                    os.environ,
                    {"ASTERION_CLAUDE_EXECUTABLE": str(executable)},
                    clear=True,
                ):
                    runtime = default_runtime_factory_registry().select(
                        "claude-code.reference"
                    ).factory(
                        RuntimeFactoryContext(
                            provider_id="dci-agent-lite",
                            application_id="dci.research-capability",
                            application_version="1.0.0",
                            runtime_id="claude-code.reference",
                            assembly_path=root / "assembly.json",
                            options={
                                "authentication_mode": "subscription",
                                "cwd_host_capability": "corpus.local-root",
                                "evidence_root": str(root / "claude-evidence"),
                                "model": None,
                                "provider": None,
                                "timeout_seconds": "10",
                                "tools": "read,grep,glob",
                            },
                            host_services={"corpus.local-root": service},
                        )
                    )
                original_popen = claude_runtime.subprocess.Popen
                swapped = False

                def swap_then_start(*args, **kwargs):
                    nonlocal swapped
                    if not swapped:
                        swapped = True
                        corpus.rename(root / "original-corpus")
                        corpus.mkdir()
                        (corpus / "marker.txt").write_text("REPLACEMENT")
                    return original_popen(*args, **kwargs)

                with patch.object(
                    claude_runtime.subprocess,
                    "Popen",
                    side_effect=swap_then_start,
                ):
                    events = [
                        event
                        async for event in runtime.run(
                            RunRequest("pinned-claude", "question")
                        )
                    ]

            run_dir = runtime.completed_run_dir("pinned-claude")
            self.assertTrue(swapped)
            self.assertEqual(events[-1].type, "run.completed")
            assert run_dir is not None
            self.assertEqual(
                (run_dir / "final.txt").read_text(),
                "ORIGINAL:CLEAN\n",
            )


if __name__ == "__main__":
    unittest.main()
