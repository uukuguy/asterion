from __future__ import annotations

import ast
import importlib.util
import unittest
from pathlib import Path

from asterion.capabilities.dci.implementation.reproduction import reproduction


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"
PACKAGE = SOURCE / "capabilities/dci"
LEGACY_DCI = SOURCE / "dci"

MODULE_GROUPS = {
    "research": {
        "context_extension",
        "context_profiles",
        "effective_config",
        "experiment_profiles",
        "prompts",
        "system_prompt",
        "trajectory_resolution",
    },
    "evaluation": {
        "analysis",
        "artifacts",
        "benchmark",
        "evaluation",
        "judge",
        "metrics",
        "resolution_metrics",
    },
    "reproduction": {
        "ablation",
        "dual_runtime_verification",
        "paper_benchmarks",
        "provenance",
        "reproduction",
        "verification",
    },
    "runtime": {
        "application_executor",
        "bridge",
        "pi_rpc",
        "run",
    },
}
ROOT_MODULES = {
    "complete",
    "config",
    "datasets",
    "export",
    "implementation",
    "resource_setup",
    "services",
}


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
    return tuple(imported)


class DciPackageOwnershipTests(unittest.TestCase):
    def test_implementation_modules_have_one_package_owned_location(self) -> None:
        for group, names in MODULE_GROUPS.items():
            with self.subTest(group=group):
                self.assertEqual(
                    {
                        path.stem
                        for path in (PACKAGE / "implementation" / group).glob("*.py")
                        if path.name != "__init__.py"
                    },
                    names,
                )
        self.assertTrue(
            ROOT_MODULES.issubset(
                {
                    path.stem
                    for path in (PACKAGE / "implementation").glob("*.py")
                }
            )
        )
        self.assertEqual(
            {
                path.name
                for path in LEGACY_DCI.glob("*.py")
            },
            {"__init__.py", "cli.py"},
        )
        legacy_package = SOURCE / "capabilities/dci_research"
        self.assertFalse((legacy_package / "manifests").exists())
        for name in (
            "complete.py",
            "implementation.py",
            "private_values.py",
            "runtime_adapter.py",
        ):
            with self.subTest(legacy_module=name):
                self.assertFalse((legacy_package / name).exists())

    def test_package_never_imports_application_or_legacy_dci_modules(self) -> None:
        violations: list[tuple[str, str]] = []
        for path in sorted(PACKAGE.rglob("*.py")):
            for imported in _imports(path):
                if (
                    imported == "asterion.dci"
                    or imported.startswith("asterion.dci.")
                    or imported == "asterion.capabilities.dci_research"
                    or imported.startswith("asterion.capabilities.dci_research.")
                    or imported == "asterion.applications.dci_agent_lite"
                    or imported.startswith("asterion.applications.dci_agent_lite.")
                ):
                    violations.append((str(path.relative_to(PROJECT)), imported))
        self.assertEqual(violations, [])

    def test_generic_framework_modules_never_import_dci_package(self) -> None:
        violations: list[tuple[str, str]] = []
        allowed_roots = (
            PACKAGE,
            SOURCE / "applications/dci_agent_lite",
            SOURCE / "capabilities/dci_research",
            LEGACY_DCI,
        )
        for path in sorted(SOURCE.rglob("*.py")):
            if any(path.is_relative_to(root) for root in allowed_roots):
                continue
            for imported in _imports(path):
                if (
                    imported == "asterion.capabilities.dci"
                    or imported.startswith("asterion.capabilities.dci.")
                ):
                    violations.append((str(path.relative_to(PROJECT)), imported))
        self.assertEqual(violations, [])

    def test_resources_are_package_relative_and_reject_escape(self) -> None:
        self.assertTrue((PACKAGE / "resources/__init__.py").is_file())
        self.assertFalse((LEGACY_DCI / "resources").exists())
        with self.assertRaisesRegex(RuntimeError, "resource is invalid"):
            reproduction._resource_mapping("../payload/capability-package.json")

    def test_old_module_imports_fail(self) -> None:
        old_modules = tuple(
            f"asterion.dci.{name}"
            for names in MODULE_GROUPS.values()
            for name in names
        ) + tuple(
            f"asterion.dci.{name}"
            for name in ROOT_MODULES - {"complete", "implementation"}
        )
        for module in old_modules:
            with self.subTest(module=module):
                self.assertIsNone(importlib.util.find_spec(module))


if __name__ == "__main__":
    unittest.main()
