from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from typing import Any, Protocol, cast


PROJECT = Path(__file__).resolve().parents[1]
CAPABILITY_ROOT = PROJECT / "src" / "asterion" / "capabilities"

EXPECTED_PUBLIC = (
    "CapabilityRef",
    "CapabilityPackageRef",
    "CapabilityInvocation",
    "CapabilityExecutionResult",
    "CapabilityExecutionError",
    "CapabilityPackageProvider",
    "InstalledCapabilityPackage",
    "BenchmarkTaskBinding",
    "CancellationSignal",
    "HostServices",
    "run_capability_conformance",
)

BUILTIN_CAPABILITY_FILES = (
    CAPABILITY_ROOT / "controlled_code" / "__init__.py",
    CAPABILITY_ROOT / "controlled_code" / "implementation.py",
    CAPABILITY_ROOT / "dci_research" / "__init__.py",
    CAPABILITY_ROOT / "dci_research" / "complete.py",
    CAPABILITY_ROOT / "dci_research" / "implementation.py",
)


def imported_modules(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return tuple(sorted(modules))


def top_level(module: str) -> str:
    return module.split(".", 1)[0]


class CapabilitySdkSurfaceTests(unittest.TestCase):
    def test_public_sdk_exports_exact_stable_surface(self) -> None:
        import asterion.capability_sdk as sdk

        self.assertEqual(sdk.__all__, EXPECTED_PUBLIC)
        self.assertEqual(
            {name for name in dir(sdk) if not name.startswith("_")},
            set(EXPECTED_PUBLIC),
        )

    def test_provider_protocol_exposes_only_selected_package_loading(self) -> None:
        from asterion.capability_sdk import CapabilityPackageProvider

        public_methods = {
            name
            for name, value in CapabilityPackageProvider.__dict__.items()
            if not name.startswith("_") and callable(value)
        }
        self.assertEqual(public_methods, {"load_package"})
        forbidden = {
            "discover_metadata",
            "open_payload",
            "validate_source_identity",
            "catalog_roots",
            "application_provider",
            "compose",
            "run",
        }
        self.assertTrue(forbidden.isdisjoint(CapabilityPackageProvider.__dict__))

    def test_sdk_lets_authors_bind_implementations_without_private_binding_import(
        self,
    ) -> None:
        from asterion.capability_sdk import (
            CapabilityExecutionResult,
            CapabilityInvocation,
            CapabilityPackageRef,
            CapabilityRef,
            InstalledCapabilityPackage,
        )

        class Implementation:
            async def execute(
                self, invocation: CapabilityInvocation
            ) -> CapabilityExecutionResult:
                del invocation
                raise AssertionError("implementation must not be called")

        package = InstalledCapabilityPackage(
            package_ref=CapabilityPackageRef("example.package", "1.0.0"),
            payload_sha256="a" * 64,
            source_id="example.package.local-directory",
            source_kind="local-directory",
            catalog_roots=(),
            benchmark_suite_paths=(),
            implementations=cast(Any, (
                (CapabilityRef("example.capability", "1.0.0"), Implementation()),
            )),
            benchmark_bindings=(),
        )

        self.assertEqual(
            package.implementations[0].capability_ref.capability_id,
            "example.capability",
        )
        self.assertNotIn("CapabilityImplementationBinding", EXPECTED_PUBLIC)

    def test_host_services_is_read_only_mapping_protocol(self) -> None:
        from asterion.capability_sdk import HostServices

        self.assertTrue(issubclass(HostServices, Protocol))
        public_methods = {
            name
            for name, value in HostServices.__dict__.items()
            if not name.startswith("_") and callable(value)
        }
        self.assertEqual(public_methods, {"get"})


class BuiltinCapabilityImportBoundaryTests(unittest.TestCase):
    def test_builtin_capability_implementations_import_only_sdk_stdlib_or_package_owned(
        self,
    ) -> None:
        stdlib = sys.stdlib_module_names
        for path in BUILTIN_CAPABILITY_FILES:
            package_prefix = (
                "asterion.capabilities."
                + path.relative_to(CAPABILITY_ROOT).parts[0]
            )
            with self.subTest(path=path.relative_to(PROJECT)):
                unexpected: list[str] = []
                for module in imported_modules(path):
                    if top_level(module) in stdlib:
                        continue
                    if module == "asterion.capability_sdk":
                        continue
                    if module.startswith(package_prefix):
                        continue
                    unexpected.append(module)

                self.assertEqual(unexpected, [])


if __name__ == "__main__":
    unittest.main()
