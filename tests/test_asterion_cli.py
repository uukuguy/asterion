from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from asterion.cli import _parser, main, resolve_public_runtime_id
from asterion.applications.dci_agent_lite.provider import create_provider as create_dci_provider
from asterion.applications.provider import InstalledApplication, InstalledApplicationProvider
from asterion.applications.product import (
    CapabilityFunction,
    CapabilityProductDescription,
    ConfigurationRequirement,
    InstalledCapabilityProduct,
    VerificationCheckResult,
    VerificationProfile,
    VerificationResult,
)
from asterion.dci.application_executor import EnvironmentDciRunExecutor
from asterion.dci.config import ConfigLayers
from asterion.dci.verification import create_dci_product
from asterion.dci.pi_rpc import PiRpcClient
from asterion.dci.run import DciRunRequest, DciRunResult
from asterion.runtime.factory import RuntimeFactoryBinding, RuntimeFactoryRegistry
from asterion.runtime.host import RunEvent, RunRequest, RuntimeManifest
from asterion.services.controlled_executor import ControlledExecutionResult
from tests.test_application_discovery import FakeEntryPoint
from tests.test_installed_application_provider import provider


class FixtureRuntime:
    manifest = RuntimeManifest(runtime_id="pi.reference", capabilities=())

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del request, signal
        if False:
            yield RunEvent("", 0, "", {})


class ClaudeFixtureRuntime(FixtureRuntime):
    manifest = RuntimeManifest(runtime_id="claude-code.reference", capabilities=())


class DciClaudeFixtureRuntime:
    manifest = RuntimeManifest(
        runtime_id="claude-code.reference",
        capabilities=("filesystem.read", "shell"),
    )

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del signal
        yield RunEvent(request.run_id, 1, "run.started", {"capabilities": []})
        yield RunEvent(
            request.run_id,
            2,
            "artifact.created",
            {
                "artifact": {
                    "artifact_id": "answer",
                    "kind": "answer",
                    "media_type": "text/plain",
                    "uri": "fixture-answer.txt",
                }
            },
        )
        yield RunEvent(request.run_id, 3, "run.completed", {"status": "completed"})


class DciPiFixtureRuntime:
    manifest = RuntimeManifest(
        runtime_id="pi.reference", capabilities=("filesystem.read", "shell")
    )

    def __init__(self) -> None:
        self.requests: list[RunRequest] = []

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del signal
        self.requests.append(request)
        raise AssertionError("native DCI executor should own the Pi run")
        if False:
            yield RunEvent("", 0, "", {})


class DciNativeExecutor:
    def __init__(self) -> None:
        self.requests: list[DciRunRequest] = []

    def run(self, request: DciRunRequest) -> DciRunResult:
        self.requests.append(request)
        return DciRunResult(
            output_dir=Path("run"),
            final_text="SECRET-NATIVE-ANSWER",
            events=(
                RunEvent(request.run_id, 1, "run.started", {"capabilities": []}),
                RunEvent(
                    request.run_id,
                    2,
                    "artifact.created",
                    {
                        "artifact": {
                            "artifact_id": "answer",
                            "kind": "answer",
                            "media_type": "text/plain",
                            "uri": "final.txt",
                        }
                    },
                ),
                RunEvent(request.run_id, 3, "run.completed", {"status": "completed"}),
            ),
            status="completed",
        )


class FailingDciNativeExecutor:
    def __init__(self) -> None:
        self.requests: list[DciRunRequest] = []

    def run(self, request: DciRunRequest) -> DciRunResult:
        self.requests.append(request)
        raise RuntimeError("SECRET-NATIVE-DIAGNOSTIC")


class ControlledFixtureRuntime(FixtureRuntime):
    manifest = RuntimeManifest(
        runtime_id="pi.reference", capabilities=("filesystem.read", "shell")
    )


class FixtureExecutor:
    async def execute(self, request, *, signal=None):
        del request, signal
        return ControlledExecutionResult(
            status="succeeded",
            exit_code=0,
            stdout_bytes=0,
            stderr_bytes=0,
            stdout_truncated=False,
            stderr_truncated=False,
            duration_ms=0,
            failure_class=None,
        )


class FixtureManager:
    def __init__(self) -> None:
        self.config = None
        self.entered = False

    async def __aenter__(self):
        self.entered = True
        return FixtureExecutor()

    async def __aexit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback


def configure_manager(manager, config):
    manager.config = config
    return manager


class AsterionCliTests(unittest.TestCase):
    def test_public_runtime_names_map_to_exact_installed_ids(self) -> None:
        self.assertEqual(resolve_public_runtime_id("pi"), "pi.reference")
        self.assertEqual(
            resolve_public_runtime_id("claude-code"), "claude-code.reference"
        )
        self.assertEqual(resolve_public_runtime_id("pi.reference"), "pi.reference")
        self.assertEqual(
            resolve_public_runtime_id("claude-code.reference"),
            "claude-code.reference",
        )
        with self.assertRaises(ValueError):
            resolve_public_runtime_id("unsupported")

    def test_dci_describe_json_reports_effective_first_run_defaults(self) -> None:
        entry = FakeEntryPoint(name="dci-agent-lite", factory=create_dci_provider)
        stdout = io.StringIO()
        stderr = io.StringIO()

        code = main(
            ["describe", "--provider", "dci-agent-lite", "--json"],
            entry_points=(entry,),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(code, 0, stderr.getvalue())
        configuration = {
            item["name"]: item for item in json.loads(stdout.getvalue())["configuration"]
        }
        self.assertEqual(configuration["DCI_PROVIDER"]["default"], "openai-codex")
        self.assertEqual(configuration["DCI_MODEL"]["default"], "gpt-5.6-luna")
        self.assertEqual(configuration["DCI_PI_DIR"]["default"], "./pi")
        self.assertEqual(configuration["DCI_PI_AGENT_DIR"]["default"], "~/.pi/agent")

    def test_run_materializes_dotenv_once_without_overriding_exported_values(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            value = provider(root)
            entry = FakeEntryPoint(name="example-app", factory=lambda: value)
            (root / ".env").write_text(
                "\n".join(
                    (
                        "DCI_PROVIDER=dotenv-provider",
                        "MINIMAX_API_KEY=dotenv-minimax-secret",
                        "MINIMAX_CN_API_KEY=dotenv-minimax-cn-secret",
                        "DCI_PI_PACKAGE_DIR=dotenv-pi-package",
                        "DCI_PI_AGENT_DIR=dotenv-pi-agent",
                        "ASTERION_RUNTIME_CWD=dotenv-runtime-cwd",
                        "ASTERION_CLAUDE_EXECUTABLE=dotenv-claude",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            contexts = []
            factory_environment = {}

            def create_runtime(context):
                contexts.append(context)
                for name in (
                    "DCI_PROVIDER",
                    "MINIMAX_API_KEY",
                    "MINIMAX_CN_API_KEY",
                    "DCI_PI_PACKAGE_DIR",
                    "DCI_PI_AGENT_DIR",
                    "ASTERION_RUNTIME_CWD",
                    "ASTERION_CLAUDE_EXECUTABLE",
                ):
                    factory_environment[name] = os.environ.get(name)
                return FixtureRuntime()

            registry = RuntimeFactoryRegistry(
                (
                    RuntimeFactoryBinding(
                        runtime_id="pi.reference",
                        capabilities=(),
                        factory=create_runtime,
                    ),
                )
            )
            original_materialize = ConfigLayers.materialize
            stdout = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {
                        "DCI_PROVIDER": "exported-provider",
                        "ASTERION_RUNTIME_CWD": "exported-runtime-cwd",
                    },
                    clear=True,
                ),
                patch("asterion.cli.Path.cwd", return_value=root),
                patch.object(
                    ConfigLayers,
                    "materialize",
                    autospec=True,
                    side_effect=lambda layers, target: original_materialize(
                        layers, target
                    ),
                ) as materialize,
            ):
                code = main(
                    [
                        "run",
                        "--provider",
                        "example-app",
                        "--runtime",
                        "pi",
                        "--application",
                        "example.research@1.0.0",
                        "--input",
                        "research",
                    ],
                    entry_points=(entry,),
                    runtime_factories=registry,
                    stdout=stdout,
                    stderr=io.StringIO(),
                )

        self.assertEqual(code, 0)
        materialize.assert_called_once()
        self.assertEqual(factory_environment["DCI_PROVIDER"], "exported-provider")
        self.assertEqual(
            factory_environment["ASTERION_RUNTIME_CWD"], "exported-runtime-cwd"
        )
        self.assertEqual(
            factory_environment["MINIMAX_API_KEY"], "dotenv-minimax-secret"
        )
        self.assertEqual(
            factory_environment["MINIMAX_CN_API_KEY"],
            "dotenv-minimax-cn-secret",
        )
        self.assertEqual(
            factory_environment["DCI_PI_PACKAGE_DIR"], "dotenv-pi-package"
        )
        self.assertEqual(factory_environment["DCI_PI_AGENT_DIR"], "dotenv-pi-agent")
        self.assertEqual(
            factory_environment["ASTERION_CLAUDE_EXECUTABLE"], "dotenv-claude"
        )
        self.assertEqual(contexts[0].options["provider"], "exported-provider")
        self.assertNotIn("API_KEY", repr(contexts[0].options))
        self.assertNotIn("dotenv-minimax-secret", stdout.getvalue())

    def _product_provider(self, root: Path, calls: list[object]) -> InstalledApplicationProvider:
        valid = provider(root)
        description = CapabilityProductDescription(
            product_id="example-product",
            version="1.0.0",
            summary="Example product",
            functions=(
                CapabilityFunction(
                    function_id="research",
                    summary="Research a corpus",
                    argv=("example", "run"),
                ),
            ),
            configuration=(
                ConfigurationRequirement(
                    name="EXAMPLE_API_KEY",
                    purpose="Provider credential",
                    required_for=("basic",),
                    secret=True,
                    default=None,
                    hint="Set this in .env",
                ),
            ),
            profiles=(
                VerificationProfile(
                    level="basic",
                    summary="Run a bounded check",
                    cost_class="bounded-provider-backed",
                    provider_backed_operation_count=1,
                    full_dataset=False,
                ),
                VerificationProfile(
                    level="preflight",
                    summary="Check prerequisites",
                    cost_class="provider-free",
                    provider_backed_operation_count=0,
                    full_dataset=False,
                ),
            ),
        )

        def verify(request):
            calls.append(request)
            return VerificationResult(
                product_id="example-product",
                level=request.level,
                status="PASS",
                checks=(
                    VerificationCheckResult(
                        check_id="configuration",
                        summary="Configuration is ready",
                        status="PASS",
                        counts=(("present", 1),),
                    ),
                ),
                provider_backed_operation_count=0,
                full_dataset_ran=False,
            )

        return InstalledApplicationProvider(
            protocol=valid.protocol,
            provider_id=valid.provider_id,
            resource_root=valid.resource_root,
            applications=valid.applications,
            product=InstalledCapabilityProduct(description=description, verifier=verify),
        )

    def test_describe_loads_only_selected_product_and_renders_stable_json(self) -> None:
        calls: list[object] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            selected = FakeEntryPoint(
                name="example-app",
                factory=lambda: self._product_provider(Path(temp_dir), calls),
            )
            adjacent = FakeEntryPoint(
                name="other-app",
                factory=lambda: (_ for _ in ()).throw(AssertionError("loaded")),
            )
            stdout = io.StringIO()
            code = main(
                ["describe", "--provider", "example-app", "--json"],
                entry_points=(selected, adjacent),
                stdout=stdout,
                stderr=io.StringIO(),
            )

        self.assertEqual(code, 0)
        self.assertEqual(selected.loads, 1)
        self.assertEqual(adjacent.loads, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["product_id"], "example-product")
        self.assertEqual(payload["functions"][0]["argv"], ["example", "run"])
        self.assertNotIn("value", payload["configuration"][0])
        self.assertEqual(calls, [])

    def test_describe_human_output_is_plain_and_provider_without_product_fails(self) -> None:
        calls: list[object] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            supported = FakeEntryPoint(
                name="example-app",
                factory=lambda: self._product_provider(root, calls),
            )
            stdout = io.StringIO()
            code = main(
                ["describe", "--provider", "example-app"],
                entry_points=(supported,),
                stdout=stdout,
                stderr=io.StringIO(),
            )
            unsupported = main(
                ["describe", "--provider", "plain-app"],
                entry_points=(
                    FakeEntryPoint(name="plain-app", factory=lambda: provider(root)),
                ),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(code, 0)
        self.assertIn("Example product", stdout.getvalue())
        self.assertIn("research: Research a corpus", stdout.getvalue())
        self.assertEqual(unsupported, 2)

    def test_verify_normalizes_paths_calls_once_and_reports_the_bound(self) -> None:
        calls: list[object] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = FakeEntryPoint(
                name="example-app",
                factory=lambda: self._product_provider(root, calls),
            )
            stdout = io.StringIO()
            code = main(
                [
                    "verify",
                    "--provider",
                    "example-app",
                    "--level",
                    "preflight",
                    "--env-file",
                    ".env.fixture",
                    "--corpus-root",
                    "corpus",
                    "--output-root",
                    "outputs",
                ],
                entry_points=(entry,),
                stdout=stdout,
                stderr=io.StringIO(),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        request = calls[0]
        self.assertTrue(request.env_file.is_absolute())
        self.assertTrue(request.corpus_root.is_absolute())
        self.assertIn("Overall: PASS", stdout.getvalue())
        self.assertIn("Provider-backed operations: 0", stdout.getvalue())
        self.assertIn("Full dataset ran: no", stdout.getvalue())

    def _standalone_dci_provider(self, root: Path) -> InstalledApplicationProvider:
        value = create_dci_provider()
        return replace(
            value,
            product=create_dci_product(repo_root=root),
        )

    def test_dci_acceptance_cli_reports_installed_package_closure(self) -> None:
        entry = FakeEntryPoint(
            name="dci-agent-lite",
            factory=lambda: self._standalone_dci_provider(
                Path(__file__).resolve().parents[1]
            ),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        code = main(
            [
                "verify",
                "--provider",
                "dci-agent-lite",
                "--level",
                "acceptance",
                "--json",
            ],
            entry_points=(entry,),
            stdout=stdout,
            stderr=stderr,
        )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["provider_backed_operation_count"], 0)
        self.assertFalse(payload["full_dataset_ran"])
        self.assertEqual(
            [item["check_id"] for item in payload["checks"]],
            [
                "application-assemblies",
                "application-providers",
                "capability-manifests",
                "context-profiles",
                "paper-benchmarks",
                "paper-scopes",
                "provider-requests",
            ],
        )

    def test_dci_acceptance_cli_is_independent_of_current_directory(self) -> None:
        project = Path(__file__).resolve().parents[1]
        entry = FakeEntryPoint(
            name="dci-agent-lite",
            factory=lambda: self._standalone_dci_provider(project),
        )
        baseline = io.StringIO()
        self.assertEqual(
            main(
                [
                    "verify",
                    "--provider",
                    "dci-agent-lite",
                    "--level",
                    "acceptance",
                    "--json",
                ],
                entry_points=(entry,),
                stdout=baseline,
                stderr=io.StringIO(),
            ),
            0,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            previous = Path.cwd()
            try:
                os.chdir(temp_dir)
                isolated = io.StringIO()
                code = main(
                    [
                        "verify",
                        "--provider",
                        "dci-agent-lite",
                        "--level",
                        "acceptance",
                        "--json",
                    ],
                    entry_points=(entry,),
                    stdout=isolated,
                    stderr=io.StringIO(),
                )
            finally:
                os.chdir(previous)

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(isolated.getvalue()), json.loads(baseline.getvalue()))

    def test_list_reports_metadata_without_loading_provider(self) -> None:
        entry = FakeEntryPoint(name="example-app", factory=lambda: None)
        stdout = io.StringIO()

        code = main(
            ["list"],
            entry_points=(entry,),
            runtime_factories=RuntimeFactoryRegistry(()),
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(code, 0)
        self.assertEqual(entry.loads, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload[0]["provider_id"], "example-app")
        self.assertNotIn("SECRET-MODULE-PATH", stdout.getvalue())

    def test_list_selected_provider_reports_exact_applications(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            value = provider(Path(temp_dir))
            entry = FakeEntryPoint(name="example-app", factory=lambda: value)
            stdout = io.StringIO()
            code = main(
                ["list", "--provider", "example-app"],
                entry_points=(entry,),
                stdout=stdout,
                stderr=io.StringIO(),
            )

        self.assertEqual(code, 0)
        self.assertEqual(entry.loads, 1)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "applications": [
                    {
                        "application_id": "example.research",
                        "runtime_ids": ["pi.reference"],
                        "selector": "example.research@1.0.0",
                        "version": "1.0.0",
                    }
                ],
                "provider_id": "example-app",
            },
        )

    def test_run_preflights_then_constructs_runtime_and_outputs_one_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            value = provider(Path(temp_dir))
            entry = FakeEntryPoint(name="example-app", factory=lambda: value)
            factory_calls = []

            def create_runtime(context):
                factory_calls.append(context)
                return FixtureRuntime()

            registry = RuntimeFactoryRegistry(
                (
                    RuntimeFactoryBinding(
                        runtime_id="pi.reference",
                        capabilities=(),
                        factory=create_runtime,
                    ),
                )
            )
            stdout = io.StringIO()
            code = main(
                [
                    "run",
                    "--provider",
                    "example-app",
                    "--runtime",
                    "pi.reference",
                    "--run-id",
                    "cli-run",
                    "--input",
                    "SECRET-INPUT",
                    "--assembly",
                    str(value.applications[0].assembly_paths[0]),
                ],
                entry_points=(entry,),
                runtime_factories=registry,
                stdout=stdout,
                stderr=io.StringIO(),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(factory_calls), 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["application_id"], "example.research")
        self.assertEqual(payload["runtime_id"], "pi.reference")
        self.assertEqual(payload["run_id"], "cli-run")
        self.assertNotIn("SECRET-INPUT", stdout.getvalue())

    def test_run_selects_application_without_an_assembly_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            value = provider(Path(temp_dir))
            entry = FakeEntryPoint(name="example-app", factory=lambda: value)
            registry = RuntimeFactoryRegistry(
                (
                    RuntimeFactoryBinding(
                        runtime_id="pi.reference",
                        capabilities=(),
                        factory=lambda context: FixtureRuntime(),
                    ),
                )
            )
            stdout = io.StringIO()
            code = main(
                [
                    "run",
                    "--provider",
                    "example-app",
                    "--runtime",
                    "pi.reference",
                    "--application",
                    "example.research@1.0.0",
                    "--input",
                    "research",
                ],
                entry_points=(entry,),
                runtime_factories=registry,
                stdout=stdout,
                stderr=io.StringIO(),
            )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["application_id"], "example.research")

    def test_run_selects_matching_runtime_assembly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            value = provider(root)
            application = value.applications[0]
            pi_assembly = application.assembly_paths[0]
            claude_assembly = pi_assembly.with_name("claude.json")
            claude_manifest = json.loads(pi_assembly.read_text())
            claude_manifest["runtime_id"] = "claude-code.reference"
            claude_assembly.write_text(json.dumps(claude_manifest))
            compatible = InstalledApplicationProvider(
                protocol=value.protocol,
                provider_id=value.provider_id,
                resource_root=value.resource_root,
                applications=(
                    InstalledApplication(
                        application_id=application.application_id,
                        version=application.version,
                        assembly_paths=(pi_assembly, claude_assembly),
                        catalog_roots=application.catalog_roots,
                        implementations=application.implementations,
                        runtime_ids=("claude-code.reference", "pi.reference"),
                    ),
                ),
            )
            entry = FakeEntryPoint(name="example-app", factory=lambda: compatible)
            contexts = []
            registry = RuntimeFactoryRegistry(
                (
                    RuntimeFactoryBinding(
                        runtime_id="claude-code.reference",
                        capabilities=(),
                        factory=lambda context: contexts.append(context)
                        or ClaudeFixtureRuntime(),
                    ),
                )
            )

            code = main(
                [
                    "run",
                    "--provider",
                    "example-app",
                    "--runtime",
                    "claude-code.reference",
                    "--application",
                    "example.research@1.0.0",
                    "--input",
                    "SECRET-INPUT",
                ],
                entry_points=(entry,),
                runtime_factories=registry,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].assembly_path.name, "claude.json")

    def test_run_defaults_runtime_selection_from_environment_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            value = provider(root)
            application = value.applications[0]
            pi_assembly = application.assembly_paths[0]
            claude_assembly = pi_assembly.with_name("claude.json")
            claude_manifest = json.loads(pi_assembly.read_text())
            claude_manifest["runtime_id"] = "claude-code.reference"
            claude_assembly.write_text(json.dumps(claude_manifest))
            compatible = InstalledApplicationProvider(
                protocol=value.protocol,
                provider_id=value.provider_id,
                resource_root=value.resource_root,
                applications=(
                    InstalledApplication(
                        application_id=application.application_id,
                        version=application.version,
                        assembly_paths=(pi_assembly, claude_assembly),
                        catalog_roots=application.catalog_roots,
                        implementations=application.implementations,
                        runtime_ids=("claude-code.reference", "pi.reference"),
                    ),
                ),
            )
            entry = FakeEntryPoint(name="example-app", factory=lambda: compatible)
            contexts = []
            registry = RuntimeFactoryRegistry(
                (
                    RuntimeFactoryBinding(
                        runtime_id="claude-code.reference",
                        capabilities=(),
                        factory=lambda context: contexts.append(context)
                        or ClaudeFixtureRuntime(),
                    ),
                )
            )

            with patch.dict(
                os.environ,
                {
                    "DCI_RUNTIME": "claude-code.reference",
                    "DCI_PROVIDER": "minimax",
                    "DCI_MODEL": "MiniMax-M2.7",
                },
                clear=True,
            ):
                code = main(
                    [
                        "run",
                        "--provider",
                        "example-app",
                        "--application",
                        "example.research@1.0.0",
                        "--input",
                        "SECRET-INPUT",
                    ],
                    entry_points=(entry,),
                    runtime_factories=registry,
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )

        self.assertEqual(code, 0)
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].runtime_id, "claude-code.reference")
        self.assertEqual(contexts[0].assembly_path.name, "claude.json")

    def test_run_rejects_ambiguous_runtime_assemblies_before_factory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            value = provider(root)
            application = value.applications[0]
            pi_assembly = application.assembly_paths[0]
            claude_manifest = json.loads(pi_assembly.read_text())
            claude_manifest["runtime_id"] = "claude-code.reference"
            first_claude = pi_assembly.with_name("claude-first.json")
            second_claude = pi_assembly.with_name("claude-second.json")
            first_claude.write_text(json.dumps(claude_manifest))
            second_claude.write_text(json.dumps(claude_manifest))
            ambiguous = InstalledApplicationProvider(
                protocol=value.protocol,
                provider_id=value.provider_id,
                resource_root=value.resource_root,
                applications=(
                    InstalledApplication(
                        application_id=application.application_id,
                        version=application.version,
                        assembly_paths=(first_claude, second_claude, pi_assembly),
                        catalog_roots=application.catalog_roots,
                        implementations=application.implementations,
                        runtime_ids=("claude-code.reference", "pi.reference"),
                    ),
                ),
            )
            entry = FakeEntryPoint(name="example-app", factory=lambda: ambiguous)
            contexts = []
            registry = RuntimeFactoryRegistry(
                (
                    RuntimeFactoryBinding(
                        runtime_id="claude-code.reference",
                        capabilities=(),
                        factory=lambda context: contexts.append(context)
                        or ClaudeFixtureRuntime(),
                    ),
                )
            )

            code = main(
                [
                    "run",
                    "--provider",
                    "example-app",
                    "--runtime",
                    "claude-code.reference",
                    "--application",
                    "example.research@1.0.0",
                    "--input",
                    "SECRET-INPUT",
                ],
                entry_points=(entry,),
                runtime_factories=registry,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(code, 2)
        self.assertEqual(contexts, [])

    def test_bundled_dci_runs_with_claude_fixture(self) -> None:
        contexts = []
        registry = RuntimeFactoryRegistry(
            (
                RuntimeFactoryBinding(
                    runtime_id="claude-code.reference",
                    capabilities=("filesystem.read", "shell"),
                    factory=lambda context: contexts.append(context)
                    or DciClaudeFixtureRuntime(),
                ),
            )
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        code = main(
            [
                "run",
                "--provider",
                "dci-agent-lite",
                "--runtime",
                "claude-code.reference",
                "--application",
                "dci.research-capability@1.0.0",
                "--input",
                "SECRET-INPUT",
            ],
            entry_points=(
                FakeEntryPoint(name="dci-agent-lite", factory=create_dci_provider),
            ),
            runtime_factories=registry,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(len(contexts), 1)
        self.assertEqual(
            contexts[0].assembly_path.name,
            "dci-research-capability-claude.json",
        )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["application_id"], "dci.research-capability")
        self.assertEqual(payload["runtime_id"], "claude-code.reference")
        self.assertNotIn("SECRET-INPUT", stdout.getvalue())
        self.assertNotIn("SECRET-INPUT", stderr.getvalue())

    def test_bundled_dci_pi_application_uses_provider_native_executor(self) -> None:
        runtime = DciPiFixtureRuntime()
        native_executor = DciNativeExecutor()
        registry = RuntimeFactoryRegistry(
            (
                RuntimeFactoryBinding(
                    runtime_id="pi.reference",
                    capabilities=("filesystem.read", "shell"),
                    factory=lambda context: runtime,
                ),
            )
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        code = main(
            [
                "run",
                "--provider",
                "dci-agent-lite",
                "--runtime",
                "pi.reference",
                "--application",
                "dci.research-capability@1.0.0",
                "--run-id",
                "native-cli-run",
                "--input",
                "SECRET-INPUT",
            ],
            entry_points=(
                FakeEntryPoint(
                    name="dci-agent-lite",
                    factory=lambda: create_dci_provider(
                        native_executor=native_executor
                    ),
                ),
            ),
            runtime_factories=registry,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(runtime.requests, [])
        self.assertEqual(native_executor.requests[0].run_id, "native-cli-run")
        self.assertEqual(native_executor.requests[0].question, "SECRET-INPUT")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload["artifacts"][0]["value"]["answer_artifact_uri"], "final.txt"
        )
        self.assertNotIn("SECRET-INPUT", stdout.getvalue())
        self.assertNotIn("SECRET-NATIVE-ANSWER", stdout.getvalue())
        self.assertNotIn("SECRET-INPUT", stderr.getvalue())

    def test_bundled_dci_pi_application_emits_one_body_free_json_object(self) -> None:
        runtime = DciPiFixtureRuntime()
        registry = RuntimeFactoryRegistry(
            (
                RuntimeFactoryBinding(
                    runtime_id="pi.reference",
                    capabilities=("filesystem.read", "shell"),
                    factory=lambda context: runtime,
                ),
            )
        )

        def start(client: PiRpcClient) -> None:
            client._test_events = iter(
                (
                    {"type": "response", "id": "py-1", "success": True},
                    {"type": "agent_start"},
                    {
                        "type": "message_update",
                        "assistantMessageEvent": {
                            "type": "text_delta",
                            "delta": "SECRET-NATIVE-DELTA",
                        },
                    },
                    {"type": "agent_settled"},
                )
            )

        def next_event(client: PiRpcClient, **_: object) -> dict[str, object]:
            return next(client._test_events)

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            stdout = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {"ASTERION_RUNTIME_CWD": str(root)},
                    clear=True,
                ),
                patch.object(PiRpcClient, "start", start),
                patch.object(PiRpcClient, "stop", lambda client: None),
                patch.object(PiRpcClient, "_send", lambda client, payload: None),
                patch.object(PiRpcClient, "_read_json_line", next_event),
                patch.object(
                    PiRpcClient,
                    "probe_protocol",
                    return_value={
                        "isStreaming": False,
                        "isCompacting": False,
                        "messageCount": 1,
                        "pendingMessageCount": 0,
                    },
                ),
                patch("sys.stdout", stdout),
            ):
                code = main(
                    [
                        "run",
                        "--provider",
                        "dci-agent-lite",
                        "--runtime",
                        "pi.reference",
                        "--application",
                        "dci.research-capability@1.0.0",
                        "--run-id",
                        "native-cli-run",
                        "--input",
                        "SECRET-INPUT",
                    ],
                    entry_points=(
                        FakeEntryPoint(
                            name="dci-agent-lite",
                            factory=lambda: create_dci_provider(
                                native_executor=EnvironmentDciRunExecutor(repo_root=root)
                            ),
                        ),
                    ),
                    runtime_factories=registry,
                    stdout=stdout,
                    stderr=io.StringIO(),
                )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["application_id"], "dci.research-capability")
        self.assertEqual(payload["events"], [{"payload": {"status": "completed"}, "type": "research.completed"}])
        self.assertNotIn("SECRET-NATIVE-DELTA", stdout.getvalue())
        self.assertNotIn("SECRET-INPUT", stdout.getvalue())

    def test_bundled_dci_pi_native_failure_is_redacted(self) -> None:
        runtime = DciPiFixtureRuntime()
        native_executor = FailingDciNativeExecutor()
        registry = RuntimeFactoryRegistry(
            (
                RuntimeFactoryBinding(
                    runtime_id="pi.reference",
                    capabilities=("filesystem.read", "shell"),
                    factory=lambda context: runtime,
                ),
            )
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        code = main(
            [
                "run",
                "--provider",
                "dci-agent-lite",
                "--runtime",
                "pi.reference",
                "--application",
                "dci.research-capability@1.0.0",
                "--input",
                "SECRET-INPUT",
            ],
            entry_points=(
                FakeEntryPoint(
                    name="dci-agent-lite",
                    factory=lambda: create_dci_provider(
                        native_executor=native_executor
                    ),
                ),
            ),
            runtime_factories=registry,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(code, 2)
        self.assertEqual(runtime.requests, [])
        self.assertEqual(len(native_executor.requests), 1)
        for output in (stdout.getvalue(), stderr.getvalue()):
            self.assertNotIn("SECRET-INPUT", output)
            self.assertNotIn("SECRET-NATIVE-DIAGNOSTIC", output)

    def test_conflicting_or_missing_selection_fails_before_provider_load(self) -> None:
        entry = FakeEntryPoint(name="example-app", factory=lambda: None)
        for selection in (
            [],
            ["--application", "example.research@1.0.0", "--assembly", "/tmp/a"],
        ):
            with self.subTest(selection=selection):
                code = main(
                    [
                        "run",
                        "--provider",
                        "example-app",
                        "--runtime",
                        "pi.reference",
                        *selection,
                    ],
                    entry_points=(entry,),
                    runtime_factories=RuntimeFactoryRegistry(()),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )
                self.assertEqual(code, 2)
        self.assertEqual(entry.loads, 0)

    def test_controlled_code_requires_complete_operator_config_before_runtime(self) -> None:
        calls = []
        registry = RuntimeFactoryRegistry(
            (
                RuntimeFactoryBinding(
                    runtime_id="pi.reference",
                    capabilities=("filesystem.read", "shell"),
                    factory=lambda context: calls.append(context),
                ),
            )
        )
        code = main(
            [
                "run",
                "--provider",
                "controlled-code",
                "--application",
                "code.quality@1.0.0",
                "--runtime",
                "pi.reference",
            ],
            runtime_factories=registry,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
        self.assertEqual(code, 2)
        self.assertEqual(calls, [])

    def test_dci_rejects_executor_lifecycle_options_before_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            value = provider(Path(temp_dir))
            entry = FakeEntryPoint(name="example-app", factory=lambda: value)
            calls = []
            registry = RuntimeFactoryRegistry(
                (
                    RuntimeFactoryBinding(
                        runtime_id="pi.reference",
                        capabilities=(),
                        factory=lambda context: calls.append(context),
                    ),
                )
            )
            code = main(
                [
                    "run",
                    "--provider",
                    "example-app",
                    "--runtime",
                    "pi.reference",
                    "--application",
                    "example.research@1.0.0",
                    "--executor-binary",
                    "/SECRET-binary",
                ],
                entry_points=(entry,),
                runtime_factories=registry,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
        self.assertEqual(code, 2)
        self.assertEqual(calls, [])

    def test_executor_environment_configuration_is_used_when_flags_are_absent(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ASTERION_EXECUTOR_BINARY": "/binary",
                "ASTERION_EXECUTOR_POLICY": "/policy",
                "ASTERION_EXECUTOR_VALIDATION_CONFIG": "/validation",
            },
            clear=False,
        ):
            args = _parser().parse_args(
                [
                    "run",
                    "--provider",
                    "controlled-code",
                    "--runtime",
                    "pi.reference",
                    "--application",
                    "code.quality@1.0.0",
                ]
            )
        self.assertEqual(args.executor_binary, "/binary")
        self.assertEqual(args.executor_policy, "/policy")
        self.assertEqual(args.executor_validation_config, "/validation")

    def test_controlled_code_injects_one_explicit_managed_service(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary = root / "executor"
            policy = root / "policy.json"
            validation = root / "validation.json"
            binary.write_text("fixture")
            policy.write_text("{}")
            validation.write_text(
                json.dumps(
                    {
                        "program_id": "check",
                        "argument_prefix": [],
                        "cwd": "workspace",
                        "deadline_ms": 1000,
                        "max_output_bytes": 1024,
                    }
                )
            )
            manager = FixtureManager()
            stderr = io.StringIO()
            registry = RuntimeFactoryRegistry(
                (
                    RuntimeFactoryBinding(
                        runtime_id="pi.reference",
                        capabilities=("filesystem.read", "shell"),
                        factory=lambda context: ControlledFixtureRuntime(),
                    ),
                )
            )
            stdout = io.StringIO()
            code = main(
                [
                    "run",
                    "--provider",
                    "controlled-code",
                    "--application",
                    "code.quality@1.0.0",
                    "--runtime",
                    "pi.reference",
                    "--executor-binary",
                    str(binary),
                    "--executor-policy",
                    str(policy),
                    "--executor-validation-config",
                    str(validation),
                    "--input",
                    "src/example.py",
                ],
                runtime_factories=registry,
                managed_executor_factory=lambda config: configure_manager(manager, config),
                stdout=stdout,
                stderr=stderr,
            )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertTrue(manager.entered)
        self.assertIsNotNone(manager.config)
        self.assertEqual(json.loads(stdout.getvalue())["application_id"], "code.quality")

    def test_invalid_provider_fails_before_runtime_factory_and_redacts_input(self) -> None:
        calls = []
        registry = RuntimeFactoryRegistry(
            (
                RuntimeFactoryBinding(
                    runtime_id="pi.reference",
                    capabilities=(),
                    factory=lambda context: calls.append(context),
                ),
            )
        )
        stderr = io.StringIO()

        code = main(
            [
                "run",
                "--provider",
                "missing-app",
                "--runtime",
                "pi.reference",
                "--input",
                "SECRET-INPUT",
                "/missing/assembly.json",
            ],
            entry_points=(),
            runtime_factories=registry,
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(code, 2)
        self.assertEqual(calls, [])
        self.assertNotIn("SECRET-INPUT", stderr.getvalue())

    def test_incomplete_binding_fails_before_runtime_factory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            valid = provider(Path(temp_dir))
            application = valid.applications[0]
            incomplete = InstalledApplicationProvider(
                protocol=valid.protocol,
                provider_id=valid.provider_id,
                resource_root=valid.resource_root,
                applications=(
                    InstalledApplication(
                        application_id=application.application_id,
                        version=application.version,
                        assembly_paths=application.assembly_paths,
                        catalog_roots=application.catalog_roots,
                        implementations=(),
                        runtime_ids=application.runtime_ids,
                    ),
                ),
            )
            entry = FakeEntryPoint(name="example-app", factory=lambda: incomplete)
            calls = []
            registry = RuntimeFactoryRegistry(
                (
                    RuntimeFactoryBinding(
                        runtime_id="pi.reference",
                        capabilities=(),
                        factory=lambda context: calls.append(context),
                    ),
                )
            )
            code = main(
                [
                    "run",
                    "--provider",
                    "example-app",
                    "--runtime",
                    "pi.reference",
                    str(application.assembly_paths[0]),
                ],
                entry_points=(entry,),
                runtime_factories=registry,
                stdin=io.StringIO("input"),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(code, 2)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
