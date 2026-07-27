from __future__ import annotations

import ast
import unittest
from collections.abc import Mapping
from pathlib import Path

import asterion.capability_sdk as capability_sdk
from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import (
    CapabilityExecutionError,
    CapabilityExecutionResult,
    CapabilityInvocation,
)
from asterion.capability_packages.model import (
    BenchmarkTaskBinding,
    InstalledCapabilityPackage,
)
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.runtime.host import CancellationSignal


PROJECT = Path(__file__).resolve().parents[1]
CAPABILITIES = PROJECT / "src/asterion/capabilities"
PUBLIC_NAMES = {
    "BenchmarkTaskBinding",
    "CancellationSignal",
    "CapabilityExecutionError",
    "CapabilityExecutionResult",
    "CapabilityInvocation",
    "CapabilityPackageProvider",
    "CapabilityPackageRef",
    "CapabilityRef",
    "HostServices",
    "InstalledCapabilityPackage",
    "run_capability_conformance",
}
PRIVATE_IMPLEMENTATION_PREFIXES = (
    "asterion.applications",
    "asterion.capabilities.composition",
    "asterion.capability_packages.sources",
    "asterion.runner",
)
PRIVATE_VALUE_MODULES = {
    "asterion.capabilities.catalog",
    "asterion.capabilities.execution",
    "asterion.capability_packages.model",
    "asterion.capability_packages.protocol",
    "asterion.runtime.host",
}
PACKAGE_OWNED_PREFIXES = {
    "controlled_code": ("asterion.capabilities.controlled_code",),
    "dci_research": (
        "asterion.capabilities.dci_research",
        "asterion.dci",
    ),
}


class CapabilitySdkTests(unittest.TestCase):
    def test_public_surface_is_exact_and_reexports_stable_values(self) -> None:
        self.assertEqual(set(capability_sdk.__all__), PUBLIC_NAMES)
        self.assertEqual(len(capability_sdk.__all__), len(PUBLIC_NAMES))
        self.assertIs(capability_sdk.CapabilityRef, CapabilityRef)
        self.assertIs(capability_sdk.CapabilityPackageRef, CapabilityPackageRef)
        self.assertIs(capability_sdk.CapabilityInvocation, CapabilityInvocation)
        self.assertIs(
            capability_sdk.CapabilityExecutionResult,
            CapabilityExecutionResult,
        )
        self.assertIs(
            capability_sdk.CapabilityExecutionError,
            CapabilityExecutionError,
        )
        self.assertIs(
            capability_sdk.InstalledCapabilityPackage,
            InstalledCapabilityPackage,
        )
        self.assertIs(capability_sdk.BenchmarkTaskBinding, BenchmarkTaskBinding)
        self.assertIs(capability_sdk.CancellationSignal, CancellationSignal)

    def test_provider_protocol_describes_the_selected_factory_boundary(self) -> None:
        def provider() -> InstalledCapabilityPackage:
            raise AssertionError("type boundary only")

        self.assertIsInstance(provider, capability_sdk.CapabilityPackageProvider)
        self.assertTrue(issubclass(capability_sdk.HostServices, Mapping))

    def test_builtin_implementation_modules_do_not_import_private_execution_layers(
        self,
    ) -> None:
        implementation_files = tuple(
            path
            for path in sorted(CAPABILITIES.rglob("*.py"))
            if path.name in {"complete.py", "implementation.py"}
        )
        self.assertTrue(implementation_files)
        for path in implementation_files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    imported.append(node.module)
            with self.subTest(path=path.relative_to(PROJECT)):
                self.assertFalse(
                    tuple(
                        module
                        for module in imported
                        if module.startswith(PRIVATE_IMPLEMENTATION_PREFIXES)
                    )
                )

    def test_builtin_implementations_import_public_values_from_the_sdk(self) -> None:
        implementation_files = tuple(
            path
            for path in sorted(CAPABILITIES.rglob("*.py"))
            if path.name in {"complete.py", "implementation.py"}
        )
        for path in implementation_files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            private_public_names = []
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module in PRIVATE_VALUE_MODULES
                ):
                    private_public_names.extend(
                        alias.name for alias in node.names if alias.name in PUBLIC_NAMES
                    )
            with self.subTest(path=path.relative_to(PROJECT)):
                self.assertEqual(private_public_names, [])

    def test_builtin_implementations_import_only_sdk_and_package_owned_code(
        self,
    ) -> None:
        implementation_files = tuple(
            path
            for path in sorted(CAPABILITIES.rglob("*.py"))
            if path.name in {"complete.py", "implementation.py"}
        )
        for path in implementation_files:
            package = path.parent.name
            allowed = (
                "asterion.capability_sdk",
                *PACKAGE_OWNED_PREFIXES[package],
            )
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            violations = []
            for node in ast.walk(tree):
                modules = ()
                if isinstance(node, ast.Import):
                    modules = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    modules = (node.module,)
                violations.extend(
                    module
                    for module in modules
                    if module.startswith("asterion.")
                    and not any(
                        module == prefix or module.startswith(prefix + ".")
                        for prefix in allowed
                    )
                )
            with self.subTest(path=path.relative_to(PROJECT)):
                self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
