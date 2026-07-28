from __future__ import annotations

import ast
import shutil
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

import asterion.capability_sdk as capability_sdk
import asterion.capability_sdk.author as author_module
from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import (
    CapabilityImplementationBinding,
    CapabilityExecutionError,
    CapabilityExecutionResult,
    CapabilityInvocation,
)
from asterion.benchmarks.model import BenchmarkTaskInvocation, BenchmarkTaskRequest
from asterion.capability_packages.payload import open_portable_payload
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
    "CapabilityImplementationBinding",
    "CapabilityPackageProvider",
    "CapabilityPackageRef",
    "CapabilityRef",
    "HostServices",
    "InstalledCapabilityPackage",
    "run_capability_conformance",
    "open_portable_payload",
    "copy_portable_payload",
    "BenchmarkTaskInvocation",
    "BenchmarkTaskRequest",
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
    "implementation": ("asterion.capabilities.dci",),
    "dci_research": (
        "asterion.capabilities.dci_research",
        "asterion.dci",
    ),
}


def _asterion_import_violations(
    source: str,
    *,
    allowed: tuple[str, ...],
) -> tuple[str, ...]:
    tree = ast.parse(source)
    violations = []
    for node in ast.walk(tree):
        modules = ()
        if isinstance(node, ast.Import):
            modules = tuple(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules = tuple(
                node.module if alias.name == "*" else f"{node.module}.{alias.name}"
                for alias in node.names
            )
        violations.extend(
            module
            for module in modules
            if (module == "asterion" or module.startswith("asterion."))
            and not any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in allowed
            )
        )
    return tuple(violations)


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
            capability_sdk.CapabilityImplementationBinding,
            CapabilityImplementationBinding,
        )
        self.assertIs(
            capability_sdk.InstalledCapabilityPackage,
            InstalledCapabilityPackage,
        )
        self.assertIs(capability_sdk.BenchmarkTaskBinding, BenchmarkTaskBinding)
        self.assertIs(capability_sdk.BenchmarkTaskInvocation, BenchmarkTaskInvocation)
        self.assertIs(capability_sdk.BenchmarkTaskRequest, BenchmarkTaskRequest)
        self.assertIs(capability_sdk.CancellationSignal, CancellationSignal)
        self.assertIs(capability_sdk.open_portable_payload, open_portable_payload)
        self.assertIs(
            capability_sdk.copy_portable_payload,
            author_module.copy_portable_payload,
        )

    def test_copy_portable_payload_uses_validated_snapshot_not_mutable_source(
        self,
    ) -> None:
        fixture = PROJECT / "tests/fixtures/extensions/minimal/payload"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source"
            target = root / "target"
            shutil.copytree(fixture, source)
            private = source / "SENTINEL_PRIVATE_AUTHORITY.txt"
            private.write_text("SECRET-AUTHORITY-BYTES", encoding="utf-8")
            snapshot = open_portable_payload(fixture)

            original_open = author_module.open_portable_payload
            try:
                author_module.open_portable_payload = lambda value: snapshot  # type: ignore[assignment]
                digest = capability_sdk.copy_portable_payload(source, target)
            finally:
                author_module.open_portable_payload = original_open

            self.assertEqual(digest, snapshot.payload_sha256)
            self.assertFalse((target / private.name).exists())
            copied = open_portable_payload(target)
            self.assertEqual(copied.payload_sha256, snapshot.payload_sha256)
            for path in sorted(Path(str(snapshot.resource_root)).rglob("*")):
                if path.is_file():
                    relative = path.relative_to(Path(str(snapshot.resource_root)))
                    self.assertEqual(
                        (target / relative).read_bytes(),
                        path.read_bytes(),
                    )

    def test_copy_portable_payload_rejects_existing_symlink_and_invalid_sources(
        self,
    ) -> None:
        fixture = PROJECT / "tests/fixtures/extensions/minimal/payload"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "target"
            target.mkdir()
            with self.assertRaisesRegex(
                ValueError,
                "^portable payload copy target is invalid$",
            ):
                capability_sdk.copy_portable_payload(fixture, target)

            link = root / "target-link"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(
                ValueError,
                "^portable payload copy target is invalid$",
            ):
                capability_sdk.copy_portable_payload(fixture, link)

            source_link = root / "source-link"
            source_link.symlink_to(fixture, target_is_directory=True)
            symlink_target = root / "symlink-source-target"
            with self.assertRaises(ValueError):
                capability_sdk.copy_portable_payload(source_link, symlink_target)
            self.assertFalse(symlink_target.exists())

            invalid = root / "invalid-source"
            shutil.copytree(fixture, invalid)
            (invalid / "SENTINEL_PRIVATE_AUTHORITY.txt").write_text(
                "SECRET-AUTHORITY-BYTES",
                encoding="utf-8",
            )
            failed_target = root / "failed-target"
            with self.assertRaises(ValueError):
                capability_sdk.copy_portable_payload(invalid, failed_target)
            self.assertFalse(failed_target.exists())

    def test_copy_portable_payload_does_not_remove_raced_target(self) -> None:
        fixture = PROJECT / "tests/fixtures/extensions/minimal/payload"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "target"
            sentinel = target / "SENTINEL_EXISTING_TARGET.txt"
            snapshot = open_portable_payload(fixture)

            def race_target_into_place(value: Path):
                target.mkdir()
                sentinel.write_text("do-not-remove", encoding="utf-8")
                return snapshot

            original_open = author_module.open_portable_payload
            try:
                author_module.open_portable_payload = race_target_into_place  # type: ignore[assignment]
                with self.assertRaises(FileExistsError):
                    capability_sdk.copy_portable_payload(fixture, target)
            finally:
                author_module.open_portable_payload = original_open

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "do-not-remove")

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
            violations = _asterion_import_violations(
                path.read_text(encoding="utf-8"),
                allowed=allowed,
            )
            with self.subTest(path=path.relative_to(PROJECT)):
                self.assertEqual(violations, ())

    def test_import_guard_rejects_parent_bare_and_private_star_imports(
        self,
    ) -> None:
        allowed = ("asterion.capability_sdk",)
        private_sources = (
            "from asterion import runtime\n",
            "from asterion.capabilities import execution\n",
            "import asterion\n",
            "from asterion import *\n",
            "from asterion.runtime import *\n",
        )
        for source in private_sources:
            with self.subTest(source=source):
                self.assertTrue(_asterion_import_violations(source, allowed=allowed))

        safe_sources = (
            "from asterion import capability_sdk\n",
            "from asterion.capability_sdk import CapabilityRef\n",
            "from asterion.capability_sdk import *\n",
        )
        for source in safe_sources:
            with self.subTest(source=source):
                self.assertEqual(
                    _asterion_import_violations(source, allowed=allowed),
                    (),
                )


if __name__ == "__main__":
    unittest.main()
