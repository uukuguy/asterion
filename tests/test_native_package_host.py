"""Provider-free host that assembles the dci and controlled-code packages."""

from __future__ import annotations

import ast
import unittest
from importlib import metadata
from pathlib import Path

from asterion.applications.discovery import (
    list_application_providers,
    load_application_provider,
    select_application_provider_id,
)
from asterion.applications.first_party_packages import builtin_capability_registrations
from asterion.applications.provider import resolve_installed_provider
from asterion.capability_packages.preparation import (
    load_prepared_capability_source,
    prepare_capability_source,
)
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource
from asterion.runtime.defaults import default_runtime_factory_registry


SOURCE = Path(__file__).resolve().parents[1] / "src" / "asterion"
PACKAGE_REFS = (
    CapabilityPackageRef("controlled-code", "1.0.0"),
    CapabilityPackageRef("dci", "1.0.0"),
)
FORBIDDEN_IMPORTS = (
    "asterion.capabilities.controlled_code",
    "asterion.capabilities.dci",
)
BASE_DIRECTORIES = (
    "runtime",
    "runtimes",
    "assembly",
    "runner",
    "services",
)
BASE_FILES = (
    "applications/__init__.py",
    "applications/provider.py",
    "applications/discovery.py",
    "applications/product.py",
    "applications/selection.py",
)


def _bound_packages():
    source = BuiltinCapabilitySource(builtin_capability_registrations())
    return tuple(
        load_prepared_capability_source(
            prepare_capability_source(package_ref, (source,), None)
        )
        for package_ref in PACKAGE_REFS
    )


def _base_sources() -> tuple[Path, ...]:
    paths = [SOURCE / relative for relative in BASE_FILES]
    for name in BASE_DIRECTORIES:
        root = SOURCE / name
        if root.is_dir():
            paths.extend(
                path
                for path in root.rglob("*.py")
                if "__pycache__" not in path.parts
            )
    return tuple(paths)


class NativePackageHostTests(unittest.TestCase):
    def test_provider_free_assembly_resolves_both_packages_on_pi_reference(self) -> None:
        from asterion.applications.native import create_provider

        provider = create_provider()
        self.assertEqual(provider.provider_id, "native")
        self.assertEqual(
            select_application_provider_id("native.packages@1.0.0"),
            "native",
        )
        entries = tuple(metadata.entry_points(group="asterion.applications"))
        self.assertIn(
            "native",
            [item.provider_id for item in list_application_providers(entry_points=entries)],
        )
        loaded = load_application_provider("native")
        self.assertEqual(loaded.provider_id, provider.provider_id)

        packages = _bound_packages()
        resolved = resolve_installed_provider(
            loaded,
            runtime_factories=default_runtime_factory_registry(),
            installed_packages=packages,
        )
        application = resolved.applications[0]
        self.assertEqual(
            (application.application_id, application.version),
            ("native.packages", "1.0.0"),
        )
        self.assertEqual(application.runtime_ids, ("pi.reference",))
        self.assertEqual(application.capability_packages, PACKAGE_REFS)
        self.assertEqual(len(application.assemblies), 1)
        assembly = application.assemblies[0]
        self.assertEqual(assembly.runtime_id, "pi.reference")
        self.assertEqual(assembly.plan.capability_package_refs, PACKAGE_REFS)
        self.assertEqual(
            assembly.plan.host_capabilities,
            ("corpus.local-root", "executor.controlled"),
        )

        owned = {
            binding.capability_ref: binding.implementation
            for package in packages
            for binding in package.implementations
        }
        resolved_bindings = dict(application.implementations)
        self.assertEqual(set(resolved_bindings), set(owned))
        for ref, implementation in resolved_bindings.items():
            self.assertIs(implementation, owned[ref])

        modules_by_package: dict[str, set[str]] = {}
        for package in packages:
            modules_by_package[package.package_ref.package_id] = {
                type(binding.implementation).__module__
                for binding in package.implementations
            }
        self.assertTrue(
            modules_by_package["controlled-code"].isdisjoint(
                modules_by_package["dci"]
            )
        )
        provider_source = (SOURCE / "applications/native/provider.py").read_text(
            encoding="utf-8"
        )
        for name in FORBIDDEN_IMPORTS:
            self.assertNotIn(name, provider_source)

    def test_base_does_not_import_either_package(self) -> None:
        offenders: list[str] = []
        for path in _base_sources():
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
            imported: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.append(node.module)
            for name in imported:
                if name.startswith(FORBIDDEN_IMPORTS):
                    offenders.append(f"{path.relative_to(SOURCE)} imports {name}")
        self.assertEqual(offenders, [])

    def test_single_package_applications_register_beside_native_packages(self) -> None:
        from asterion.applications.native import create_provider

        provider = create_provider()
        self.assertEqual(
            tuple(
                (item.application_id, item.version) for item in provider.applications
            ),
            (
                ("native.packages", "1.0.0"),
                ("native.dci-research", "1.0.0"),
                ("native.controlled-code", "1.0.0"),
            ),
        )
        names = {
            entry.name
            for entry in metadata.entry_points(group="asterion.application_index")
        }
        self.assertIn("native.packages__1.0.0", names)
        self.assertNotIn("native.dci-research__1.0.0", names)
        self.assertNotIn("native.controlled-code__1.0.0", names)

        resolved = resolve_installed_provider(
            provider,
            runtime_factories=default_runtime_factory_registry(),
            installed_packages=_bound_packages(),
        )
        self.assertEqual(resolved.applications[0].application_id, "native.packages")
        by_id = {
            application.application_id: application
            for application in resolved.applications
        }
        dci = by_id["native.dci-research"]
        code = by_id["native.controlled-code"]
        self.assertEqual(
            dci.capability_packages,
            (CapabilityPackageRef("dci", "1.0.0"),),
        )
        self.assertEqual(
            dci.assemblies[0].plan.host_capabilities,
            ("corpus.local-root",),
        )
        self.assertEqual(
            tuple(ref.capability_id for ref in dci.assemblies[0].plan.capability_refs),
            ("dci.research", "policy.local-corpus"),
        )
        self.assertEqual(dci.assemblies[0].runtime_id, "pi.reference")
        self.assertEqual(
            code.capability_packages,
            (CapabilityPackageRef("controlled-code", "1.0.0"),),
        )
        self.assertEqual(
            code.assemblies[0].plan.host_capabilities,
            ("executor.controlled",),
        )
        self.assertEqual(
            tuple(ref.capability_id for ref in code.assemblies[0].plan.capability_refs),
            (
                "evaluation.code-quality",
                "observability.execution-audit",
                "policy.controlled-code-check",
                "workflow.code-quality",
            ),
        )
        self.assertEqual(code.assemblies[0].runtime_id, "pi.reference")
        provider_source = (SOURCE / "applications/native/provider.py").read_text(
            encoding="utf-8"
        )
        for name in FORBIDDEN_IMPORTS:
            self.assertNotIn(name, provider_source)


if __name__ == "__main__":
    unittest.main()
