from __future__ import annotations

import ast
import importlib.util
import unittest
from pathlib import Path

from asterion.capabilities.dci.implementation import (
    DciPackageResourceError,
    package_resource,
)


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"
PACKAGE = SOURCE / "capabilities/dci"
IMPLEMENTATION = PACKAGE / "implementation"
EXPECTED_MODULES = {
    "research": {
        "context_extension.py",
        "context_profiles.py",
        "effective_config.py",
        "experiment_profiles.py",
        "pathlight_observation.py",
        "prompts.py",
        "system_prompt.py",
        "trajectory_resolution.py",
    },
    "evaluation": {
        "analysis.py",
        "artifacts.py",
        "benchmark.py",
        "evaluation.py",
        "judge.py",
        "metrics.py",
        "resolution_metrics.py",
    },
    "reproduction": {
        "ablation.py",
        "dual_runtime_verification.py",
        "paper_benchmarks.py",
        "provenance.py",
        "reproduction.py",
        "verification.py",
    },
    "runtime": {
        "application_executor.py",
        "bridge.py",
        "pi_rpc.py",
        "run.py",
    },
}
EXPECTED_ROOT_MODULES = {
    "__init__.py",
    "_analysis.py",
    "_artifacts.py",
    "_provenance.py",
    "_runtime.py",
    "benchmark_bindings.py",
    "complete.py",
    "config.py",
    "datasets.py",
    "export.py",
    "implementation.py",
    "local_provider.py",
    "operator_inputs.py",
    "resource_setup.py",
    "services.py",
}


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.append(node.module)
    return tuple(names)


class DciPackageOwnershipTests(unittest.TestCase):
    def test_all_domain_modules_have_one_package_owner(self) -> None:
        self.assertFalse((SOURCE / "dci").exists())
        self.assertFalse((SOURCE / "capabilities/dci_research").exists())
        self.assertEqual(
            {path.name for path in IMPLEMENTATION.glob("*.py")},
            EXPECTED_ROOT_MODULES,
        )
        for group, expected in EXPECTED_MODULES.items():
            with self.subTest(group=group):
                self.assertEqual(
                    {
                        path.name
                        for path in (IMPLEMENTATION / group).glob("*.py")
                        if path.name != "__init__.py"
                    },
                    expected,
                )

    def test_generic_framework_never_imports_dci_package(self) -> None:
        generic_roots = (
            SOURCE / "runtime",
            SOURCE / "packages",
            SOURCE / "assembly",
            SOURCE / "runner",
            SOURCE / "services",
            SOURCE / "benchmarks",
            SOURCE / "capability_packages",
        )
        offenders = {
            str(path.relative_to(SOURCE))
            for root in generic_roots
            if root.is_dir()
            for path in root.rglob("*.py")
            if any(
                name == "asterion.capabilities.dci"
                or name.startswith("asterion.capabilities.dci.")
                for name in _imports(path)
            )
        }
        self.assertEqual(offenders, set())

    def test_package_does_not_depend_on_application_or_old_owner(self) -> None:
        forbidden = (
            "asterion.applications.dci_agent_lite",
            "asterion.capabilities.dci_research",
            "asterion.dci",
            "asterion.capability_packages",
            "asterion.capabilities.catalog",
            "asterion.capabilities.execution",
        )
        offenders = {
            str(path.relative_to(SOURCE))
            for path in PACKAGE.rglob("*.py")
            if any(
                name == prefix or name.startswith(f"{prefix}.")
                for name in _imports(path)
                for prefix in forbidden
            )
        }
        self.assertEqual(offenders, set())
        for path in PACKAGE.rglob("*.py"):
            with self.subTest(path=path.relative_to(SOURCE)):
                self.assertNotIn(
                    "asterion.capabilities.dci_research",
                    path.read_text(encoding="utf-8"),
                )
                self.assertNotIn(
                    "applications/dci_agent_lite",
                    path.read_text(encoding="utf-8"),
                )

    def test_package_resources_are_relative_and_reject_escape(self) -> None:
        self.assertTrue(package_resource("batch-profiles.json").is_file())
        for unsafe in (
            "",
            "../batch-profiles.json",
            "/batch-profiles.json",
            "paper-fixtures/../../batch-profiles.json",
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaisesRegex(
                    DciPackageResourceError,
                    "^DCI package resource is invalid$",
                ):
                    package_resource(unsafe)

    def test_old_domain_imports_are_absent(self) -> None:
        for module in (
            "asterion.dci.metrics",
            "asterion.dci.services",
            "asterion.dci.reproduction",
            "asterion.capabilities.dci_research.implementation",
            "asterion.capabilities.dci_research.complete",
        ):
            with self.subTest(module=module):
                try:
                    spec = importlib.util.find_spec(module)
                except ModuleNotFoundError:
                    spec = None
                self.assertIsNone(spec)

    def test_every_dci_named_module_is_package_or_application_owned(self) -> None:
        offenders = {
            path.relative_to(SOURCE).as_posix()
            for path in SOURCE.rglob("*.py")
            if "dci" in path.relative_to(SOURCE).as_posix().lower()
            and not path.is_relative_to(PACKAGE)
            and not path.is_relative_to(SOURCE / "applications/dci_agent_lite")
        }

        self.assertEqual(offenders, set())


if __name__ == "__main__":
    unittest.main()
