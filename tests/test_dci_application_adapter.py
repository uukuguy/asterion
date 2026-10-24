from __future__ import annotations

import ast
import io
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest.mock import patch

from asterion.applications.dci.acceptance import operator_provider
from asterion.applications.dci.cli import main
from asterion.applications.dci.operator_config import (
    DciOperatorConfig,
    load_operator_config,
)
from asterion.benchmarks.cli import BenchmarkCommandHost


PROJECT = Path(__file__).resolve().parents[1]
ADAPTER = PROJECT / "src/asterion/applications/dci/cli.py"
ASSEMBLIES = (
    PROJECT / "src/asterion/applications/dci/assemblies"
).glob("*.json")


class TestDciApplicationAdapter(unittest.TestCase):
    def test_native_attempt_limit_rejects_non_one_before_provider_loading(
        self,
    ) -> None:
        with patch(
            "asterion.applications.dci.cli.load_operator_config",
            side_effect=AssertionError("private config must not load"),
        ):
            code = main(
                [
                    "benchmark",
                    "run",
                    "--instance",
                    "dci.bright.biology@1.0.0",
                    "--max-native-attempts",
                    "2",
                    "--execute",
                    "--capability-source-lock",
                    "/private/source-lock.json",
                    "--evidence-root",
                    "/private/evidence",
                ],
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(code, 2)

    def test_cost_limit_rejects_nonfinite_values_before_provider_loading(
        self,
    ) -> None:
        for value in ("NaN", "Infinity", "-Infinity"):
            with (
                self.subTest(value=value),
                patch(
                    "asterion.applications.dci.cli.load_operator_config",
                    side_effect=AssertionError("private config must not load"),
                ),
            ):
                code = main(
                    [
                        "benchmark",
                        "run",
                        "--instance",
                        "dci.bright.biology@1.0.0",
                        "--max-cost-usd",
                        value,
                        "--execute",
                        "--capability-source-lock",
                        "/private/source-lock.json",
                        "--evidence-root",
                        "/private/evidence",
                    ],
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )

            self.assertEqual(code, 2)

    def test_injected_cost_limit_requires_exact_decimal_before_provider_loading(
        self,
    ) -> None:
        for value in (True, 1.0):
            with (
                self.subTest(value=value),
                patch(
                    "asterion.applications.dci.cli.load_operator_config",
                    side_effect=AssertionError("private config must not load"),
                ),
            ):
                code = main(
                    [
                        "benchmark",
                        "run",
                        "--instance",
                        "dci.bright.biology@1.0.0",
                        "--execute",
                        "--capability-source-lock",
                        "/private/source-lock.json",
                        "--evidence-root",
                        "/private/evidence",
                    ],
                    amount=value,
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )
                self.assertEqual(code, 2)

    def test_benchmark_lock_is_metadata_only(self) -> None:
        from tests.test_dci_benchmark_source_lock import RecordingSource

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "source-lock.json"
            with patch(
                "asterion.applications.dci.cli.load_operator_config",
                side_effect=AssertionError("private config must not load"),
            ):
                code = main(
                    [
                        "benchmark",
                        "lock",
                        "--instance",
                        "dci.local-fixture@1.0.0",
                        "--output",
                        str(output),
                    ],
                    benchmark_package_sources=(RecordingSource(),),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )

            self.assertEqual(code, 0)
            self.assertTrue(output.is_file())

    def test_provider_declares_exact_application_package_and_runtimes(self) -> None:
        installed = operator_provider()
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
        local = next(
            item
            for item in installed.applications
            if item.application_id == "dci.local-benchmark-application"
        )
        self.assertEqual(local.version, "1.0.0")
        self.assertEqual(local.capability_packages, complete.capability_packages)
        self.assertEqual(local.runtime_ids, complete.runtime_ids)

    def test_distribution_indexes_local_benchmark_application(self) -> None:
        value = (PROJECT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertNotIn("dci-agent-lite", value)
        self.assertNotIn("dci.local-benchmark-application__1.0.0", value)
        self.assertNotIn("dci.complete-application__1.0.0", value)
        self.assertNotIn("dci.research-capability__1.0.0", value)

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
            [
                "benchmark",
                "plan",
                "--instance",
                "dci.qa.bamboogle@1.0.0",
                "--case-limit",
                "2",
            ],
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
                    "dci.complete-application@1.0.0",
                    "--suite",
                    "dci.qa.bamboogle.paper-full125@1.0.0",
                    "--case-limit",
                    "2",
                ]
            ],
        )

    def test_benchmark_instances_lists_public_catalog_as_json(self) -> None:
        stdout = io.StringIO()

        code = main(
            ["benchmark", "instances", "--json"],
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(code, 0)
        values = json.loads(stdout.getvalue())
        self.assertEqual(len(values), 15)
        self.assertEqual(values[0]["instance"], "dci.bcplus.level3@1.0.0")
        self.assertEqual(
            tuple(
                value["instance"]
                for value in values
                if value["implementation_state"] == "implemented"
            ),
            tuple(value["instance"] for value in values),
        )
        self.assertIn(
            "dci.qa.bamboogle@1.0.0",
            tuple(value["instance"] for value in values),
        )

    def test_benchmark_plan_defaults_to_one_case(self) -> None:
        calls: list[list[str]] = []

        def benchmark_main(argv, **kwargs):
            del kwargs
            calls.append(list(argv))
            return 0

        code = main(
            [
                "benchmark",
                "plan",
                "--instance",
                "dci.local-fixture@1.0.0",
            ],
            benchmark_main=benchmark_main,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )

        self.assertEqual(code, 0)
        self.assertEqual(
            calls,
            [[
                "plan",
                "--application",
                "dci.local-benchmark-application@1.0.0",
                "--suite",
                "dci.all@1.0.0",
                "--case-limit",
                "1",
            ]],
        )

    def test_benchmark_all_cases_resolves_finite_count(self) -> None:
        calls: list[list[str]] = []

        def benchmark_main(argv, **kwargs):
            del kwargs
            calls.append(list(argv))
            return 0

        code = main(
            [
                "benchmark",
                "plan",
                "--instance",
                "dci.qa.bamboogle@1.0.0",
                "--all-cases",
            ],
            benchmark_main=benchmark_main,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )

        self.assertEqual(code, 0)
        self.assertEqual(calls[0][-2:], ["--case-limit", "125"])

    def test_benchmark_execution_keeps_generic_explicit_authorization(self) -> None:
        stderr = io.StringIO()
        code = main(
            [
                "benchmark",
                "run",
                "--instance",
                "dci.local-fixture@1.0.0",
            ],
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
                    "--instance",
                    "dci.bright.biology@1.0.0",
                    "--max-cost-usd",
                    "0.20",
                    "--max-native-attempts",
                    "1",
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
        self.assertEqual(config.benchmark_inputs.amount, Decimal("0.20"))
        self.assertEqual(config.max_native_attempts, 1)
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
                "dci.complete-application@1.0.0",
                "--suite",
                "dci.bright.biology@1.0.0",
                "--case-limit",
                "1",
                "--execute",
                "--capability-source-lock",
                str(source_lock),
                "--evidence-root",
                str(root / "evidence"),
            ],
        )

    def test_installed_local_execution_wires_formal_host_without_private_config(
        self,
    ) -> None:
        host = cast(BenchmarkCommandHost, object())
        calls: list[object] = []

        def benchmark_main(argv, **kwargs):
            calls.append((list(argv), kwargs["host"]))
            return 0

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_lock = root / "source-lock.json"
            source_lock.write_text("{}\n", encoding="utf-8")
            with (
                patch(
                    "asterion.applications.dci.cli.load_operator_config",
                    side_effect=AssertionError("local config must not load"),
                ),
                patch(
                    "asterion.applications.dci.benchmark_host.DciBenchmarkHost",
                    return_value=host,
                ) as host_type,
            ):
                code = main(
                    [
                        "benchmark",
                        "run",
                        "--instance",
                        "dci.local-fixture@1.0.0",
                        "--execute",
                        "--capability-source-lock",
                        str(source_lock),
                        "--evidence-root",
                        str(root / "evidence"),
                    ],
                    benchmark_main=benchmark_main,
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )

        self.assertEqual(code, 0)
        host_type.assert_called_once()
        self.assertIsNone(host_type.call_args.kwargs["operator_config"])
        self.assertIs(cast(tuple[list[str], object], calls[0])[1], host)

    def test_unauthorized_run_never_loads_private_operator_config(self) -> None:
        calls: list[object] = []

        def host_factory(config):
            calls.append(config)
            return cast(BenchmarkCommandHost, object())

        stderr = io.StringIO()
        code = main(
            [
                "benchmark",
                "run",
                "--instance",
                "dci.local-fixture@1.0.0",
            ],
            benchmark_host_factory=host_factory,
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(code, 2)
        self.assertEqual(calls, [])
        self.assertIn("requires --execute", stderr.getvalue())

    def test_product_commands_do_not_delegate_to_a_provider(self) -> None:
        def application_main(argv, **kwargs):
            del argv, kwargs
            raise AssertionError("provider command")

        for argv in (["list"], ["run", "--runtime", "pi", "--input", "{}"]):
            with self.subTest(argv=argv):
                stderr = io.StringIO()
                self.assertEqual(
                    main(
                        argv,
                        application_main=application_main,
                        stdout=io.StringIO(),
                        stderr=stderr,
                    ),
                    2,
                )
                self.assertEqual(stderr.getvalue(), "asterion-dci: command failed\n")

        stdout = io.StringIO()
        self.assertEqual(
            main(
                ["describe", "--json"],
                application_main=application_main,
                stdout=stdout,
                stderr=io.StringIO(),
            ),
            0,
        )
        described = json.loads(stdout.getvalue())
        self.assertEqual(described["product_id"], "asterion-dci")
        self.assertNotIn("dci-agent-lite", stdout.getvalue())

        stdout = io.StringIO()
        code = main(
            ["preflight", "--json"],
            application_main=application_main,
            repo_root=PROJECT,
            stdout=stdout,
            stderr=io.StringIO(),
        )
        payload = json.loads(stdout.getvalue())
        self.assertIn(code, {0, 1})
        self.assertEqual(payload["product_id"], "asterion-dci")
        self.assertEqual(payload["level"], "preflight")
        self.assertEqual(payload["provider_backed_operation_count"], 0)

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
