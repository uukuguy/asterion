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
    "CapabilityImplementation",
    "CapabilityImplementationBinding",
    "CapabilityPackageProvider",
    "InstalledCapabilityPackage",
    "BenchmarkTaskBinding",
    "BenchmarkTaskImplementation",
    "BenchmarkTaskInvocation",
    "BenchmarkTaskRequest",
    "CancellationSignal",
    "HostServices",
    "open_portable_payload",
    "run_capability_conformance",
)

BUILTIN_CAPABILITY_DIRS = (
    CAPABILITY_ROOT / "controlled_code",
)
DCI_CAPABILITY_IMPLEMENTATIONS = tuple(
    CAPABILITY_ROOT / "dci/implementation" / name
    for name in (
        "_analysis.py",
        "_artifacts.py",
        "_provenance.py",
        "_runtime.py",
        "benchmark_bindings.py",
        "complete.py",
        "implementation.py",
        "local_provider.py",
        "operator_inputs.py",
    )
)


def imported_modules(path: Path) -> tuple[str, ...]:
    return imports_from_source(path.read_text(), module_name(path), filename=str(path))


def imports_from_source(source: str, module: str, *, filename: str = "<test>") -> tuple[str, ...]:
    tree = ast.parse(source, filename=filename)
    modules: list[str] = []
    importlib_aliases: set[str] = set()
    import_module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
                if alias.name == "importlib":
                    importlib_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                resolved = resolve_import_from(module, node.level, node.module)
                if resolved:
                    modules.append(resolved)
            elif node.module:
                modules.append(node.module)
                if node.module == "importlib":
                    for alias in node.names:
                        if alias.name == "import_module":
                            import_module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Call):
            imported = dynamic_import_target(
                node,
                importlib_aliases=importlib_aliases,
                import_module_aliases=import_module_aliases,
            )
            if imported is not None:
                modules.append(imported)
    return tuple(sorted(modules))


def module_name(path: Path) -> str:
    relative = path.relative_to(PROJECT / "src").with_suffix("")
    parts = relative.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def resolve_import_from(module: str, level: int, imported: str | None) -> str | None:
    parts = module.split(".")
    if not parts:
        return imported
    package_parts = parts if parts[-1] == "__init__" else parts[:-1]
    prefix = package_parts[: max(0, len(package_parts) - level + 1)]
    if imported:
        prefix.append(imported)
    return ".".join(prefix) if prefix else imported


def dynamic_import_target(
    node: ast.Call,
    *,
    importlib_aliases: set[str],
    import_module_aliases: set[str],
) -> str | None:
    if not node.args or not isinstance(node.args[0], ast.Constant):
        return None
    if not isinstance(node.args[0].value, str):
        return None
    function = node.func
    if isinstance(function, ast.Name) and function.id == "__import__":
        return node.args[0].value
    if isinstance(function, ast.Name) and function.id in import_module_aliases:
        return node.args[0].value
    if (
        isinstance(function, ast.Attribute)
        and function.attr == "import_module"
        and isinstance(function.value, ast.Name)
        and function.value.id in importlib_aliases
    ):
        return node.args[0].value
    return None


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
        self.assertFalse(hasattr(sdk, "_InProcessArtifactPayload"))
        self.assertFalse(hasattr(sdk, "_project_public_value"))
        self.assertFalse(hasattr(sdk, "_PRIVATE_HELPERS"))

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
        self.assertIn("CapabilityImplementationBinding", EXPECTED_PUBLIC)

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
        files = tuple(
            path
            for root in BUILTIN_CAPABILITY_DIRS
            for path in sorted(root.rglob("*.py"))
        ) + DCI_CAPABILITY_IMPLEMENTATIONS
        self.assertGreater(len(files), 5)
        for path in files:
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

    def test_import_gate_detects_relative_and_dynamic_framework_bypasses(self) -> None:
        cases = {
            "relative": "from ..execution import CapabilityImplementationBinding\n",
            "builtin": "__import__('asterion.runner.composed')\n",
            "importlib": (
                "import importlib as il\n"
                "il.import_module('asterion.capability_packages.payload')\n"
            ),
            "alias": (
                "from importlib import import_module as im\n"
                "im('asterion.capabilities.execution')\n"
            ),
        }

        detected = {
            name: imports_from_source(
                source,
                "asterion.capabilities.example.local_provider",
            )
            for name, source in cases.items()
        }

        self.assertIn("asterion.capabilities.execution", detected["relative"])
        self.assertIn("asterion.runner.composed", detected["builtin"])
        self.assertIn("asterion.capability_packages.payload", detected["importlib"])
        self.assertIn("asterion.capabilities.execution", detected["alias"])


if __name__ == "__main__":
    unittest.main()
