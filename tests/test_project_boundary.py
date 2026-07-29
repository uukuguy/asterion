from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"
BENCHMARK_SOURCE = SOURCE / "benchmarks"
TEXT_SUFFIXES = frozenset(
    {
        ".cfg",
        ".ini",
        ".json",
        ".jsonl",
        ".md",
        ".mjs",
        ".py",
        ".rs",
        ".sh",
        ".template",
        ".toml",
        ".ts",
        ".txt",
        ".yaml",
        ".yml",
    }
)
TEXT_NAMES = frozenset({"AGENTS.md", "Makefile", ".gitignore"})
RECURSIVE_EXCLUDED_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
    }
)
HISTORICAL_DOCUMENT_ROOTS = (
    Path("docs/status"),
    Path("docs/superpowers/plans"),
    Path("docs/superpowers/specs"),
)
GENERATED_SDD_EVIDENCE_ROOT = Path(".superpowers/sdd")
FORBIDDEN_PROTOCOL_IDENTIFIERS = (
    "dci." + "agent-runtime/v1",
    "dci." + "package/v1",
    "dci." + "assembly/v1",
)
FORBIDDEN_BENCHMARK_IMPORT_PREFIXES = (
    "asterion.dci",
    "asterion.capabilities.dci",
)
FORBIDDEN_DCI_BENCHMARK_LITERAL_PREFIXES = (
    "ASTERION_DCI_",
    "DCI_",
    "beir.",
    "bright.",
    "qa.",
)
FORBIDDEN_DCI_BENCHMARK_LITERALS = frozenset(
    {
        "browsecomp-plus",
        "bcplus",
        "bcplus-qa",
        "level0",
        "level1",
        "level2",
        "level3",
        "level4",
    }
)
PRIVATE_BENCHMARK_SERIALIZATION_FIELDS = frozenset(
    {
        "assembly_paths",
        "benchmark_suite_paths",
        "output_directory",
        "private_payload",
        "resource_root",
        "source_lock_path",
    }
)


def benchmark_trees() -> tuple[tuple[Path, ast.Module], ...]:
    return tuple(
        (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in sorted(BENCHMARK_SOURCE.glob("*.py"))
    )


def imported_names(tree: ast.AST) -> tuple[str, ...]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.append(node.module)
    return tuple(names)


def identity_files(*, root: Path = PROJECT) -> tuple[Path, ...]:
    project_root = root.resolve()
    files: list[Path] = []
    for path in project_root.rglob("*"):
        relative = path.relative_to(project_root)
        if (
            not path.is_file()
            or any(part in RECURSIVE_EXCLUDED_NAMES for part in relative.parts)
            or relative == GENERATED_SDD_EVIDENCE_ROOT
            or relative.is_relative_to(GENERATED_SDD_EVIDENCE_ROOT)
            or any(
                relative == root or relative.is_relative_to(root)
                for root in HISTORICAL_DOCUMENT_ROOTS
            )
            or (path.suffix not in TEXT_SUFFIXES and path.name not in TEXT_NAMES)
        ):
            continue
        files.append(path)
    return tuple(sorted(files))


class AsterionProjectBoundaryTests(unittest.TestCase):
    def test_production_source_never_imports_original_dci_or_repository_tests(self) -> None:
        forbidden: list[tuple[Path, str]] = []
        for path in SOURCE.rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    if (
                        name == "dci"
                        or name.startswith("dci.")
                        or name == "tests"
                        or name.startswith("tests.")
                    ):
                        forbidden.append((path.relative_to(PROJECT), name))
        self.assertEqual(forbidden, [])

    def test_project_metadata_and_resources_are_internal(self) -> None:
        self.assertTrue((PROJECT / "pyproject.toml").is_file())
        self.assertTrue((PROJECT / "schemas/agent-runtime/v1/event.schema.json").is_file())
        self.assertTrue((SOURCE / "dci/resources/batch-profiles.json").is_file())

    def test_project_metadata_does_not_require_a_parent_workspace(self) -> None:
        text = (PROJECT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotIn("../", text)
        self.assertNotRegex(text, r"(?m)^\s*members\s*=")

    def test_identity_files_can_scan_an_isolated_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            active = root / ".superpowers/active-protocol-guide.md"
            active.parent.mkdir(parents=True)
            active.write_text("# Active protocol guide\n", encoding="utf-8")

            self.assertEqual(identity_files(root=root), (active,))

    def test_active_repository_surfaces_do_not_reference_old_protocol_ids(self) -> None:
        offenders: list[tuple[Path, str]] = []
        for path in identity_files():
            text = path.read_text(encoding="utf-8")
            for value in FORBIDDEN_PROTOCOL_IDENTIFIERS:
                if value in text:
                    offenders.append((path.relative_to(PROJECT), value))
        self.assertEqual(offenders, [])

    def test_active_superpowers_documents_are_scanned_when_not_historical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            path = root / ".superpowers/active-protocol-guide.md"
            path.parent.mkdir(parents=True)
            path.write_text("# Active protocol guide\n", encoding="utf-8")

            self.assertIn(path, identity_files(root=root))

    def test_generated_sdd_evidence_is_not_scanned_as_active_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            path = root / ".superpowers/sdd/generated-review-evidence.md"
            path.parent.mkdir(parents=True)
            path.write_text("# Generated review evidence\n", encoding="utf-8")

            self.assertNotIn(path, identity_files(root=root))

    def test_generic_benchmarks_do_not_import_dci_product_modules(self) -> None:
        offenders = [
            (path.relative_to(PROJECT), name)
            for path, tree in benchmark_trees()
            for name in imported_names(tree)
            if any(
                name == prefix or name.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_BENCHMARK_IMPORT_PREFIXES
            )
        ]

        self.assertEqual(offenders, [])

    def test_generic_benchmarks_do_not_embed_dci_operator_identifiers(self) -> None:
        offenders: list[tuple[Path, str]] = []
        for path, tree in benchmark_trees():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(
                    node.value, str
                ):
                    continue
                value = node.value
                if value in FORBIDDEN_DCI_BENCHMARK_LITERALS or value.startswith(
                    FORBIDDEN_DCI_BENCHMARK_LITERAL_PREFIXES
                ):
                    offenders.append((path.relative_to(PROJECT), value))

        self.assertEqual(offenders, [])

    def test_generic_benchmark_runner_does_not_discover_package_sources(self) -> None:
        runner = ast.parse(
            (BENCHMARK_SOURCE / "execution.py").read_text(encoding="utf-8"),
            filename=str(BENCHMARK_SOURCE / "execution.py"),
        )
        forbidden: list[str] = []
        for node in ast.walk(runner):
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            else:
                continue
            if "discover" in name.lower() or name in {
                "open_payload",
                "resolve_capability_source",
            }:
                forbidden.append(name)

        self.assertEqual(forbidden, [])

    def test_generic_benchmark_subprocess_use_is_isolated_to_process_adapter(
        self,
    ) -> None:
        offenders = [
            (path.relative_to(PROJECT), name)
            for path, tree in benchmark_trees()
            if path.name != "process.py"
            for name in imported_names(tree)
            if name == "subprocess" or name.startswith("subprocess.")
        ]

        self.assertEqual(offenders, [])

    def test_public_benchmark_serializers_do_not_read_private_payloads_or_paths(
        self,
    ) -> None:
        offenders: list[tuple[Path, str, str]] = []
        for path, tree in benchmark_trees():
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not (
                    node.name.startswith("public_")
                    or node.name.startswith("render_")
                    or "serialize" in node.name
                ):
                    continue
                for child in ast.walk(node):
                    if (
                        isinstance(child, ast.Attribute)
                        and child.attr in PRIVATE_BENCHMARK_SERIALIZATION_FIELDS
                    ):
                        offenders.append(
                            (path.relative_to(PROJECT), node.name, child.attr)
                        )

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
