from __future__ import annotations

import ast
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"
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


def identity_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for path in PROJECT.rglob("*"):
        relative = path.relative_to(PROJECT)
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

    def test_active_repository_surfaces_do_not_reference_old_protocol_ids(self) -> None:
        offenders: list[tuple[Path, str]] = []
        for path in identity_files():
            text = path.read_text(encoding="utf-8")
            for value in FORBIDDEN_PROTOCOL_IDENTIFIERS:
                if value in text:
                    offenders.append((path.relative_to(PROJECT), value))
        self.assertEqual(offenders, [])

    def test_active_superpowers_documents_are_scanned_when_not_historical(self) -> None:
        path = PROJECT / ".superpowers/active-protocol-guide.md"
        path.write_text("# Active protocol guide\n", encoding="utf-8")
        try:
            self.assertIn(path, identity_files())
        finally:
            path.unlink()

    def test_generated_sdd_evidence_is_not_scanned_as_active_surface(self) -> None:
        path = PROJECT / ".superpowers/sdd/generated-review-evidence.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Generated review evidence\n", encoding="utf-8")
        try:
            self.assertNotIn(path, identity_files())
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
