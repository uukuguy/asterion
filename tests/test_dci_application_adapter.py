from __future__ import annotations

import ast
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import cast

from asterion.applications.dci_agent_lite import provider
from asterion.applications.dci_agent_lite.cli import (
    DCI_APPLICATION_SELECTOR,
    DCI_BENCHMARK_SUITE_SELECTOR,
    main,
)
from asterion.applications.dci_agent_lite.operator_config import (
    DciOperatorConfig,
    load_operator_config,
)
from asterion.benchmarks.cli import BenchmarkCommandHost


PROJECT = Path(__file__).resolve().parents[1]
ADAPTER = PROJECT / "src/asterion/applications/dci_agent_lite/cli.py"
ASSEMBLIES = (
    PROJECT / "src/asterion/applications/dci_agent_lite/assemblies"
).glob("*.json")


class TestDciApplicationAdapter(unittest.TestCase):
    def test_provider_declares_exact_application_package_and_runtimes(self) -> None:
        installed = provider.create_provider()
        complete = next(
            item
            for item in installed.applications
            if item.application_id == "dci.complete-application"
        )

        self.assertEqual(complete.version, "1.0.0")
        self.assertEqual(
            tuple((item.package_id, item.version) for item in complete.capability_packages),
            (("dci", "1.0.0"),),
        )
        self.assertEqual(
            complete.runtime_ids,
            ("claude-code.reference", "pi.reference"),
        )

    def test_all_dci_assemblies_use_public_protocol_and_exact_package(self) -> None:
        for path in ASSEMBLIES:
            with self.subTest(path=path.name):
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    value["protocol"], "asterion.application-assembly/v1"
                )
                self.assertEqual(
                    value["capability_packages"],
                    [{"package_id": "dci", "version": "1.0.0"}],
                )
                self.assertIn(
                    value["runtime_id"],
                    {"claude-code.reference", "pi.reference"},
                )

    def test_operator_env_is_private_and_omitted_amount_remains_none(self) -> None:
        sentinel = "operator-secret-sentinel"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            resource_root = root / "private-resources"
            env_file = root / ".env"
            env_file.write_text(
                "ASTERION_DCI_RESOURCE_ROOT=dotenv-resources\n"
                "DCI_MODEL=dotenv-model\n",
                encoding="utf-8",
            )

            config = load_operator_config(
                root,
                env_file=env_file,
                environment={
                    "ASTERION_DCI_RESOURCE_ROOT": str(resource_root),
                    "DCI_API_TOKEN": sentinel,
                },
            )

        self.assertIsNone(config.benchmark_inputs.amount)
        self.assertEqual(
            config.benchmark_inputs.dataset_roots["qa.hotpotqa"],
            resource_root.resolve()
            / "data/dci-bench/data/hotpotqa/test.jsonl",
        )
        self.assertEqual(
            config.benchmark_inputs.private_environment["DCI_API_TOKEN"],
            sentinel,
        )
        self.assertNotIn(sentinel, repr(config))
        self.assertNotIn(sentinel, json.dumps(config.public_summary(), sort_keys=True))

    def test_benchmark_plan_delegates_with_exact_refs(self) -> None:
        calls: list[list[str]] = []

        def benchmark_main(argv, **kwargs):
            del kwargs
            calls.append(list(argv))
            return 0

        code = main(
            ["benchmark", "plan", "--case-limit", "2"],
            benchmark_main=benchmark_main,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )

        self.assertEqual(code, 0)
        self.assertEqual(
            calls,
            [
                [
                    "plan",
                    "--application",
                    DCI_APPLICATION_SELECTOR,
                    "--suite",
                    DCI_BENCHMARK_SUITE_SELECTOR,
                    "--case-limit",
                    "2",
                ]
            ],
        )

    def test_benchmark_execution_keeps_generic_explicit_authorization(self) -> None:
        stderr = io.StringIO()
        code = main(
            ["benchmark", "run"],
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(code, 2)
        self.assertIn("requires --execute", stderr.getvalue())

    def test_authorized_host_factory_receives_private_operator_config(self) -> None:
        sentinel = "private-host-factory-sentinel"
        calls: list[object] = []
        host = cast(BenchmarkCommandHost, object())

        def host_factory(config):
            calls.append(config)
            return host

        def benchmark_main(argv, **kwargs):
            calls.append((list(argv), kwargs["host"]))
            return 0

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_lock = root / "source-lock.json"
            source_lock.write_text("{}\n", encoding="utf-8")
            code = main(
                [
                    "benchmark",
                    "run",
                    "--execute",
                    "--capability-source-lock",
                    str(source_lock),
                    "--evidence-root",
                    str(root / "evidence"),
                ],
                benchmark_main=benchmark_main,
                benchmark_host_factory=host_factory,
                repo_root=root,
                environment={
                    "ASTERION_DCI_RESOURCE_ROOT": str(root / "resources"),
                    "DCI_API_TOKEN": sentinel,
                },
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(code, 0)
        config = cast(DciOperatorConfig, calls[0])
        self.assertNotIn(sentinel, repr(config))
        self.assertEqual(
            config.benchmark_inputs.private_environment["DCI_API_TOKEN"],
            sentinel,
        )
        delegated = cast(tuple[list[str], BenchmarkCommandHost], calls[1])
        self.assertEqual(delegated[1], host)
        self.assertEqual(
            delegated[0],
            [
                "run",
                "--application",
                DCI_APPLICATION_SELECTOR,
                "--suite",
                DCI_BENCHMARK_SUITE_SELECTOR,
                "--execute",
                "--capability-source-lock",
                str(source_lock),
                "--evidence-root",
                str(root / "evidence"),
            ],
        )

    def test_unauthorized_run_never_loads_private_operator_config(self) -> None:
        calls: list[object] = []

        def host_factory(config):
            calls.append(config)
            return cast(BenchmarkCommandHost, object())

        stderr = io.StringIO()
        code = main(
            ["benchmark", "run"],
            benchmark_host_factory=host_factory,
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(code, 2)
        self.assertEqual(calls, [])
        self.assertIn("requires --execute", stderr.getvalue())

    def test_metadata_and_preflight_delegate_without_provider_loading_here(self) -> None:
        calls: list[list[str]] = []

        def application_main(argv, **kwargs):
            del kwargs
            calls.append(list(argv))
            return 0

        for argv in (["list"], ["describe", "--json"], ["preflight", "--json"]):
            with self.subTest(argv=argv):
                self.assertEqual(
                    main(
                        argv,
                        application_main=application_main,
                        stdout=io.StringIO(),
                        stderr=io.StringIO(),
                    ),
                    0,
                )

        self.assertEqual(
            calls,
            [
                ["list", "--provider", "dci-agent-lite"],
                ["describe", "--provider", "dci-agent-lite", "--json"],
                [
                    "verify",
                    "--provider",
                    "dci-agent-lite",
                    "--level",
                    "preflight",
                    "--json",
                ],
            ],
        )

    def test_run_selects_exact_application_and_allowed_runtime(self) -> None:
        calls: list[list[str]] = []

        def application_main(argv, **kwargs):
            del kwargs
            calls.append(list(argv))
            return 0

        code = main(
            ["run", "--runtime", "pi", "--input", "{}"],
            application_main=application_main,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )

        self.assertEqual(code, 0)
        self.assertEqual(
            calls,
            [
                [
                    "run",
                    "--provider",
                    "dci-agent-lite",
                    "--application",
                    DCI_APPLICATION_SELECTOR,
                    "--runtime",
                    "pi.reference",
                    "--input",
                    "{}",
                ]
            ],
        )

    def test_adapter_ast_contains_no_framework_or_execution_implementation(self) -> None:
        tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
        imported = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        } | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }

        self.assertFalse(
            imported
            & {
                "asterion.assembly",
                "asterion.capabilities.execution",
                "asterion.capability_packages.sources",
                "asterion.runner",
            }
        )
        self.assertTrue(
            names.isdisjoint(
                {
                    "compose",
                    "create_benchmark_plan",
                    "run_benchmark",
                    "run_composed_application",
                    "BenchmarkEvidenceStore",
                    "Popen",
                    "scandir",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
