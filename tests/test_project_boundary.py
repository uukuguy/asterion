from __future__ import annotations

import ast
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"
FORBIDDEN_PROTOCOL_IDENTIFIERS = tuple(
    f"dci.{name}/v1" for name in ("agent-runtime", "package", "assembly")
)
IDENTITY_SUFFIXES = frozenset(
    {
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
IDENTITY_NAMES = frozenset({".gitignore", "Makefile"})
GENERATED_DIRECTORIES = frozenset(
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


def identity_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for path in PROJECT.rglob("*"):
        relative = path.relative_to(PROJECT)
        if any(part in GENERATED_DIRECTORIES for part in relative.parts):
            continue
        if relative.parts[:3] in {
            ("docs", "superpowers", "plans"),
            ("docs", "superpowers", "specs"),
        }:
            continue
        if relative == Path("docs/status/JOURNAL.md"):
            continue
        if relative.parts[:2] == (".superpowers", "sdd"):
            continue
        if (
            path.is_file()
            and (
                path.suffix in IDENTITY_SUFFIXES
                or path.name in IDENTITY_NAMES
            )
        ):
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

    def test_active_identity_files_do_not_use_retired_protocols(self) -> None:
        for path in identity_files():
            text = path.read_text(encoding="utf-8")
            for value in FORBIDDEN_PROTOCOL_IDENTIFIERS:
                with self.subTest(path=path.relative_to(PROJECT), value=value):
                    self.assertNotIn(value, text)


if __name__ == "__main__":
    unittest.main()
