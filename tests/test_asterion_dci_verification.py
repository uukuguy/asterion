from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from importlib import resources
from pathlib import Path
from unittest.mock import patch

from asterion.applications.controlled_code import (
    create_provider as create_controlled_provider,
)
from asterion.applications.dci_agent_lite import create_provider as create_dci_provider
from asterion.applications.product import VerificationRequest
from asterion.applications.provider import validate_installed_provider
from asterion.dci.verification import (
    DciProductVerifier,
    LocalDciVerificationBackend,
    create_dci_product,
)
from asterion.dci.config import resolve_dci_paths


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"
EXPECTED_CHECKS = (
    "application-assemblies",
    "application-providers",
    "capability-manifests",
    "context-profiles",
    "paper-benchmarks",
    "paper-scopes",
    "provider-requests",
)


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
    def __init__(
        self, node_version: tuple[int, int, int] | None = (22, 19, 0)
    ) -> None:
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


def acceptance_request(*, acceptance_root: Path | None = None) -> VerificationRequest:
    return VerificationRequest(
        level="acceptance",
        env_file=None,
        corpus_root=None,
        output_root=None,
        acceptance_root=acceptance_root,
    )


class InstalledAcceptanceTests(unittest.TestCase):
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
            path
            for application in applications
            for path in application.assembly_paths
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
            len(tuple((package_root / "capabilities").glob("*/manifests/*.json"))),
            11,
        )

    def test_acceptance_is_package_owned_exact_and_provider_free(self) -> None:
        verifier = DciProductVerifier(repo_root=PROJECT, backend=ExplodingBackend())

        result = verifier(acceptance_request())

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.provider_backed_operation_count, 0)
        self.assertFalse(result.full_dataset_ran)
        self.assertEqual(tuple(check.check_id for check in result.checks), EXPECTED_CHECKS)
        self.assertTrue(all(check.status == "PASS" for check in result.checks))
        self.assertEqual(
            {check.check_id: dict(check.counts) for check in result.checks},
            {
                "application-assemblies": {"actual": 6, "expected": 6},
                "application-providers": {"actual": 2, "expected": 2},
                "capability-manifests": {"actual": 11, "expected": 11},
                "context-profiles": {"actual": 5, "expected": 5},
                "paper-benchmarks": {"actual": 13, "expected": 13},
                "paper-scopes": {"actual": 16, "expected": 16},
                "provider-requests": {"actual": 0, "expected": 0},
            },
        )


class FirstRunPreflightTests(unittest.TestCase):
    def test_description_exposes_effective_runtime_and_path_defaults(self) -> None:
        requirements = {
            requirement.name: requirement
            for requirement in create_dci_product(repo_root=PROJECT).description.configuration
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
            verifier = DciProductVerifier(repo_root=root, backend=backend)
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
                        "asterion.dci.verification.subprocess.run",
                        return_value=completed,
                    ),
                    patch.dict(
                        os.environ,
                        {"DCI_PI_AGENT_DIR": "./missing-agent"},
                        clear=True,
                    ),
                ):
                    root = Path(temp_dir)
                    result = DciProductVerifier(
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
            verifier = DciProductVerifier(repo_root=root, backend=backend)
            with patch.dict(os.environ, {}, clear=True):
                result = verifier.preflight(
                    env_file=env_file, corpus_root=root / "corpus"
                )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.provider_backed_operation_count, 0)
        self.assertFalse(result.full_dataset_ran)
        self.assertEqual(backend.calls, [])
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
                result = DciProductVerifier(
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
                result = DciProductVerifier(
                    repo_root=root, backend=PreflightBackend()
                ).preflight(env_file=env_file, corpus_root=root / "corpus")

        checks = {check.check_id: check for check in result.checks}
        self.assertEqual(checks["judge"].status, "FAIL")
        self.assertIn("DCI_EVAL_JUDGE", checks["judge"].summary)
        self.assertNotIn("SECRET-JUDGE", repr(result))


class InstalledAcceptanceBoundaryTests(unittest.TestCase):

    def test_acceptance_ignores_source_evidence_path(self) -> None:
        verifier = DciProductVerifier(repo_root=PROJECT, backend=ExplodingBackend())
        with tempfile.TemporaryDirectory() as temp_dir:
            result = verifier(
                acceptance_request(acceptance_root=Path(temp_dir) / "untrusted")
            )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(tuple(check.check_id for check in result.checks), EXPECTED_CHECKS)

    def test_acceptance_fails_when_packaged_manifest_closure_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir) / "asterion"
            shutil.copytree(SOURCE, package_root)
            next(
                (package_root / "capabilities/dci_research/manifests").glob("*.json")
            ).unlink()
            verifier = DciProductVerifier(
                repo_root=Path(temp_dir), backend=ExplodingBackend()
            )
            with patch("importlib.resources.files", return_value=package_root):
                result = verifier(acceptance_request())

        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.provider_backed_operation_count, 0)
        self.assertFalse(result.full_dataset_ran)


if __name__ == "__main__":
    unittest.main()
