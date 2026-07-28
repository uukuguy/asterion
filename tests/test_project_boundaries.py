from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
BENCHMARK_SOURCE = PROJECT / "src/asterion/benchmarks"

_FORBIDDEN_IMPORT_PREFIXES = (
    "asterion.dci",
    "asterion.capabilities.dci",
)
_DCI_LITERAL_IDENTIFIERS = frozenset(
    {
        "beir.arguana",
        "beir.scifact",
        "bcplus.level3",
        "bcplus.main",
        "bcplus.openai",
        "bright.biology",
        "bright.earth-science",
        "bright.economics",
        "bright.robotics",
        "browsecomp-plus",
        "qa.2wikimultihopqa",
        "qa.bamboogle",
        "qa.hotpotqa",
        "qa.musique",
        "qa.nq",
        "qa.triviaqa",
    }
)
_DCI_LITERAL_PATTERN = re.compile(
    r"(?<![a-z0-9])dci(?:[._-]|$)",
    re.IGNORECASE,
)
_DISCOVERY_IMPORT_PREFIXES = (
    "asterion.applications.discovery",
    "asterion.capability_packages.sources",
    "importlib.metadata",
)
_DISCOVERY_CALLS = frozenset(
    {
        "discover_metadata",
        "entry_points",
        "load_application_provider",
        "load_provider",
        "open_payload",
    }
)
_PROCESS_CALLS = frozenset(
    {
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
        "os.popen",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.system",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.run",
    }
)
_GENERIC_SERIALIZERS = frozenset(
    {
        "asdict",
        "dataclasses.asdict",
        "model_dump",
        "vars",
    }
)
_SERIALIZATION_CALLS = frozenset({"json.dump", "json.dumps"})
_PRIVATE_SERIALIZATION_NAMES = frozenset(
    {
        "__dict__",
        "argv",
        "cwd",
        "environment",
        "evidence_root",
        "output_directory",
        "path",
        "private_payload",
        "stderr",
        "stdout",
    }
)


def _benchmark_trees() -> tuple[tuple[Path, ast.Module], ...]:
    return tuple(
        (
            path,
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path)),
        )
        for path in sorted(BENCHMARK_SOURCE.glob("*.py"))
    )


def _imported_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (
            node.module,
            *(
                f"{node.module}.{alias.name}"
                for alias in node.names
                if alias.name != "*"
            ),
        )
    return ()


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return node.attr if parent is None else f"{parent}.{node.attr}"
    return None


def _names_below(node: ast.AST) -> frozenset[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            names.add(child.value)
    return frozenset(names)


class GenericBenchmarkProjectBoundaryTests(unittest.TestCase):
    def test_generic_modules_do_not_import_dci_product_code(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for path, tree in _benchmark_trees():
            for node in ast.walk(tree):
                for name in _imported_names(node):
                    if any(
                        name == prefix or name.startswith(f"{prefix}.")
                        for prefix in _FORBIDDEN_IMPORT_PREFIXES
                    ):
                        violations.append((path.name, node.lineno, name))
        self.assertEqual(violations, [])

    def test_generic_modules_do_not_embed_dci_identifiers(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for path, tree in _benchmark_trees():
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                ):
                    continue
                value = node.value.casefold()
                if (
                    _DCI_LITERAL_PATTERN.search(value) is not None
                    or any(
                        value == identifier
                        or value.startswith(f"{identifier}.")
                        or value.startswith(f"{identifier}/")
                        for identifier in _DCI_LITERAL_IDENTIFIERS
                    )
                ):
                    violations.append((path.name, node.lineno, node.value))
        self.assertEqual(violations, [])

    def test_runner_does_not_discover_packages_or_providers(self) -> None:
        path = BENCHMARK_SOURCE / "execution.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            for name in _imported_names(node):
                if any(
                    name == prefix or name.startswith(f"{prefix}.")
                    for prefix in _DISCOVERY_IMPORT_PREFIXES
                ):
                    violations.append((node.lineno, name))
            if isinstance(node, ast.Call):
                name = _qualified_name(node.func)
                if name is not None and name.rsplit(".", 1)[-1] in _DISCOVERY_CALLS:
                    violations.append((node.lineno, name))
        self.assertEqual(violations, [])

    def test_subprocess_use_is_confined_to_process_module(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for path, tree in _benchmark_trees():
            if path.name == "process.py":
                continue
            for node in ast.walk(tree):
                for name in _imported_names(node):
                    if name == "subprocess" or name.startswith("subprocess."):
                        violations.append((path.name, node.lineno, name))
                if isinstance(node, ast.Call):
                    name = _qualified_name(node.func)
                    if name in _PROCESS_CALLS or (
                        name is not None and name.startswith("os.spawn")
                    ):
                        violations.append((path.name, node.lineno, name))
        self.assertEqual(violations, [])

    def test_public_serialization_is_allowlisted_not_recursive_or_private(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for path, tree in _benchmark_trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "__dict__":
                    violations.append((path.name, node.lineno, "__dict__"))
                if not isinstance(node, ast.Call):
                    continue
                name = _qualified_name(node.func)
                if name in _GENERIC_SERIALIZERS:
                    violations.append((path.name, node.lineno, name))
                if (
                    name not in _SERIALIZATION_CALLS
                    and (
                        name is None
                        or name.rsplit(".", 1)[-1] not in {"dump", "dumps"}
                    )
                ):
                    continue
                serialized = (
                    *node.args,
                    *(keyword.value for keyword in node.keywords),
                )
                private_names = set().union(
                    *(_names_below(value) for value in serialized)
                ) & _PRIVATE_SERIALIZATION_NAMES
                for private_name in sorted(private_names):
                    violations.append(
                        (path.name, node.lineno, private_name)
                    )
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
