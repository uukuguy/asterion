"""DCI CLI adapter tests: defaults, private operator config, and delegation."""

from __future__ import annotations

import ast
import io
import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from asterion.applications.dci_agent_lite import cli, operator_config
from asterion.applications.dci_agent_lite.provider import create_provider
from asterion.capability_packages.sources.builtin import (
    BuiltinCapabilityPackageSource,
)
from asterion.capabilities.dci.implementation.operator_inputs import (
    DciBenchmarkOperatorInputs,
)


PROJECT = Path(__file__).resolve().parents[1]
APPLICATION_ROOT = PROJECT / "src/asterion/applications/dci_agent_lite"
ASSEMBLIES = APPLICATION_ROOT / "assemblies"
PYPROJECT = PROJECT / "pyproject.toml"
SENTINEL = "DCI-PRIVATE-SENTINEL"


class DciApplicationAdapterTests(unittest.TestCase):
    def test_entry_point_targets_thin_application_adapter(self) -> None:
        self.assertIn(
            'asterion-dci = "asterion.applications.dci_agent_lite.cli:main"',
            PYPROJECT.read_text(encoding="utf-8"),
        )

    def test_provider_selects_exact_dci_applications_and_runtimes(self) -> None:
        provider = create_provider()

        self.assertEqual(provider.provider_id, "dci-agent-lite")
        by_id = {
            (application.application_id, application.version): application
            for application in provider.applications
        }
        self.assertEqual(
            set(by_id),
            {
                ("dci.complete-application", "1.0.0"),
                ("dci.research-capability", "1.0.0"),
            },
        )
        for application in by_id.values():
            with self.subTest(application=application.application_id):
                self.assertEqual(
                    tuple(
                        (ref.package_id, ref.version)
                        for ref in application.capability_packages
                    ),
                    (("dci", "1.0.0"),),
                )
                self.assertEqual(
                    application.runtime_ids,
                    ("claude-code.reference", "pi.reference"),
                )

    def test_all_adapter_assemblies_use_exact_dci_package_contract(self) -> None:
        for path in sorted(ASSEMBLIES.glob("*.json")):
            with self.subTest(assembly=path.name):
                document = json.loads(path.read_text(encoding="utf-8"))

                self.assertEqual(
                    document["protocol"], "asterion.application-assembly/v1"
                )
                self.assertEqual(
                    document["capability_packages"],
                    [{"package_id": "dci", "version": "1.0.0"}],
                )
                rendered = json.dumps(document, sort_keys=True)
                for private in (
                    ".env",
                    "ASTERION_DCI_",
                    "DCI_DATASET",
                    "DCI_CORPUS",
                    "OPENAI_API_KEY",
                    SENTINEL,
                ):
                    self.assertNotIn(private, rendered)

    def test_operator_config_translates_env_paths_and_keeps_amount_optional(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            env_file = root / ".env"
            dataset = root / "datasets"
            corpus = root / "corpora"
            dataset.mkdir()
            corpus.mkdir()
            env_file.write_text(
                "\n".join(
                    (
                        f"ASTERION_DCI_DATASET_BCPLUS={dataset / 'bcplus'}",
                        f"ASTERION_DCI_CORPUS_WIKI={corpus / 'wiki'}",
                        f"ASTERION_DCI_PRIVATE_SECRET={SENTINEL}",
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            inputs = operator_config.load_operator_inputs(
                operator_root=root,
                env_file=env_file,
            )

        self.assertIsInstance(inputs, DciBenchmarkOperatorInputs)
        self.assertEqual(inputs.dataset_roots["bcplus"], dataset / "bcplus")
        self.assertEqual(inputs.corpus_roots["wiki"], corpus / "wiki")
        self.assertEqual(inputs.private_environment["ASTERION_DCI_PRIVATE_SECRET"], SENTINEL)
        self.assertIsNone(inputs.amount)
        self.assertNotIn(str(dataset), repr(inputs))
        self.assertNotIn(str(corpus), repr(inputs))
        self.assertNotIn(SENTINEL, repr(inputs))

    def test_operator_config_accepts_explicit_roots_and_private_amount(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            inputs = operator_config.load_operator_inputs(
                operator_root=root,
                dataset_roots={"qa": root / "qa"},
                corpus_roots={"wiki": root / "wiki"},
                private_environment={"DCI_TOKEN": SENTINEL},
                amount="12.50",
            )

        self.assertEqual(inputs.dataset_roots["qa"], root / "qa")
        self.assertEqual(inputs.corpus_roots["wiki"], root / "wiki")
        self.assertEqual(inputs.amount, Decimal("12.50"))
        self.assertNotIn("12.50", repr(inputs))

    def test_operator_config_resolves_relative_values_against_owner_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator_root = Path(directory, "operator").resolve()
            env_root = Path(directory, "config").resolve()
            operator_root.mkdir()
            env_root.mkdir()
            env_file = env_root / "dci.env"
            env_file.write_text(
                "\n".join(
                    (
                        "ASTERION_DCI_DATASET_QA=env-datasets/qa",
                        "ASTERION_DCI_CORPUS_WIKI=env-corpora/wiki",
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            file_inputs = operator_config.load_operator_inputs(
                operator_root=operator_root,
                env_file=Path("../config/dci.env"),
            )
            explicit_inputs = operator_config.load_operator_inputs(
                operator_root=operator_root,
                dataset_roots={"bright": Path("explicit-datasets/bright")},
                corpus_roots={"bright": Path("explicit-corpora/bright")},
            )
            with patch.dict(
                os.environ,
                {
                    "ASTERION_DCI_DATASET_BCPLUS": "process-datasets/bcplus",
                    "ASTERION_DCI_CORPUS_BCPLUS": "process-corpora/bcplus",
                    "ASTERION_DCI_PRIVATE_SECRET": SENTINEL,
                },
                clear=True,
            ):
                process_inputs = operator_config.process_environment_inputs(
                    operator_root,
                )

        self.assertEqual(
            file_inputs.dataset_roots["qa"], env_root / "env-datasets/qa"
        )
        self.assertEqual(
            file_inputs.corpus_roots["wiki"], env_root / "env-corpora/wiki"
        )
        self.assertEqual(
            explicit_inputs.dataset_roots["bright"],
            operator_root / "explicit-datasets/bright",
        )
        self.assertEqual(
            explicit_inputs.corpus_roots["bright"],
            operator_root / "explicit-corpora/bright",
        )
        self.assertEqual(
            process_inputs.dataset_roots["bcplus"],
            operator_root / "process-datasets/bcplus",
        )
        self.assertEqual(
            process_inputs.corpus_roots["bcplus"],
            operator_root / "process-corpora/bcplus",
        )
        self.assertNotIn(SENTINEL, repr(process_inputs))

    def test_host_service_preflight_validates_required_roots_and_redacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            dataset_roots = {
                key: root / f"datasets/{key}"
                for key in ("bcplus", "beir", "bright", "paper-full", "qa")
            }
            corpus_roots = {
                key: root / f"corpora/{key}"
                for key in ("bcplus", "beir", "bright", "wiki")
            }
            for path in (*dataset_roots.values(), *corpus_roots.values()):
                path.mkdir(parents=True)
            report = operator_config.preflight_host_services(
                operator_config.load_operator_inputs(
                    operator_root=root,
                    dataset_roots=dataset_roots,
                    corpus_roots=corpus_roots,
                    private_environment={"DCI_TOKEN": SENTINEL},
                )
            )

        self.assertEqual(report["status"], "ready")
        rendered = json.dumps(report, sort_keys=True)
        self.assertIn("dataset_roots", rendered)
        self.assertNotIn(str(root), rendered)
        self.assertNotIn(SENTINEL, rendered)

    def test_host_service_preflight_fails_closed_for_missing_unsafe_or_incomplete_roots(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            present = root / "present"
            present.mkdir()
            file_path = root / "not-directory"
            file_path.write_text(SENTINEL, encoding="utf-8")
            target = root / "target"
            target.mkdir()
            symlink = root / "symlink"
            symlink.symlink_to(target, target_is_directory=True)
            cases = (
                (
                    "missing required keys",
                    {"qa": present},
                    {"wiki": present},
                ),
                (
                    "missing directory",
                    {
                        "bcplus": root / "absent",
                        "beir": present,
                        "bright": present,
                        "paper-full": present,
                        "qa": present,
                    },
                    {"bcplus": present, "beir": present, "bright": present, "wiki": present},
                ),
                (
                    "not directory",
                    {
                        "bcplus": file_path,
                        "beir": present,
                        "bright": present,
                        "paper-full": present,
                        "qa": present,
                    },
                    {"bcplus": present, "beir": present, "bright": present, "wiki": present},
                ),
                (
                    "symlink",
                    {
                        "bcplus": symlink,
                        "beir": present,
                        "bright": present,
                        "paper-full": present,
                        "qa": present,
                    },
                    {"bcplus": present, "beir": present, "bright": present, "wiki": present},
                ),
            )

            for label, datasets, corpora in cases:
                with self.subTest(label=label):
                    inputs = operator_config.load_operator_inputs(
                        operator_root=root,
                        dataset_roots=datasets,
                        corpus_roots=corpora,
                        private_environment={"DCI_TOKEN": SENTINEL},
                    )
                    with self.assertRaises(operator_config.DciOperatorConfigError) as raised:
                        operator_config.preflight_host_services(inputs)
                    rendered = str(raised.exception)
                    self.assertNotIn(str(root), rendered)
                    self.assertNotIn(SENTINEL, rendered)

    def test_benchmark_plan_delegates_to_generic_host_with_dci_defaults(self) -> None:
        captured: list[list[str]] = []

        def fake_main(argv: list[str], **kwargs: object) -> int:
            captured.append(argv)
            self.assertIs(kwargs["stdout"], stdout)
            self.assertIs(kwargs["stderr"], stderr)
            kwargs["stdout"].write('{"status":"planned"}\n')
            return 0

        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("asterion.applications.dci_agent_lite.cli.asterion_main", fake_main):
            code = cli.main(
                ["benchmark", "plan", "--suite", "github", "--case-limit", "1"],
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(
            captured,
            [
                [
                    "benchmark",
                    "plan",
                    "--application",
                    "dci.complete-application@1.0.0",
                    "--suite",
                    "dci.github@1.0.0",
                    "--case-limit",
                    "1",
                ]
            ],
        )
        self.assertNotIn("dataset", stdout.getvalue())

    def test_execution_authorization_remains_generic_gate(self) -> None:
        captured: list[list[str]] = []

        def fake_main(argv: list[str], **_kwargs: object) -> int:
            captured.append(argv)
            return 2

        with patch("asterion.applications.dci_agent_lite.cli.asterion_main", fake_main):
            code = cli.main(
                ["benchmark", "run", "--suite", "github"],
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(code, 2)
        self.assertNotIn("--execute", captured[0])

    def test_benchmark_run_uses_generic_builtin_source_registration(self) -> None:
        captured_sources: list[object] = []

        def fake_main(argv: list[str], **kwargs: object) -> int:
            del argv
            captured_sources.extend(kwargs["capability_package_sources"])
            return 0

        with patch("asterion.applications.dci_agent_lite.cli.asterion_main", fake_main):
            code = cli.main(
                ["benchmark", "run", "--suite", "github", "--execute"],
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(captured_sources), 1)
        self.assertIsInstance(captured_sources[0], BuiltinCapabilityPackageSource)

    def test_list_describe_and_preflight_do_not_load_benchmark_provider(self) -> None:
        calls: list[list[str]] = []

        def fake_main(argv: list[str], **_kwargs: object) -> int:
            calls.append(argv)
            return 0

        with patch("asterion.applications.dci_agent_lite.cli.asterion_main", fake_main):
            self.assertEqual(cli.main(["list"], stdout=io.StringIO(), stderr=io.StringIO()), 0)
            self.assertEqual(
                cli.main(["describe", "--json"], stdout=io.StringIO(), stderr=io.StringIO()),
                0,
            )

        self.assertEqual(
            calls,
            [
                ["list", "--provider", "dci-agent-lite"],
                ["describe", "--provider", "dci-agent-lite", "--json"],
            ],
        )
        with patch(
            "asterion.applications.dci_agent_lite.cli.asterion_main",
            side_effect=AssertionError("provider operation"),
        ):
            stderr = io.StringIO()
            self.assertEqual(
                cli.main(["preflight"], stdout=io.StringIO(), stderr=stderr),
                2,
            )
            self.assertEqual(stderr.getvalue(), "asterion-dci: command failed\n")

    def test_adapter_source_has_no_benchmark_orchestration_implementation(self) -> None:
        forbidden_names = {
            "AuthorizedProcessTaskExecutor",
            "BenchmarkRunner",
            "LocalPrivateBenchmarkEvidenceStore",
            "discover_capabilities",
            "resolve_assembly",
            "resolve_benchmark_execution",
            "run_benchmark",
            "run_pi_research",
        }
        forbidden_attributes = {
            "Popen",
            "run",
            "check_call",
            "check_output",
        }
        forbidden_function_names = {
            "discover_metadata",
            "load_provider",
            "open_payload",
            "validate_source_identity",
        }
        for path in (
            APPLICATION_ROOT / "cli.py",
            APPLICATION_ROOT / "operator_config.py",
            APPLICATION_ROOT / "provider.py",
        ):
            with self.subTest(path=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                names = {
                    node.id
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Name)
                }
                attributes = {
                    node.attr
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Attribute)
                }
                function_names = {
                    node.name
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
                }
                self.assertFalse(names & forbidden_names)
                self.assertFalse(attributes & forbidden_attributes)
                self.assertFalse(function_names & forbidden_function_names)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
