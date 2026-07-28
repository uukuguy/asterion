from __future__ import annotations

import os
import json
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from importlib import resources
from pathlib import Path
from unittest.mock import patch

from asterion.applications.controlled_code import (
    create_provider as create_controlled_provider,
)
from asterion.applications.dci_agent_lite import create_provider as create_dci_provider
from asterion.applications.product import VerificationRequest
from asterion.applications.provider import (
    ApplicationProviderError,
    compose_installed_provider,
    validate_installed_provider,
)
from asterion.capabilities.builtin import create_controlled_code_package
from asterion.capabilities.dci_research.provider import (
    create_provider as create_dci_package,
)
from asterion.capabilities.dci.implementation.reproduction.verification import (
    DciProductVerifier,
    LocalDciVerificationBackend,
    create_dci_product,
)
from asterion.capabilities.dci.implementation.config import resolve_dci_paths
from asterion.capabilities.dci.implementation.runtime.run import DciRunResult
from asterion.runtime.factory import RuntimeFactoryError


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"
EXPECTED_CHECKS = (
    "application-providers",
    "bound-assemblies",
    "capability-manifests",
    "composed-assemblies",
    "context-profiles",
    "executable-assemblies",
    "packaged-assemblies",
    "paper-benchmarks",
    "paper-scopes",
    "provider-requests",
)


def _dci_product_verifier(
    *,
    repo_root: Path,
    backend: object,
) -> DciProductVerifier:
    return DciProductVerifier(
        repo_root=repo_root,
        backend=backend,
        application_acceptance_inventory_factory=(
            _create_application_acceptance_inventory
        ),
    )


def _create_application_acceptance_inventory() -> object:
    from asterion.applications.dci_agent_lite.provider import (
        create_application_acceptance_inventory,
    )

    return create_application_acceptance_inventory()


class ExplodingBackend:
    def node_version(self) -> tuple[int, int, int] | None:
        raise AssertionError("acceptance called the backend")

    def run_research_case(self, *args, **kwargs):
        del args, kwargs
        raise AssertionError("acceptance called the backend")

    def evaluate_case(self, *args, **kwargs):
        del args, kwargs
        raise AssertionError("acceptance called the backend")


class PreflightBackend:
    def __init__(self, node_version: tuple[int, int, int] | None = (22, 19, 0)) -> None:
        self.node = node_version
        self.calls: list[object] = []

    def node_version(self) -> tuple[int, int, int] | None:
        return self.node

    def run_research_case(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("preflight called the Agent")

    def evaluate_case(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("preflight called the Judge")


class RecordingBasicBackend:
    def __init__(self) -> None:
        self.paths = []

    def node_version(self) -> tuple[int, int, int] | None:
        return (22, 19, 0)

    def run_research_case(self, paths, request, *, output_dir):
        del request
        self.paths.append(paths)
        return DciRunResult(
            output_dir=output_dir,
            final_text="fixture",
            events=(),
            status="completed",
        )

    def evaluate_case(self, output_dir, *, expected_answer, judge_config):
        del output_dir, expected_answer, judge_config
        return True


def acceptance_request(*, acceptance_root: Path | None = None) -> VerificationRequest:
    return VerificationRequest(
        level="acceptance",
        env_file=None,
        corpus_root=None,
        output_root=None,
        acceptance_root=acceptance_root,
    )


class InstalledAcceptanceTests(unittest.TestCase):
    def test_paper_inventory_separates_dataset_and_binding_provenance(self) -> None:
        """Paper-full Bamboogle must remain distinct from upstream sample-50."""

        resource_root = PROJECT / "src/asterion/capabilities/dci/resources"
        benchmarks = json.loads(
            (resource_root / "paper-benchmarks.json").read_text(encoding="utf-8")
        )["datasets"]
        scopes = json.loads(
            (resource_root / "paper-experiment-scopes.json").read_text(encoding="utf-8")
        )["scopes"]
        by_dataset = {item["dataset_id"]: item for item in benchmarks}
        by_scope = {item["scope_id"]: item for item in scopes}

        self.assertEqual(len(benchmarks), 13)
        self.assertEqual(
            {item["source_family"] for item in benchmarks}, {"paper-reference"}
        )
        self.assertTrue(
            all(item["source_reference"] == "arxiv:2605.05242v1" for item in benchmarks)
        )
        self.assertTrue(
            all(
                item["selection_kind"] == "full"
                and item["selection_count"] == item["source_count"]
                and item["selection_seed_status"] == "reported"
                for item in benchmarks
            )
        )
        self.assertEqual(
            sum(item["binding_origin"] == "upstream-github" for item in benchmarks),
            11,
        )
        self.assertEqual(
            {
                item["dataset_id"]
                for item in benchmarks
                if item["binding_origin"] == "asterion-added"
            },
            {"beir.arguana", "beir.scifact"},
        )
        self.assertEqual(by_dataset["qa.bamboogle"]["source_count"], 125)
        self.assertIsNone(by_dataset["qa.bamboogle"]["batch_profile"])
        self.assertEqual(
            by_dataset["qa.bamboogle"]["benchmark_binding_id"],
            "qa.bamboogle.paper-full125",
        )
        self.assertEqual(
            {
                item["benchmark_binding_id"]
                for item in benchmarks
            },
            {
                "bcplus.main",
                "beir.arguana",
                "beir.scifact",
                "bright.biology",
                "bright.earth-science",
                "bright.economics",
                "bright.robotics",
                "qa.2wikimultihopqa",
                "qa.bamboogle.paper-full125",
                "qa.hotpotqa",
                "qa.musique",
                "qa.nq",
                "qa.triviaqa",
            },
        )
        obsolete_field = "launch" + "er"
        self.assertNotIn(obsolete_field, by_dataset["qa.bamboogle"])

        self.assertEqual(len(scopes), 17)
        self.assertTrue(
            all(
                item["source_family"] == "paper-reference"
                and item["source_reference"] == "arxiv:2605.05242v1"
                for item in scopes
                if item["scope_id"] != "qa.bamboogle.upstream.sample50"
            )
        )
        self.assertTrue(
            all(
                item["selection_kind"] == "full"
                and item["selection_seed_status"] == "reported"
                for item in scopes
                if item["selection_mode"] == "all"
            )
        )
        self.assertTrue(
            all(
                item["selection_kind"]
                in {"full", "random-sample", "fixed-selected-ids"}
                and item["binding_origin"]
                in {"upstream-github", "asterion-added", "unavailable"}
                for item in scopes
            )
        )
        upstream_bamboogle = by_scope["qa.bamboogle.upstream.sample50"]
        self.assertEqual(upstream_bamboogle["selection_kind"], "fixed-selected-ids")
        self.assertEqual(upstream_bamboogle["selection_count"], 50)
        self.assertIsNone(upstream_bamboogle["selection_seed"])
        self.assertEqual(
            upstream_bamboogle["selected_ids_sha256"],
            "8b51d12a1a899aab455e6c20c4c36ae5fd5a0eca30816614f85bd2304e5a642d",
        )
        paper_bamboogle = by_scope["qa.bamboogle.main.full"]
        self.assertNotEqual(
            paper_bamboogle["source_family"], upstream_bamboogle["source_family"]
        )
        self.assertNotEqual(
            paper_bamboogle["execution_class"],
            upstream_bamboogle["execution_class"],
        )
        for item in scopes:
            if item["source_family"] == "paper-reference":
                self.assertEqual(item["source_reference"], "arxiv:2605.05242v1")
                self.assertEqual(item["execution_class"], "paper-full")
            else:
                self.assertEqual(item["source_family"], "upstream-github")
                self.assertEqual(
                    item["source_reference"],
                    "github:DCI-Agent/DCI-Agent-Lite@271f37e71f053bf0c99c05ce6d2fb53b841d922e;"
                    "hf:datasets/DCI-Agent/dci-bench@7fdd41059ef06df2a22d10d0f704768d44f1031b"
                    "#data/bamboogle/test.jsonl",
                )
                self.assertEqual(item["execution_class"], "upstream-reference")

        from asterion.capabilities.dci.implementation.reproduction.paper_benchmarks import (
            all_experiment_scope_ids,
            paper_experiment_scope_ids,
            resolve_experiment_scope,
            select_and_verify_experiment_scope_ids,
        )

        self.assertEqual(len(all_experiment_scope_ids()), 17)
        self.assertEqual(len(paper_experiment_scope_ids()), 16)
        self.assertNotIn("qa.bamboogle.upstream.sample50", paper_experiment_scope_ids())
        self.assertEqual(
            resolve_experiment_scope("qa.bamboogle.main.full").selection_count, 125
        )
        self.assertEqual(
            resolve_experiment_scope("qa.bamboogle.upstream.sample50").selection_count,
            50,
        )
        selected_ids = json.loads(
            (resource_root / "paper-selected-id-manifests.json").read_text(
                encoding="utf-8"
            )
        )["manifests"]["qa.bamboogle.upstream.sample50"]
        self.assertEqual(
            select_and_verify_experiment_scope_ids(
                "qa.bamboogle.upstream.sample50", selected_ids
            ),
            tuple(selected_ids),
        )

    def test_builtin_provider_and_resource_closure_has_exact_counts(self) -> None:
        providers = (
            validate_installed_provider(
                create_controlled_provider(), selected_id="controlled-code"
            ),
            validate_installed_provider(
                create_dci_provider(), selected_id="dci-agent-lite"
            ),
        )
        applications = tuple(
            application
            for provider in providers
            for application in provider.applications
        )
        bound_assemblies = tuple(
            path for application in applications for path in application.assembly_paths
        )
        package_root = Path(str(resources.files("asterion"))).resolve()

        self.assertEqual(len(providers), 2)
        self.assertEqual(len(applications), 3)
        self.assertEqual(len(bound_assemblies), 5)
        self.assertEqual(
            len(tuple((package_root / "applications").glob("*/assemblies/*.json"))),
            6,
        )
        self.assertEqual(
            sum(
                len(tuple(root.glob("*.json")))
                for package in (
                    create_controlled_code_package(),
                    create_dci_package(),
                )
                for root in package.catalog_roots
            ),
            11,
        )

    def test_acceptance_is_package_owned_exact_and_provider_free(self) -> None:
        verifier = _dci_product_verifier(repo_root=PROJECT, backend=ExplodingBackend())

        result = verifier(acceptance_request())

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.provider_backed_operation_count, 0)
        self.assertFalse(result.full_dataset_ran)
        self.assertEqual(
            tuple(check.check_id for check in result.checks), EXPECTED_CHECKS
        )
        self.assertTrue(all(check.status == "PASS" for check in result.checks))
        self.assertEqual(
            {check.check_id: dict(check.counts) for check in result.checks},
            {
                "application-providers": {"actual": 2, "expected": 2},
                "bound-assemblies": {"actual": 5, "expected": 5},
                "capability-manifests": {"actual": 11, "expected": 11},
                "composed-assemblies": {"actual": 5, "expected": 5},
                "context-profiles": {"actual": 5, "expected": 5},
                "executable-assemblies": {"actual": 5, "expected": 5},
                "packaged-assemblies": {"actual": 6, "expected": 6},
                "paper-benchmarks": {"actual": 13, "expected": 13},
                "paper-scopes": {"actual": 16, "expected": 16},
                "provider-requests": {"actual": 0, "expected": 0},
            },
        )
        checks = {check.check_id: check for check in result.checks}
        self.assertEqual(
            checks["packaged-assemblies"].unbound_resources,
            ("applications/dci_agent_lite/assemblies/dci-local-research.json",),
        )
        self.assertTrue(
            all(
                not Path(reference).is_absolute()
                for reference in checks["packaged-assemblies"].unbound_resources
            )
        )
        self.assertEqual(checks["executable-assemblies"].unbound_resources, ())

    def test_acceptance_resolves_manifests_without_constructing_runtime_clients(
        self,
    ) -> None:
        verifier = _dci_product_verifier(repo_root=PROJECT, backend=ExplodingBackend())
        with (
            patch(
                "asterion.runtime.defaults._create_pi_runtime",
                side_effect=AssertionError("acceptance constructed Pi"),
            ),
            patch(
                "asterion.runtime.defaults._create_claude_code_runtime",
                side_effect=AssertionError("acceptance constructed Claude"),
            ),
        ):
            result = verifier(acceptance_request())

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.provider_backed_operation_count, 0)


class FirstRunPreflightTests(unittest.TestCase):
    def test_description_exposes_effective_runtime_and_path_defaults(self) -> None:
        requirements = {
            requirement.name: requirement
            for requirement in create_dci_product(
                repo_root=PROJECT
            ).description.configuration
        }

        self.assertEqual(requirements["DCI_PROVIDER"].default, "openai-codex")
        self.assertEqual(requirements["DCI_MODEL"].default, "gpt-5.6-luna")
        self.assertEqual(requirements["DCI_PI_DIR"].default, "./pi")
        self.assertEqual(requirements["DCI_PI_AGENT_DIR"].default, "~/.pi/agent")
        self.assertEqual(
            requirements["DCI_EVAL_JUDGE_API_KEY_ENV"].default,
            "DEEPSEEK_API_KEY",
        )
        with patch.dict(os.environ, {}, clear=True):
            paths = resolve_dci_paths(PROJECT)
        self.assertEqual(paths.pi.agent_dir, Path("~/.pi/agent").expanduser())

    def test_missing_first_run_prerequisites_have_stable_repairs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backend = PreflightBackend(node_version=(22, 18, 0))
            verifier = _dci_product_verifier(repo_root=root, backend=backend)
            with patch.dict(
                os.environ,
                {"DCI_PI_AGENT_DIR": "./missing-agent"},
                clear=True,
            ):
                result = verifier.preflight(
                    env_file=root / ".env", corpus_root=root / "corpus"
                )

        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.provider_backed_operation_count, 0)
        self.assertFalse(result.full_dataset_ran)
        self.assertEqual(backend.calls, [])
        self.assertEqual(
            tuple(check.check_id for check in result.checks),
            (
                "agent-authentication",
                "agent-selection",
                "built-pi-cli",
                "environment",
                "judge",
                "node",
                "pi-checkout",
                "resources-basic",
            ),
        )
        summaries = {check.check_id: check.summary for check in result.checks}
        self.assertIn("DCI_PI_AGENT_DIR", summaries["agent-authentication"])
        self.assertIn("make setup-pi", summaries["built-pi-cli"])
        self.assertIn("cp .env.template .env", summaries["environment"])
        self.assertIn("make setup-resources-basic", summaries["resources-basic"])
        self.assertNotIn(temp_dir, repr(result))

    def test_preflight_requires_the_locked_pi_node_version(self) -> None:
        cases = (
            ("v22.18.0\n", "FAIL"),
            ("v22.19.0\n", "PASS"),
            ("v23.11.0\n", "PASS"),
        )
        for version, expected in cases:
            with self.subTest(version=version):
                completed = subprocess.CompletedProcess(
                    ["node", "--version"],
                    0,
                    stdout=version,
                    stderr="",
                )
                with (
                    tempfile.TemporaryDirectory() as temp_dir,
                    patch(
                        "asterion.capabilities.dci.implementation.reproduction.verification.subprocess.run",
                        return_value=completed,
                    ),
                    patch.dict(
                        os.environ,
                        {"DCI_PI_AGENT_DIR": "./missing-agent"},
                        clear=True,
                    ),
                ):
                    root = Path(temp_dir)
                    result = _dci_product_verifier(
                        repo_root=root,
                        backend=LocalDciVerificationBackend(),
                    ).preflight(
                        env_file=root / ".env",
                        corpus_root=root / "corpus",
                    )

                checks = {check.check_id: check for check in result.checks}
                self.assertEqual(checks["node"].status, expected)
                self.assertIn("22.19.0", checks["node"].summary)

    def test_complete_fixture_passes_without_agent_or_judge_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "pi/packages/coding-agent"
            (package / "dist").mkdir(parents=True)
            (package / "package.json").write_text("{}")
            (package / "dist/cli.js").write_text("// fixture\n")
            for corpus in ("wiki_corpus", "bc_plus_docs"):
                directory = root / "corpus" / corpus
                directory.mkdir(parents=True)
                (directory / "fixture.txt").write_text("fixture\n")
            agent = root / "user-agent"
            agent.mkdir()
            (agent / "auth.json").write_text("{}")
            env_file = root / ".env"
            env_file.write_text(
                "DCI_PROVIDER=openai-codex\n"
                "DCI_MODEL=gpt-5.6-luna\n"
                "DCI_PI_AGENT_DIR=./user-agent\n"
                "DCI_EVAL_JUDGE_MODEL=fixture-judge\n"
                "DCI_EVAL_JUDGE_API_KEY_ENV=JUDGE_KEY\n"
                "JUDGE_KEY=SECRET-JUDGE\n"
            )
            backend = PreflightBackend()
            verifier = _dci_product_verifier(repo_root=root, backend=backend)
            with patch.dict(os.environ, {}, clear=True):
                result = verifier.preflight(
                    env_file=env_file, corpus_root=root / "corpus"
                )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.provider_backed_operation_count, 0)
        self.assertFalse(result.full_dataset_ran)
        self.assertEqual(backend.calls, [])
        self.assertNotIn("SECRET-JUDGE", repr(result))

    def test_explicit_environment_anchors_relative_operator_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            operator_root = Path(temp_dir)
            package = operator_root / "pi/packages/coding-agent"
            (package / "dist").mkdir(parents=True)
            (package / "package.json").write_text("{}")
            (package / "dist/cli.js").write_text("// fixture\n")
            for corpus in ("wiki_corpus", "bc_plus_docs"):
                directory = operator_root / "corpus" / corpus
                directory.mkdir(parents=True)
                (directory / "fixture.txt").write_text("fixture\n")
            agent = operator_root / "user-agent"
            agent.mkdir()
            (agent / "auth.json").write_text("{}")
            env_file = operator_root / ".env"
            env_file.write_text(
                "DCI_PROVIDER=openai-codex\n"
                "DCI_MODEL=gpt-5.6-luna\n"
                "DCI_PI_DIR=./pi\n"
                "DCI_PI_AGENT_DIR=./user-agent\n"
                "ASTERION_DCI_CORPUS_ROOT=./corpus\n"
                "DCI_EVAL_JUDGE_MODEL=fixture-judge\n"
                "DCI_EVAL_JUDGE_API_KEY_ENV=JUDGE_KEY\n"
                "JUDGE_KEY=SECRET-JUDGE\n"
            )
            backend = PreflightBackend()
            verifier = _dci_product_verifier(repo_root=SOURCE, backend=backend)
            with patch.dict(os.environ, {}, clear=True):
                result = verifier.preflight(env_file=env_file, corpus_root=None)

        self.assertEqual(result.status, "PASS")
        self.assertEqual(backend.calls, [])
        self.assertNotIn("SECRET-JUDGE", repr(result))

    def test_basic_execution_reuses_the_preflight_operator_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            operator_root = Path(temp_dir)
            package = operator_root / "pi/packages/coding-agent"
            (package / "dist").mkdir(parents=True)
            (package / "package.json").write_text("{}")
            (package / "dist/cli.js").write_text("// fixture\n")
            for corpus in ("wiki_corpus", "bc_plus_docs"):
                directory = operator_root / "corpus" / corpus
                directory.mkdir(parents=True)
                (directory / "fixture.txt").write_text("fixture\n")
            agent = operator_root / "user-agent"
            agent.mkdir()
            (agent / "auth.json").write_text("{}")
            env_file = operator_root / ".env"
            env_file.write_text(
                "DCI_PROVIDER=openai-codex\n"
                "DCI_MODEL=gpt-5.6-luna\n"
                "DCI_PI_DIR=./pi\n"
                "DCI_PI_AGENT_DIR=./user-agent\n"
                "ASTERION_DCI_CORPUS_ROOT=./corpus\n"
                "DCI_EVAL_JUDGE_MODEL=fixture-judge\n"
                "DCI_EVAL_JUDGE_API_KEY_ENV=JUDGE_KEY\n"
                "JUDGE_KEY=SECRET-JUDGE\n"
            )
            backend = RecordingBasicBackend()
            verifier = _dci_product_verifier(repo_root=SOURCE, backend=backend)
            request = VerificationRequest(
                level="basic",
                env_file=env_file,
                corpus_root=None,
                output_root=operator_root / "outputs",
                acceptance_root=None,
            )
            with patch.dict(os.environ, {}, clear=True):
                result = verifier.basic(request)

        self.assertEqual(result.status, "PASS")
        self.assertEqual(len(backend.paths), 2)
        self.assertTrue(
            all(paths.repo_root == operator_root.resolve() for paths in backend.paths)
        )
        self.assertNotIn("SECRET-JUDGE", repr(result))

    def test_symlinked_agent_directory_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "pi/packages/coding-agent"
            (package / "dist").mkdir(parents=True)
            (package / "package.json").write_text("{}")
            (package / "dist/cli.js").write_text("// fixture\n")
            for corpus in ("wiki_corpus", "bc_plus_docs"):
                directory = root / "corpus" / corpus
                directory.mkdir(parents=True)
                (directory / "fixture.txt").write_text("fixture\n")
            real_agent = root / "real-agent"
            real_agent.mkdir()
            (real_agent / "auth.json").write_text("{}")
            try:
                os.symlink(real_agent, root / "linked-agent")
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            env_file = root / ".env"
            env_file.write_text(
                "DCI_PI_AGENT_DIR=./linked-agent\n"
                "DCI_EVAL_JUDGE_API_KEY_ENV=JUDGE_KEY\n"
                "JUDGE_KEY=SECRET-JUDGE\n"
            )
            with patch.dict(os.environ, {}, clear=True):
                result = _dci_product_verifier(
                    repo_root=root, backend=PreflightBackend()
                ).preflight(env_file=env_file, corpus_root=root / "corpus")

        checks = {check.check_id: check for check in result.checks}
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(checks["agent-authentication"].status, "FAIL")
        self.assertIn("DCI_PI_AGENT_DIR", checks["agent-authentication"].summary)

    def test_invalid_judge_request_configuration_fails_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.write_text(
                "DCI_EVAL_JUDGE_BASE_URL=not-a-url\n"
                "DCI_EVAL_JUDGE_MODEL=fixture-judge\n"
                "DCI_EVAL_JUDGE_API_KEY_ENV=JUDGE_KEY\n"
                "JUDGE_KEY=SECRET-JUDGE\n"
            )
            with patch.dict(
                os.environ,
                {"DCI_PI_AGENT_DIR": "./missing-agent"},
                clear=True,
            ):
                result = _dci_product_verifier(
                    repo_root=root, backend=PreflightBackend()
                ).preflight(env_file=env_file, corpus_root=root / "corpus")

        checks = {check.check_id: check for check in result.checks}
        self.assertEqual(checks["judge"].status, "FAIL")
        self.assertIn("DCI_EVAL_JUDGE", checks["judge"].summary)
        self.assertNotIn("SECRET-JUDGE", repr(result))


class InstalledAcceptanceBoundaryTests(unittest.TestCase):
    def assert_named_layers(
        self,
        result,
        *,
        packaged: str,
        bound: str,
        composed: str,
        executable: str,
    ) -> None:
        checks = {check.check_id: check for check in result.checks}
        self.assertNotIn("installed-closure", checks)
        self.assertEqual(checks["packaged-assemblies"].status, packaged)
        self.assertEqual(checks["bound-assemblies"].status, bound)
        self.assertEqual(checks["composed-assemblies"].status, composed)
        self.assertEqual(checks["executable-assemblies"].status, executable)
        self.assertEqual(result.provider_backed_operation_count, 0)

    def assert_only_named_failure(
        self,
        result,
        *,
        check_id: str,
        actual: int,
    ) -> None:
        checks = {check.check_id: check for check in result.checks}
        self.assertNotIn("installed-closure", checks)
        self.assertEqual(
            tuple(
                identity for identity, check in checks.items() if check.status == "FAIL"
            ),
            (check_id,),
        )
        self.assertEqual(dict(checks[check_id].counts)["actual"], actual)
        for application_check in (
            "packaged-assemblies",
            "bound-assemblies",
            "composed-assemblies",
            "executable-assemblies",
        ):
            self.assertEqual(checks[application_check].status, "PASS")
        self.assertEqual(result.provider_backed_operation_count, 0)

    def test_acceptance_ignores_source_evidence_path(self) -> None:
        verifier = _dci_product_verifier(repo_root=PROJECT, backend=ExplodingBackend())
        with tempfile.TemporaryDirectory() as temp_dir:
            result = verifier(
                acceptance_request(acceptance_root=Path(temp_dir) / "untrusted")
            )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(
            tuple(check.check_id for check in result.checks), EXPECTED_CHECKS
        )

    def test_acceptance_fails_when_packaged_manifest_closure_is_incomplete(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir) / "asterion"
            shutil.copytree(SOURCE, package_root)
            next(
                (package_root / "capabilities/dci/payload/capabilities").glob(
                    "*.json"
                )
            ).unlink()
            verifier = _dci_product_verifier(
                repo_root=Path(temp_dir), backend=ExplodingBackend()
            )
            resource_files = resources.files
            with (
                patch(
                    "importlib.resources.files",
                    side_effect=lambda anchor: (
                        package_root if anchor == "asterion" else resource_files(anchor)
                    ),
                ),
                patch(
                    "asterion.capabilities.dci_research.provider.__file__",
                    str(package_root / "capabilities/dci_research/provider.py"),
                ),
            ):
                result = verifier(acceptance_request())

        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.provider_backed_operation_count, 0)
        self.assertFalse(result.full_dataset_ran)
        checks = {check.check_id: check for check in result.checks}
        self.assertEqual(tuple(checks), ("installed-closure",))
        self.assertEqual(checks["installed-closure"].status, "FAIL")

    def test_acceptance_reports_independent_damage_layers(self) -> None:
        verifier = _dci_product_verifier(repo_root=PROJECT, backend=ExplodingBackend())

        with self.subTest(layer="packaged"), tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir) / "asterion"
            shutil.copytree(SOURCE, package_root)
            assembly_root = package_root / "applications/dci_agent_lite/assemblies"
            (assembly_root / "dci-local-research.json").rename(
                assembly_root / "same-count-substitute.json"
            )
            resource_files = resources.files
            with patch(
                "importlib.resources.files",
                side_effect=lambda anchor: (
                    package_root if anchor == "asterion" else resource_files(anchor)
                ),
            ):
                result = verifier(acceptance_request())
            self.assert_named_layers(
                result,
                packaged="FAIL",
                bound="PASS",
                composed="PASS",
                executable="PASS",
            )
            packaged = next(
                check
                for check in result.checks
                if check.check_id == "packaged-assemblies"
            )
            self.assertEqual(dict(packaged.counts)["actual"], 6)

        with self.subTest(layer="bound"):
            installed = create_dci_provider()
            damaged = replace(installed, applications=(installed.applications[0],))
            with patch(
                "asterion.applications.dci_agent_lite.create_provider",
                return_value=damaged,
            ):
                result = verifier(acceptance_request())
            self.assert_named_layers(
                result,
                packaged="PASS",
                bound="FAIL",
                composed="FAIL",
                executable="FAIL",
            )

        def fail_dci_composition(
            provider,
            *,
            installed_packages,
            runtime_factories,
        ):
            if provider.provider_id == "dci-agent-lite":
                raise ApplicationProviderError(
                    "installed application composition closure is invalid"
                )
            return compose_installed_provider(
                provider,
                installed_packages=installed_packages,
                runtime_factories=runtime_factories,
            )

        with (
            self.subTest(layer="composed"),
            patch(
                "asterion.applications.provider.compose_installed_provider",
                side_effect=fail_dci_composition,
            ),
        ):
            result = verifier(acceptance_request())
            self.assert_named_layers(
                result,
                packaged="PASS",
                bound="PASS",
                composed="FAIL",
                executable="FAIL",
            )

        with self.subTest(layer="executable"):
            installed = create_dci_package()
            binding = installed.implementations[0]
            damaged = replace(
                installed,
                implementations=(
                    replace(
                        binding,
                        implementation=object(),
                    ),
                    *installed.implementations[1:],
                ),
            )
            with patch(
                "asterion.capabilities.dci_research.provider.create_provider",
                return_value=damaged,
            ):
                result = verifier(acceptance_request())
            self.assert_named_layers(
                result,
                packaged="PASS",
                bound="PASS",
                composed="PASS",
                executable="FAIL",
            )

    def test_acceptance_reports_profile_and_paper_damage_independently(
        self,
    ) -> None:
        verifier = _dci_product_verifier(repo_root=PROJECT, backend=ExplodingBackend())

        cases = (
            (
                "same-cardinality-profile-substitution",
                "context_profile_names",
                ("level0", "level1", "level2", "level3", "substitute"),
                "context-profiles",
                5,
            ),
            (
                "profile-enumeration-failure",
                "context_profile_names",
                RuntimeError("profile enumeration failed"),
                "context-profiles",
                0,
            ),
            (
                "profile-resolver-failure",
                "resolve_context_profile",
                RuntimeError("profile resolver failed"),
                "context-profiles",
                5,
            ),
            (
                "benchmark-resolver-failure",
                "resolve_paper_benchmark",
                RuntimeError("benchmark resolver failed"),
                "paper-benchmarks",
                13,
            ),
            (
                "benchmark-checksum-failure",
                "paper_benchmark_inventory_sha256",
                "invalid",
                "paper-benchmarks",
                13,
            ),
            (
                "scope-resolver-failure",
                "resolve_paper_experiment_scope",
                RuntimeError("scope resolver failed"),
                "paper-scopes",
                16,
            ),
            (
                "scope-checksum-failure",
                "paper_experiment_scopes_sha256",
                "invalid",
                "paper-scopes",
                16,
            ),
        )
        for case, target, outcome, check_id, actual in cases:
            kwargs = (
                {"side_effect": outcome}
                if isinstance(outcome, Exception)
                else {"return_value": outcome}
            )
            with (
                self.subTest(case=case),
                patch(f"asterion.capabilities.dci.implementation.reproduction.verification.{target}", **kwargs),
            ):
                result = verifier(acceptance_request())

            self.assert_only_named_failure(result, check_id=check_id, actual=actual)

    def test_acceptance_reports_registry_construction_as_composition_damage(
        self,
    ) -> None:
        verifier = _dci_product_verifier(repo_root=PROJECT, backend=ExplodingBackend())
        with (
            patch(
                "asterion.runtime.defaults.default_runtime_factory_registry",
                side_effect=RuntimeFactoryError("runtime factory binding is invalid"),
            ),
            patch(
                "asterion.runtime.defaults._create_pi_runtime",
                side_effect=AssertionError("acceptance constructed Pi"),
            ) as pi_factory,
            patch(
                "asterion.runtime.defaults._create_claude_code_runtime",
                side_effect=AssertionError("acceptance constructed Claude"),
            ) as claude_factory,
        ):
            result = verifier(acceptance_request())

        self.assert_named_layers(
            result,
            packaged="PASS",
            bound="PASS",
            composed="FAIL",
            executable="FAIL",
        )
        self.assertEqual(
            tuple(check.check_id for check in result.checks if check.status == "FAIL"),
            ("composed-assemblies", "executable-assemblies"),
        )
        pi_factory.assert_not_called()
        claude_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
