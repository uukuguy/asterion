from __future__ import annotations

import ast
import email
from importlib.util import resolve_name
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from tests.core_module_allowlist import (
    CORE_MODULES,
    FORBIDDEN_CORE_IMPORT_PREFIXES,
    NON_CORE_MODULE_PREFIXES,
)


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src"


def module_source(module: str) -> Path:
    path = SOURCE.joinpath(*module.split("."))
    file = path.with_suffix(".py")
    return file if file.is_file() else path / "__init__.py"


def source_module(path: Path) -> str:
    parts = list(path.relative_to(SOURCE).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def has_prefix(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def imported_names(module: str, source: Path, tree: ast.AST) -> tuple[str, ...]:
    names: list[str] = []
    package = module if source.name == "__init__.py" else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = resolve_name(f"{'.' * node.level}{base}", package)
            if base:
                names.append(base)
            names.extend(
                f"{base}.{alias.name}" if base else alias.name
                for alias in node.names
                if alias.name != "*"
            )
    return tuple(names)


class CoreOnlyImportBoundaryTests(unittest.TestCase):
    def test_allowlist_covers_every_non_product_python_module(self) -> None:
        discovered = {
            source_module(path)
            for path in (SOURCE / "asterion").rglob("*.py")
            if "__pycache__" not in path.parts
        }
        expected = {
            module
            for module in discovered
            if not has_prefix(module, NON_CORE_MODULE_PREFIXES)
        }
        self.assertEqual(set(CORE_MODULES), expected)

    def test_allowlisted_modules_do_not_import_first_party_products(self) -> None:
        offenders: list[tuple[str, str]] = []
        for module in CORE_MODULES:
            source = module_source(module)
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for name in imported_names(module, source, tree):
                if has_prefix(name, FORBIDDEN_CORE_IMPORT_PREFIXES):
                    offenders.append((module, name))
        self.assertEqual(offenders, [])

    def test_relative_imports_resolve_before_product_boundary_check(self) -> None:
        cases = (
            (
                "asterion.applications.discovery",
                Path("discovery.py"),
                "from . import first_party_cli",
                "asterion.applications.first_party_cli",
            ),
            (
                "asterion.runtime",
                Path("__init__.py"),
                "from ..capabilities import dci",
                "asterion.capabilities.dci",
            ),
        )
        for module, source, text, expected in cases:
            with self.subTest(text=text):
                names = imported_names(module, source, ast.parse(text))
                self.assertIn(expected, names)
                self.assertTrue(has_prefix(expected, FORBIDDEN_CORE_IMPORT_PREFIXES))

    def test_dependency_free_wheel_imports_every_core_module_in_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            wheel_directory = temporary / "wheel"
            target = temporary / "target"
            build = subprocess.run(
                ["uv", "build", ".", "--out-dir", str(wheel_directory)],
                cwd=PROJECT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            wheel = next(wheel_directory.glob("asterion-*.whl"))
            with ZipFile(wheel) as archive:
                metadata_path = next(
                    name for name in archive.namelist() if name.endswith("/METADATA")
                )
                metadata = email.message_from_bytes(archive.read(metadata_path))
            unconditional = [
                value
                for value in metadata.get_all("Requires-Dist", [])
                if ";" not in value or "extra" not in value.partition(";")[2]
            ]
            self.assertEqual(unconditional, [])
            install = subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--no-deps",
                    "--target",
                    str(target),
                    str(wheel),
                ],
                cwd=temporary,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            script = "\n".join(
                (
                    "import importlib",
                    "import pathlib",
                    "import sys",
                    f"target = {str(target.resolve())!r}",
                    f"repository_source = {str(SOURCE.resolve())!r}",
                    "sys.path.insert(0, target)",
                    "assert all(not pathlib.Path(path).resolve().is_relative_to(repository_source) for path in sys.path if path)",
                    "assert all('site-packages' not in path for path in sys.path)",
                    f"modules = {CORE_MODULES!r}",
                    "for module in modules:",
                    "    imported = importlib.import_module(module)",
                    "    location = getattr(imported, '__file__', None)",
                    "    if location is not None:",
                    "        assert pathlib.Path(location).resolve().is_relative_to(target), (module, location)",
                )
            )
            environment = {"PATH": os.environ["PATH"]}
            isolated = subprocess.run(
                [sys.executable, "-I", "-S", "-c", script],
                cwd=temporary,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                isolated.returncode,
                0,
                f"stdout:\n{isolated.stdout}\nstderr:\n{isolated.stderr}",
            )


if __name__ == "__main__":
    unittest.main()
